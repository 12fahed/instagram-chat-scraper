# scrape-instagram

Rebuild a readable Instagram DM archive from the GraphQL responses the web app
actually uses, because the official "Download your information" export drops
the parts that make a conversation make sense.

## Why

In the account export (both the JSON and HTML flavours) every message is a flat,
standalone entity. A reply is just another message — the export does not say what
it was replying to, and shared posts/reels/stories come through as bare links or
not at all. The `fetch__SlideThread` GraphQL query that instagram.com itself calls
when you scroll a chat returns the full object, including the **entire replied-to
message nested inside the reply** and structured attachment cards.

So: drive the real web app, record the responses, rebuild the thread offline.

## Layout

```
src/capture.py            Playwright: arm on Enter, record the chat opening,
                          auto-scroll up, save responses to data/captures/
src/analyze/              Offline: read captures -> normalised chat -> HTML
  load.py                 find SlideMessage nodes in any capture shape
  parse.py                raw node -> render-ready message
  schema.py               structural report + "what did we not understand"
  render.py               single self-contained Instagram-like HTML page
  media.py                optional: mirror IG CDN images locally
src/inspect_captures.py   older ad-hoc explorer (kept for poking at new shapes)
src/build_html.py         older generic renderer (superseded by src/analyze)
data/sample/              two consecutive scrolls, used to develop the parser
data/captures/            a real run's responses (gitignored)
data/out/                 generated output (gitignored)
```

Everything stays local. `data/` is gitignored. The only network access in
`src/analyze` is the optional `--media` download, and only to instagram/fbcdn hosts.

## Use

### Capture

```bash
python src/capture.py
```

Recording is off until you press Enter, and you press it **before** opening the
chat — so the first thread request, the bottom of the conversation, is recorded
too. After that the script waits for the chat to actually open (it watches for the
first response carrying messages), settles, then scrolls on its own.

It stops when Instagram reports `has_next_page: false` and two more scrolls stay
quiet, or after 10 scrolls with nothing new — and tells you which of the two
happened, so you know whether you really reached the top. Re-running continues the
file numbering instead of overwriting the previous run.

### Rebuild

```bash
python -m src.analyze report data/captures
python -m src.analyze build  data/captures --me <your-username> --media
```

The same commands work on the bundled sample:

```bash
python -m src.analyze report data/sample
python -m src.analyze build  data/sample --me <your-username> --media
```

`report` describes what is in the captures and, importantly, lists anything the
parser did not recognise — run it after a real capture so new message types show
up instead of silently rendering as "Unsupported".

`build` writes `data/out/chat.json` (normalised) and `data/out/chat.html`
(self-contained: day dividers, reply quotes that jump to the quoted message,
reaction chips, share cards, search, dark mode, system-line toggle).

`--me` accepts a username, igid or sender id and decides which side is "yours".
`--media` downloads preview images and avatars into `data/out/media/` and rewrites
the page to use them — worth doing, because the CDN URLs in a capture are signed
and expire within days.

## Response shape (from `data/sample`, 2 scrolls / 40 messages)

```
data.fetch__SlideThread.as_ig_direct_thread.slide_messages
  edges[].node          one message
  page_info             start_cursor / end_cursor / has_next_page / has_previous_page
```

20 messages per page, newest first. Pages are contiguous: the two sample scrolls
meet with 31 seconds between them and zero overlap.

Per node, the fields that matter:

| field | notes |
| --- | --- |
| `message_id` / `id` | `mid.$...` — contains `.` and `$`, so never use it in a CSS selector |
| `timestamp_ms` | string, epoch ms |
| `sender_fbid`, `sender` | `sender.user_dict` carries username, full name, profile pic |
| `content.__typename` | the real discriminator, see below |
| `content_type` | `TEXT` / `MESSAGE_INLINE_SHARE` / `MONTAGE_SHARE_XMA` |
| `replied_to_message` | **the whole quoted message object**, not just an id — this is what the export loses |
| `reactions[]` | `{reaction: "😂", sender_fbid}` |
| `msg_reactions[]` | same reactors, ids only; redundant with `reactions` |
| `mentions[]`, `slide_edit_history[]`, `is_pinned`, `igd_is_forwarded` | empty in the sample, carried through anyway |

`content.__typename` splits three ways:

- `SlideMessageText` — plain text in `content.text_body`.
- `SlideMessageAdminText` — system line, text in `content.text_fragments[].plaintext`.
  In the sample these are all `is_reaction_action_log: true` ("Reacted 😡 to your
  message"), i.e. duplicates of `reactions[]`. The HTML shows them behind the
  **System** toggle.
- `SlideMessageXMAContent` — an attachment card, further split by `content.xma.__typename`:
  - `SlideMessagePortraitXMA` — post / reel / story share. Has `preview_image`
    (+`width`/`height`/`preview_image_decoration_type`: `REEL`, `COLLAGE`,
    `INSTAGRAM_ICON`), `header_title_text` + `header_icon` for the author,
    `target_url`, and `eyebrow_text` for story context.
  - `SlideMessageStandardXMA` — either a share with no preview (the post's caption
    sits in `title_text`, link in `target_url`) or the `"Message expired"` tombstone
    (empty `target_url`).
  - `SlideMessagePlaceholderXMA` — `"Message unavailable"`, deleted or privacy-hidden.

Sample breakdown: 15 text, 10 shares, 9 unavailable/expired, 5 system lines,
1 story share; 11 replies and 6 reacted messages — all 11 replies resolved to a
message inside the same two scrolls.

## Capture notes

- Pages are contiguous by construction, so a time gap between two captured pages is
  usually just a quiet stretch, not a missed scroll. The only hard check is the
  cursor chain, which needs the *request* variables — `capture.py` records those, so
  `report` verifies it automatically on real captures (the raw sample bodies can't be
  checked and the report says so).
- `capture.py` strips auth tokens (`fb_dtsg`, `lsd`, …) before writing anything, and
  writes under `data/` so the gitignore covers captured conversations.
- `src/analyze` reads raw response bodies, `capture.py` records, lists of either,
  and `.jsonl` — so it works on `data/sample` and on a full run unchanged.



-----------

Instagram reports no older messages left — reached the top of the thread.

935 responses in /home/fahed/Fahed/Personal/scrape-instagram/data/captures
18636 unique messages across 932 thread pages
range: 2020-03-26 13:04  ..  2024-10-24 18:51

Next: python -m src.analyze report data/captures

-----------
