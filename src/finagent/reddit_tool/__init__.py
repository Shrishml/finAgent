"""Reddit thread scraper — fetch and parse Reddit posts via JSON API."""
import re
import httpx

_REDDIT_URL_RE = re.compile(
    r'(?:https?://)?(?:(?:www|old|new)\.)?reddit\.com/r/(\w+)/comments/(\w+)'
)
_SHARE_URL_RE = re.compile(
    r'(?:https?://)?(?:(?:www|old|new)\.)?reddit\.com/r/(\w+)/s/(\w+)'
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def normalize_reddit_url(url: str) -> tuple[str, str]:
    """Convert any Reddit URL to JSON API URL. Returns (json_url, post_id)."""
    m = _REDDIT_URL_RE.search(url)
    if m:
        subreddit, post_id = m.group(1), m.group(2)
        json_url = f"https://old.reddit.com/r/{subreddit}/comments/{post_id}.json"
        return json_url, post_id
    if _SHARE_URL_RE.search(url):
        raise ValueError(
            "Share links (/r/.../s/...) can't be resolved server-side. "
            "Please open the link in your browser and copy the full URL from the address bar "
            "(it should contain /comments/ in the path)."
        )
    raise ValueError(f"Invalid Reddit URL. Expected format: reddit.com/r/subreddit/comments/post_id/...")


async def fetch_thread(url: str) -> dict:
    """Fetch Reddit thread and return structured data."""
    json_url, post_id = normalize_reddit_url(url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(json_url, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, list) or len(data) < 2:
        raise ValueError("Unexpected Reddit JSON structure")

    post = data[0]["data"]["children"][0]["data"]
    comments_raw = data[1]["data"]["children"]

    # Extract top-level comments (skip "more" placeholders)
    comments = []
    for c in comments_raw:
        if c.get("kind") == "t1":
            body = c["data"].get("body", "")
            if body and body not in ("[deleted]", "[removed]"):
                comments.append({
                    "author": c["data"].get("author", "[deleted]"),
                    "body": body,
                    "score": c["data"].get("score", 0),
                })

    # Sort by score, keep top 10
    comments.sort(key=lambda x: x["score"], reverse=True)

    return {
        "post_id": post_id,
        "subreddit": post.get("subreddit", ""),
        "title": post.get("title", ""),
        "body": post.get("selftext", ""),
        "author": post.get("author", "[deleted]"),
        "score": post.get("score", 0),
        "url": url,
        "comments": comments[:10],
    }
