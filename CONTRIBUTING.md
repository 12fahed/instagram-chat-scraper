# Contributing

Fixes are very welcome. This is an early project that reads an undocumented API,
so things break — if you hit something and work out why, a PR saves the next
person the same hour.

## Contents

- [Before anything: never commit chat data](#before-anything-never-commit-chat-data)
- [Getting set up](#getting-set-up)
- [Reporting a bug](#reporting-a-bug)
- [The most common change: a new message type](#the-most-common-change-a-new-message-type)
- [Testing your change](#testing-your-change)
- [Code style](#code-style)
- [Commits and pull requests](#commits-and-pull-requests)

## Before anything: never commit chat data

Everything this tool produces contains private conversations — yours and someone
else's, who never agreed to any of it.

- `data/` is gitignored. Keep it that way; do not add exceptions.
- **`report.txt` is not safe to paste as-is.** It lists participant usernames,
  display names, numeric ids and the thread id. Redact those before sharing it.
- Screenshots are the easiest way to leak a conversation by accident. Crop, blur,
  or use a synthetic thread instead (see [Testing](#testing-your-change)).
- Never attach files from `data/captures/`. If a maintainer needs the shape of a
  message, post the **structure** with the values stripped — field names and
  types, not content.

In issues, PRs and code comments, refer to participants as **userA** and
**userB**.

## Getting set up

```bash
git clone <your fork>
cd instagram-chat-scraper
python -m venv venv
source venv/bin/activate
pip install playwright
playwright install chromium
```

Python 3.10 or newer. There are no other dependencies: the capture half needs
Playwright, and the analyser is standard library only. Please keep it that way —
a dependency in `src/analyze` has to earn itself.

## Reporting a bug

Useful reports include:

1. **Which command**, with the flags, and whether it was a fresh run or a resume.
2. **What the terminal printed** — the stop banner in particular, since it names
   the reason the run ended.
3. **The relevant `analyze report` sections**, redacted: `SHAPES`, `rendered as`
   and `UNHANDLED` carry no message content and are usually the whole story.
   `COVERAGE` and `CONTINUITY` do carry identifiers, so trim them.
4. **The message shape**, if the report flagged something under `UNHANDLED`. Find
   one of the listed ids in `data/captures/` and post its `content` object with
   the values replaced — field names and types are what matter.

If Instagram changed something, say which of the two halves broke: capture
stopping early is a different problem from the analyser not recognising a shape.

## The most common change: a new message type

`UNHANDLED` in the report means Instagram sent something the parser does not
know, and the renderer would show it as "Unsupported". The walkthrough is in
[docs/DEVELOPERS.md §5](docs/DEVELOPERS.md#5-adding-a-new-message-type). In short:

1. Look at the real payload first — do not guess field names.
2. Add the branch in `parse.parse_content`. For a media family, that is usually
   just `MEDIA_CONTENT` plus knowing where the attachment list lives.
3. Add a label to `parse.MEDIA_NOUNS` and `render.MEDIA_LABELS` — a missing one
   raises `KeyError` on the empty-payload path, which is the path these often
   take.
4. Render it.
5. Whitelist it in `schema.KNOWN_CONTENT` or `KNOWN_XMA`.
6. Re-run `analyze report`: `UNHANDLED` empty, `unknown` zero.

Handle the payload being empty. Several types arrive with `attachments: []` or
`attachment: null` — the message existed, the media is gone. Those become
tombstones, never silent gaps.

## Testing your change

There is no automated suite yet. Adding one would be a genuinely useful PR.

Until then:

**Build a synthetic thread.** A fixture with one of every message kind — text,
reply, reaction, system line, image, view-once blur, video, empty audio, removed
shell, share card — run through `report`, `build` and both split modes catches
most parser and renderer regressions, and contains no real data. This is also
what screenshots in issues should use.

**Stub the browser for capture changes.** Replace `playwright.async_api` in
`sys.modules` with a module exposing `Error`, and hand the loops a fake page
whose `evaluate` returns scripted responses. That covers both capture loops,
every stop reason, pause and resume, and resume-from-disk without a browser.

**Then run it for real once.** The stubs do not catch everything — several bugs
in this project only appeared against the live site.

Say in the PR which of these you did. "Tested with stubs, not run live" is a
fine thing to write; an untested claim is not.

## Code style

- Match what is there. Nothing exotic, no framework.
- Comments explain **why**, not what. If the code says what it does, leave it
  alone; if a line looks wrong until you know a reason, write the reason down.
- Keep the two halves separate: capture never interprets a message beyond
  counting it, and the analyser never touches the network except in `media.py`.
- Auth tokens never reach disk or stdout. `clean_request` strips them; the
  in-memory request template is the one exception and must stay in memory.
- Capture loops return a reason, they do not raise. If you add a way for a run to
  end, add it to the table in `terminal.report_outcome` and tell the user what to
  do about it.
- Prefer being honest in output over being reassuring. A run that may have
  stopped early should say so.

## Commits and pull requests

Commit subjects follow what is already in the log: a type, a colon, then an
imperative summary.

```
feat:     a new capability
fix:      a bug fix
enhance:  an improvement to something that already worked
refactor: no behaviour change
docs:     documentation
chore:    housekeeping
```

In the body, explain why the change was needed, not just what it does.

For a PR:

- one concern per PR
- say what you tested, and what you did not
- if it changes behaviour, update the README or `docs/DEVELOPERS.md` in the same
  PR
- no real conversation data anywhere in the diff, the description or the
  screenshots
