import json
from pathlib import Path

_config: dict | None = None
_SRC_DIR = Path(__file__).parent.parent

# Try TOML first (Python 3.11+), fall back to JSON
def _load_toml(path: Path) -> dict:
    try:
        import tomllib
    except ImportError:
        try:
            import toml
            return toml.load(path)
        except ImportError:
            raise ImportError("Python 3.11+ or 'pip install toml' required for TOML config")
    with open(path, "rb") as f:
        return tomllib.load(f)


def get_config() -> dict:
    global _config
    if _config is not None:
        return _config

    # Try config.toml
    toml_path = _SRC_DIR / "config.toml"
    toml_example = _SRC_DIR / "config.toml.example"
    json_path = _SRC_DIR / "config.json"

    for path in (toml_path, toml_example):
        if path.exists():
            try:
                _config = _load_toml(path)
                return _config
            except ImportError:
                pass  # Fall through to JSON

    if json_path.exists():
        _config = json.loads(json_path.read_text())
        return _config

    # Defaults
    _config = {"llm": {"default": "kiro"}, "server": {"host": "127.0.0.1", "port": 8000}}
    return _config
