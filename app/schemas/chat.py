from typing import Any
from pydantic import BaseModel, Field

class MediaAsset(BaseModel):
    url: str
    label: str


class ToolCallData(BaseModel):
    tool_name: str
    tool_input: Any
    tool_output: Any


class AgentOutput(BaseModel):
    message: str = Field(description="A brief 1-2 paragraph description/summary of the city/area.")
    video_script: str = Field(description="A detailed, full-length voiceover video narration script (300-500 words) detailing a chronological walkthrough of 6 to 7 top attractions.")
    pics: list[MediaAsset] = Field(default_factory=list, description="List of picture assets collected.")
    videos: list[MediaAsset] = Field(default_factory=list, description="List of video assets collected.")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=12_000)
    debug: bool = Field(default=False)


class ChatResponse(BaseModel):
    message: str
    pics: list[MediaAsset] = Field(default_factory=list)
    videos: list[MediaAsset] = Field(default_factory=list)
    tool_data: list[ToolCallData] = Field(default_factory=list)
    video_script: str = ""

