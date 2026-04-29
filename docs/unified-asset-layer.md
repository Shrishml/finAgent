# Unified Asset Layer — Design Doc

**Status:** Proposed
**Author:** Suraj / Arth
**Date:** 2026-04-29

## Problem

Arth has two parallel storage systems for financial assets that don't talk to each other:

| Source | Storage | Used by |
|--------|---------|---------|
| CAS upload (verified) | `holdings` table | MF agent, holdings API, portfolio history, insights |
| Chat declaration | `user_assets` table (type=`mf_declared`) | Overview, goals, profile page |

**Consequences:**
1. **Double-counting** — Overview adds CAS MF value + declared MF value for the same fund
2. **Blind spots** — MF agent, holdings API, insights, portfolio history can't see declared MFs
3. **No reconciliation** — uploading CAS doesn't update/remove stale declared entries
4. **Two query paths** — every new feature must decide which table to read from
5. **Scales poorly** — future connectors (NPS statement, Zerodha CSV, bank statement) would each need their own table

## Design: Single Storage with Source Tracking

### Schema Change

Extend `user_assets` with source metadata. No new tables.

```sql
ALTER TABLE user_assets ADD COLUMN source TEXT DEFAULT 'declared';
-- values: 'declared' | 'verified'

ALTER TABLE user_assets ADD COLUMN source_detail TEXT DEFAULT 'chat';
-- values: 'chat' | 'cas_upload' | 'nps_statement' | 'zerodha_csv' | ...

ALTER TABLE user_assets ADD COLUMN verified_at TIMESTAMP;
-- set when source='verified', NULL for declared
```

### Unified MF Storage

Retire the `holdings` table. MF data lives in `user_assets` with `asset_type='mf'`:

```json
{
  "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
  "folio": "DEMO-001",
  "amc": "PPFAS",
  "isin": "INF879O01027",
  "amfi_code": "122639",
  "plan": "direct",
  "units": 1140.5,
  "nav": 83.0,
  "current_value": 94661.5,
  "invested_value": 90000,
  "expense_ratio": 0.63,
  "category": "Flexi Cap",
  "transactions": [...]
}
```

Declared MFs (from chat) use the same `asset_type='mf'` but with `source='declared'` and fewer fields:

```json
{
  "scheme": "Parag Parikh Flexi Cap",
  "monthly_sip": 5000,
  "current_value": 100000,
  "category": "flexi_cap"
}
```

### Reconciliation on Upload

When CAS is uploaded, `reconcile_and_save()` runs:

```
For each verified holding from CAS:
  1. Fuzzy-match against existing source='declared' MF entries (scheme name)
  2. Match found → REPLACE declared with verified data
  3. No match → INSERT as new source='verified' entry

For each remaining declared entry with no CAS match:
  Keep as source='declared' — user may have funds in a different AMC
  Agent can ask: "You mentioned X but it's not in your CAS — still hold it?"
```

### Read Path: One Function

```python
def load_mf_assets(user_id: int) -> list[MFHolding]:
    """Load all MF assets — verified first, declared as supplement."""
    assets = load_assets(user_id, "mf")
    # Convert to MFHolding objects for backward compatibility
    # Verified entries have full data; declared entries have partial data
    return [_to_mf_holding(a) for a in assets]
```

All consumers switch from `load_holdings()` → `load_mf_assets()`:
- Overview, MF agent, holdings API, portfolio history, insights, goals, suggestions

### Future Connectors

Same pattern for every asset type:

| Asset Type | Verified Source | Connector |
|------------|----------------|-----------|
| `mf` | CAS PDF | `CAMSConnector` (exists) |
| `stocks` | NSDL/CDSL CAS | `NSDLConnector` (future) |
| `nps` | NPS statement | `NPSConnector` (future) |
| `fd` | Bank statement | `BankConnector` (future) |
| `epf_ppf` | EPFO passbook | `EPFOConnector` (future) |

Each connector returns standardized assets → `reconcile_and_save()` handles the rest.

## What Changes

### Storage (`sqlite.py`)
- Add `source`, `source_detail`, `verified_at` columns to `user_assets`
- Add `reconcile_and_save(user_id, asset_type, verified_assets, source_detail)` function
- Add `load_mf_assets(user_id)` that returns `list[MFHolding]`
- Keep `save_holdings` / `load_holdings` / `clear_holdings` as deprecated wrappers during migration

### CAS Upload (`api/holdings.py`)
- `upload()` calls `reconcile_and_save()` instead of `save_holdings()`
- Parsed MFHoldings → converted to user_assets format before saving

### Extraction (`agents/onboarding.py`)
- `mf_sips` extraction saves as `asset_type='mf', source='declared'` instead of `mf_declared`

### Overview (`api/overview.py`)
- Remove separate `load_holdings()` call
- All MF value comes from `load_assets(user_id, 'mf')` — no double-counting

