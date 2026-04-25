"""Goal-based financial planning models."""
from dataclasses import dataclass, field


GOAL_TEMPLATES = {
    "retirement": {"label": "🏖️ Retirement", "default_growth": 0.12, "suggested_amount": 10_000_000},
    "house": {"label": "🏠 House", "default_growth": 0.10, "suggested_amount": 5_000_000},
    "education": {"label": "🎓 Education", "default_growth": 0.12, "suggested_amount": 2_500_000},
    "car": {"label": "🚗 Car", "default_growth": 0.08, "suggested_amount": 1_000_000},
    "marriage": {"label": "💍 Marriage", "default_growth": 0.10, "suggested_amount": 1_500_000},
    "emergency": {"label": "🚨 Emergency Fund", "default_growth": 0.07, "suggested_amount": 300_000},
    "travel": {"label": "✈️ Travel", "default_growth": 0.08, "suggested_amount": 200_000},
    "custom": {"label": "⚙️ Custom", "default_growth": 0.10, "suggested_amount": 0},
}


@dataclass
class Goal:
    """A user's financial goal linked to holdings."""
    user_id: int
    name: str
    template: str  # key from GOAL_TEMPLATES
    target_amount: float
    target_date: str  # ISO date "2035-01-01"
    linked_folios: list = field(default_factory=list)  # [{"folio": "F1/Scheme", "pct": 60}, ...]
    growth_rate: float = 0.0  # 0 = use template default
    status: str = "active"  # "active" or "suggested"
    id: int | None = None
    created_at: str = ""

    def __post_init__(self):
        if self.growth_rate == 0 and self.template in GOAL_TEMPLATES:
            self.growth_rate = GOAL_TEMPLATES[self.template]["default_growth"]
