# Reddit Response Tool — Design Doc

## Overview

A standalone admin tool that takes a Reddit thread URL, auto-generates personalized
financial advice using Arth's existing pipeline, and outputs a Reddit-ready response.
Supports manual intervention to correct/add context before finalizing.

## Goals

1. **Reduce effort** from ~15 min (manual onboarding + chat) to ~1 min (paste URL, review, copy)
2. **Reuse real Arth framework** — extraction, profile save, orchestrator, advisor — so this also serves as integration testing
3. **Persist conversations** under anonymous users for audit trail and quality review
4. **Enable manual refinement** — operator can add/correct context before copying final response

## Non-Goals (V1)

- No auto-posting to Reddit (manual copy-paste)
- No Reddit authentication or API keys
- No public-facing page (admin-only, behind auth)
- No batch processing of multiple threads

---

## Architecture

```
┌────────────────────────────────────────────────────┐
│  /reddit-tool  (standalone HTML page)              │
│                                                    │
│  ┌─────────────────────────────────────────────┐   │
│  │ [Reddit URL] [Generate]                     │   │
│  └─────────────────────────────────────────────┘   │
│                                                    │
│  ┌─ Extracted Profile ──────────────────────────┐  │
│  │ Age: 25 | Income: 80k | Goals: ...          │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  ┌─ Conversation Panel ─────────────────────────┐  │
│  │ [Auto-generated turns shown here]            │  │
│  │ [Operator can type to add/correct]           │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  ┌─ Reddit Reply ───────────────────────────────┐  │
│  │ [Formatted markdown] [Copy]                  │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

### Backend Flow

```
POST /api/reddit-tool/generate {url}
  │
  ├─ 1. Fetch Reddit thread JSON (old.reddit.com/{path}.json)
  ├─ 2. Extract OP text + relevant comments
  ├─ 3. Create/reuse anonymous user: reddit_anon_{post_id}
  ├─ 4. Run extraction pipeline → save profile
  ├─ 5. Run advisor (multi-turn internally):
  │     Turn 1: Advisor sees profile, identifies gaps
  │     Turn 2: Auto-fill gaps from thread context or mark as assumed
  │     Turn 3: Generate final advice
  ├─ 6. Save all turns to chat_history
  ├─ 7. Format final response as Reddit markdown
  └─ Return: {profile, conversation[], reddit_reply, user_id}

POST /api/reddit-tool/chat {user_id, message}
  │
  ├─ Standard Arth chat endpoint but with reddit_anon user
  ├─ Operator adds context / asks for reformatting
  └─ Return: {response, updated_reddit_reply}
```

---

## Data Model

### Anonymous User

```python
user_id = f"reddit_anon_{post_id}"  # deterministic, idempotent
# Stored in same user_profiles + user_assets tables
# Flagged with source="reddit" for filtering
```

### Conversation Persistence

Uses existing `chat_history` table. Tagged with:
- `user_id`: reddit_anon_{post_id}
- `source`: "reddit_tool"
- `reddit_url`: original thread URL

---

## Reddit Scraping

No API key needed — uses old.reddit.com JSON endpoint.

---

## Reddit-Specific Advisor Prompt

Added as a system prompt modifier when source="reddit_tool":

```
You are responding to a Reddit post on r/IndiaInvestments. Format rules:
- Keep response under 300 words
- Use Reddit markdown (**, *, numbered lists)
- Be direct and actionable — no "as an AI" disclaimers
- If you made assumptions due to missing data, state them briefly at the end
- Tone: knowledgeable peer, not financial advisor
- End with: "---\n*Generated with [Arth](https://askarth.com) — ran the math on your numbers*"
```

---

## UI Design

Single HTML page at `/reddit-tool` (admin-only, behind magic cookie or session auth).

### Sections

1. **Input bar** — URL text field + Generate button
2. **Profile card** — Extracted profile summary (read-only, collapsible)
3. **Conversation panel** — Shows all turns (auto + manual). Chat input at bottom.
4. **Reddit Reply panel** — Final formatted output with Copy button. Auto-updates.

### States

- **Empty** — just the URL input
- **Loading** — spinner with step indicators
- **Ready** — all panels populated
- **Chatting** — operator adding messages, reply panel updates live

---

## Tasks

### Phase 1: Backend

| # | Task | Est | Depends |
|---|------|-----|---------|
| 1.1 | Reddit URL parser — normalize URL formats to JSON API URL | 20m | — |
| 1.2 | Reddit thread fetcher — fetch OP text + title + top comments | 20m | 1.1 |
| 1.3 | Anonymous user creation — `reddit_anon_{post_id}`, save to DB | 15m | — |
| 1.4 | `/api/reddit-tool/generate` endpoint — wire scraper → extraction → advisor | 45m | 1.1-1.3 |
| 1.5 | Multi-turn auto-conversation — gap detection + auto-fill | 30m | 1.4 |
| 1.6 | Reddit markdown formatter | 20m | — |
| 1.7 | `/api/reddit-tool/chat` endpoint — continue conversation | 15m | 1.4 |

### Phase 2: Frontend

| # | Task | Est | Depends |
|---|------|-----|---------|
| 2.1 | HTML page skeleton — `/reddit-tool` route, 4-panel layout | 30m | — |
| 2.2 | URL input + Generate button + loading states | 20m | 1.4, 2.1 |
| 2.3 | Profile card component | 20m | 2.1 |
| 2.4 | Conversation panel + chat input | 30m | 2.1 |
| 2.5 | Reddit Reply panel + copy button | 15m | 2.1 |
| 2.6 | Live update on operator messages | 20m | 2.4, 1.7 |

### Phase 3: Polish

| # | Task | Est | Depends |
|---|------|-----|---------|
| 3.1 | Handle sparse posts — confidence flags | 20m | 1.5 |
| 3.2 | Handle deleted/private threads | 10m | 1.2 |
| 3.3 | Rate limiting + caching | 15m | 1.2 |
| 3.4 | History page for quality review | 30m | 1.4 |

---

## Open Questions

1. Should the tool also fetch and display existing Reddit answers (to avoid duplicating)?
2. Do we want a "regenerate" button with different temperature/framing?
3. Should we track which responses were actually posted (manual checkbox)?
