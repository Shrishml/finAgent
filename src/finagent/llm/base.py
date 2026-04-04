from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    """Abstract base for all LLM providers (CLI or API)."""

    @abstractmethod
    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        """Send prompt, get response. json_mode forces JSON output."""

    @abstractmethod
    async def complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        """Streaming response for chat UI."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier for logging."""
