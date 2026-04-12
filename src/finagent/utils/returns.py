"""Portfolio return calculations (stdlib-only)."""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finagent.models.mf import MFHolding


def _xirr_newton(cashflows: list[tuple[date, float]], guess: float = 0.1, tol: float = 1e-6, max_iter: int = 100) -> float | None:
    """Compute XIRR via Newton-Raphson. Returns annualized rate or None."""
    if not cashflows or len(cashflows) < 2:
        return None
    d0 = cashflows[0][0]
    def npv(r: float) -> float:
        return sum(cf / (1 + r) ** ((d - d0).days / 365.25) for d, cf in cashflows)
    def dnpv(r: float) -> float:
        return sum(-cf * ((d - d0).days / 365.25) / (1 + r) ** ((d - d0).days / 365.25 + 1) for d, cf in cashflows)
    r = guess
    for _ in range(max_iter):
        d = dnpv(r)
        if abs(d) < 1e-12:
            return None
        r_new = r - npv(r) / d
        if abs(r_new - r) < tol:
            return r_new
        r = r_new
    return None


def compute_portfolio_xirr(holdings: list[MFHolding]) -> float | None:
    """Compute aggregate XIRR across all holdings by pooling all transactions."""
    cashflows = []
    total_value = 0.0
    for h in holdings:
        if not h.transactions or h.invested_value <= 0:
            continue
        for t in sorted(h.transactions, key=lambda x: x.date):
            if not t.amount:
                continue
            if t.type in ("PURCHASE", "SIP", "SWITCH_IN", "PURCHASE_SIP"):
                cashflows.append((t.date, -abs(t.amount)))
            elif t.type in ("REDEMPTION", "SWITCH_OUT"):
                cashflows.append((t.date, abs(t.amount)))
            elif t.amount > 0:
                cashflows.append((t.date, -abs(t.amount)))
        total_value += h.current_value
    if not cashflows or total_value <= 0:
        return None
    cashflows.append((date.today(), total_value))
    result = _xirr_newton(cashflows)
    return round(result * 100, 2) if result is not None else None


def compute_holding_returns(h: MFHolding) -> dict:
    """Compute return metrics for a single holding."""
    invested = h.invested_value
    current = h.current_value
    abs_return = current - invested if invested else 0.0
    pct_return = (abs_return / invested * 100) if invested else 0.0

    # XIRR from transactions
    xirr_val = None
    if h.transactions and invested > 0:
        cashflows = []
        for t in sorted(h.transactions, key=lambda x: x.date):
            amt = t.amount
            if not amt:
                continue
            # Outflows (purchases/SIPs) are negative, inflows (redemptions) positive
            if t.type in ("PURCHASE", "SIP", "SWITCH_IN", "PURCHASE_SIP"):
                cashflows.append((t.date, -abs(amt)))
            elif t.type in ("REDEMPTION", "SWITCH_OUT"):
                cashflows.append((t.date, abs(amt)))
            elif amt > 0:
                cashflows.append((t.date, -abs(amt)))  # assume purchase
        if cashflows:
            # Terminal cashflow: current value today
            cashflows.append((date.today(), current))
            xirr_val = _xirr_newton(cashflows)

    return {
        "absolute_return": round(abs_return, 2),
        "return_pct": round(pct_return, 2),
        "xirr": round(xirr_val * 100, 2) if xirr_val is not None else None,
    }
