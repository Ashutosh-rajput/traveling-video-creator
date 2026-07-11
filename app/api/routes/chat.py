from fastapi import APIRouter, Depends, HTTPException, Response, status, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
import os

from app.schemas.chat import ChatRequest, ChatResponse, MediaAsset
from app.services.agent import AgentService, get_agent_service
from app.services.tts import generate_tts
from app.services.video import generate_travel_video, ensure_transition_sounds

router = APIRouter(tags=["chat"])


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
    ensure_transition_sounds()
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


@router.post("/chat/generate-video")
async def generate_video_endpoint(payload: VideoRequest):
    """Generate a travel guide video from script, photos, and video clips."""
    output_dir = "data/output_videos"
    
    # Clean the output directory when starting a new generation
    if os.path.exists(output_dir):
        try:
            for f in os.listdir(output_dir):
                if f.endswith(".mp4"):
                    os.remove(os.path.join(output_dir, f))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to clear output videos directory: {e}")

    try:
        import asyncio

        video_bytes = await asyncio.to_thread(
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

        # Cache the generated video inside data/output_videos preserving filename
        import re
        safe_city = re.sub(r"[^\w\-]", "_", payload.city_name).strip() if payload.city_name else "travel_guide"
        if not safe_city:
            safe_city = "travel_guide"
        filename = f"{safe_city}_vlog.mp4"
        
        cached_path = os.path.join(output_dir, filename)
        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(cached_path, "wb") as f:
                f.write(video_bytes)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to cache generated video: {e}")

        return Response(
            content=video_bytes,
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video generation failed: {str(exc)}",
        ) from exc


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


@router.get("/diagnostic-tts", response_class=HTMLResponse)
async def diagnostic_tts_page():
    """Serve the diagnostic TTS test HTML utility page directly from same origin to bypass CORS blocks."""
    html_path = "scratch/test_tts.html"
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    raise HTTPException(status_code=404, detail="Diagnostic tool HTML file not found.")


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

