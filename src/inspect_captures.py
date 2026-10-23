"""
Figure out where messages live in the captured responses.

    python inspect_captures.py                      # summary of every query captured
    python inspect_captures.py --find "see you at 8" # JSON paths where that text appears
    python inspect_captures.py --show 00042          # pretty-print one capture

Use --find with a message you KNOW is in the chat (ideally one that is a reply).
The printed path shows you the message object's shape, including the key that
holds the replied-to message, which you then set in build_html.py's CONFIG.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

CAPTURES = Path("captures")


def load():
    for f in sorted(CAPTURES.glob("*.json")):
        try:
            yield f, json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"skip {f.name}: {e}")


def expand_strings(obj):
    """Some IG payloads embed JSON as a string (e.g. Lightspeed 'payload'). Decode those too."""
    if isinstance(obj, dict):
        return {k: expand_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_strings(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 20 and obj.lstrip()[:1] in "{[":
        try:
            return expand_strings(json.loads(obj))
        except json.JSONDecodeError:
            pass
    return obj


def walk(obj, path="$"):
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def lightspeed_procs(obj):
    """Lightspeed responses encode calls as ["5", "procName", args...]. Count the proc names."""
    names = Counter()
    for _, v in walk(obj):
        if isinstance(v, list) and len(v) >= 2 and v[0] == "5" and isinstance(v[1], str):
            names[v[1]] += 1
    return names


def summary():
    by_name = defaultdict(list)
    for f, rec in load():
        by_name[rec.get("friendly_name") or rec.get("url")].append((f, rec))
    for name, items in sorted(by_name.items(), key=lambda x: -len(x[1])):
        size = sum(f.stat().st_size for f, _ in items)
        print(f"\n{name}  —  {len(items)} responses, {size/1024:.0f} KB")
        _, rec = items[-1]
        data = expand_strings(rec.get("chunks") or [])
        top = [p for p, _ in walk(data) if p.count(".") <= 4][:12]
        for p in top:
            print(f"    {p}")
        procs = lightspeed_procs(data)
        if procs:
            print("    Lightspeed procedures:", ", ".join(f"{k}×{v}" for k, v in procs.most_common(8)))


def find(text):
    hits = 0
    for f, rec in load():
        data = expand_strings(rec.get("chunks") or [])
        for path, v in walk(data):
            if isinstance(v, str) and text.lower() in v.lower():
                hits += 1
                print(f"\n{f.name}  [{rec.get('friendly_name')}]\n  {path}")
                parent_path = path.rsplit(".", 1)[0] if "." in path else path
                parent = dict(walk(data)).get(parent_path)
                print("  parent object:")
                print("   ", json.dumps(parent, ensure_ascii=False, indent=2)[:2500].replace("\n", "\n    "))
                if hits >= 5:
                    print("\n(stopping after 5 hits)")
                    return
    if not hits:
        print("Not found. The text may be in websocket_frames.jsonl (enable CAPTURE_WEBSOCKET).")


def show(seq):
    for f, rec in load():
        if f.name.startswith(seq):
            rec["chunks"] = expand_strings(rec.get("chunks"))
            print(json.dumps(rec, ensure_ascii=False, indent=2))
            return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--find")
    ap.add_argument("--show")
    a = ap.parse_args()
    if a.find:
        find(a.find)
    elif a.show:
        show(a.show)
    else:
        summary()
