"""The stylesheet and script embedded in every generated page.

Kept apart from the rendering logic purely for readability: these are long
literal strings, and interleaving them with the code that builds the markup
made both harder to follow.
"""

CSS = """
:root{
  --bg:#fff; --fg:#000; --muted:#737373; --line:#dbdbdb; --panel:#fafafa;
  --them:#efefef; --me:#3797f0; --me-fg:#fff; --card:#fff; --chip:#fff;
  --shadow:0 1px 2px rgba(0,0,0,.08);
}
:root:not([data-theme=light]) { color-scheme:light dark; }
@media (prefers-color-scheme:dark){
  :root:not([data-theme=light]){
    --bg:#000; --fg:#f5f5f5; --muted:#a8a8a8; --line:#262626; --panel:#121212;
    --them:#262626; --card:#1a1a1a; --chip:#262626; --shadow:none;
  }
}
:root[data-theme=dark]{
  --bg:#000; --fg:#f5f5f5; --muted:#a8a8a8; --line:#262626; --panel:#121212;
  --them:#262626; --card:#1a1a1a; --chip:#262626; --shadow:none; color-scheme:dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,"Apple Color Emoji","Segoe UI Emoji",sans-serif}
a{color:inherit}

header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.hwrap{max-width:880px;margin:0 auto;display:flex;align-items:center;gap:12px;padding:10px 16px}
.hwrap .av{width:44px;height:44px;flex:0 0 auto}
.htitle{font-weight:600;font-size:16px;line-height:1.2}
.hsub{color:var(--muted);font-size:13px}
.hspace{flex:1}
.tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.tools input[type=search]{background:var(--panel);border:1px solid var(--line);color:var(--fg);
  border-radius:999px;padding:7px 12px;font:inherit;font-size:13px;width:170px;min-width:0}
.tools button{background:var(--panel);border:1px solid var(--line);color:var(--fg);
  border-radius:999px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
.tools button[aria-pressed=true]{background:var(--me);border-color:var(--me);color:#fff}

main{max-width:880px;margin:0 auto;padding:12px 16px 80px}
.day{position:sticky;top:var(--sticky,64px);z-index:2;text-align:center;
  background:var(--bg);padding:8px 0;margin:16px 0 6px}
.day span{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:.3px}
.clock{text-align:center;color:var(--muted);font-size:11px;margin:16px 0 8px}

.row{display:flex;align-items:flex-end;gap:8px;margin-top:2px}
.row.grouped{margin-top:1px}
.row.me{flex-direction:row-reverse}
.stack{display:flex;flex-direction:column;max-width:min(74%,520px);min-width:0}
.row.me .stack{align-items:flex-end}
.who{color:var(--muted);font-size:12px;margin:12px 0 3px 12px}
.av{width:28px;height:28px;border-radius:50%;flex:0 0 auto;object-fit:cover;background:var(--them);
  display:grid;place-items:center;font-size:11px;font-weight:600;color:var(--muted);overflow:hidden}
.av.ghost{visibility:hidden}

.bubble{background:var(--them);border-radius:20px;padding:8px 13px;overflow-wrap:anywhere;
  white-space:pre-wrap;max-width:100%}
.row.me .bubble{background:var(--me);color:var(--me-fg)}
.row.grouped.them .bubble{border-top-left-radius:6px}
.row.grouped.me  .bubble{border-top-right-radius:6px}
.row.cont.them .bubble{border-bottom-left-radius:6px}
.row.cont.me   .bubble{border-bottom-right-radius:6px}
/* must outrank ".row.me .bubble", or cards and photos you sent sit on a blue slab */
.row .bubble.plain{background:none;padding:0}

.quote{display:block;text-decoration:none;margin:10px 0 -12px;padding:8px 12px 18px;
  border-radius:18px;background:var(--panel);border:1px solid var(--line);max-width:100%}
.row.me .quote{text-align:right}
.qlabel{display:block;color:var(--muted);font-size:11px;margin-bottom:2px}
.qbody{display:block;color:var(--muted);font-size:13px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.qbody .tag{color:var(--fg);opacity:.6}

.cardlink{display:block;text-decoration:none;color:inherit}
.card{width:230px;max-width:100%;border-radius:18px;overflow:hidden;background:var(--card);
  border:1px solid var(--line);box-shadow:var(--shadow)}
.card .eyebrow{font-size:12px;color:var(--muted);padding:8px 12px 0}
.card .shot{display:block;width:100%;max-height:340px;background:var(--them);
  aspect-ratio:9/16;object-fit:cover}
.card .foot{display:flex;align-items:center;gap:8px;padding:9px 11px;font-size:13px;min-width:0}
.card .foot .av{width:22px;height:22px}
.card .foot b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card .cap{padding:0 12px 11px;font-size:13px;color:var(--muted);white-space:pre-wrap;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.card .badge{margin-left:auto;font-size:11px;color:var(--muted);flex:0 0 auto}
.card.dead{display:flex;flex-direction:column;gap:4px;padding:14px;width:auto;max-width:300px;
  border-style:dashed;background:none}
.card.dead b{font-size:13px;font-weight:600}
.card.dead span{font-size:12px;color:var(--muted)}

.media{display:block;width:100%;max-width:260px;border-radius:18px;background:var(--them);
  object-fit:cover}
.medialink{position:relative;display:block;line-height:0;text-decoration:none;max-width:260px}
.medialink .play{position:absolute;inset:0;display:grid;place-items:center;font-size:34px;
  color:#fff;text-shadow:0 2px 8px rgba(0,0,0,.7);pointer-events:none}
.medialink .once{position:absolute;left:8px;top:8px;background:rgba(0,0,0,.55);color:#fff;
  font-size:10px;letter-spacing:.4px;border-radius:999px;padding:2px 7px;pointer-events:none}
.mediagrid{display:flex;flex-wrap:wrap;gap:3px;max-width:100%}
.voice{display:flex;align-items:center;gap:10px;background:var(--them);border-radius:22px;
  padding:7px 12px 7px 10px;max-width:300px}
.row.me .voice{background:var(--me)}
.voice audio{height:34px;max-width:230px}
.voice .dur{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.row.me .voice .dur{color:#e8f2fd}
.mediadead{border:1px dashed var(--line);border-radius:18px;padding:18px 20px;color:var(--muted);
  font-size:13px;line-height:1.5;text-align:center;min-width:150px}
.mediadead small{opacity:.75}
.sticker .media{background:none;border-radius:8px;max-width:160px}
.removed{border:1px dashed var(--line);border-radius:18px;padding:9px 14px;color:var(--muted);
  font-size:13px;font-style:italic}
.xtext{margin-top:6px}
.reacts{display:flex;gap:3px;margin:-11px 10px 6px;z-index:1}
.reacts span{background:var(--chip);border:1px solid var(--line);border-radius:999px;
  padding:1px 6px;font-size:12px;line-height:1.5;box-shadow:var(--shadow)}
.flags{font-size:11px;color:var(--muted);margin:3px 10px 0}

.sys{text-align:center;margin:10px 0}
.sys span{color:var(--muted);font-size:12px;background:var(--panel);border-radius:999px;padding:3px 12px}
.hidden{display:none!important}
.hit .bubble,.hit .card{outline:2px solid var(--me);outline-offset:2px}
mark{background:rgba(55,151,240,.35);color:inherit;border-radius:3px}
.empty{text-align:center;color:var(--muted);padding:40px 0}
@media (max-width:560px){
  .stack{max-width:84%}
  .tools input[type=search]{width:120px}
}
"""

