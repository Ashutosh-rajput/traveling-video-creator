from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
import os

from app.schemas.chat import ChatRequest, ChatResponse, MediaAsset
from app.services.agent import AgentService, get_agent_service
from app.services.tts import generate_tts
from app.services.video import generate_travel_video

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

