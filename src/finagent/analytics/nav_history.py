"""NAV History Engine — fetch, cache, and compute metrics from historical NAV data."""
import json
import logging
import math
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("finagent.analytics.nav_history")

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "finagent.db"
_MFAPI_URL = "https://api.mfapi.in/mf"
_RISK_FREE_RATE = 0.065  # 6.5% — India 10Y govt bond approx

# Known crash periods (start, trough, label)
CRASH_PERIODS = {
    "GFC": (date(2008, 1, 1), date(2009, 3, 9), "2008 Global Financial Crisis"),
    "NBFC": (date(2018, 9, 1), date(2019, 2, 28), "2018 NBFC/IL&FS Crisis"),
    "COVID": (date(2020, 1, 15), date(2020, 3, 23), "COVID-19 Crash"),
}


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nav_history (
            amfi_code TEXT,
            date TEXT,
            nav REAL,
            PRIMARY KEY (amfi_code, date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nav_history_meta (
            amfi_code TEXT PRIMARY KEY,
            last_fetched TEXT
        )
    """)
    conn.commit()
    return conn


def _needs_refresh(conn: sqlite3.Connection, amfi_code: str) -> bool:
    row = conn.execute(
        "SELECT last_fetched FROM nav_history_meta WHERE amfi_code = ?", (amfi_code,)
    ).fetchone()
    if not row:
        return True
    last = datetime.fromisoformat(row[0])
    return (datetime.now() - last).days >= 7


def _fetch_from_api(amfi_code: str) -> list[tuple[date, float]]:
    """Fetch full NAV history from api.mfapi.in."""
    url = f"{_MFAPI_URL}/{amfi_code}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Arth/0.1",
        "Accept-Encoding": "gzip, deflate",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            # Handle gzip if server sends compressed
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode())
    except Exception as e:
        log.warning(f"mfapi.in fetch failed for {amfi_code}: {e}")
        return []

    result = []
    for entry in data.get("data", []):
        try:
            d = datetime.strptime(entry["date"], "%d-%m-%Y").date()
            nav = float(entry["nav"])
            result.append((d, nav))
        except (ValueError, KeyError):
            continue
    result.sort(key=lambda x: x[0])
    return result


def _store(conn: sqlite3.Connection, amfi_code: str, history: list[tuple[date, float]]):
    conn.executemany(
        "INSERT OR REPLACE INTO nav_history (amfi_code, date, nav) VALUES (?, ?, ?)",
        [(amfi_code, d.isoformat(), nav) for d, nav in history],
    )
    conn.execute(
        "INSERT OR REPLACE INTO nav_history_meta (amfi_code, last_fetched) VALUES (?, ?)",
        (amfi_code, datetime.now().isoformat()),
    )
    conn.commit()


class NAVHistoryEngine:
    """Fetch + cache historical NAV, compute derived metrics."""

    def fetch(self, amfi_code: str) -> list[tuple[date, float]]:
        """Get NAV history (cached, weekly refresh)."""
        conn = _get_conn()
        if _needs_refresh(conn, amfi_code):
            log.info(f"Fetching NAV history for {amfi_code}")
            history = _fetch_from_api(amfi_code)
            if history:
                _store(conn, amfi_code, history)
        rows = conn.execute(
            "SELECT date, nav FROM nav_history WHERE amfi_code = ? ORDER BY date",
            (amfi_code,),
        ).fetchall()
        conn.close()
        return [(date.fromisoformat(r[0]), r[1]) for r in rows]

    def cagr(self, amfi_code: str, years: int | None = None) -> float | None:
        """CAGR over full history or last N years."""
        history = self.fetch(amfi_code)
        if len(history) < 2:
            return None
        if years:
            cutoff = history[-1][0] - timedelta(days=years * 365)
            history = [(d, n) for d, n in history if d >= cutoff]
            if len(history) < 2:
                return None
        start_nav = history[0][1]
        end_nav = history[-1][1]
        t = (history[-1][0] - history[0][0]).days / 365.25
        if t < 0.1 or start_nav <= 0:
            return None
        return (end_nav / start_nav) ** (1 / t) - 1

    def rolling_returns(self, amfi_code: str, years: int = 3) -> list[dict]:
        """All rolling N-year return windows."""
        history = self.fetch(amfi_code)
        window_days = int(years * 365.25)
        results = []
        nav_by_date = {d: n for d, n in history}
        dates = [d for d, _ in history]
        for i, start_date in enumerate(dates):
            end_date = start_date + timedelta(days=window_days)
            # Find closest available date
            end_nav = None
            for offset in range(0, 5):
                candidate = end_date + timedelta(days=offset)
                if candidate in nav_by_date:
                    end_nav = nav_by_date[candidate]
                    end_date = candidate
                    break
            if end_nav is None:
                continue
            start_nav = nav_by_date[start_date]
            if start_nav <= 0:
                continue
            t = (end_date - start_date).days / 365.25
            cagr = (end_nav / start_nav) ** (1 / t) - 1
            results.append({"start": start_date.isoformat(), "end": end_date.isoformat(), "cagr": round(cagr * 100, 2)})
        return results

    def volatility(self, amfi_code: str) -> float | None:
        """Annualized volatility (std dev of daily returns)."""
        history = self.fetch(amfi_code)
        if len(history) < 30:
            return None
        daily_returns = []
        for i in range(1, len(history)):
            if history[i - 1][1] > 0:
                daily_returns.append(history[i][1] / history[i - 1][1] - 1)
        if not daily_returns:
            return None
        mean = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean) ** 2 for r in daily_returns) / len(daily_returns)
        return math.sqrt(variance * 252)  # annualize

    def max_drawdown(self, amfi_code: str) -> dict | None:
        """Worst peak-to-trough drawdown."""
        history = self.fetch(amfi_code)
        if len(history) < 2:
            return None
        peak = history[0][1]
        peak_date = history[0][0]
        worst = {"drawdown": 0.0, "peak_date": "", "trough_date": "", "peak_nav": 0, "trough_nav": 0}
        for d, nav in history:
            if nav >= peak:
                peak = nav
                peak_date = d
            dd = (peak - nav) / peak if peak > 0 else 0
            if dd > worst["drawdown"]:
                worst = {"drawdown": round(dd * 100, 2), "peak_date": peak_date.isoformat(), "trough_date": d.isoformat(), "peak_nav": round(peak, 2), "trough_nav": round(nav, 2)}
        # Find recovery date
        if worst["drawdown"] > 0:
            trough_d = date.fromisoformat(worst["trough_date"])
            peak_nav = worst["peak_nav"]
            for d, nav in history:
                if d > trough_d and nav >= peak_nav:
                    worst["recovery_date"] = d.isoformat()
                    worst["recovery_months"] = round((d - trough_d).days / 30.44, 1)
                    break
        return worst if worst["drawdown"] > 0 else None

    def sharpe_ratio(self, amfi_code: str) -> float | None:
        """Sharpe ratio = (CAGR - risk_free) / volatility."""
        c = self.cagr(amfi_code)
        v = self.volatility(amfi_code)
        if c is None or v is None or v == 0:
            return None
        return round((c - _RISK_FREE_RATE) / v, 2)

    def crash_stress_test(self, amfi_code: str) -> list[dict]:
        """Drawdown + recovery during known crash periods."""
        history = self.fetch(amfi_code)
        if not history:
            return []
        nav_by_date = {d: n for d, n in history}
        results = []
        for key, (start, trough_end, label) in CRASH_PERIODS.items():
            # Find pre-crash peak and trough
            period_navs = [(d, n) for d, n in history if start <= d <= trough_end]
            if len(period_navs) < 2:
                continue
            peak = max(period_navs, key=lambda x: x[1])
            trough = min((x for x in period_navs if x[0] >= peak[0]), key=lambda x: x[1], default=None)
            if not trough or peak[1] <= 0:
                continue
            dd = (peak[1] - trough[1]) / peak[1] * 100
            # Find recovery
            recovery = None
            for d, n in history:
                if d > trough[0] and n >= peak[1]:
                    recovery = round((d - trough[0]).days / 30.44, 1)
                    break
            results.append({
                "event": key, "label": label,
                "drawdown_pct": round(dd, 1),
                "peak": {"date": peak[0].isoformat(), "nav": round(peak[1], 2)},
                "trough": {"date": trough[0].isoformat(), "nav": round(trough[1], 2)},
                "recovery_months": recovery,
            })
        return results

    def sip_simulation(self, amfi_code: str, monthly_amount: float = 10000, start_year: int | None = None) -> dict | None:
        """Simulate monthly SIP and compute returns."""
        history = self.fetch(amfi_code)
        if not history:
            return None
        start = date(start_year, 1, 1) if start_year else history[0][0]
        nav_by_date = {d: n for d, n in history}
        total_invested = 0.0
        total_units = 0.0
        investments = []
        current = start.replace(day=1)
        end = history[-1][0]
        while current <= end:
            # Find nearest NAV on or after SIP date
            nav = None
            for offset in range(0, 7):
                candidate = current + timedelta(days=offset)
                if candidate in nav_by_date:
                    nav = nav_by_date[candidate]
                    break
            if nav and nav > 0:
                units = monthly_amount / nav
                total_units += units
                total_invested += monthly_amount
                investments.append((current, monthly_amount))
            # Next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        if total_invested == 0:
            return None
        final_nav = history[-1][1]
        final_value = total_units * final_nav
        # XIRR for SIP
        from finagent.utils.returns import _xirr_newton
        cashflows = [(_d, -amt) for _d, amt in investments]
        cashflows.append((history[-1][0], final_value))
        xirr = _xirr_newton(cashflows)
        return {
            "monthly_amount": monthly_amount,
            "start_date": start.isoformat(),
            "end_date": history[-1][0].isoformat(),
            "months": len(investments),
            "total_invested": round(total_invested, 0),
            "final_value": round(final_value, 0),
            "absolute_gain": round(final_value - total_invested, 0),
            "xirr_pct": round(xirr * 100, 2) if xirr else None,
        }

    def consistency_score(self, amfi_code: str) -> float | None:
        """% of rolling 3-year periods with positive returns."""
        rolls = self.rolling_returns(amfi_code, years=3)
        if not rolls:
            return None
        positive = sum(1 for r in rolls if r["cagr"] > 0)
        return round(positive / len(rolls) * 100, 1)

    def full_report(self, amfi_code: str) -> dict:
        """All metrics in one call."""
        return {
            "cagr_since_inception": self.cagr(amfi_code),
            "cagr_1y": self.cagr(amfi_code, 1),
            "cagr_3y": self.cagr(amfi_code, 3),
            "cagr_5y": self.cagr(amfi_code, 5),
            "cagr_10y": self.cagr(amfi_code, 10),
            "volatility": self.volatility(amfi_code),
            "max_drawdown": self.max_drawdown(amfi_code),
            "sharpe_ratio": self.sharpe_ratio(amfi_code),
            "crash_stress_test": self.crash_stress_test(amfi_code),
            "sip_simulation": self.sip_simulation(amfi_code),
            "consistency_score_3y": self.consistency_score(amfi_code),
        }
