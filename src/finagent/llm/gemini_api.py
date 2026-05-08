"""Gemini API provider — direct HTTP call, no CLI overhead."""
import json
import logging
import os
import time
from typing import AsyncIterator

from .base import LLMProvider

log = logging.getLogger("finagent")

_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


class GeminiAPIProvider(LLMProvider):
    def __init__(self, model: str = "gemini-2.0-flash", timeout: int = 120):
        self._model = model
        self._timeout = timeout
        self._key = os.environ.get("GEMINI_API_KEY", "")

    @property
    def name(self) -> str:
        return "gemini-api"

    async def _complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str:
        import urllib.request
        import urllib.error

        if not self._key:
            raise RuntimeError("GEMINI_API_KEY not set. Get one free at https://aistudio.google.com/apikey")

        parts = []
        if system:
            parts.append(f"[System: {system}]")
        if json_mode:
            parts.append("Respond with valid JSON only. No markdown, no explanation.")
        parts.append(prompt)

        body = json.dumps({
            "contents": [{"parts": [{"text": "\n\n".join(parts)}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
        }).encode()

        url = _API_URL.format(model=self._model, key=self._key)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

        log.info(f"[gemini-api] calling {self._model} (timeout={self._timeout}s, json_mode={json_mode})")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:500]
            log.error(f"[gemini-api] HTTP {e.code}: {err}")
            raise RuntimeError(f"Gemini API error {e.code}: {err}")

        text = data["candidates"][0]["content"]["parts"][0]["text"]
        log.info(f"[gemini-api] completed in {time.time()-t0:.1f}s, response_len={len(text)}")

        if json_mode:
            # Extract JSON from possible markdown wrapping
            import re
            m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if m:
                return m.group(1)
            m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if m:
                try:
                    json.loads(m.group(1))
                    return m.group(1)
                except json.JSONDecodeError:
                    pass
        return text

    async def _complete_stream(self, prompt: str, system: str = "") -> AsyncIterator[str]:
        yield await self._complete(prompt, system)
