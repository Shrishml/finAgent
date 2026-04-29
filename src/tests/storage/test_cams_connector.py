"""Tests for CAMS/KFintech CAS PDF connector and parsing helpers."""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

from finagent.connectors.cams import CAMSConnector, _parse_date, _safe_float


class TestParseDate:
    def test_dd_mon_yyyy(self):
        assert _parse_date("15-Jan-2026") == date(2026, 1, 15)

    def test_dd_slash_mm_slash_yyyy(self):
        assert _parse_date("15/01/2026") == date(2026, 1, 15)

    def test_iso_format(self):
        assert _parse_date("2026-01-15") == date(2026, 1, 15)

    def test_invalid_returns_epoch(self):
        assert _parse_date("garbage") == date(1970, 1, 1)

    def test_empty_returns_epoch(self):
        assert _parse_date("") == date(1970, 1, 1)


class TestSafeFloat:
    def test_none_returns_zero(self):
        assert _safe_float(None) == 0.0

    def test_valid_string(self):
        assert _safe_float("123.45") == 123.45

    def test_invalid_string_returns_zero(self):
        assert _safe_float("N/A") == 0.0


class TestCAMSConnector:
    def test_detect_pdf(self, tmp_path):
        c = CAMSConnector()
        assert c.detect(tmp_path / "test.pdf") is True
        assert c.detect(tmp_path / "test.csv") is False

    def test_target_domain(self):
        assert CAMSConnector().target_domain() == "mf"

    def test_parse_maps_casparser_to_mfholding(self):
        """casparser output is correctly mapped to MFHolding fields."""
        tx = MagicMock(date="15-Jan-2026", description="SIP", amount=5000,
                       units=10.5, nav=45.67, balance=100.5, type="PURCHASE", dividend_rate=None)
        valuation = MagicMock(nav=45.67, value=4589.0, cost=4000.0)
        scheme = MagicMock(scheme="Axis Bluechip Fund - Direct Growth", isin="INF846K01DP8",
                           amfi="120503", rta="CAMS", open=100.5, close=100.5,
                           valuation=valuation, transactions=[tx], advisor=None, rta_code=None,
                           type=None, nominees=None, close_calculated=100.5)
        folio = MagicMock(folio="12345", amc="Axis Mutual Fund", schemes=[scheme])
        cas_data = MagicMock(folios=[folio], spec=["folios", "cas_type", "file_type",
                             "statement_period", "investor_info"])
        # Ensure hasattr(data, 'accounts') returns False — prevents NSDL rejection
        del cas_data.accounts

        with patch("casparser.read_cas_pdf", return_value=cas_data):
            holdings = CAMSConnector().parse(Path("fake.pdf"), "password")

        assert len(holdings) == 1
        h = holdings[0]
        assert h.scheme_name == "Axis Bluechip Fund - Direct Growth"
        assert h.folio == "12345"
        assert h.amc == "Axis Mutual Fund"
        assert h.isin == "INF846K01DP8"
        assert h.plan == "direct"
        assert h.units == 100.5
        assert h.nav == 45.67
        assert len(h.transactions) == 1
        assert h.transactions[0].amount == 5000
