import shutil

from .base import LLMProvider
from .kiro import KiroCLIProvider
from .gemini import GeminiCLIProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "kiro": KiroCLIProvider,
    "gemini": GeminiCLIProvider,
    "gemini-cli": GeminiCLIProvider,
}

_instances: dict[str, LLMProvider] = {}


def get_provider(role: str = "default") -> LLMProvider:
    """Get an LLM provider instance by role (default, parsing, reasoning).

    Reads from config to determine which provider to use for each role.
    Falls back to 'default' if role-specific config is missing.
    """
    from finagent.config import get_config

    cfg = get_config()
    llm_cfg = cfg.get("llm", {})
    provider_name = llm_cfg.get(role, llm_cfg.get("default", "kiro"))

    if provider_name not in _instances:
        cls = _PROVIDERS.get(provider_name)
        if cls is None:
            available = ", ".join(_PROVIDERS.keys())
            raise ValueError(f"Unknown LLM provider '{provider_name}'. Available: {available}")
        # Check if CLI tool exists
        if provider_name in ("kiro",) and not shutil.which("kiro-cli"):
            raise RuntimeError(
                "kiro-cli not found. Install it or configure an API key in config.toml"
            )
        if provider_name in ("gemini", "gemini-cli") and not shutil.which("gemini"):
            raise RuntimeError(
                "gemini (Gemini CLI) not found. Install it or configure an API key in config.toml"
            )
        _instances[provider_name] = cls()

    return _instances[provider_name]
