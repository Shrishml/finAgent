"""User financial profile for advisor onboarding."""
from dataclasses import dataclass, field

PILLAR_ORDER = ["income", "expenses", "assets", "liabilities", "insurance", "goals"]


@dataclass
class UserProfile:
    """Complete financial profile built through conversational onboarding."""
    user_id: int

    # Pillar 1: Income
    monthly_income: float = 0
    annual_bonus: float = 0
    spouse_income: float = 0
    other_income: float = 0

    # Pillar 2: Expenses
    monthly_expenses: float = 0
    rent: float = 0
    emis: float = 0

    # Pillar 3: Assets — computed from holdings table, no fields here

    # Pillar 4: Liabilities
    loans: list[dict] = field(default_factory=list)
    # [{"type": "home", "principal": 4000000, "rate": 8.5, "emi": 35000, "remaining_months": 180}]

    # Pillar 5: Insurance
    term_cover: float = 0
    health_cover: float = 0
    health_employer_only: bool = True

    # Pillar 6: Goals
    goals_mentioned: list[str] = field(default_factory=list)

    # Demographics
    age: int = 0
    dependents: int = 0
    occupation: str = ""
    employer: str = ""
    risk_tolerance: str = ""  # conservative | moderate | aggressive

    # Tax
    tax_regime: str = ""  # old | new
    section_80c_used: float = 0

    # Onboarding state
    pillars_completed: list[str] = field(default_factory=list)
    pillars_skipped: list[str] = field(default_factory=list)
    onboarding_complete: bool = False

    @property
    def current_pillar(self) -> str | None:
        """Next pillar to complete in strict order."""
        for p in PILLAR_ORDER:
            if p not in self.pillars_completed and p not in self.pillars_skipped:
                return p
        return None

    @property
    def savings_rate(self) -> float | None:
        """Monthly savings as percentage of income."""
        if self.monthly_income <= 0:
            return None
        return (self.monthly_income - self.monthly_expenses) / self.monthly_income

    @property
    def total_emi(self) -> float:
        """Sum of all loan EMIs."""
        return sum(l.get("emi", 0) for l in self.loans)
