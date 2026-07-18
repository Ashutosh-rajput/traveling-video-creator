from fastapi import APIRouter, Depends, HTTPException, Response, status, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
import asyncio
import logging
import os
import re
import urllib.parse

from dotenv import set_key

from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse, MediaAsset
from app.services.agent import AgentService, get_agent_service
from app.services.progress import get_progress, set_progress
from app.services.tts import generate_tts
from app.services.video import generate_travel_video, set_generation_progress

router = APIRouter(tags=["chat"])

GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


class TTSRequest(BaseModel):
    text: str
    speaker: str = Field(default="Shubh", description="Voice profile for TTS generation.")
    language_code: str = Field(default="en-IN", description="Target language code for narration.")


class VideoRequest(BaseModel):
    script: str = Field(..., description="The video_script text with [attraction: ...] markers.")
    pics: list[dict] = Field(default_factory=list, description="List of {url, label} photo assets.")
    videos: list[dict] = Field(default_factory=list, description="List of {url, label} video assets.")
    city_name: str = Field(default="", description="Destination city name for the intro title overlay.")
    aspect_ratio: str = Field(default="horizontal", description="Resolution aspect ratio ('horizontal', 'portrait').")
    speaker: str = Field(default="Shubh", description="Voice profile for TTS generation.")
    language_code: str = Field(default="en-IN", description="Target language code for narration.")
    music_mood: str = Field(default="none", description="Background music mood ('none', 'cinematic', 'lofi', 'acoustic').")
    music_volume: float = Field(default=0.5, description="Volume level for background music (0.0 to 1.0).")
    transition_style: str = Field(default="none", description="Visual transition style ('none', 'fade', 'zoom', 'slide').")
    transition_sound: str = Field(default="none", description="Transition sound effect ('none', 'whoosh', 'click', 'glitch').")
    caption_theme: str = Field(default="Neon Yellow (Default)", description="Subtitles visual preset style")


@router.get("/login/google")
async def login_google() -> RedirectResponse:
    """Start personal Google Drive OAuth and request an offline refresh token."""
    if not settings.gdrive_client_id or not settings.gdrive_client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET must be configured in .env first.",
        )

    params = {
        "client_id": settings.gdrive_client_id,
        "redirect_uri": settings.gdrive_redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(authorization_url)


@router.get("/login/google/callback", response_class=HTMLResponse)
async def google_login_callback(code: str | None = None, error: str | None = None) -> HTMLResponse:
    """Exchange Google's authorization code and persist the personal refresh token locally."""
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return an authorization code.")

    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.gdrive_client_id,
                "client_secret": settings.gdrive_client_secret,
                "code": code,
                "redirect_uri": settings.gdrive_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if response.is_error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google could not exchange the authorization code. Check the configured redirect URI and OAuth client.",
        )

    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google did not issue a refresh token. Revoke this app in your Google Account and try Connect Drive again.",
        )

    env_path = os.path.abspath(".env")
    set_key(env_path, "GDRIVE_REFRESH_TOKEN", refresh_token)
    os.environ["GDRIVE_REFRESH_TOKEN"] = refresh_token

    return HTMLResponse(
        "<h1>Google Drive connected</h1>"
        "<p>Your personal refresh token has been saved locally. You can close this tab and upload the video from Voyageur AI Studio.</p>"
    )


@router.get("/chat/gdrive-status")
async def google_drive_status() -> dict[str, bool]:
    """Expose only whether this local app has a reusable Drive refresh token."""
    return {"connected": bool(os.getenv("GDRIVE_REFRESH_TOKEN"))}


