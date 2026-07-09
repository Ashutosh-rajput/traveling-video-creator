from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent import AgentService, get_agent_service

router = APIRouter(tags=["chat"])


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

