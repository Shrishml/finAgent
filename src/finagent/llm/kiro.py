import asyncio
import json
import re
from typing import AsyncIterator

from .base import LLMProvider

# Markers kiro-cli may emit that aren't part of the LLM response
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_STRIP_PATTERNS = [
    re.compile(r"^╭.*╮$", re.MULTILINE),
    re.compile(r"^╰.*╯$", re.MULTILINE),
    re.compile(r"^│.*│$", re.MULTILINE),
    re.compile(r"^\s*kiro-cli.*$", re.MULTILINE),
]


class KiroCLIProvider(LLMProvider):
    """Uses kiro-cli chat --no-interactive as LLM backend."""

    def __init__(self, timeout: int = 120):
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "kiro"

    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        full_prompt = self._build_prompt(prompt, system, json_mode)
        proc = await asyncio.create_subprocess_exec(
            "kiro-cli", "chat", "--no-interactive", "--trust-all-tools", full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"kiro-cli timed out after {self._timeout}s")
        raw = stdout.decode()
        return self._extract_response(raw, json_mode)

    async def complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        # For now, yield the full response as a single chunk.
        # True streaming can be added later by reading stdout line-by-line.
        result = await self.complete(prompt, system)
        yield result

    def _build_prompt(self, prompt: str, system: str, json_mode: bool) -> str:
        parts = []
        if system:
            parts.append(f"[System instruction: {system}]")
        if json_mode:
            parts.append("You MUST respond with valid JSON only. No markdown, no explanation.")
        parts.append(prompt)
        return "\n\n".join(parts)

    def _extract_response(self, raw: str, json_mode: bool) -> str:
        text = _ANSI_RE.sub("", raw)  # strip ANSI color codes first
        for pat in _STRIP_PATTERNS:
            text = pat.sub("", text)
        text = text.strip()
        if json_mode:
            # Try to extract JSON from the response
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    json.loads(match.group())
                    return match.group()
                except json.JSONDecodeError:
                    pass
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                try:
                    json.loads(match.group())
                    return match.group()
                except json.JSONDecodeError:
                    pass
        return text
