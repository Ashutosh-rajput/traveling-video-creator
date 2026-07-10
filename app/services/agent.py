from functools import lru_cache
import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import Settings, settings
from app.schemas.chat import AgentOutput, ChatRequest, ChatResponse, MediaAsset, ToolCallData
from app.services.media_tools import get_media_tools

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional travel video producer, scriptwriter, and guide. "
    "When a user asks about a city, area, or destination, you MUST identify exactly 6 to 7 top attractions "
    "or interesting places to visit in that city/area. "
    "For each of these 6 to 7 attractions, you MUST use the available media search tools to search for "
    "photos and videos (e.g. search_pexels_place_media, search_pixabay_place_media, or search_unsplash_place_photos). "
    "Search specifically for each attraction by its name to gather photos and videos. "
    "Your response must focus primarily on producing a detailed, full-length, professional video voiceover script. "
    "Populate the structured output schema with the following fields:\n"
    "- message: A brief 1-2 paragraph description/summary introduction of the city/area. Do NOT list/describe the attractions here.\n"
    "- video_script: A detailed, highly engaging video voiceover script (about 250 words) describing a travel itinerary "
    "or vlog walkthrough of the city.\n"
    "  CRITICAL SCRIPT RULES:\n"
    "  1. Before each attraction's narration, insert a marker tag on its own line in the format: [attraction: Exact Attraction Name]\n"
    "     The very first line of the script should also start with the first attraction marker.\n"
    "     Example format:\n"
    "     [attraction: Lalbagh Botanical Garden]\n"
    "     We start our morning at the stunning Lalbagh Botanical Garden! The fresh morning air...\n"
    "     [attraction: Bangalore Palace]\n"
    "     Now, let us step into royalty at the magnificent Bangalore Palace...\n"
    "  2. Do NOT include any other director instructions, camera angles, sound effects, or scene transitions "
    "  in brackets or parentheses (e.g., do NOT output '[Opening Shot: ...]', '[Cut to: ...]', '(Morning)'). "
    "  The ONLY brackets allowed are the [attraction: ...] markers. Only output the actual spoken dialogue narration.\n"
    "  3. To achieve a highly expressive human tone and help the Text-to-Speech (TTS) engine speak with natural emotions and inflections, "
    "  write using conversational phrases, warm tones, and expressive punctuation (like exclamation marks '!', pauses '...', and emphasis words).\n"
    "- pics: A list of collected photo objects, where each object contains 'url' (from the src/large or image_url fields of tool results) and 'label' (name of the attraction).\n"
    "- videos: A list of collected video objects, where each object contains 'url' (from the video_url or link fields of tool results) and 'label' (name of the attraction).\n"
    "Note: Do NOT output or write any image or video URLs in your text response outside the structured fields, as the system will extract them automatically."
)


def repair_json_string(s: str) -> str:
    s = s.strip()
    if not s:
        return s

    in_quote = False
    escaped = False
    for char in s:
        if char == '\\':
            escaped = not escaped
        elif char == '"':
            if not escaped:
                in_quote = not in_quote
            escaped = False
        else:
            escaped = False

    if in_quote:
        s += '"'

    open_braces = 0
    open_brackets = 0
    in_quote = False
    escaped = False
    for char in s:
        if char == '\\':
            escaped = not escaped
        elif char == '"':
            if not escaped:
                in_quote = not in_quote
            escaped = False
        elif not in_quote:
            if char == '{':
                open_braces += 1
            elif char == '}':
                open_braces = max(0, open_braces - 1)
            elif char == '[':
                open_brackets += 1
            elif char == ']':
                open_brackets = max(0, open_brackets - 1)
            escaped = False
        else:
            escaped = False

    s += ']' * open_brackets
    s += '}' * open_braces
    return s


def merge_media(existing_list: list[MediaAsset], new_data: Any) -> list[MediaAsset]:
    seen_urls = {item.url for item in existing_list}
    if isinstance(new_data, list):
        for item in new_data:
            url = None
            label = ""
            if isinstance(item, dict):
                url = item.get("url")
                label = item.get("label") or ""
            elif hasattr(item, "url"):
                url = getattr(item, "url")
                label = getattr(item, "label", "") or ""
            if url and url not in seen_urls:
                existing_list.append(MediaAsset(url=url, label=label))
                seen_urls.add(url)
    return existing_list


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

        # Extract message and video_script
        answer = ""
        video_script = ""
        structured = result.get("structured_response")

        if structured:
            if hasattr(structured, "message"):
                answer = structured.message
            elif isinstance(structured, dict) and "message" in structured:
                answer = structured["message"]

            if hasattr(structured, "video_script"):
                video_script = structured.video_script
            elif isinstance(structured, dict) and "video_script" in structured:
                video_script = structured["video_script"]

            if hasattr(structured, "pics"):
                merge_media(pics, structured.pics)
            elif isinstance(structured, dict) and "pics" in structured:
                merge_media(pics, structured["pics"])

            if hasattr(structured, "videos"):
                merge_media(videos, structured.videos)
            elif isinstance(structured, dict) and "videos" in structured:
                merge_media(videos, structured["videos"])

        # Fallback to tag/JSON parsing if structured response is missing
        if not answer:
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

            # 1. Try parsing answer as raw JSON or markdown-wrapped JSON
            clean_answer = answer.strip()
            if clean_answer.startswith("```"):
                lines = clean_answer.split("\n")
                if lines[0].strip().startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                clean_answer = "\n".join(lines).strip()

            parsed_json = None
            try:
                parsed_json = json.loads(clean_answer)
            except Exception:
                try:
                    repaired = repair_json_string(clean_answer)
                    parsed_json = json.loads(repaired)
                except Exception:
                    pass

            if isinstance(parsed_json, dict) and ("message" in parsed_json or "video_script" in parsed_json):
                answer = parsed_json.get("message", "")
                video_script = parsed_json.get("video_script", "")
                if "pics" in parsed_json:
                    merge_media(pics, parsed_json["pics"])
                if "videos" in parsed_json:
                    merge_media(videos, parsed_json["videos"])
            else:
                # 2. Try parsing out <video_script> tags
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

