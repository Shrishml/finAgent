#!/usr/bin/env python3
"""Reddit Scout — find recent threads to engage with for FinBestie warming.

Usage:
    python3 reddit_scout.py                  # scan all configured subs
    python3 reddit_scout.py --sub IndiaInvestments  # scan one sub
    python3 reddit_scout.py --days 3         # only last 3 days (default 7)
    python3 reddit_scout.py --download       # also save full thread comments
"""

import argparse, json, time, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SUBS = {
    "IndiaInvestments": [
        "expense ratio", "direct plan", "regular plan", "XIRR",
        "portfolio review", "financial advisor", "mutual fund returns",
        "SIP", "distributor commission", "fee only"
    ],
    "IndiaPersonalFinance": [
        "expense ratio", "direct vs regular", "portfolio review",
        "mutual fund", "XIRR", "advisor fee"
    ],
    "personalfinance": [
        "portfolio analysis", "financial advisor worth",
        "expense ratio", "index fund vs active"
    ],
    "FIREIndia": [
        "expense ratio", "SIP", "portfolio", "mutual fund"
    ],
}

HEADERS = {"User-Agent": "FinBestie-Scout/1.0 (personal research tool)"}
OUTPUT_DIR = Path(__file__).parent.parent / "marketing" / "posts" / "scout-reports"


def fetch_json(url, retries=2):
    for i in range(retries + 1):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 429 and i < retries:
                time.sleep(3)
                continue
            print(f"  ⚠️  HTTP {e.code} for {url}", file=sys.stderr)
            return None
        except Exception as e:
            if i < retries:
                time.sleep(2)
                continue
            print(f"  ⚠️  Error: {e}", file=sys.stderr)
            return None


def get_new_posts(sub, limit=50):
    url = f"https://www.reddit.com/r/{sub}/new.json?limit={limit}"
    data = fetch_json(url)
    if not data or "data" not in data:
        return []
    return [p["data"] for p in data["data"].get("children", [])]


def matches_keywords(post, keywords):
    text = (post.get("title", "") + " " + post.get("selftext", "")).lower()
    return [kw for kw in keywords if kw.lower() in text]


def get_thread_comments(permalink, limit=20):
    url = f"https://www.reddit.com{permalink}.json?limit={limit}"
    data = fetch_json(url)
    if not data or len(data) < 2:
        return []
    comments = []
    for c in data[1]["data"].get("children", []):
        if c["kind"] != "t1":
            continue
        cd = c["data"]
        comments.append({
            "author": cd.get("author", "[deleted]"),
            "score": cd.get("score", 0),
            "body": cd.get("body", "")[:500],
            "created": datetime.fromtimestamp(cd.get("created_utc", 0), tz=timezone.utc).isoformat(),
        })
    return comments


def scan_subreddit(sub, keywords, max_age_days=7, download=False):
    print(f"\n🔍 Scanning r/{sub}...")
    posts = get_new_posts(sub)
    if not posts:
        print(f"  No posts fetched (may be rate-limited)")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    results = []

    for p in posts:
        created = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)
        if created < cutoff:
            continue
        matched = matches_keywords(p, keywords)
        if not matched:
            continue

        thread = {
            "sub": sub,
            "title": p.get("title", ""),
            "url": f"https://reddit.com{p.get('permalink', '')}",
            "author": p.get("author", "[deleted]"),
            "score": p.get("score", 0),
            "num_comments": p.get("num_comments", 0),
            "created": created.strftime("%Y-%m-%d %H:%M UTC"),
            "age_hours": round((datetime.now(timezone.utc) - created).total_seconds() / 3600, 1),
            "matched_keywords": matched,
            "selftext_preview": p.get("selftext", "")[:300],
            "flair": p.get("link_flair_text", ""),
        }

        if download:
            print(f"  📥 Downloading: {thread['title'][:60]}...")
            thread["comments"] = get_thread_comments(p.get("permalink", ""))
            time.sleep(1)

        results.append(thread)

    print(f"  Found {len(results)} matching threads (last {max_age_days} days)")
    return results


def generate_report(all_results):
    if not all_results:
        return "# Reddit Scout Report\n\nNo matching threads found.\n"

    lines = [
        f"# 🔍 Reddit Scout Report",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Threads found:** {len(all_results)}",
        "", "---", "",
    ]

    all_results.sort(key=lambda x: x["score"], reverse=True)

    for i, t in enumerate(all_results, 1):
        lines.append(f"## {i}. [{t['title']}]({t['url']})")
        lines.append(f"**r/{t['sub']}** | ⬆️ {t['score']} | 💬 {t['num_comments']} | 🕐 {t['age_hours']}h ago | Flair: {t.get('flair') or 'none'}")
        lines.append(f"**Keywords:** {', '.join(t['matched_keywords'])}")
        lines.append("")
        if t["selftext_preview"]:
            lines.append(f"> {t['selftext_preview'][:200]}...")
        lines.append("")
        if "comments" in t and t["comments"]:
            lines.append(f"**Top comments ({len(t['comments'])}):**")
            for c in t["comments"][:5]:
                lines.append(f"- **u/{c['author']}** (⬆️ {c['score']}): {c['body'][:150]}...")
            lines.append("")
        lines.extend(["---", ""])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Scout Reddit for engagement opportunities")
    parser.add_argument("--sub", help="Scan only this subreddit")
    parser.add_argument("--days", type=int, default=7, help="Max thread age in days (default 7)")
    parser.add_argument("--download", action="store_true", help="Download thread comments too")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()

    subs = {args.sub: SUBS.get(args.sub, SUBS["IndiaInvestments"])} if args.sub else SUBS

    all_results = []
    for sub, keywords in subs.items():
        results = scan_subreddit(sub, keywords, max_age_days=args.days, download=args.download)
        all_results.extend(results)
        time.sleep(2)

    report = generate_report(all_results)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.output or str(OUTPUT_DIR / f"scout-{datetime.now().strftime('%Y-%m-%d')}.md")
    Path(out_path).write_text(report)
    print(f"\n✅ Report saved to {out_path}")
    print(f"📊 Total: {len(all_results)} threads")

    if all_results:
        print(f"\n{'='*60}\nTOP THREADS:\n{'='*60}")
        for i, t in enumerate(sorted(all_results, key=lambda x: x["score"], reverse=True)[:5], 1):
            print(f"{i}. [r/{t['sub']}] {t['title'][:70]}")
            print(f"   ⬆️ {t['score']} | 💬 {t['num_comments']} | 🕐 {t['age_hours']}h ago")
            print(f"   {t['url']}\n")


if __name__ == "__main__":
    main()
