from functools import lru_cache
import json
import logging
from typing import Any

from langgraph.prebuilt import create_react_agent
from langchain_core.messages import ToolMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import Settings, settings
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    EditScriptRequest,
    MediaAsset,
    ToolCallData,
)
from app.services.media_tools import get_media_tools


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
        self._llm: ChatGoogleGenerativeAI | None = None

    def _build_llm(self) -> ChatGoogleGenerativeAI:
        if self._llm is None:
            if not self.settings.google_api_key:
                raise ValueError("GOOGLE_API_KEY is missing. Add it to .env before calling /chat.")
            self._llm = ChatGoogleGenerativeAI(
                model=self.settings.gemma_model,
                google_api_key=self.settings.google_api_key,
                temperature=self.settings.llm_temperature,
                max_output_tokens=self.settings.llm_max_output_tokens,
                timeout=self.settings.request_timeout_seconds,
            )
        return self._llm

    def _build_agent(self, system_prompt: str) -> Any:
        return create_react_agent(
            self._build_llm(),
            get_media_tools(),
            prompt=system_prompt,
        )

    def _compile_prompt(self, language: str, num_places: int, video_length: str, script_style: str = "reel") -> str:
        # Determine word length prompt
        length_desc = "about 250 words"  # medium
        if video_length == "short":
            length_desc = "about 120 words"
        elif video_length == "long":
            length_desc = "about 400 words"

        # Narration style block, injected into the script rules below.
        if script_style == "classic":
            style_instructions = (
                "  SCRIPT STYLE — CLASSIC GUIDE:\n"
                "  Write a warm, professional travel-guide voiceover: an engaging general introduction, then "
                "  vivid, descriptive narration for each attraction in turn.\n"
            )
        else:  # "reel"
            style_instructions = (
                "  SCRIPT STYLE — SOCIAL TRAVEL REEL (write like a punchy, first-person travel reel for a young audience):\n"
                "  a) Open the intro paragraph with a direct, aspirational HOOK spoken to the viewer ('you'), framing the "
                "     destination as an underrated, hidden-gem escape.\n"
                "  b) Weave PRACTICAL trip info naturally into the narration (conversationally, not as a list): an approximate "
                "     total trip budget, how to reach the place (e.g. train/bus/bike/rental), and rough hotel and food cost ranges. "
                "     Use the currency that fits the destination.\n"
                f"  c) Present the {num_places} attractions as a DAY-WISE itinerary (Day 1, Day 2, ...), using flow phrases like "
                "     'start your morning at...', 'in the evening head to...', 'on day two...'. Each attraction STILL gets its own "
                "     [attraction: Exact Name] marker line before its narration.\n"
                "  d) End the final attraction's narration with a short, social CALL TO ACTION (e.g. save this video and share it "
                "     with the travel buddy you'd take here).\n"
                "  Keep the tone casual, energetic, and direct.\n"
            )

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
            "Your response must focus solely on producing a detailed, full-length, professional video voiceover script. "
            "Populate the structured output schema with the following fields:\n"
            f"- video_script: A detailed, highly engaging video voiceover script ({length_desc}) describing a travel itinerary "
            "or vlog walkthrough of the city.\n"
            f"{style_instructions}"
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
        logger = logging.getLogger(__name__)
        logger.info(f"[Agent] Received user query: '{payload.message}'")
        logger.info(f"[Agent] Options — Lang: {payload.language}, Places: {payload.num_places}, Length: {payload.video_length}")
        logger.info("[Agent] Consulting LLM and preparing tool calls...")

        # Set the context-local current city name for query sanitization in search tools
        from app.services.media_tools import set_current_city
        set_current_city(payload.message)

        # Dynamically compile the prompt and create a request-specific agent instance
        system_prompt = self._compile_prompt(
            language=payload.language,
            num_places=payload.num_places,
            video_length=payload.video_length,
            script_style=payload.script_style,
        )
        agent = self._build_agent(system_prompt)

        result = await agent.ainvoke({"messages": [{"role": "user", "content": payload.message}]})

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

            # Extract the video script. The separate destination-summary
            # ("message") field has been removed — the script is the only
            # narrative output the agent produces.
            video_script = ""
            structured = result.get("structured_response") if isinstance(result, dict) else None

            if structured:
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

            # Fallback to tag/JSON parsing if a structured response is missing.
            if not video_script:
                raw_text = ""
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
                        raw_text = self._flatten_content(msg.content)
                        break
                if not raw_text and messages:
                    raw_text = self._flatten_content(
                        getattr(messages[-1], "content", str(messages[-1]))
                    )

                # 1. Try parsing as raw or markdown-fenced JSON
                clean = raw_text.strip()
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    if lines[0].strip().startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip().startswith("```"):
                        lines = lines[:-1]
                    clean = "\n".join(lines).strip()

                parsed_json = None
                try:
                    parsed_json = json.loads(clean)
                except Exception:
                    try:
                        parsed_json = json.loads(repair_json_string(clean))
                    except Exception:
                        pass

                if isinstance(parsed_json, dict) and "video_script" in parsed_json:
                    video_script = parsed_json.get("video_script", "")
                    if "pics" in parsed_json:
                        merge_media(pics, parsed_json["pics"])
                    if "videos" in parsed_json:
                        merge_media(videos, parsed_json["videos"])
                else:
                    # 2. Try extracting a <video_script> tag block
                    lower = raw_text.lower()
                    tag_start = lower.find("<video_script>")
                    if tag_start != -1:
                        rest = raw_text[tag_start + len("<video_script>"):]
                        tag_end = rest.lower().find("</video_script>")
                        video_script = rest[:tag_end].strip() if tag_end != -1 else rest.strip()
                    else:
                        # 3. No JSON, no tags — treat the whole text as the script.
                        video_script = raw_text.strip()

            logger.info(
                f"[Agent] Finished query processing. "
                f"Generated video script (~{len(video_script.split())} words). "
                f"Collected {len(pics)} photos and {len(videos)} videos in total."
            )

            return ChatResponse(
                pics=pics,
                videos=videos,
                tool_data=tool_data,
                video_script=video_script
            )
        except Exception as e:
            logger.error(f"Error processing agent response: {type(e).__name__}: {e}", exc_info=True)
            raise

    @staticmethod
    def _flatten_content(content: Any) -> str:
        """Collapse an LLM message's content (str or list of blocks) into text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        continue
                    else:
                        parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p)
        return str(content)

    async def edit_script(self, payload: EditScriptRequest) -> str:
        """Revise an existing voiceover script per a natural-language instruction,
        preserving the [attraction: ...] markers and formatting rules. No media
        tools are involved — this is a pure LLM rewrite of the provided script."""
        logger = logging.getLogger(__name__)
        logger.info(f"[Agent] Editing script with instruction: '{payload.instruction[:120]}'")

        llm = self._build_llm()

        style_note = (
            "Keep the punchy, first-person social-reel tone (hook, day-wise itinerary, "
            "practical budget/travel notes, closing call to action)."
            if payload.script_style != "classic"
            else "Keep the warm, professional travel-guide tone."
        )

        lang_note = ""
        if payload.language and payload.language != "en-IN":
            lang_note = (
                f"\nWrite the narration in the same language as the original script "
                f"(target locale: {payload.language}). Do NOT translate the attraction "
                f"names inside the [attraction: ...] markers — keep those in English."
            )

        system_prompt = (
            "You are a professional travel video script editor. You will be given an existing "
            "voiceover narration script and an edit instruction. Apply the instruction and return "
            "the FULL revised script.\n"
            "STRICT RULES you must preserve:\n"
            "1. Keep every attraction as its own block, each introduced by a marker line in the exact "
            "format [attraction: Exact Attraction Name] followed by its spoken narration. Do not rename, "
            "add, or remove attractions unless the instruction explicitly asks you to.\n"
            "2. Start with a short, untagged intro paragraph (no marker), just like the original.\n"
            "3. The ONLY brackets allowed are the [attraction: ...] markers. Do NOT add camera directions, "
            "scene notes, or sound cues in brackets or parentheses. Output ONLY spoken narration.\n"
            f"4. {style_note}"
            f"{lang_note}\n"
            "Return ONLY the revised script text — no preamble, no explanation, no markdown code fences."
        )

        user_prompt = (
            f"CURRENT SCRIPT:\n{payload.current_script}\n\n"
            f"EDIT INSTRUCTION:\n{payload.instruction}\n\n"
            "Now output the full revised script."
        )

        result = await llm.ainvoke(
            [("system", system_prompt), ("human", user_prompt)]
        )
        revised = self._flatten_content(getattr(result, "content", result)).strip()

        # Strip an accidental markdown code fence if the model wrapped the output.
        if revised.startswith("```"):
            lines = revised.split("\n")
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            revised = "\n".join(lines).strip()

        if not revised:
            # Fall back to the original so the caller never loses the user's script.
            logger.warning("[Agent] Script edit produced empty output; returning original.")
            return payload.current_script

        logger.info(f"[Agent] Script edited (~{len(revised.split())} words).")
        return revised


@lru_cache
def get_agent_service() -> AgentService:
    return AgentService(settings)
