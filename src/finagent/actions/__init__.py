"""Action registry — auto-discovers all action modules in this package."""
import importlib
import pkgutil

ACTION_REGISTRY: dict[str, dict] = {}

for _, name, _ in pkgutil.iter_modules(__path__):
    if name == "base":
        continue
    mod = importlib.import_module(f".{name}", __package__)
    if hasattr(mod, "SCHEMA") and hasattr(mod, "execute"):
        ACTION_REGISTRY[mod.SCHEMA["name"]] = {
            "schema": mod.SCHEMA,
            "execute": mod.execute,
        }


def get_tools_prompt() -> str:
    """Build tool descriptions for LLM system prompt."""
    if not ACTION_REGISTRY:
        return ""
    lines = [
        "\n\nYou have these tools available. Call a tool ONLY when the user's request requires creating, searching, or modifying something — not for general advice.",
        "To call a tool, include this exact marker in your response:",
        "[ACTION: tool_name(param1=value1, param2=value2)]",
        "",
        "Available tools:",
    ]
    for name, entry in ACTION_REGISTRY.items():
        s = entry["schema"]
        params = ", ".join(
            f"{p}" + (" (required)" if v.get("required") else "")
            for p, v in s.get("parameters", {}).items()
        )
        lines.append(f"- {name}({params}): {s['description']}")
    lines.append("\nOnly call a tool when you have all required parameters from the user. If missing, ask first.")
    return "\n".join(lines)
