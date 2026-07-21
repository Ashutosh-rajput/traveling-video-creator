from typing import Any
from pydantic import BaseModel, Field

class MediaAsset(BaseModel):
    url: str
    label: str
    provider: str | None = None
    title: str | None = None
    page_url: str | None = None
    creator: str | None = None
    creator_url: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: int | None = None


class ToolCallData(BaseModel):
    tool_name: str
    tool_input: Any
    tool_output: Any



class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=12_000)
    debug: bool = Field(default=False)
    language: str = Field(default="en-IN", description="Language code for the output (e.g. en-IN, hi-IN).")
    num_places: int = Field(default=5, ge=3, le=10, description="Number of attractions to cover.")
    video_length: str = Field(default="medium", description="Length profile of script ('short', 'medium', 'long').")
    speaker: str = Field(default="Shubh", description="Voice profile for TTS generation.")
    script_style: str = Field(default="reel", description="Narration style: 'reel' (social travel reel with hook, budget/itinerary, CTA) or 'classic' (professional guide walkthrough).")


class ChatResponse(BaseModel):
    pics: list[MediaAsset] = Field(default_factory=list)
    videos: list[MediaAsset] = Field(default_factory=list)
    tool_data: list[ToolCallData] = Field(default_factory=list)
    video_script: str = ""


class EditScriptRequest(BaseModel):
    current_script: str = Field(..., min_length=1, max_length=20_000, description="The existing voiceover script to revise.")
    instruction: str = Field(..., min_length=1, max_length=2_000, description="Natural-language edit instruction, e.g. 'make it shorter' or 'add more about the food'.")
    language: str = Field(default="en-IN", description="Language code for the output (e.g. en-IN, hi-IN).")
    script_style: str = Field(default="reel", description="Narration style: 'reel' or 'classic'.")


class EditScriptResponse(BaseModel):
    video_script: str = ""


class IntroImageRequest(BaseModel):
    city_name: str = Field(default="", description="Destination city for the intro banner headline.")
    places: list[str] = Field(default_factory=list, description="Attraction names to reflect in the banner imagery.")
    num_places: int = Field(default=5, ge=1, le=10, description="Number shown in the 'TOP N' headline.")


class IntroImageResponse(BaseModel):
    url: str
    prompt: str = ""
