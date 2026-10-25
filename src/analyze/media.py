"""Optionally mirror IG CDN images next to the HTML.

The preview/avatar URLs in a capture are signed and expire within days, so an
archive that only links to them goes blank. This downloads them once into
data/out/media/ and rewrites the chat to point at the local copies. It is the
only part of this project that touches the network, and only to instagram/fbcdn.
"""

from __future__ import annotations

import hashlib
import mimetypes
from collections import Counter
import urllib.error
import urllib.request
from pathlib import Path

ALLOWED_HOSTS = ("cdninstagram.com", "fbcdn.net", "instagram.com")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"


def _allowed(url: str) -> bool:
    host = url.split("/", 3)[2].split("@")[-1].split(":")[0] if url.startswith("http") else ""
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _targets(chat: dict, videos: bool):
    """(container, key) pairs holding a remote media URL."""
    for person in chat["people"].values():
        if person.get("avatar"):
            yield person, "avatar"
    for msg in chat["messages"]:
        for card in (msg.get("card"), (msg.get("reply") or {}).get("card")):
            if not card:
                continue
            if card.get("author_avatar"):
                yield card, "author_avatar"
            img = card.get("image")
            if img and img.get("url"):
                yield img, "url"
        for item in (msg.get("media") or []) + ((msg.get("reply") or {}).get("media") or []):
            if item.get("preview"):
                yield item, "preview"
            # The full-size original is the thing worth archiving for photos. Video
            # originals are big and the oldest ones rarely still resolve, so they
            # are opt-in; without --media-video the poster frame is kept and the
            # "open original" link stays pointed at the (probably dead) CDN url.
            if item.get("full") and item["full"] != item.get("preview"):
                if item.get("kind") != "video" or videos:
                    yield item, "full"


def mirror(chat: dict, out_dir: Path, timeout: float = 20.0, videos: bool = False) -> dict:
    media = out_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    cache: dict[str, str] = {}
    stats = {"downloaded": 0, "cached": 0, "skipped": 0, "failed": 0}
    seen_failures: Counter = Counter()

    for holder, key in _targets(chat, videos):
        url = holder[key]
        if not url.startswith("http") or not _allowed(url):
            stats["skipped"] += 1
            continue
        if url in cache:
            holder[key] = cache[url]
            continue
        name = hashlib.sha1(url.encode()).hexdigest()[:16]
        existing = next((p for p in media.glob(name + ".*")), None)
        if existing:
            cache[url] = f"media/{existing.name}"
            holder[key] = cache[url]
            stats["cached"] += 1
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                blob = resp.read()
                ext = mimetypes.guess_extension(resp.headers.get_content_type() or "") or ".jpg"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            stats["failed"] += 1
            reason = getattr(exc, "code", None) or type(exc).__name__
            seen_failures[reason] += 1
            if seen_failures[reason] <= 3:   # expired CDN urls repeat in the thousands
                print(f"  media: {reason} for {url[:70]}…")
            elif seen_failures[reason] == 4:
                print(f"  media: further {reason} failures will not be printed")
            continue
        path = media / (name + (".jpg" if ext == ".jpe" else ext))
        path.write_bytes(blob)
        cache[url] = f"media/{path.name}"
        holder[key] = cache[url]
        stats["downloaded"] += 1
    if seen_failures:
        stats["failed_by_reason"] = dict(seen_failures)
    return stats
