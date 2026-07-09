from functools import lru_cache
from typing import Any

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import Settings, settings
from app.schemas.chat import ChatRequest, ChatResponse

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise, helpful travel planning assistant. "
    "Ask for missing constraints when they are necessary, and otherwise provide practical answers."
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
            tools=[],
            system_prompt=system_prompt,
        )

    async def invoke(self, payload: ChatRequest) -> ChatResponse:
        prompt = payload.system_prompt or DEFAULT_SYSTEM_PROMPT
        if prompt == DEFAULT_SYSTEM_PROMPT:
            if self._agent is None:
                self._agent = self._build_agent(DEFAULT_SYSTEM_PROMPT)
            agent = self._agent
        else:
            agent = self._build_agent(prompt)

        result = await agent.ainvoke({"messages": [{"role": "user", "content": payload.message}]})
        answer = _extract_answer(result)
        return ChatResponse(answer=answer, model=self.settings.gemma_model)


def _extract_answer(result: Any) -> str:
    messages = result.get("messages", []) if isinstance(result, dict) else []
    if not messages:
        return str(result)

    last_message = messages[-1]
    content = getattr(last_message, "content", last_message)
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", item)) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


@lru_cache
def get_agent_service() -> AgentService:
    return AgentService(settings)
