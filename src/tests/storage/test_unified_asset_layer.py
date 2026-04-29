"""Tests for unified asset layer: reconcile_and_save, load_mf_assets, migration."""
import json

from finagent.models.mf import MFHolding, MFTransaction
from finagent.storage.sqlite import (
    _get_conn, _scheme_match, reconcile_and_save, load_mf_assets,
    clear_mf_assets, save_assets, load_assets, get_or_create_user,
    save_holdings, load_holdings,
)
from datetime import date


def _uid():
    return get_or_create_user("test-unified-asset", "unified@test.com", "Test Unified")


def _make_holding(name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                  folio="TEST-001", value=94000, invested=90000, units=1140,
                  nav=83, amfi="122639", plan="direct") -> MFHolding:
    return MFHolding(
        scheme_name=name, folio=folio, amc="PPFAS", amfi_code=amfi,
        plan=plan, units=units, nav=nav, current_value=value,
        invested_value=invested,
        transactions=[MFTransaction(date=date(2024, 1, 15), description="SIP",
                                    amount=5000, units=60.2, type="SIP")],
    )


class TestSchemeMatch:
    def test_exact_match(self):
        assert _scheme_match("Parag Parikh Flexi Cap Fund", "Parag Parikh Flexi Cap Fund")

    def test_prefix_match(self):
        assert _scheme_match(
            "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            "Parag Parikh Flexi Cap Fund"
        )

    def test_reverse_prefix(self):
        assert _scheme_match(
            "Parag Parikh Flexi Cap",
            "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
        )

    def test_fuzzy_match(self):
        assert _scheme_match(
            "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
            "HDFC Mid Cap Opportunities"
        )

    def test_no_match(self):
        assert not _scheme_match("Parag Parikh Flexi Cap", "HDFC Mid Cap Opportunities")

    def test_empty(self):
        assert not _scheme_match("", "Parag Parikh")
        assert not _scheme_match("Parag Parikh", "")


class TestReconcileAndSave:
    def setup_method(self):
        self.uid = _uid()
        clear_mf_assets(self.uid)

    def test_save_verified_holdings(self):
        h = _make_holding()
        result = reconcile_and_save(self.uid, "mf", [h])
        assert result["saved"] == 1
        assert result["new"] == 1
        assert result["replaced"] == 0

    def test_replaces_declared_on_match(self):
        # User declared via chat
        save_assets(self.uid, "mf", [
            {"scheme": "Parag Parikh Flexi Cap", "monthly_sip": 5000, "current_value": 100000}
        ], source="declared")
        # CAS upload with same fund
        h = _make_holding(value=94000)
        result = reconcile_and_save(self.uid, "mf", [h])
        assert result["replaced"] == 1
        # Declared entry replaced by verified — only 1 MF total
        holdings = load_mf_assets(self.uid)
        assert len(holdings) == 1
        assert holdings[0].current_value == 94000

    def test_keeps_unmatched_declared(self):
        # User declared a fund not in CAS
        save_assets(self.uid, "mf", [
            {"scheme": "SBI Small Cap Fund", "monthly_sip": 3000, "current_value": 50000}
        ], source="declared")
        # CAS has different fund
        h = _make_holding()
        reconcile_and_save(self.uid, "mf", [h])
        # SBI declared entry should remain alongside verified Parag Parikh
        all_mf = load_assets(self.uid, "mf")
        sbi = [a for a in all_mf if a.get("scheme") == "SBI Small Cap Fund"]
        assert len(sbi) == 1

    def test_re_upload_replaces_verified(self):
        h1 = _make_holding(value=90000)
        reconcile_and_save(self.uid, "mf", [h1])
        # Re-upload with updated value
        h2 = _make_holding(value=95000)
        reconcile_and_save(self.uid, "mf", [h2])
        holdings = load_mf_assets(self.uid)
        assert len(holdings) == 1
        assert holdings[0].current_value == 95000

    def test_multiple_holdings(self):
        holdings = [
            _make_holding(name="Fund A - Direct", folio="F1", value=50000),
            _make_holding(name="Fund B - Direct", folio="F2", value=30000),
        ]
        result = reconcile_and_save(self.uid, "mf", holdings)
        assert result["saved"] == 2
        loaded = load_mf_assets(self.uid)
        assert len(loaded) == 2


class TestLoadMfAssets:
    def setup_method(self):
        self.uid = _uid()
        clear_mf_assets(self.uid)

    def test_loads_verified(self):
        reconcile_and_save(self.uid, "mf", [_make_holding()])
        holdings = load_mf_assets(self.uid)
        assert len(holdings) == 1
        assert holdings[0].scheme_name == "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
        assert len(holdings[0].transactions) == 1

    def test_loads_legacy_declared(self):
        save_assets(self.uid, "mf", [
            {"scheme": "SBI Small Cap", "current_value": 50000, "monthly_sip": 3000}
        ], source="declared")
        holdings = load_mf_assets(self.uid)
        assert len(holdings) == 1
        assert holdings[0].scheme_name == "SBI Small Cap"
        assert holdings[0].current_value == 50000

    def test_loads_both_verified_and_declared(self):
        reconcile_and_save(self.uid, "mf", [_make_holding()])
        save_assets(self.uid, "mf", [
            {"scheme": "SBI Small Cap", "current_value": 50000}
        ], source="declared")
        holdings = load_mf_assets(self.uid)
        assert len(holdings) == 2

    def test_skips_zero_value(self):
        reconcile_and_save(self.uid, "mf", [_make_holding(value=0, units=0)])
        holdings = load_mf_assets(self.uid)
        assert len(holdings) == 0

    def test_transaction_roundtrip(self):
        h = _make_holding()
        reconcile_and_save(self.uid, "mf", [h])
        loaded = load_mf_assets(self.uid)
        t = loaded[0].transactions[0]
        assert t.date == date(2024, 1, 15)
        assert t.amount == 5000
        assert t.type == "SIP"


class TestSourceColumns:
    def setup_method(self):
        self.uid = _uid()
        clear_mf_assets(self.uid)

    def test_verified_has_source_metadata(self):
        reconcile_and_save(self.uid, "mf", [_make_holding()])
        conn = _get_conn()
        row = conn.execute(
            "SELECT source, source_detail, verified_at FROM user_assets "
            "WHERE user_id = ? AND asset_type = 'mf'", (self.uid,)
        ).fetchone()
        conn.close()
        assert row[0] == "verified"
        assert row[1] == "cas_upload"
        assert row[2] is not None

    def test_declared_has_default_source(self):
        save_assets(self.uid, "mf", [{"scheme": "Test", "current_value": 1000}], source="declared")
        conn = _get_conn()
        row = conn.execute(
            "SELECT source FROM user_assets "
            "WHERE user_id = ? AND asset_type = 'mf' AND source = 'declared'", (self.uid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "declared"
