from functools import lru_cache
import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import Settings, settings
from app.schemas.chat import ChatRequest, ChatResponse, MediaAsset, ToolCallData
from app.services.media_tools import get_media_tools

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert travel guide assistant and creative video scriptwriter. "
    "When a user asks about a city, area, or destination, you MUST identify exactly 6 to 7 top attractions "
    "or interesting places to visit in that city/area. "
    "For each of these 6 to 7 attractions, you MUST use the available media search tools to search for "
    "photos and videos (e.g. search_pexels_place_media, search_pixabay_place_media, or search_unsplash_place_photos). "
    "Search specifically for each attraction by its name to gather photos and videos. "
    "In your final response message, list and describe these 6 to 7 attractions clearly using markdown. "
    "Note: Do NOT output or write any image or video URLs in your final response body, as the system will extract them automatically. "
    "CRITICAL REQUIREMENT: At the very end of your response, you MUST write an engaging, detailed, and descriptive "
    "video narration script (around 150 to 250 words) enclosed in <video_script> and </video_script> tags. "
    "The script should tell a compelling story of how to spend a perfect day in this city/area. "
    "Structure the narration sequentially: start the morning at a primary attraction, transition to "
    "afternoon sightseeing, highlight scenic views or cultural experiences to enjoy next, and wrap up "
    "the day with a relaxing evening activity or sunset spot. Use descriptive sensory language to make the script "
    "feel like a high-quality travel vlog narration."
)


class AgentService:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings
        self._agent: Any | None = None

    def _build_llm(self) -> ChatGoogleGenerativeAI:
        if not self.settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is missing. Add it to .env before calling /chat.")

        return ChatGoogleGenerativeAI(
            model=self.settings.gemma_model,
            google_api_key=self.settings.google_api_key,
            temperature=self.settings.llm_temperature,
            max_output_tokens=self.settings.llm_max_output_tokens,
            timeout=self.settings.request_timeout_seconds,
        )

    def _build_agent(self, system_prompt: str) -> Any:
        return create_agent(
            model=self._build_llm(),
            tools=get_media_tools(),
            system_prompt=system_prompt,
        )

    async def invoke(self, payload: ChatRequest) -> ChatResponse:
        if self._agent is None:
            self._agent = self._build_agent(DEFAULT_SYSTEM_PROMPT)
        agent = self._agent

        result = await agent.ainvoke({"messages": [{"role": "user", "content": payload.message}]})
        messages = result.get("messages", []) if isinstance(result, dict) else []

        pics = []
        videos = []
        tool_data = []

        # Find tool requests (from AI messages) and pair them with outputs (from Tool messages)
        # Store calls by tool_call_id
        tool_calls_by_id = {}
        for msg in messages:
            if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
                for tc in getattr(msg, "tool_calls", []):
                    tool_calls_by_id[tc["id"]] = {
                        "name": tc["name"],
                        "args": tc["args"]
                    }

        for msg in messages:
            if isinstance(msg, ToolMessage) or getattr(msg, "type", None) == "tool":
                call_id = getattr(msg, "tool_call_id", None)
                t_name = getattr(msg, "name", "unknown_tool")
                t_input = None
                
                if call_id and call_id in tool_calls_by_id:
                    t_name = tool_calls_by_id[call_id]["name"]
                    t_input = tool_calls_by_id[call_id]["args"]

                try:
                    data = json.loads(msg.content)
                    if payload.debug:
                        tool_data.append(ToolCallData(
                            tool_name=t_name,
                            tool_input=t_input,
                            tool_output=data
                        ))
                    if isinstance(data, dict):
                        label = (data.get("place_name") or "Travel Asset").title()
                        # Extract photos
                        for photo in data.get("photos", []):
                            url = photo.get("image_url") or photo.get("src", {}).get("large")
                            if url:
                                pics.append(MediaAsset(url=url, label=label))
                        # Extract videos
                        for video in data.get("videos", []):
                            url = video.get("video_url") or video.get("link")
                            if url:
                                videos.append(MediaAsset(url=url, label=label))
                except Exception:
                    # Capture raw content if JSON load fails
                    if payload.debug:
                        tool_data.append(ToolCallData(
                            tool_name=t_name,
                            tool_input=t_input,
                            tool_output=msg.content
                        ))

        # Extract answer/explanation from last AIMessage
        answer = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
                content = msg.content
                if isinstance(content, list):
                    text_blocks = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_blocks.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_blocks.append(block)
                    answer = "\n".join(text_blocks)
                else:
                    answer = str(content)
                break

        if not answer and messages:
            last_message = messages[-1]
            answer = getattr(last_message, "content", str(last_message))

        video_script = ""
        lower_answer = answer.lower()
        tag_start = lower_answer.find("<video_script>")
        if tag_start != -1:
            try:
                msg_body = answer[:tag_start].strip()
                rest = answer[tag_start + len("<video_script>"):]
                tag_end = rest.lower().find("</video_script>")
                if tag_end != -1:
                    video_script = rest[:tag_end].strip()
                    after_tag = rest[tag_end + len("</video_script>"):]
                    if after_tag.strip():
                        msg_body += "\n" + after_tag.strip()
                else:
                    video_script = rest.strip()
                answer = msg_body.strip()
            except Exception:
                pass

        return ChatResponse(
            message=answer,
            pics=pics,
            videos=videos,
            tool_data=tool_data,
            video_script=video_script
        )


@lru_cache
def get_agent_service() -> AgentService:
    return AgentService(settings)

