from dataclasses import dataclass, field


@dataclass
class FinancialSummary:
    """Thin adapter for cross-domain reasoning. This is all the orchestrator sees."""

    product_type: str          # "mutual_fund", "insurance", "loan"
    product_name: str          # "Axis Bluechip Fund - Direct Growth"
    annual_cost: float         # Total annual cost to the user
    current_value: float       # Current value or coverage amount
    currency: str = "INR"      # Multi-currency support
    tax_sections: list[str] = field(default_factory=list)  # ["80C", "80D"]
    risk_tags: list[str] = field(default_factory=list)     # ["equity", "large_cap"]
    liquidity: str = "unknown" # "instant", "t+3", "locked_3yr", "illiquid"
    metadata: dict = field(default_factory=dict)           # Agent-specific extras
