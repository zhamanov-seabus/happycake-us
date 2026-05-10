"""One-shot: fetch Google Business reviews from the sandbox and write
them as a static JSON the website can render at build time.

Run from the repo root:
    uv run --active --project wrapper python scripts/pull-reviews.py

Output: data/reviews.json with a stable shape:
    {
      "fetchedAt": "...",
      "averageRating": 4.5,
      "totalCount": 4,
      "reviews": [{ author, rating, text, date }]
    }
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wrapper" / "src"))

from happycake_wrapper import mcp_client  # noqa: E402

OUT = ROOT / "data" / "reviews.json"


def main() -> None:
    reviews = mcp_client.call("gb_list_reviews") or []
    if not isinstance(reviews, list):
        print(f"Unexpected shape: {type(reviews)}")
        return
    items = []
    for r in reviews:
        rating = r.get("rating") or r.get("stars") or 5
        items.append({
            "id": r.get("id") or r.get("reviewId"),
            "author": r.get("author") or r.get("authorName") or "A guest",
            "rating": int(rating),
            "text": r.get("text") or r.get("comment") or "",
            "date": r.get("date") or r.get("createdAt") or "",
        })
    avg = round(sum(i["rating"] for i in items) / len(items), 1) if items else 0
    payload = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "averageRating": avg,
        "totalCount": len(items),
        "reviews": items,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} — {len(items)} reviews, avg {avg}")


if __name__ == "__main__":
    main()