JS = """
// The header and the year/month nav wrap differently at different widths, so the
// day divider's sticky offset is measured rather than guessed.
function setOffsets() {
  const header = document.querySelector('header');
  const nav = document.querySelector('.navwrap');
  const top = header ? header.offsetHeight : 0;
  document.documentElement.style.setProperty('--hdr', top + 'px');
  document.documentElement.style.setProperty('--sticky', (top + (nav ? nav.offsetHeight : 0)) + 'px');
}
setOffsets();
addEventListener('resize', setOffsets);

const main = document.querySelector('main');
const q = document.getElementById('q');
const sysBtn = document.getElementById('sysBtn');
const themeBtn = document.getElementById('themeBtn');

sysBtn.addEventListener('click', () => {
  const on = sysBtn.getAttribute('aria-pressed') !== 'true';
  sysBtn.setAttribute('aria-pressed', on);
  document.body.classList.toggle('nosys', !on);
});

themeBtn.addEventListener('click', () => {
  const now = document.documentElement.getAttribute('data-theme');
  const next = now === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  themeBtn.textContent = next === 'dark' ? 'Light' : 'Dark';
});

document.addEventListener('click', ev => {
  const a = ev.target.closest('a.quote');
  if (!a || !a.getAttribute('href')) return;
  // A link into another year's file is a real navigation; leave it alone.
  if (!a.getAttribute('href').startsWith('#')) return;
  // IDs are IG message ids like "m-mid.$cAAA..." - '.' and '$' make them invalid
  // CSS selectors, so never querySelector them.
  const t = document.getElementById(a.getAttribute('href').slice(1));
  if (!t) return;
  ev.preventDefault();
  t.scrollIntoView({block: 'center', behavior: 'smooth'});
  t.classList.add('hit');
  setTimeout(() => t.classList.remove('hit'), 1600);
});

let timer;
q.addEventListener('input', () => {
  clearTimeout(timer);
  timer = setTimeout(() => {
    const term = q.value.trim().toLowerCase();
    document.querySelectorAll('.row, .sys').forEach(el => {
      el.classList.toggle('hidden', !!term && !el.textContent.toLowerCase().includes(term));
    });
    document.querySelectorAll('.day, .clock').forEach(el => el.classList.toggle('hidden', !!term));
  }, 120);
});

function flash(el) {
  el.scrollIntoView({block: 'center'});
  el.classList.add('hit');
  setTimeout(() => el.classList.remove('hit'), 1600);
}

// Arriving from another year's file: land on the quoted message, not the bottom.
const deep = location.hash && document.getElementById(location.hash.slice(1));
if (deep) flash(deep); else window.scrollTo(0, document.body.scrollHeight);
"""