@router.get("/chat/background-music")
async def list_background_music_endpoint():
    """List all available background music tracks from the data folder."""
    music_dir = "data/background_music"
    if not os.path.exists(music_dir):
        return []
    
    tracks = []
    for f in os.listdir(music_dir):
        if f.endswith((".mp3", ".wav")):
            name_without_ext = os.path.splitext(f)[0]
            pretty_name = name_without_ext.replace("_", " ").replace("-", " ").title()
            
            emoji = "🎵"
            if "lofi" in name_without_ext.lower():
                emoji = "🎧"
            elif "cinematic" in name_without_ext.lower():
                emoji = "🎬"
            elif "acoustic" in name_without_ext.lower():
                emoji = "🎸"
                
            tracks.append({
                "id": name_without_ext,
                "name": f"{emoji} {pretty_name}",
                "filename": f
            })
    return tracks


@router.get("/chat/background-music/file/{filename}")
async def get_background_music_file_endpoint(filename: str):
    """Retrieve preview audio file for a background track."""
    safe_filename = os.path.basename(filename)
    music_file = os.path.join("data/background_music", safe_filename)
    if os.path.exists(music_file):
        media_type = "audio/mpeg" if safe_filename.endswith(".mp3") else "audio/wav"
        return FileResponse(
            path=music_file,
            media_type=media_type,
            filename=safe_filename
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Background music file '{safe_filename}' not found."
    )


@router.post("/chat/background-music/upload")
async def upload_background_music_endpoint(file: UploadFile = File(...)):
    """Upload a background music track (MP3 or WAV)."""
    if not file.filename.endswith((".mp3", ".wav")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only MP3 and WAV files are supported for background music."
        )
    
    music_dir = "data/background_music"
    os.makedirs(music_dir, exist_ok=True)
    
    safe_filename = os.path.basename(file.filename)
    dest_path = os.path.join(music_dir, safe_filename)
    
    try:
        with open(dest_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        return {"status": "success", "filename": safe_filename}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )


@router.delete("/chat/background-music/file/{filename}")
async def delete_background_music_file_endpoint(filename: str):
    """Delete a background music file from the data folder."""
    safe_filename = os.path.basename(filename)
    music_file = os.path.join("data/background_music", safe_filename)
    if os.path.exists(music_file):
        try:
            os.remove(music_file)
            return {"status": "success", "message": f"Deleted background music track '{safe_filename}'"}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete file: {str(e)}"
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Background music file '{safe_filename}' not found."
    )


@router.get("/chat/transition-sounds")
async def list_transition_sounds_endpoint():
    """List all available transition sound effects from the data folder."""
    sound_dir = "data/transition_sounds"
    if not os.path.exists(sound_dir):
        return []
    
    sounds = []
    for f in os.listdir(sound_dir):
        if f.endswith((".mp3", ".wav")):
            name_without_ext = os.path.splitext(f)[0]
            pretty_name = name_without_ext.replace("_", " ").replace("-", " ").title()
            
            emoji = "🔊"
            if "whoosh" in name_without_ext.lower():
                emoji = "💨"
            elif "click" in name_without_ext.lower():
                emoji = "📸"
            elif "glitch" in name_without_ext.lower():
                emoji = "⚡"
                
            sounds.append({
                "id": name_without_ext,
                "name": f"{emoji} {pretty_name}",
                "filename": f
            })
    return sounds


@router.get("/chat/transition-sounds/file/{filename}")
async def get_transition_sound_file_endpoint(filename: str):
    """Retrieve preview audio file for a transition sound effect."""
    safe_filename = os.path.basename(filename)
    sound_file = os.path.join("data/transition_sounds", safe_filename)
    if os.path.exists(sound_file):
        media_type = "audio/mpeg" if safe_filename.endswith(".mp3") else "audio/wav"
        return FileResponse(
            path=sound_file,
            media_type=media_type,
            filename=safe_filename
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Transition sound file '{safe_filename}' not found."
    )


