from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.schemas.chat import ChatRequest, ChatResponse, MediaAsset
from app.services.agent import AgentService, get_agent_service
from app.services.tts import generate_tts
from app.services.video import generate_travel_video

router = APIRouter(tags=["chat"])


class TTSRequest(BaseModel):
    text: str


class VideoRequest(BaseModel):
    script: str = Field(..., description="The video_script text with [attraction: ...] markers.")
    pics: list[dict] = Field(default_factory=list, description="List of {url, label} photo assets.")
    videos: list[dict] = Field(default_factory=list, description="List of {url, label} video assets.")


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


@router.post("/tts")
async def text_to_speech_endpoint(payload: TTSRequest):
    try:
        audio_data = generate_tts(payload.text)
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
    try:
        import asyncio

        video_bytes = await asyncio.to_thread(
            generate_travel_video,
            payload.script,
            payload.pics,
            payload.videos,
        )
        return Response(
            content=video_bytes,
            media_type="video/mp4",
            headers={
                "Content-Disposition": 'attachment; filename="travel_guide.mp4"'
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

