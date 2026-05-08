import logging
import os
import shutil

from .base import LLMProvider
from .kiro import KiroCLIProvider
from .gemini import GeminiCLIProvider
from .gemini_api import GeminiAPIProvider

log = logging.getLogger("finagent")

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "kiro": KiroCLIProvider,
    "gemini": GeminiCLIProvider,
    "gemini-cli": GeminiCLIProvider,
    "gemini-api": GeminiAPIProvider,
}

# Detection order: prefer kiro-cli first, then gemini-api if key set, then gemini-cli
_DETECT_ORDER = [("kiro", "kiro-cli"), ("gemini-api", None), ("gemini", "gemini")]

_instances: dict[str, LLMProvider] = {}


def _auto_detect() -> str:
    """Find the first available LLM provider."""
    for provider_name, cli_cmd in _DETECT_ORDER:
        if cli_cmd is None:
            # API-based provider — check for env var
            if provider_name == "gemini-api" and os.environ.get("GEMINI_API_KEY"):
                return provider_name
        elif shutil.which(cli_cmd):
            return provider_name
        else:
            log.debug(f"[llm] auto-detect: {cli_cmd} not found on PATH={os.environ.get('PATH', 'unset')}")
    log.error(f"[llm] No LLM found. PATH={os.environ.get('PATH', 'unset')}")
    raise RuntimeError(
        "No LLM found. Set GEMINI_API_KEY env var, or install gemini CLI or kiro-cli."
    )


def get_provider(role: str = "default") -> LLMProvider:
    """Get an LLM provider instance by role (default, parsing, reasoning).

    Reads from config to determine which provider to use for each role.
    If set to "auto" or not found on PATH, auto-detects the best available.
    """
    from finagent.config import get_config

    cfg = get_config()
    llm_cfg = cfg.get("llm", {})
    provider_name = llm_cfg.get(role, llm_cfg.get("default", "auto"))

    # Auto-detect if configured as "auto" or if the configured provider isn't installed
    if provider_name == "auto":
        provider_name = _auto_detect()
    elif provider_name in _PROVIDERS:
        cls = _PROVIDERS[provider_name]
        # Check if the configured CLI actually exists, fall back to auto-detect
        cli_map = {"kiro": "kiro-cli", "gemini": "gemini", "gemini-cli": "gemini"}
        cli_cmd = cli_map.get(provider_name)
        if cli_cmd and not shutil.which(cli_cmd):
            provider_name = _auto_detect()

    if provider_name not in _instances:
        cls = _PROVIDERS.get(provider_name)
        if cls is None:
            available = ", ".join(_PROVIDERS.keys())
            raise ValueError(f"Unknown LLM provider '{provider_name}'. Available: {available}")
        _instances[provider_name] = cls()
        log.info(f"[llm] initialized provider={provider_name} for role={role}")

    return _instances[provider_name]
