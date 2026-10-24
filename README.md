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
src/capture.py            Playwright: open a chat, auto-scroll up, save every
                          matching response to ./captures/
src/analyze/              Offline: read captures -> normalised chat -> HTML
  load.py                 find SlideMessage nodes in any capture shape
  parse.py                raw node -> render-ready message
  schema.py               structural report + "what did we not understand"
  render.py               single self-contained Instagram-like HTML page
  media.py                optional: mirror IG CDN images locally
src/inspect_captures.py   older ad-hoc explorer (kept for poking at new shapes)
src/build_html.py         older generic renderer (superseded by src/analyze)
data/sample/              two consecutive scrolls, used to develop the parser
data/out/                 generated output (gitignored)
```

Everything stays local. `data/` is gitignored. The only network access in
`src/analyze` is the optional `--media` download, and only to instagram/fbcdn hosts.

## Use

```bash
python -m src.analyze report data/sample
python -m src.analyze build  data/sample --me <your-username> --title "Chat"
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
- `capture.py` strips auth tokens (`fb_dtsg`, `lsd`, …) before writing anything.
- `src/analyze` reads raw response bodies, `capture.py` records, lists of either,
  and `.jsonl` — so it works on `data/sample` and on a full run unchanged.
