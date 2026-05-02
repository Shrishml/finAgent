"""Tests for AMFI NAV enrichment — live fetch, caching, and error handling."""
import json
import pytest
from unittest.mock import patch, MagicMock

from finagent.models.mf import MFHolding
import finagent.storage as storage_mod


@pytest.mark.asyncio
class TestAMFIEnrichment:
    def _make_holding(self, amfi="120503", units=100, nav=50):
        return MFHolding(scheme_name="Test Fund", folio="F1", amc="AMC",
                         amfi_code=amfi, units=units, nav=nav,
                         current_value=units * nav, expense_ratio=0.01)

    async def test_updates_nav_and_expense(self):
        from finagent.connectors.amfi import enrich_holdings
        from tests.conftest import async_return
        h = self._make_holding(units=100, nav=50)
        fake_data = {"nav": 55.50, "expense_ratio": 0.63, "name": "Test", "category": "Flexi Cap"}
        # Mock both cache check and fetch
        with patch("finagent.connectors.amfi.get_cached_nav", async_return(None)), \
             patch("finagent.connectors.amfi._fetch_scheme", return_value=fake_data), \
             patch("finagent.connectors.amfi.save_nav_cache", async_return(None)):
            await enrich_holdings([h])
        assert h.nav == 55.50
        assert h.current_value == 5550.0
        assert h.expense_ratio == 0.0063  # 0.63% → 0.0063

    async def test_uses_cache_when_available(self):
        from finagent.connectors.amfi import enrich_holdings
        await storage_mod.save_nav_cache("120503", 60.0, "Test", 0.005)
        h = self._make_holding(units=100)
        with patch("finagent.connectors.amfi._fetch_scheme") as mock_fetch:
            await enrich_holdings([h])
            mock_fetch.assert_not_called()
        assert h.nav == 60.0
        assert h.expense_ratio == 0.005

    async def test_skips_holding_without_amfi_code(self):
        from finagent.connectors.amfi import enrich_holdings
        h = self._make_holding(amfi="")
        with patch("finagent.connectors.amfi._fetch_scheme") as mock_fetch:
            await enrich_holdings([h])
            mock_fetch.assert_not_called()

    async def test_handles_fetch_failure_gracefully(self):
        from finagent.connectors.amfi import enrich_holdings
        from tests.conftest import async_return
        h = self._make_holding(units=100, nav=50)
        # Mock cache miss and fetch failure
        with patch("finagent.connectors.amfi.get_cached_nav", async_return(None)), \
             patch("finagent.connectors.amfi._fetch_scheme", side_effect=Exception("timeout")):
            await enrich_holdings([h])
        assert h.nav == 50  # unchanged

    def test_fetch_scheme_sends_user_agent(self):
        from finagent.connectors.amfi import _fetch_scheme
        with patch("finagent.connectors.amfi.urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"status": "success", "data": {"nav": 50}}).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            _fetch_scheme("120503")
            req = mock_urlopen.call_args[0][0]
            assert req.get_header("User-agent") == "FinAgent/0.1"
