"""
Usage: python3 fetch_reddit_thread.py <reddit_thread_url>

Fetches a Reddit thread and all its comments, writes to a markdown file
in the user-discussion-reddit/ folder matching the existing format.

No dependencies beyond the standard library.
"""

import sys
import os
import re
import json
import urllib.request
from datetime import datetime, timezone


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:80].strip('-')


def format_date(utc_timestamp):
    dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
    return dt.strftime("%B %d, %Y")


def clean_body(text):
    if not text:
        return ""
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&nbsp;", " ")
    return text.strip()


def render_comment(comment, depth=0):
    """Recursively render a comment and its replies as markdown lines."""
    lines = []
    if comment.get("kind") != "t1":
        return lines

    data = comment.get("data", {})
    author = data.get("author", "[deleted]")
    body = clean_body(data.get("body", ""))
    score = data.get("score", 0)
    created = data.get("created_utc", 0)
    date_str = format_date(created) if created else "Unknown"

    if not body or body in ("[deleted]", "[removed]"):
        body = data.get("body", "[deleted]")

    heading = "#" * min(depth + 3, 6)

    if depth == 0:
        lines.append(f"\n{heading} Comment")
    else:
        parent_author = data.get("parent_id", "")
        lines.append(f"\n{heading} Reply")

    lines += [
        "",
        f"- **User:** u/{author}",
        f"- **Date:** {date_str}",
        f"- **Upvotes:** {score}",
        "",
        body,
        "",
        "---",
    ]

    # Recurse into replies
    replies = data.get("replies", "")
    if isinstance(replies, dict):
        for child in replies.get("data", {}).get("children", []):
            lines.extend(render_comment(child, depth + 1))

    return lines


def fetch_thread(url):
    # Clean up URL
    clean_url = re.sub(r'[?#].*', '', url).rstrip('/')
    json_url = clean_url + ".json"

    print(f"Fetching: {json_url}")

    req = urllib.request.Request(
        json_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        },
    )

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())

    if not isinstance(data, list) or len(data) < 2:
        print("Error: unexpected JSON structure from Reddit")
        sys.exit(1)

    # --- Post ---
    post = data[0]["data"]["children"][0]["data"]
    title = post.get("title", "Untitled")
    author = post.get("author", "[deleted]")
    subreddit = post.get("subreddit", "unknown")
    score = post.get("score", 0)
    num_comments = post.get("num_comments", 0)
    created = post.get("created_utc", 0)
    selftext = clean_body(post.get("selftext", ""))
    date_str = format_date(created) if created else "Unknown"

    lines = [
        f"# {title}",
        "",
        f"- **Subreddit:** r/{subreddit}",
        f"- **Posted by:** u/{author}",
        f"- **Date:** {date_str}",
        f"- **URL:** {clean_url}",
        f"- **Upvotes:** {score}",
        f"- **Comments:** {num_comments}",
        "",
        "---",
        "",
        "## Thread Body",
        "",
        selftext if selftext else "*(No text body)*",
        "",
        "---",
        "",
        "## Comments",
    ]

    # --- Comments ---
    comment_num = 0
    for comment in data[1]["data"]["children"]:
        if comment.get("kind") == "t1":
            comment_num += 1
            comment_lines = render_comment(comment, depth=0)
            # Number the top-level comments
            for i, line in enumerate(comment_lines):
                if line.startswith("### Comment"):
                    comment_lines[i] = f"### Comment {comment_num}"
                    break
            lines.extend(comment_lines)

    # --- Write file ---
    slug = slugify(title)
    filename = f"{slug}-{subreddit.lower()}.md"
    filepath = os.path.join("user-discussion-reddit", filename)

    os.makedirs("user-discussion-reddit", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Done → {filepath}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_reddit_thread.py <reddit_thread_url>")
        sys.exit(1)

    fetch_thread(sys.argv[1])
