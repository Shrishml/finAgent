import logging
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator

log = logging.getLogger("finagent")


class LLMProvider(ABC):
    """Abstract base for all LLM providers (CLI or API)."""

    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        """Send prompt, get response. json_mode forces JSON output."""
        log.debug(f"[llm:{self.name}] >>> CALL complete (json_mode={json_mode})")
        log.debug(f"[llm:{self.name}] system={system[:200]}{'...' if len(system)>200 else ''}")
        log.debug(f"[llm:{self.name}] prompt={prompt[:500]}{'...' if len(prompt)>500 else ''}")
        t0 = time.time()
        result = await self._complete(prompt, system, json_mode)
        log.debug(f"[llm:{self.name}] <<< RESPONSE ({time.time()-t0:.1f}s, {len(result)} chars): {result[:300]}{'...' if len(result)>300 else ''}")
        return result

    async def complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        """Streaming response for chat UI."""
        log.debug(f"[llm:{self.name}] >>> STREAM complete")
        log.debug(f"[llm:{self.name}] system={system[:200]}{'...' if len(system)>200 else ''}")
        log.debug(f"[llm:{self.name}] prompt={prompt[:500]}{'...' if len(prompt)>500 else ''}")
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