### MF Agent (`agents/mf.py`)
- `_build_context()` uses `load_mf_assets()` — sees both verified and declared MFs

### Holdings API (`api/holdings.py`)
- `GET /holdings` uses `load_mf_assets()`
- Portfolio history, insights, suggestions — all use `load_mf_assets()`

### Goals (`api/goals.py`)
- Remove special-casing for `mf_declared` / `mf_sips`
- All MF goal links use `asset_type='mf'`

### Demo (`api/holdings.py`, `api/dev.py`)
- Demo MFs saved as `user_assets` type=`mf`, source=`verified` (simulating CAS upload)

### Profile (`api/profile.py`)
- `mf_declared` section renamed to `mf` with source=`declared`

### Freshness (`freshness.py`)
- `mf_declared` → `mf` (source-aware: verified=30 days, declared=90 days)

## Migration

### Data Migration
1. All existing `user_assets` rows get `source='declared'`, `source_detail='chat'`
2. All existing `holdings` rows → `user_assets` type=`mf`, source=`verified`, source_detail=`cas_upload`
3. Fuzzy-match to deduplicate: if a declared MF matches a holdings entry, delete the declared one
4. Drop `holdings` table (or rename to `holdings_backup`)

### Code Migration Order
1. Schema migration (add columns, migrate data)
2. Add `reconcile_and_save()` + `load_mf_assets()`
3. Update CAS upload path
4. Update overview (fixes double-counting)
5. Update MF agent, holdings API, goals
6. Update extraction to use new asset_type
7. Update demo seeding
8. Remove deprecated `save_holdings` / `load_holdings` / `clear_holdings`
9. Drop `holdings` table

## Risks

1. **Transaction history size** — CAS holdings have full transaction history in JSON. The `user_assets.data` column is already JSON, so this works, but rows will be larger.
2. **MFHolding dataclass coupling** — Many functions expect `MFHolding` objects. The `load_mf_assets()` adapter handles this, but we need to ensure all fields map correctly.
3. **Test breakage** — Existing tests use `save_holdings` / `load_holdings` directly. Need to update or add adapter.

## Non-Goals

- Changing the `user_assets` table structure beyond adding 3 columns
- Building new connectors (NPS, Zerodha, etc.) — just ensuring the design supports them
- Changing the frontend — it reads from APIs, which will return the same shape

---

## Task Breakdown

### Task 1: Schema Migration
**Files:** `storage/sqlite.py`
**Work:**
- Add `source`, `source_detail`, `verified_at` columns to `user_assets` table
- Write migration: existing rows → `source='declared'`, `source_detail='chat'`
- Write migration: `holdings` rows → `user_assets` type=`mf`, source=`verified'`
- Fuzzy dedup declared vs verified MFs
- Add `reconcile_and_save()` function
- Add `load_mf_assets()` → returns `list[MFHolding]`
- Tests for migration + reconciliation

### Task 2: CAS Upload → Unified Storage
**Files:** `api/holdings.py`, `connectors/cams.py`
**Work:**
- `upload()` uses `reconcile_and_save()` instead of `save_holdings()`
- Convert `MFHolding` → user_assets dict format for storage
- `load_mf_assets()` converts back to `MFHolding` for API compatibility
- Tests for upload → reconcile → load round-trip

### Task 3: Fix Overview Double-Counting
**Files:** `api/overview.py`
**Work:**
- Remove separate `load_holdings()` call
- MF value comes from `load_assets(user_id, 'mf')` only
- Source badge in overview response (verified/declared per asset)
- Tests

### Task 4: Update MF Agent + Holdings API
**Files:** `agents/mf.py`, `api/holdings.py`
**Work:**
- MF agent `_build_context()` → `load_mf_assets()`
- `GET /holdings` → `load_mf_assets()`
- Portfolio history, insights, suggestions → `load_mf_assets()`
- Declared MFs now visible to agent (with source context)
- Tests

### Task 5: Update Goals + Link Asset
**Files:** `api/goals.py`, `actions/link_asset_to_goal.py`
**Work:**
- Remove `mf_declared` / `mf_sips` special-casing
- All MF goal links use `asset_type='mf'`
- Goal progress resolution uses unified MF data
- Tests

### Task 6: Update Extraction + Profile
**Files:** `agents/onboarding.py`, `actions/collect_profile_data.py`, `api/profile.py`, `freshness.py`
**Work:**
- `mf_sips` extraction → saves as `asset_type='mf', source='declared'`
- Profile page reads `mf` instead of `mf_declared`
- Freshness thresholds: source-aware (verified=30d, declared=90d)
- Collect profile action updated
- Tests

### Task 7: Update Demo + Cleanup
**Files:** `api/holdings.py`, `api/dev.py`, `storage/sqlite.py`
**Work:**
- Demo MFs saved via `user_assets` type=`mf`
- Remove `save_holdings`, `load_holdings`, `clear_holdings`
- Remove `holdings` table (or rename to backup)
- Update all imports
- Full regression test run
