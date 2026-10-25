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

**The browser is never closed behind your back.** Whatever ends the run — the top of
the thread, a stall, a renderer crash, an unexpected error — the script prints what
happened and leaves Chromium open. If the chat pane is still alive you can type `r`
to carry on scrolling *from where it stopped*, which matters: a crash 1,100 pages in
would otherwise mean walking the whole thread again. A transient `page.evaluate`
failure is retried five times (re-finding the chat pane each time) before it counts
as fatal.

On a long run the likeliest crash is Chromium running out of memory — the chat pane
keeps every message you scrolled past, plus its images, in the DOM. Nothing is lost
when that happens: responses are written as they arrive.

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

`build` writes `data/out/chat.json` (normalised) plus the HTML (day dividers, reply
quotes that jump to the quoted message, reaction chips, share cards, photo/video
bubbles, search, dark mode, system-line toggle).

`--me` accepts a username, igid or sender id and decides which side is "yours".

`--split` is `auto` by default: over 3,000 messages the archive becomes one page
per year (`chat-2021.html`, …) with `chat.html` as an index, because a single page
for a multi-year thread is slow to open and to search. Reply quotes that cross a
year boundary link into the other file and land on the quoted message. Force it
either way with `--split year` / `--split none`.

`--media` downloads preview images and avatars into `data/out/media/` and rewrites
the pages to use them — worth doing, because the CDN URLs in a capture are signed
and expire within days. Video originals are skipped unless you add `--media-video`.
Anything that fails leaves a visible placeholder rather than vanishing.

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

`content.__typename` splits several ways:

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
  - `SlideMessageExpiredPlaceholderXMA` — an expired story share.
- `SlideMessageImageContent` / `SlideMessageRavenImageContent` /
  `SlideMessageRavenVideoContent` / `SlideMessageAnimatedMediaContent` — media sent
  straight into the chat rather than shared. "Raven" is Meta's name for
  disappearing / view-once media. All four expose the same fields
  (`preview_cdn_url`, `attachment_cdn_url`, `preview_width/height`,
  `attachment_fbid`); they differ only in `attachment` vs `attachments[]` vs
  `animated_media[]`, and animated media uses `attachment_webp_url` /
  `attachment_mp4_url` instead.
- `content: null` with `content_type: "NOT_SET"` — an empty shell, no
  `tombstone_reason`. Rendered as "Message removed" rather than dropped.

Two traps in the media urls:

- IG encodes the render size as `_s<W>x<H>` in the path. A view-once photo that has
  already been consumed comes back as a **12×12 blur with no larger url anywhere** —
  there is no image left. Those attachments are dropped so the message falls through
  to the "unavailable" tombstone instead of rendering a smudge.
- `*_cdn_fallback_url` is a bare path into IG's `media_fallback` endpoint, not a
  usable URL, so it is ignored.

Sample breakdown: 15 text, 10 shares, 9 unavailable/expired, 5 system lines,
1 story share; 11 replies and 6 reacted messages — all 11 replies resolved to a
message inside the same two scrolls.

A participant can come back **unhydrated**: blank `name`, `user_dict: null`, only an
`igid` — a deleted account or someone who left. They are a real sender, so their
messages are kept, but they do not count toward "is this a group" (which decides
whether every incoming bubble gets a name label) and labels fall back to the igid.

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