# Extra rules for the split archive: the year/month bar and the index page.
NAV_CSS = """
.navwrap{position:sticky;top:var(--hdr,64px);z-index:3;background:var(--bg);
  border-bottom:1px solid var(--line)}
nav.years{padding:8px 16px 0;display:flex;gap:6px;flex-wrap:wrap;justify-content:center}
nav.months{padding:6px 16px 8px}
nav.years a{text-decoration:none;color:var(--muted);font-size:13px;border:1px solid var(--line);
  border-radius:999px;padding:3px 11px}
nav.months a{font-size:12px;padding:2px 9px}
nav.years a.on{background:var(--me);border-color:var(--me);color:#fff}
.index{max-width:680px;margin:0 auto;padding:24px 16px 60px}
.yearblock{border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px}
.yearhead{display:flex;align-items:baseline;gap:12px;margin-bottom:10px}
.yearhead b{font-size:19px}
.yearhead .n{margin-left:auto;color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.monthrow{display:flex;flex-wrap:wrap;gap:6px}
.monthrow a{display:flex;align-items:baseline;gap:6px;text-decoration:none;color:inherit;
  border:1px solid var(--line);border-radius:999px;padding:4px 11px;font-size:13px}
.monthrow a:hover{background:var(--panel)}
.monthrow em{font-style:normal;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.index > a{display:flex;align-items:baseline;gap:12px;text-decoration:none;color:inherit;
  border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:8px}
.index > a:hover{background:var(--panel)}
.index > a b{font-size:18px;min-width:3.5em}
.index > a span{color:var(--muted);font-size:13px}
.index .n{margin-left:auto;font-variant-numeric:tabular-nums}
"""
