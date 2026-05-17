#!/usr/bin/env python3
"""Fetch configured RSS feeds, filter by keywords, write ../public/data/news.json."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parent
OUT_PATH = ROOT.parent / "public" / "data" / "news.json"
CONFIG_PATH = ROOT / "sources.yaml"

UA = (
    "OutbreakDashboardIngest/0.1 "
    "(GitHub Actions; contact: repository owner)"
)


DROP_QUERY_KEYS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "at_medium",
        "at_campaign",
    },
)


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    # Drop fragment; strip common marketing/query noise.
    q = []
    if parsed.query:
        for pair in parsed.query.split("&"):
            if not pair:
                continue
            key = pair.split("=", 1)[0].lower()
            if key.startswith("utm_") or key in DROP_QUERY_KEYS:
                continue
            q.append(pair)
    query = "&".join(q)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            query,
            "",
        )
    )


def stable_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def text_matches(text: str, keywords: list[str]) -> bool:
    hay = text.lower()
    return any(k.lower() in hay for k in keywords)


def fetch_bytes(client: httpx.Client, url: str) -> bytes | None:
    try:
        r = client.get(url, timeout=30.0)
        r.raise_for_status()
        return r.content
    except Exception as exc:  # noqa: BLE001 — ingest must not crash entire job
        print(f"[warn] fetch failed {url!r}: {exc}")
        return None


def merge_items(
    existing: list[dict],
    incoming: list[dict],
    *,
    max_items: int = 100,
) -> list[dict]:
    by_url: dict[str, dict] = {}
    for row in existing + incoming:
        u = row.get("url") or ""
        if not u:
            continue
        key = normalize_url(u)
        prev = by_url.get(key)
        if prev is None:
            row["url"] = key
            by_url[key] = row
            continue
        # Prefer lower tier number (more trusted) and longer title.
        if (row.get("source_tier", 99), -len(row.get("title", ""))) < (
            prev.get("source_tier", 99),
            -len(prev.get("title", "")),
        ):
            row["url"] = key
            by_url[key] = row

    merged = list(by_url.values())

    def sort_key(item: dict) -> tuple:
        pub = item.get("published_at") or ""
        return (pub, item.get("title") or "")

    merged.sort(key=sort_key, reverse=True)
    return merged[:max_items]


def main() -> None:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    keywords: list[str] = cfg.get("keywords") or []
    sources: list[dict] = cfg.get("sources") or []

    existing_items: list[dict] = []
    if OUT_PATH.exists():
        try:
            raw_existing = json.loads(OUT_PATH.read_text(encoding="utf-8")).get(
                "items",
                [],
            )
            existing_items = [
                x for x in raw_existing if x.get("id") != "seed-example-1"
            ]
        except json.JSONDecodeError:
            print("[warn] existing news.json not valid JSON — rebuilding")

    incoming: list[dict] = []
    with httpx.Client(
        headers={"User-Agent": UA},
        follow_redirects=True,
    ) as client:
        for src in sources:
            url = src.get("rss_url")
            if not url:
                continue
            raw = fetch_bytes(client, url)
            if raw is None:
                continue
            parsed = feedparser.parse(raw)
            for entry in parsed.entries:
                title = (entry.get("title") or "").strip()
                summary = (
                    entry.get("summary")
                    or entry.get("description")
                    or entry.get("subtitle")
                    or ""
                )
                link = (
                    entry.get("link")
                    or (entry.get("links") or [{}])[0].get("href")
                    or ""
                )
                if not title or not link:
                    continue
                blob = f"{title}\n{summary}"
                if keywords and not text_matches(blob, keywords):
                    continue
                norm = normalize_url(link)
                published = None
                if entry.get("published_parsed"):
                    try:
                        published = datetime(
                            *entry.published_parsed[:6],
                            tzinfo=timezone.utc,
                        ).date().isoformat()
                    except (TypeError, ValueError):
                        published = entry.get("published")
                elif entry.get("updated_parsed"):
                    try:
                        published = datetime(
                            *entry.updated_parsed[:6],
                            tzinfo=timezone.utc,
                        ).date().isoformat()
                    except (TypeError, ValueError):
                        published = entry.get("updated")

                incoming.append(
                    {
                        "id": stable_id(norm),
                        "title": title,
                        "url": norm,
                        "published_at": published,
                        "source_name": src.get("name") or src.get("id") or "feed",
                        "source_tier": int(src.get("tier") or 2),
                        "summary": summary[:400] if summary else None,
                    },
                )

    merged = merge_items(existing_items, incoming)
    payload = {
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "items": merged,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[ok] wrote {OUT_PATH} ({len(merged)} items)")


if __name__ == "__main__":
    main()