@router.post("/chat/transition-sounds/upload")
async def upload_transition_sound_endpoint(file: UploadFile = File(...)):
    """Upload a transition sound effect (MP3 or WAV)."""
    if not file.filename.endswith((".mp3", ".wav")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only MP3 and WAV files are supported for transition sounds."
        )
    
    sound_dir = "data/transition_sounds"
    os.makedirs(sound_dir, exist_ok=True)
    
    safe_filename = os.path.basename(file.filename)
    dest_path = os.path.join(sound_dir, safe_filename)
    
    try:
        with open(dest_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        return {"status": "success", "filename": safe_filename}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )


@router.delete("/chat/transition-sounds/file/{filename}")
async def delete_transition_sound_file_endpoint(filename: str):
    """Delete a transition sound effect file from the data folder."""
    safe_filename = os.path.basename(filename)
    sound_file = os.path.join("data/transition_sounds", safe_filename)
    
    # Check if they are trying to delete a default generated sound file
    default_sounds = ["whoosh.wav", "click.wav", "glitch.wav"]
    if safe_filename.lower() in default_sounds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete default transition sound effect '{safe_filename}'."
        )
        
    if os.path.exists(sound_file):
        try:
            os.remove(sound_file)
            return {"status": "success", "message": f"Deleted transition sound effect '{safe_filename}'"}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete file: {str(e)}"
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Transition sound file '{safe_filename}' not found."
    )


@router.post("/chat", response_model=ChatResponse)
async def chat_with_agent(
    payload: ChatRequest,
    agent_service: AgentService = Depends(get_agent_service),
) -> ChatResponse:
    try:
        return await agent_service.invoke(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The language model request failed.",
        ) from exc


@router.post(
    "/tts",
    response_class=Response,
    responses={
        200: {
            "content": {"audio/wav": {}},
            "description": "Return the generated TTS voiceover audio file (WAV).",
        }
    }
)
async def text_to_speech_endpoint(payload: TTSRequest):
    try:
        audio_data = generate_tts(
            payload.text,
            speaker=payload.speaker,
            language_code=payload.language_code,
        )
        return Response(content=audio_data, media_type="audio/wav")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"TTS generation failed: {str(exc)}",
        ) from exc


# Strong references to in-flight background render tasks so the event loop
# doesn't garbage-collect them mid-run.
_render_tasks: set = set()


@router.post("/chat/generate-video")
async def generate_video_endpoint(payload: VideoRequest):
    """Kick off video generation in the background and return immediately.

    Rendering (TTS + downloads + MoviePy) can take minutes, so it runs detached
    from this request instead of holding the connection open — which avoids
    reverse-proxy timeouts and lets the client close the tab and come back.
    Poll ``/chat/generate-status`` for progress; fetch the finished file from
    ``/chat/last-video`` once the stage reports ``completed``.
    """
    # Only one render at a time — a second concurrent MoviePy render would
    # double peak memory and OOM small hosts (e.g. a 1 GB Railway instance).
    if _render_tasks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A video is already being generated. Please wait for it to finish before starting another.",
        )

    output_dir = "data/output_videos"

    # Clear any previous render so /last-video can't serve a stale video while
    # the new one is still rendering.
    if os.path.exists(output_dir):
        try:
            for f in os.listdir(output_dir):
                if f.endswith(".mp4"):
                    os.remove(os.path.join(output_dir, f))
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to clear output videos directory: {e}")

    city_name = payload.city_name or ""
    # Reset progress synchronously so an early poll can't observe a previous
    # run's terminal ('completed'/'error') state.
    set_generation_progress(city_name, "starting", 0, "Starting video generation...")

    async def _run_render():
        try:
            output_path = await asyncio.to_thread(
                generate_travel_video,
                payload.script,
                payload.pics,
                payload.videos,
                payload.city_name,
                payload.aspect_ratio,
                payload.speaker,
                payload.language_code,
                payload.music_mood,
                payload.music_volume,
                payload.transition_style,
                payload.transition_sound,
                payload.caption_theme,
            )

            # Move to a stable, city-named filename for nicer downloads / Drive upload.
            safe_city = re.sub(r"[^\w\-]", "_", payload.city_name).strip() if payload.city_name else "travel_guide"
            if not safe_city:
                safe_city = "travel_guide"
            cached_path = os.path.join(output_dir, f"{safe_city}_vlog.mp4")
            try:
                os.makedirs(output_dir, exist_ok=True)
                if os.path.abspath(output_path) != os.path.abspath(cached_path):
                    os.replace(output_path, cached_path)
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to cache generated video: {e}")

            set_generation_progress(city_name, "completed", 100, "Video compiled successfully!")
        except ValueError as exc:
            set_generation_progress(city_name, "error", 0, str(exc))
        except Exception as exc:
            logging.getLogger(__name__).exception("Background video generation failed")
            set_generation_progress(city_name, "error", 0, f"Video generation failed: {exc}")

    task = asyncio.create_task(_run_render())
    _render_tasks.add(task)
    task.add_done_callback(_render_tasks.discard)

    return {"status": "started", "city_name": city_name}


