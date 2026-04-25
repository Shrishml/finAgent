"""User financial profile — reconstructed from user_assets (single storage)."""
from dataclasses import dataclass, field


@dataclass
class UserProfile:
    """Complete financial profile built from user_assets table."""
    user_id: int

    # Personal (asset_type='personal')
    name: str = ""
    age: int = 0
    occupation: str = ""
    employer: str = ""
    location: str = ""
    marital_status: str = ""       # Single | Married
    kids: int = 0
    dependent_parents: str = ""
    parents_health_insurance: str = ""
    risk_tolerance: str = ""       # Conservative | Moderate | Aggressive

    # Income (asset_type='income')
    monthly_income: float = 0
    annual_bonus: float = 0
    spouse_income: float = 0
    other_income: float = 0
    annual_rsu: float = 0

    # Expenses (asset_type='expenses')
    total_monthly_expenses: float = 0
    rent: float = 0
    groceries: float = 0
    utilities: float = 0
    dining: float = 0
    annual_big_ticket: float = 0
    emis: float = 0

    # Insurance (asset_type='insurance')
    term_cover: float = 0
    term_premium: float = 0
    health_cover: float = 0
    health_premium: float = 0

    # Onboarding state (asset_type='meta')
    onboarding_complete: bool = False

    # Legacy compat
    monthly_expenses: float = 0  # alias for total_monthly_expenses
    total_investments: float = 0
    loans: list[dict] = field(default_factory=list)
    goals_mentioned: list[str] = field(default_factory=list)
    health_employer_only: bool = True
    dependents: int = 0
    tax_regime: str = ""
    section_80c_used: float = 0
    pillars_completed: list[str] = field(default_factory=list)
    pillars_skipped: list[str] = field(default_factory=list)
    financial_snapshot: str = ""

    @property
    def savings_rate(self) -> float | None:
        inc = self.monthly_income
        exp = (self.total_monthly_expenses or self.monthly_expenses) + self.emis
        if inc <= 0:
            return None
        return (inc - exp) / inc

    @property
    def total_emi(self) -> float:
        return sum(l.get("emi", 0) for l in self.loans)
