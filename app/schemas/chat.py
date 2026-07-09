from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=12_000)
    system_prompt: str | None = Field(default=None, max_length=4_000)


class ChatResponse(BaseModel):
    answer: str
    model: str

