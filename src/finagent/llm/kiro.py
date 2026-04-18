import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

from .base import LLMProvider

log = logging.getLogger("finagent")

# Markers kiro-cli may emit that aren't part of the LLM response
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\[(?:[0-9;]+)m')
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

    async def _complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        full_prompt = self._build_prompt(prompt, system, json_mode)
        log.info(f"[kiro] calling kiro-cli (timeout={self._timeout}s, json_mode={json_mode})")
        t0 = time.time()
        proc = await asyncio.create_subprocess_exec(
            "kiro-cli", "chat", "--no-interactive", "--trust-all-tools", full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            log.error(f"[kiro] TIMEOUT after {self._timeout}s")
            raise TimeoutError(f"kiro-cli timed out after {self._timeout}s")
        raw = stdout.decode()
        log.info(f"[kiro] completed in {time.time()-t0:.1f}s, response_len={len(raw)}")
        return self._extract_response(raw, json_mode)

    async def _complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        full_prompt = self._build_prompt(prompt, system, False)
        log.info(f"[kiro] streaming kiro-cli")
        proc = await asyncio.create_subprocess_exec(
            "kiro-cli", "chat", "--no-interactive", "--trust-all-tools", full_prompt,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            async for line in proc.stdout:
                yield line.decode()
        finally:
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()

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
