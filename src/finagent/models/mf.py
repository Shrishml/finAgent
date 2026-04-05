from dataclasses import dataclass, field
from datetime import date

from .summary import FinancialSummary


@dataclass
class MFTransaction:
    """A single mutual fund transaction."""

    date: date
    description: str
    amount: float
    units: float | None = None
    nav: float | None = None
    balance: float | None = None
    type: str = ""  # PURCHASE, SIP, REDEMPTION, SWITCH_IN, etc.


@dataclass
class MFHolding:
    """Rich model for a single mutual fund scheme in a folio."""

    # Identity
    scheme_name: str
    folio: str
    amc: str
    isin: str = ""
    amfi_code: str = ""
    plan: str = ""  # "direct" or "regular"
    rta: str = ""   # "CAMS" or "KFINTECH"

    # Current state
    units: float = 0.0
    nav: float = 0.0
    current_value: float = 0.0
    invested_value: float = 0.0

    # Cost
    expense_ratio: float = 0.0
    annual_expense: float = 0.0  # expense_ratio × current_value
    category: str = ""  # e.g. "Equity - Large Cap", "Debt - Short Duration"

    # Performance
    xirr: float = 0.0

    # Tax
    tax_section: str = ""  # "80C" for ELSS, empty for others

    # Transactions
    transactions: list[MFTransaction] = field(default_factory=list)

    def to_summary(self) -> FinancialSummary:
        """Adapter: rich model → thin summary for orchestrator."""
        risk_tags = []
        if self.expense_ratio > 0.01:
            risk_tags.append("high_expense")
        if self.plan == "regular":
            risk_tags.append("regular_plan")

        return FinancialSummary(
            product_type="mutual_fund",
            product_name=self.scheme_name,
            annual_cost=self.annual_expense,
            current_value=self.current_value,
            tax_sections=["80C"] if self.tax_section == "80C" else [],
            risk_tags=risk_tags,
            liquidity="locked_3yr" if self.tax_section == "80C" else "t+3",
            metadata={"xirr": self.xirr, "expense_ratio": self.expense_ratio, "folio": self.folio},
        )
