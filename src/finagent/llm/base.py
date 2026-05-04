import logging
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator

from finagent.tracing.decorators import traced_llm, traced_llm_stream

log = logging.getLogger("finagent")


class LLMProvider(ABC):
    """Abstract base for all LLM providers (CLI or API)."""

    @traced_llm
    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        """Send prompt, get response. json_mode forces JSON output."""
        log.debug(f"[llm:{self.name}] >>> CALL complete (json_mode={json_mode})")
        log.debug(f"[llm:{self.name}] system={system.replace(chr(10),' ')}")
        log.debug(f"[llm:{self.name}] prompt={prompt.replace(chr(10),' ')}")
        t0 = time.time()
        result = await self._complete(prompt, system, json_mode)
        log.debug(f"[llm:{self.name}] <<< RESPONSE ({time.time()-t0:.1f}s, {len(result)} chars): {result.replace(chr(10),' ')}")
        return result

    @traced_llm_stream
    async def complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        """Streaming response for chat UI."""
        log.debug(f"[llm:{self.name}] >>> STREAM complete")
        log.debug(f"[llm:{self.name}] system={system.replace(chr(10),' ')}")
        log.debug(f"[llm:{self.name}] prompt={prompt.replace(chr(10),' ')}")
        async for chunk in self._complete_stream(prompt, system):
            yield chunk

    @abstractmethod
    async def _complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        """Provider implementation of complete."""

    @abstractmethod
    async def _complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        """Provider implementation of streaming."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier for logging."""
