from typing import Any
from pydantic import BaseModel, Field

class MediaAsset(BaseModel):
    url: str
    label: str


class ToolCallData(BaseModel):
    tool_name: str
    tool_input: Any
    tool_output: Any


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=12_000)
    debug: bool = Field(default=False)


class ChatResponse(BaseModel):
    message: str
    pics: list[MediaAsset] = Field(default_factory=list)
    videos: list[MediaAsset] = Field(default_factory=list)
    tool_data: list[ToolCallData] = Field(default_factory=list)
    video_script: str = ""

