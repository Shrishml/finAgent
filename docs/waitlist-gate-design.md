# Waitlist & Access Gate — Design Doc

## Context

Arth is ready for early beta testers but not for public access. We need a gate between "signed up via Google OAuth" and "can use the product." This lets us recruit testers (Reddit, LinkedIn) while controlling who gets in and when.

## Current Flow

```
Google OAuth → get_or_create_user() → Full access
```

## Target Flow

```
Google OAuth → get_or_create_user() → access_status check
  ├─ "active"   → Full access (current behavior)
  ├─ "waitlist"  → Waitlist page (position, what Arth does, "we'll let you in soon")
  └─ "blocked"   → 403 page
```

## Decision: Merge dev → main First

All new features live on `dev`. Before building the gate, merge dev → main and deploy to askarth.com. Beta users use the real production URL. One environment, one branch going forward.

---

## Implementation Plan

### Phase 1: DB Schema Change

**File:** `src/finagent/storage/sqlite.py`

Add `access_status` column to `users` table:
- Values: `waitlist` | `active` | `blocked`
- Default for new users: `waitlist`
- Existing users (you + friends): auto-set to `active`

```sql
ALTER TABLE users ADD COLUMN access_status TEXT DEFAULT 'waitlist';
-- Grandfather existing users
UPDATE users SET access_status = 'active' WHERE access_status IS NULL;
```

Add helper functions:
```python
def get_user_access_status(user_id: int) -> str:
    """Returns 'waitlist', 'active', or 'blocked'."""

def set_user_access_status(user_id: int, status: str) -> None:
    """Admin: change user access status."""

def list_waitlist_users() -> list[dict]:
    """Admin: list all users on waitlist with signup date."""

def approve_user(user_id: int) -> None:
    """Shortcut: set access_status = 'active'."""
```

### Phase 2: Middleware Gate

**File:** `src/finagent/api/deps.py`

Modify `require_auth()` to also check access status:

```python
def require_auth(request: Request) -> int:
    user_id = get_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    status = get_user_access_status(user_id)
    if status == "blocked":
        raise HTTPException(status_code=403, detail="Access denied")
    if status == "waitlist":
        raise HTTPException(status_code=403, detail="waitlist")
    return user_id
```

Frontend catches the `"waitlist"` detail and shows the waitlist page instead of the app.

### Phase 3: Waitlist Page (Frontend)

**File:** `src/ui/waitlist.html` (new) or inline in existing SPA

When `/auth/me` returns 200 but access is gated, show:
- "You're on the early access list! 🎉"
- Brief explanation of what Arth does (2-3 bullet points)
- "We're letting people in gradually to ensure quality. We'll notify you when it's your turn."
- Optional: "Tell us your biggest financial question" (textarea → saves to DB, gives you signal)

### Phase 4: Invite Codes (Primary Access Mechanism)

**File:** `src/finagent/storage/sqlite.py` + `src/finagent/api/auth.py`

New table:
```sql
CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    max_uses INTEGER DEFAULT 1,
    used_count INTEGER DEFAULT 0,
    note TEXT  -- e.g., "Reddit batch 1"
);
```

Flow:
1. You generate codes: `POST /admin/invite-codes` → returns code like `BRAVE-A1B2`
2. Share code with approved testers (Reddit DM, WhatsApp)
3. User enters code on waitlist page → `POST /auth/redeem-invite`
4. If valid + not exhausted → set `access_status = 'active'`

### Phase 5: Admin Endpoints

**File:** `src/finagent/api/admin.py` (new)

Protected by a simple secret (env var `ADMIN_SECRET`) or your specific user_id:

```
GET  /admin/waitlist          → list waitlisted users
POST /admin/approve           → approve user by id or email
POST /admin/invite-codes      → generate N invite codes
GET  /admin/invite-codes      → list codes + usage stats
POST /admin/block             → block a user
```

No admin dashboard UI needed — curl or a simple script is fine for now.

---

## What We're NOT Building

- Email notifications on approval (just DM them manually)
- Waitlist position numbers (unnecessary complexity)
- Referral/viral mechanics (premature)
- Fancy admin UI (curl is fine)
- Rate limiting on invite redemption (overkill at this scale)

---

## Build Order

| Step | What | Time Est |
|------|------|----------|
| 0 | Merge dev → main, deploy | 30 min |
| 1 | DB migration + helper functions | 30 min |
| 2 | Modify `require_auth` + frontend gate | 1 hr |
| 3 | Waitlist page UI | 1 hr |
| 4 | Invite codes table + redeem endpoint | 45 min |
| 5 | Admin endpoints | 30 min |
| 6 | Test end-to-end | 30 min |

**Total: ~4.5 hours**

---

## Post-Build: Go-to-Market

1. Generate 20 invite codes tagged "reddit-batch-1"
2. Post on r/IndiaInvestments recruiting beta testers
3. DM invite codes to interested people
4. Create WhatsApp/Telegram group for feedback
5. Let in 5-10 people/week, fix issues as they come
