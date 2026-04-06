import asyncio
import json
import re
from typing import AsyncIterator

from .base import LLMProvider

# Markers gemini-cli may emit that aren't part of the LLM response
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_STRIP_PATTERNS = [
    # Strip any lines that look like status headers or CLI chrome
    re.compile(r"^# .*", re.MULTILINE),
    re.compile(r"^> .*", re.MULTILINE),
    re.compile(r"^\s*gemini-cli.*$", re.MULTILINE),
]


class GeminiCLIProvider(LLMProvider):
    """Uses gemini -p <prompt> --approval-mode=yolo as LLM backend."""

    def __init__(self, timeout: int = 600):
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "gemini"

    async def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        full_prompt = self._build_prompt(prompt, system, json_mode)
        # Using -p for headless prompt and --approval-mode=yolo to auto-approve tool calls
        proc = await asyncio.create_subprocess_exec(
            "gemini", "-p", full_prompt, "--approval-mode=yolo",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"gemini-cli timed out after {self._timeout}s")
        
        if proc.returncode != 0:
            err_msg = stderr.decode()
            raise RuntimeError(f"gemini-cli failed with code {proc.returncode}: {err_msg}")
            
        raw = stdout.decode()
        return self._extract_response(raw, json_mode)

    async def complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        # For now, yield the full response as a single chunk.
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
            # Try to extract JSON from the response (it might be wrapped in markdown)
            # Look for JSON block or just braces/brackets
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
            else:
                match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
                if match:
                    text = match.group(1)
            
            # Basic validation
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError:
                pass
                
        return text