@router.get("/chat/last-video")
async def get_last_video_endpoint():
    """Retrieve the last successfully generated video cache (recovery endpoint)."""
    output_dir = "data/output_videos"
    if os.path.exists(output_dir):
        files = [f for f in os.listdir(output_dir) if f.endswith(".mp4")]
        if files:
            video_path = os.path.join(output_dir, files[0])
            return FileResponse(
                path=video_path,
                media_type="video/mp4",
                filename=files[0]
            )
            
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No previously generated video found. Please compile a video first."
    )


@router.head("/chat/last-video")
async def get_last_video_metadata_endpoint():
    """Check existence of the last successfully generated video cache without downloading it."""
    output_dir = "data/output_videos"
    if os.path.exists(output_dir):
        files = [f for f in os.listdir(output_dir) if f.endswith(".mp4")]
        if files:
            return Response(status_code=status.HTTP_200_OK)
            
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No previously generated video found."
    )


_DIAGNOSTIC_TTS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TTS Diagnostic</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  label { display: block; margin: 0.75rem 0 0.25rem; font-weight: 600; }
  textarea, input { width: 100%; padding: 0.5rem; font: inherit; box-sizing: border-box; }
  textarea { height: 6rem; }
  button { margin-top: 1rem; padding: 0.6rem 1.2rem; font: inherit; cursor: pointer; }
  #status { margin-top: 1rem; white-space: pre-wrap; }
  audio { width: 100%; margin-top: 1rem; }
