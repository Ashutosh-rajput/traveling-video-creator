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
    "When a user asks about a city, area, or destination, you MUST identify exactly 5 top attractions "
    "or interesting places to visit in that city/area.\n"
    "CRITICAL SEARCH PROCESS:\n"
    "1. First, call the search_all_place_media tool with the general city name (e.g. 'Mangalore' or 'Paris') "
    "   to gather general city photos and videos. Label these assets with the city name (e.g. 'Mangalore'). These will be used for the video intro.\n"
    "2. Then, call search_all_place_media ONCE for each of the 5 specific attractions. Label those with the attraction name.\n"
    "Do NOT call individual provider tools separately. Just use search_all_place_media.\n"
    "Your response must focus primarily on producing a detailed, full-length, professional video voiceover script. "
    "Populate the structured output schema with the following fields:\n"
    "- message: A brief 1-2 paragraph description/summary introduction of the city/area. Do NOT list/describe the attractions here.\n"
    "- video_script: A detailed, highly engaging video voiceover script (about 250 words) describing a travel itinerary "
    "or vlog walkthrough of the city.\n"
    "  CRITICAL SCRIPT RULES:\n"
    "  1. Start the script with a brief, highly engaging general introduction paragraph (about 30-40 words) that is NOT prefixed by any tag. "
    "     This serves as the 'Intro' segment of the video.\n"
    "  2. Immediately after the intro paragraph, insert the first attraction marker tag on its own line in the format: [attraction: Exact Attraction Name] "
    "     followed by its narration text. Do this for all 5 attractions.\n"
    "     Example format:\n"
    "     Welcome to beautiful Bangalore, the vibrant Garden City of India! Let's explore the best spots together!\n"
    "     [attraction: Lalbagh Botanical Garden]\n"
    "     We start our morning at the stunning Lalbagh Botanical Garden! The fresh morning air...\n"
    "     [attraction: Bangalore Palace]\n"
    "     Now, let us step into royalty at the magnificent Bangalore Palace...\n"
    "  3. Do NOT include any other director instructions, camera angles, sound effects, or scene transitions "
    "  in brackets or parentheses (e.g., do NOT output '[Opening Shot: ...]', '[Cut to: ...]', '(Morning)'). "
    "  The ONLY brackets allowed are the [attraction: ...] markers. Only output the actual spoken dialogue narration.\n"
    "  4. To achieve a highly expressive human tone and help the Text-to-Speech (TTS) engine speak with natural emotions and inflections, "
    "  write using conversational phrases, warm tones, and expressive punctuation (like exclamation marks '!', pauses '...', and emphasis words).\n"
    "- pics: A list of collected photo objects, where each object contains 'url' (from the src/large or image_url fields of tool results) and 'label' (name of the attraction or the city name).\n"
    "- videos: A list of collected video objects, where each object contains 'url' (from the video_url or link fields of tool results) and 'label' (name of the attraction or the city name).\n"
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

    def _compile_prompt(self, language: str, num_places: int, video_length: str) -> str:
        # Determine word length prompt
        length_desc = "about 250 words"  # medium
        if video_length == "short":
            length_desc = "about 120 words"
        elif video_length == "long":
            length_desc = "about 400 words"

        # Determine language instruction
        lang_instruction = ""
        if language != "en-IN":
            lang_map = {
                "hi-IN": "HINDI",
                "hi-Latn": "HINGLISH",
                "bn-IN": "BENGALI",
                "ta-IN": "TAMIL",
                "te-IN": "TELUGU",
                "gu-IN": "GUJARATI",
                "kn-IN": "KANNADA",
                "ml-IN": "MALAYALAM",
                "mr-IN": "MARATHI",
                "pa-IN": "PUNJABI",
                "od-IN": "ODIA"
            }
            lang_name = lang_map.get(language, "ENGLISH")
            if lang_name == "HINGLISH":
                lang_instruction = (
                    "\nCRITICAL LANGUAGE RULE: You MUST write the description message, script narration, "
                    "and all spoken dialog entirely in HINGLISH (which means Hindi language written using the English/Latin alphabet characters, e.g. "
                    "'Namaskar dosto, swagat hai aapka Bangalore Palace mein...'). "
                    "Do NOT translate or write in Devanagari script (Hindi characters). Use ONLY English letters for the script. "
                    "However, do NOT translate or change the attraction names inside the tags (like [attraction: Lalbagh Botanical Garden] and the 'label' keys in pics/videos). "
                    "The attraction tags/labels MUST remain in standard English so the media tool results match correctly."
                )
            else:
                lang_instruction = (
                    f"\nCRITICAL LANGUAGE RULE: You MUST write the description message, script narration, "
                    f"and all spoken dialog entirely in {lang_name}. However, do NOT translate the attraction names "
                    f"inside the tags (like [attraction: Lalbagh Botanical Garden] and the 'label' keys in pics/videos). "
                    f"The attraction tags/labels MUST remain in English so the media tool results match correctly."
                )

        prompt = (
            "You are a professional travel video producer, scriptwriter, and guide. "
            f"When a user asks about a city, area, or destination, you MUST identify exactly {num_places} top attractions "
            "or interesting places to visit in that city/area.\n"
            "CRITICAL SEARCH PROCESS:\n"
            "1. First, call the search_all_place_media tool with the general city name (e.g. 'Mangalore' or 'Paris') "
            "   to gather general city photos and videos. Label these assets with the city name (e.g. 'Mangalore'). These will be used for the video intro.\n"
            f"2. Then, call search_all_place_media ONCE for each of the {num_places} specific attractions. Label those with the attraction name.\n"
            "Do NOT call individual provider tools separately. Just use search_all_place_media.\n"
            "Your response must focus primarily on producing a detailed, full-length, professional video voiceover script. "
            "Populate the structured output schema with the following fields:\n"
            "- message: A brief 1-2 paragraph description/summary introduction of the city/area. Do NOT list/describe the attractions here.\n"
            f"- video_script: A detailed, highly engaging video voiceover script ({length_desc}) describing a travel itinerary "
            "or vlog walkthrough of the city.\n"
            "  CRITICAL SCRIPT RULES:\n"
            "  1. Start the script with a brief, highly engaging general introduction paragraph (about 30-40 words) that is NOT prefixed by any tag. "
            "     This serves as the 'Intro' segment of the video.\n"
            "  2. Immediately after the intro paragraph, insert the first attraction marker tag on its own line in the format: [attraction: Exact Attraction Name] "
            f"     followed by its narration text. Do this for all {num_places} attractions.\n"
            "     Example format:\n"
            "     Welcome to beautiful Bangalore, the vibrant Garden City of India! Let's explore the best spots together!\n"
            "     [attraction: Lalbagh Botanical Garden]\n"
            "     We start our morning at the stunning Lalbagh Botanical Garden! The fresh morning air...\n"
            "     [attraction: Bangalore Palace]\n"
            "     Now, let us step into royalty at the magnificent Bangalore Palace...\n"
            "  3. Do NOT include any other director instructions, camera angles, sound effects, or scene transitions "
            "  in brackets or parentheses (e.g., do NOT output '[Opening Shot: ...]', '[Cut to: ...]', '(Morning)'). "
            "  The ONLY brackets allowed are the [attraction: ...] markers. Only output the actual spoken dialogue narration.\n"
            "  4. To achieve a highly expressive human tone and help the Text-to-Speech (TTS) engine speak with natural emotions and inflections, "
            "  write using conversational phrases, warm tones, and expressive punctuation (like exclamation marks '!', pauses '...', and emphasis words).\n"
            "- pics: A list of collected photo objects, where each object contains 'url' (from the src/large or image_url fields of tool results) and 'label' (name of the attraction or the city name).\n"
            "- videos: A list of collected video objects, where each object contains 'url' (from the video_url or link fields of tool results) and 'label' (name of the attraction or the city name).\n"
            "Note: Do NOT output or write any image or video URLs in your text response outside the structured fields, as the system will extract them automatically."
            f"{lang_instruction}"
        )
        return prompt

    async def invoke(self, payload: ChatRequest) -> ChatResponse:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[Agent] Received user query: '{payload.message}'")
        logger.info(f"[Agent] Options — Lang: {payload.language}, Places: {payload.num_places}, Length: {payload.video_length}")
        logger.info("[Agent] Consulting LLM and preparing tool calls...")

        # Dynamically compile the prompt and create a request-specific agent instance
        system_prompt = self._compile_prompt(
            language=payload.language,
            num_places=payload.num_places,
            video_length=payload.video_length
        )
        agent = self._build_agent(system_prompt)

        result = await agent.ainvoke({"messages": [{"role": "user", "content": payload.message}]})

        import logging
        logger = logging.getLogger(__name__)

        try:
            messages = result.get("messages", []) if isinstance(result, dict) else []
        except Exception as e:
            logger.error(f"Failed to get messages from result. Type: {type(result)}, Error: {e}")
            logger.error(f"Result repr (first 500 chars): {repr(result)[:500]}")
            raise

        try:
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
                                    pics.append(MediaAsset(
                                        url=url,
                                        label=label,
                                        provider=photo.get("provider") or data.get("provider"),
                                        title=photo.get("title"),
                                        page_url=photo.get("page_url"),
                                        creator=photo.get("creator"),
                                        creator_url=photo.get("creator_url"),
                                        thumbnail_url=photo.get("thumbnail_url"),
                                    ))
                            # Extract videos
                            for video in data.get("videos", []):
                                url = video.get("video_url") or video.get("link")
                                if url:
                                    videos.append(MediaAsset(
                                        url=url,
                                        label=label,
                                        provider=video.get("provider") or data.get("provider"),
                                        title=video.get("title"),
                                        page_url=video.get("page_url"),
                                        creator=video.get("creator"),
                                        creator_url=video.get("creator_url"),
                                        thumbnail_url=video.get("thumbnail_url"),
                                        duration_seconds=video.get("duration_seconds"),
                                    ))
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
            structured = result.get("structured_response") if isinstance(result, dict) else None

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
                    raw = getattr(last_message, "content", str(last_message))
                    if isinstance(raw, list):
                        text_parts = []
                        for block in raw:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                                elif block.get("type") == "thinking":
                                    continue
                                else:
                                    text_parts.append(str(block))
                            elif isinstance(block, str):
                                text_parts.append(block)
                            else:
                                text_parts.append(str(block))
                        answer = "\n".join(text_parts)
                    else:
                        answer = str(raw)

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

            if not answer.strip():
                answer = "I apologize, but I encountered an issue while generating the city description. Please try submitting your request again."

            logger.info(
                f"[Agent] Finished query processing. "
                f"Generated description (~{len(answer.split())} words) and video script (~{len(video_script.split())} words). "
                f"Collected {len(pics)} photos and {len(videos)} videos in total."
            )

            return ChatResponse(
                message=answer,
                pics=pics,
                videos=videos,
                tool_data=tool_data,
                video_script=video_script
            )
        except Exception as e:
            logger.error(f"Error processing agent response: {type(e).__name__}: {e}", exc_info=True)
            raise


@lru_cache
def get_agent_service() -> AgentService:
    return AgentService(settings)
