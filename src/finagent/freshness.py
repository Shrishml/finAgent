"""Data freshness — confidence scoring for time-sensitive financial data."""
from datetime import datetime

# Half-life in days: confidence drops to 0.5 after this many days
DECAY_HALF_LIFE = {
    # Fast decay — changes frequently
    "insurance": 180,
    # Medium decay — changes with job/life events
    "income": 180,
    "expenses": 120,
    "loan": 180,
    "mf_declared": 90,
    # Slow decay — rarely changes
    "personal": 730,
    "epf_ppf": 365,
    "nps": 365,
    "fd": 180,
    "gold": 365,
    "real_estate": 730,
    "esop": 180,
    "meta": 9999,  # never stale
}

DEFAULT_HALF_LIFE = 180  # 6 months for unknown types


def get_confidence(asset_type: str, updated_at: str | None) -> float:
    """Return confidence 0.0–1.0 based on how stale the data is.

    Uses exponential decay: confidence = 0.5 ^ (days_old / half_life)
    """
    if not updated_at:
        return 0.0
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        days_old = (datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds() / 86400
    except (ValueError, AttributeError):
        return 0.0
    if days_old < 0:
        days_old = 0
    half_life = DECAY_HALF_LIFE.get(asset_type, DEFAULT_HALF_LIFE)
    return 0.5 ** (days_old / half_life)


def freshness_label(confidence: float) -> str:
    """Human-readable label for confidence score."""
    if confidence >= 0.8:
        return "fresh"
    if confidence >= 0.5:
        return "aging"
    return "stale"


def get_stale_fields(assets: list[dict], threshold: float = 0.5) -> list[dict]:
    """Return assets with confidence below threshold."""
    stale = []
    for a in assets:
        conf = get_confidence(a.get("asset_type", ""), a.get("updated_at"))
        if conf < threshold:
            stale.append({
                "asset_type": a.get("asset_type"),
                "confidence": round(conf, 2),
                "label": freshness_label(conf),
                "updated_at": a.get("updated_at"),
            })
    return stale
