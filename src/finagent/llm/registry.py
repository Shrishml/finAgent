import shutil

from .base import LLMProvider
from .kiro import KiroCLIProvider
from .gemini import GeminiCLIProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "kiro": KiroCLIProvider,
    "gemini": GeminiCLIProvider,
    "gemini-cli": GeminiCLIProvider,
}

# Detection order: prefer gemini if available, then kiro
_DETECT_ORDER = [("gemini", "gemini"), ("kiro", "kiro-cli")]

_instances: dict[str, LLMProvider] = {}


def _auto_detect() -> str:
    """Find the first available LLM CLI tool on this machine."""
    for provider_name, cli_cmd in _DETECT_ORDER:
        if shutil.which(cli_cmd):
            return provider_name
    raise RuntimeError(
        "No LLM CLI found. Install gemini (Gemini CLI) or kiro-cli."
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

    return _instances[provider_name]