</style>
</head>
<body>
<h1>TTS Diagnostic</h1>
<p>Posts to the same-origin <code>./tts</code> endpoint and plays the returned audio (bypasses CORS).</p>
<label for="text">Text</label>
<textarea id="text">Welcome to beautiful Bangalore, the vibrant Garden City of India!</textarea>
<label for="speaker">Speaker</label>
<input id="speaker" value="Shubh">
<label for="lang">Language code</label>
<input id="lang" value="en-IN">
<button id="go">Generate &amp; Play</button>
<div id="status"></div>
<audio id="player" controls hidden></audio>
<script>
const btn = document.getElementById('go');
const status = document.getElementById('status');
const player = document.getElementById('player');
btn.addEventListener('click', async () => {
  btn.disabled = true;
  status.textContent = 'Generating...';
  player.hidden = true;
  try {
    const res = await fetch('./tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: document.getElementById('text').value,
        speaker: document.getElementById('speaker').value,
        language_code: document.getElementById('lang').value,
      }),
    });
    if (!res.ok) {
      const detail = await res.text();
      status.textContent = 'Error ' + res.status + ': ' + detail;
      return;
    }
    const blob = await res.blob();
    player.src = URL.createObjectURL(blob);
    player.hidden = false;
    player.play();
    status.textContent = 'OK — ' + Math.round(blob.size / 1024) + ' KB';
  } catch (e) {
    status.textContent = 'Request failed: ' + e;
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>"""


@router.get("/diagnostic-tts", response_class=HTMLResponse)
async def diagnostic_tts_page():
    """Serve a self-contained TTS test page from the same origin to bypass CORS blocks."""
    return HTMLResponse(content=_DIAGNOSTIC_TTS_HTML)


@router.get("/chat/reddit-search")
async def search_reddit_endpoint(
    query: str,
    limit: int = 5,
    sort: str = "relevance"
):
    """Search public Reddit posts using client credentials from environment variables."""
    import os
    import httpx

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit Client ID or Client Secret is not configured in .env."
        )

    headers = {
        "User-Agent": "travel-video-creator:v1.0 (by /u/ashutosh-rajput)"
    }

    try:
        async with httpx.AsyncClient() as client:
            # 1. Get access token
            auth = httpx.BasicAuth(client_id, client_secret)
            token_res = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                data={"grant_type": "client_credentials"},
                headers=headers,
                timeout=10.0
            )
            token_res.raise_for_status()
            token_data = token_res.json()
            access_token = token_data.get("access_token")

            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to retrieve access token from Reddit."
                )

            # 2. Search posts
            search_headers = {
                **headers,
                "Authorization": f"Bearer {access_token}"
            }
            search_params = {
                "q": query,
                "limit": limit,
                "sort": sort,
                "type": "link"
            }
            search_res = await client.get(
                "https://oauth.reddit.com/search",
                headers=search_headers,
                params=search_params,
                timeout=10.0
            )
            search_res.raise_for_status()
            results = search_res.json()

            posts = []
            children = results.get("data", {}).get("children", [])
            for child in children:
                data = child.get("data", {})
                posts.append({
                    "title": data.get("title"),
                    "subreddit": data.get("subreddit"),
                    "score": data.get("score"),
                    "url": data.get("url"),
                    "selftext": data.get("selftext"),
                    "permalink": f"https://reddit.com{data.get('permalink')}"
                })

            return {"posts": posts}

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reddit API returned error status {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search Reddit: {str(exc)}"
        ) from exc


# Only one Drive upload ("the latest render") is ever active, so progress is
# tracked under a single fixed key rather than a per-filename one. This avoids
# the client needing to know the server-side filename to poll status.
_UPLOAD_PROGRESS_KEY = "latest"

def set_upload_progress(percent: int, stage: str = "uploading", message: str = ""):
    set_progress("gdrive_upload", _UPLOAD_PROGRESS_KEY, {"percent": percent, "stage": stage, "message": message})

def get_upload_progress() -> dict:
    return get_progress(
        "gdrive_upload", _UPLOAD_PROGRESS_KEY, {"percent": 0, "stage": "idle", "message": "No active upload."}
    )


async def _gdrive_multipart_stream(metadata_bytes, media_header_bytes, file_path, closing_bytes, on_progress):
    total = len(metadata_bytes) + len(media_header_bytes) + os.path.getsize(file_path) + len(closing_bytes)
    sent = 0

    yield metadata_bytes
    sent += len(metadata_bytes)
    yield media_header_bytes
    sent += len(media_header_bytes)

    chunk_size = 512 * 1024
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            yield chunk
            sent += len(chunk)
            on_progress(int(sent / total * 100))

    yield closing_bytes
    on_progress(100)


@router.get("/chat/generate-status")
async def get_generate_status_endpoint(city_name: str | None = None):
    """Retrieve real-time video generation progress.

    With ``city_name`` → that city's progress. Without it → the most recent
    render's progress (used by the client on load to reattach to a render that
    is still running server-side).
    """
    from app.services.video import get_generation_progress, get_latest_generation_progress
    if city_name:
        return get_generation_progress(city_name)
    return get_latest_generation_progress()


@router.get("/chat/upload-gdrive-status")
async def get_upload_status_endpoint():
    """Retrieve real-time progress of the active Google Drive upload."""
    return get_upload_progress()


@router.post("/chat/upload-gdrive")
async def upload_video_to_gdrive_endpoint():
    """Upload the latest render to the user's personally connected Google Drive."""
    import json
    import httpx
    
    # 1. Locate the video
    output_dir = "data/output_videos"
    if not os.path.exists(output_dir):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No video has been generated yet. Please compile a video project first."
        )
        
    files = [f for f in os.listdir(output_dir) if f.endswith(".mp4")]
    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No compiled MP4 video found in the cache output folder. Please compile a video first."
        )
        
    # Use the newest render if the cache happens to contain more than one video.
    filename = max(files, key=lambda file: os.path.getmtime(os.path.join(output_dir, file)))
    file_path = os.path.join(output_dir, filename)
    
    # 2. Refresh the access token saved by the personal OAuth connection.
    refresh_token = os.getenv("GDRIVE_REFRESH_TOKEN")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google Drive is not connected. Select Connect Drive and approve access before uploading.",
        )
    if not settings.gdrive_client_id or not settings.gdrive_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GDRIVE_CLIENT_ID or GDRIVE_CLIENT_SECRET is missing from .env.",
        )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.gdrive_client_id,
                    "client_secret": settings.gdrive_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if token_response.is_error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your Google Drive connection has expired or was revoked. Select Connect Drive to authorize it again.",
            )
        access_token = token_response.json().get("access_token")
    except HTTPException:
        raise
    except Exception as auth_err:
        import logging
        logging.getLogger(__name__).exception("Authentication failed using the personal Google Drive refresh token")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to refresh the Google Drive connection: {auth_err}",
        ) from auth_err

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google did not return an access token.",
        )

    # 3. Perform multipart/related upload to Drive API
    try:
        url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        metadata = {
            "name": filename,
            "mimeType": "video/mp4"
        }
        
        # Add parent folder if G_DRIVE_FOLDER_ID is set in .env
        folder_id = os.getenv("G_DRIVE_FOLDER_ID")
        if folder_id:
            metadata["parents"] = [folder_id]
        
        boundary = "gdrive_upload_boundary_delimiter"
        headers["Content-Type"] = f"multipart/related; boundary={boundary}"
        
        metadata_part = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
        )
        
        media_part_header = (
            f"--{boundary}\r\n"
            "Content-Type: video/mp4\r\n\r\n"
        )
        
        closing = f"\r\n--{boundary}--"
        
        # Encode parts to bytes
        metadata_bytes = metadata_part.encode("utf-8")
        media_header_bytes = media_part_header.encode("utf-8")
        closing_bytes = closing.encode("utf-8")

        content_length = (
            len(metadata_bytes) + len(media_header_bytes)
            + os.path.getsize(file_path) + len(closing_bytes)
        )
        headers["Content-Length"] = str(content_length)

        set_upload_progress(0, "uploading", f"Starting upload of '{filename}'...")

        def on_progress(percent):
            set_upload_progress(percent, "uploading", f"Uploading '{filename}' ({percent}%)...")

        async with httpx.AsyncClient(timeout=None) as client:
            res = await client.post(
                url,
                headers=headers,
                content=_gdrive_multipart_stream(metadata_bytes, media_header_bytes, file_path, closing_bytes, on_progress),
            )
            res.raise_for_status()
            data = res.json()
            file_id = data.get("id")

            set_upload_progress(100, "completed", "Upload completed successfully!")
            return {
                "message": "Video successfully uploaded to Google Drive!",
                "file_id": file_id,
                "filename": filename,
                "view_link": f"https://drive.google.com/file/d/{file_id}/view"
            }
            
    except httpx.HTTPStatusError as exc:
        import logging
        logging.getLogger(__name__).exception("Google Drive API responded with HTTP status error")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Drive API returned error status {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Failed to upload video to Google Drive")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload video to Google Drive: {str(exc)}"
        ) from exc
