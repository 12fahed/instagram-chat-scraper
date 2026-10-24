"""Optionally mirror IG CDN images next to the HTML.

The preview/avatar URLs in a capture are signed and expire within days, so an
archive that only links to them goes blank. This downloads them once into
data/out/media/ and rewrites the chat to point at the local copies. It is the
only part of this project that touches the network, and only to instagram/fbcdn.
"""

from __future__ import annotations

import hashlib
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path

ALLOWED_HOSTS = ("cdninstagram.com", "fbcdn.net", "instagram.com")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"


def _allowed(url: str) -> bool:
    host = url.split("/", 3)[2].split("@")[-1].split(":")[0] if url.startswith("http") else ""
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _targets(chat: dict):
    """(container, key) pairs holding a remote image URL."""
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


def mirror(chat: dict, out_dir: Path, timeout: float = 20.0) -> dict:
    media = out_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    cache: dict[str, str] = {}
    stats = {"downloaded": 0, "cached": 0, "skipped": 0, "failed": 0}

    for holder, key in _targets(chat):
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
            print(f"  media: {type(exc).__name__} for {url[:70]}…")
            continue
        path = media / (name + (".jpg" if ext == ".jpe" else ext))
        path.write_bytes(blob)
        cache[url] = f"media/{path.name}"
        holder[key] = cache[url]
        stats["downloaded"] += 1
    return stats
