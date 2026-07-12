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


@router.post("/chat/upload-gdrive")
async def upload_video_to_gdrive_endpoint():
    """Find the last generated travel video and upload it to Google Drive."""
    import os
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
        
    # Pick the first video file found
    filename = files[0]
    file_path = os.path.join(output_dir, filename)
    
    # 2. Authenticate & Obtain Google Access Token
    access_token = None
    
    # A. Check GOOGLE_APPLICATION_CREDENTIALS environment variable path
    env_credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if env_credentials_path and os.path.exists(env_credentials_path):
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests
            scopes = ["https://www.googleapis.com/auth/drive"]
            creds = service_account.Credentials.from_service_account_file(env_credentials_path, scopes=scopes)
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            access_token = creds.token
        except Exception as auth_err:
            import logging
            logging.getLogger(__name__).exception("Authentication failed using GOOGLE_APPLICATION_CREDENTIALS path")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to authenticate using GOOGLE_APPLICATION_CREDENTIALS ({env_credentials_path}): {auth_err}"
            )
            
    # B. Check Service Account JSON file in project root
    elif os.path.exists("gdrive_credentials.json"):
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests
            scopes = ["https://www.googleapis.com/auth/drive"]
            creds = service_account.Credentials.from_service_account_file("gdrive_credentials.json", scopes=scopes)
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            access_token = creds.token
        except Exception as auth_err:
            import logging
            logging.getLogger(__name__).exception("Authentication failed using local gdrive_credentials.json")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to authenticate using gdrive_credentials.json: {auth_err}"
            )
            
    # C. Check Refresh Token from environment
    elif os.getenv("GDRIVE_REFRESH_TOKEN"):
        client_id = os.getenv("GDRIVE_CLIENT_ID")
        client_secret = os.getenv("GDRIVE_CLIENT_SECRET")
        refresh_token = os.getenv("GDRIVE_REFRESH_TOKEN")
        
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GDRIVE_REFRESH_TOKEN is set but GDRIVE_CLIENT_ID or GDRIVE_CLIENT_SECRET is missing in .env."
            )
            
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token"
                    },
                    timeout=10.0
                )
                res.raise_for_status()
                access_token = res.json().get("access_token")
        except Exception as auth_err:
            import logging
            logging.getLogger(__name__).exception("Authentication failed using GDRIVE_REFRESH_TOKEN")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to exchange Google OAuth2 refresh token: {auth_err}"
            )
            
    # D. Check Direct Access Token from environment (fallback / testing)
    elif os.getenv("GDRIVE_ACCESS_TOKEN"):
        access_token = os.getenv("GDRIVE_ACCESS_TOKEN")
        
    # Check if we got a token
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google Drive credentials are not configured. "
                "Please configure one of the following methods: "
                "1. Set GOOGLE_APPLICATION_CREDENTIALS environment variable pointing to a valid service account JSON. "
                "2. Add 'gdrive_credentials.json' (Google Service Account key file) to your project root folder. "
                "3. Add GDRIVE_REFRESH_TOKEN, GDRIVE_CLIENT_ID, and GDRIVE_CLIENT_SECRET to your .env file. "
                "4. Add GDRIVE_ACCESS_TOKEN directly to your .env file."
            )
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
        
        # Read MP4 bytes
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        media_part_header = (
            f"--{boundary}\r\n"
            "Content-Type: video/mp4\r\n\r\n"
        )
        
        closing = f"\r\n--{boundary}--"
        
        payload = (
            metadata_part.encode("utf-8") +
            media_part_header.encode("utf-8") +
            file_bytes +
            closing.encode("utf-8")
        )
        
        async with httpx.AsyncClient(timeout=None) as client:
            res = await client.post(
                url,
                headers=headers,
                content=payload
            )
            res.raise_for_status()
            data = res.json()
            file_id = data.get("id")
            
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

