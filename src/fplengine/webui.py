"""Presentation layer for the FPL Engine website.

Pure rendering: every figure comes from an assembled payload and every number
carries its provenance (OBSERVED / CALCULATED / MODELLED / APPROXIMATED) either
inline or within reach of a player drawer. No model logic lives here.

Design language: a dark, football-first decision product. Mobile-first layout
with a sticky bottom navigation, an intelligent desktop header, semantic colour
that never relies on colour alone, tabular numerals and restrained motion.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

ROUTES = (
    ("home", "Home"),
    ("myteam", "My Team"),
    ("transfers", "Transfers"),
    ("market", "Market"),
    ("players", "Players"),
    ("fixtures", "Fixtures"),
    ("captain", "Captain"),
    ("changes", "What Changed"),
    ("premier", "Premier League"),
    ("model", "Model / Methodology"),
)
ROUTE_TITLES = dict(ROUTES)
MOBILE_PRIMARY = ("home", "myteam", "transfers", "market")

_ICONS = {
    "home": "M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z",
    "myteam": "M4 19v-2a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v2M12 3a3.2 3.2 0 1 1 0 6.4A3.2 3.2 0 0 1 12 3z",
    "transfers": "M7 8h11m0 0-3-3m3 3-3 3M17 16H6m0 0 3 3m-3-3 3-3",
    "market": "M4 19V5m0 14h16M8 15l3-4 3 2 5-6",
    "more": "M5 12h.01M12 12h.01M19 12h.01",
}

_STYLE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=theme-color content="#000000">
<title>FPL Engine</title><style>
:root{
--bg:#000000;
--surface:#1c1c1e;
--surface2:#2c2c2e;
--raised:#3a3a3c;
--fill:rgba(120,120,128,.24);
--fill2:rgba(120,120,128,.36);
--sep:rgba(255,255,255,.08);
--text:#f5f5f7;
--muted:rgba(235,235,245,.62);
--faint:rgba(235,235,245,.34);
--accent:#30d158;
--cyan:#64d2ff;
--up:#30d158;
--down:#ff453a;
--warn:#ffd60a;
--link:#0a84ff;
--r-card:18px;--r-chip:10px;
--ease:cubic-bezier(.32,.72,0,1);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display",
ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif;
font-size:15px;line-height:1.47;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
padding-bottom:calc(84px + env(safe-area-inset-bottom))}
a{color:inherit;text-decoration:none;-webkit-tap-highlight-color:transparent}
.num{font-variant-numeric:tabular-nums;letter-spacing:-.01em}
::selection{background:rgba(48,209,88,.35)}
:focus{outline:none}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
/* ---------- chrome ---------- */
header.top{position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:.55rem;
padding:.7rem 1.1rem;background:rgba(8,8,10,.72);
backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);
border-bottom:.5px solid var(--sep)}
.logo{font-weight:700;font-size:.95rem;letter-spacing:-.01em}
.logo span{color:var(--accent)}
header.top nav{display:none;gap:.05rem;margin-left:auto}
header.top nav a{padding:.4rem .68rem;border-radius:9px;color:var(--muted);
font-size:.83rem;font-weight:600;transition:background .2s var(--ease),color .2s var(--ease)}
header.top nav a:hover{background:var(--fill);color:var(--text)}
header.top nav a[aria-current]{color:var(--text);background:var(--fill2)}
main{max-width:42rem;margin:0 auto;padding:1.1rem 1.15rem}
@media(min-width:1100px){main{max-width:64rem}}
footer{max-width:42rem;margin:2rem auto 0;padding:1.1rem 1.15rem 1rem;color:var(--faint);
font-size:.78rem}
footer a{color:var(--link)}
nav.bottom{position:fixed;left:0;right:0;bottom:0;z-index:50;display:flex;
justify-content:space-around;background:rgba(12,12,14,.78);
backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);
border-top:.5px solid rgba(255,255,255,.14);
padding:.4rem .2rem calc(.5rem + env(safe-area-inset-bottom))}
nav.bottom a,nav.bottom button{display:flex;flex-direction:column;align-items:center;gap:3px;
color:var(--faint);font-size:.58rem;font-weight:600;letter-spacing:.02em;background:none;
border:none;cursor:pointer;padding:.3rem .6rem;border-radius:12px;min-width:60px;
font-family:inherit;transition:color .2s var(--ease),transform .15s var(--ease)}
nav.bottom svg{width:22px;height:22px}
nav.bottom a[aria-current]{color:var(--accent)}
nav.bottom a:active,nav.bottom button:active{transform:scale(.92)}
.sheet,.drawer{transition:opacity .25s var(--ease)}
.sheet .veil,.drawer .veil{opacity:0;transition:opacity .28s var(--ease)}
.sheet.open .veil,.drawer.open .veil{opacity:1}
.sheet .panel{transition:transform .38s var(--ease)}
.drawer .panel{transition:transform .38s var(--ease)}
.sheet{position:fixed;inset:0;z-index:60;display:none}
.sheet.open{display:block}
.sheet .veil{position:absolute;inset:0;background:rgba(0,0,0,.5)}
.sheet .panel{position:absolute;left:0;right:0;bottom:0;background:#1c1c1e;
border-radius:22px 22px 0 0;padding:.4rem 1.1rem calc(1.4rem + env(safe-area-inset-bottom));
transform:translateY(100%)}
.sheet.open .panel{transform:translateY(0)}
.grabber::before{content:"";display:block;width:38px;height:5px;border-radius:3px;
background:rgba(255,255,255,.22);margin:2px auto 10px}
.sheet .panel a{display:flex;justify-content:space-between;align-items:center;
padding:.95rem .3rem;font-weight:600;font-size:1.02rem;
border-bottom:.5px solid var(--sep);transition:opacity .15s ease}
.sheet .panel a:last-of-type{border-bottom:none}
.sheet .panel a:active{opacity:.5}
.sheet .panel a::after{content:"\203A";color:var(--faint);font-size:1.3rem;line-height:1}
@media(min-width:920px){
body{padding-bottom:2rem}
nav.bottom,.mobmenu{display:none!important}
header.top nav{display:flex}
main{padding:1.6rem 1.15rem}
}
/* ---------- typography & layout ---------- */
h1{font-size:1.65rem;font-weight:800;letter-spacing:-.03em;margin:.2rem 0 .15rem}
h2{font-size:.76rem;margin:1.7rem 0 .6rem;text-transform:uppercase;
letter-spacing:.1em;color:var(--muted);font-weight:600}
.sub{color:var(--muted);font-size:.86rem}
.card{background:var(--surface);border-radius:var(--r-card);
padding:1.05rem 1.1rem;box-shadow:0 1px 2px rgba(0,0,0,.4),0 8px 28px rgba(0,0,0,.35);
margin-bottom:.75rem}
.grid{display:grid;gap:.75rem;margin-bottom:.75rem}
.g2{grid-template-columns:1fr}@media(min-width:720px){.g2{grid-template-columns:1fr 1fr}}
.g3{grid-template-columns:1fr}@media(min-width:720px){.g3{grid-template-columns:repeat(3,1fr)}}
.rowflex{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
.spread{display:flex;align-items:center;justify-content:space-between;gap:.6rem}
.chip{display:inline-flex;align-items:center;gap:.3rem;padding:.24rem .62rem;
border-radius:999px;font-size:.7rem;font-weight:600;letter-spacing:.01em;
background:var(--fill);color:var(--muted);white-space:nowrap;
text-transform:none}
.chip.ok{color:var(--accent);background:rgba(48,209,88,.16)}
.chip.warn{color:var(--warn);background:rgba(255,214,10,.14)}
.chip.bad{color:var(--down);background:rgba(255,69,58,.16)}
.chip.info{color:var(--cyan);background:rgba(100,210,255,.14)}
.chip.up{color:var(--up)}.chip.down{color:var(--down)}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex:none}
.dot.fresh{background:var(--up);box-shadow:0 0 10px rgba(48,209,88,.8);
animation:pulse 2.4s var(--ease) infinite}
@keyframes pulse{50%{box-shadow:0 0 2px rgba(48,209,88,.4)}}
.dot.stale{background:var(--warn)}.dot.old{background:var(--down)}
.stat .v{font-size:1.06rem;font-weight:700;letter-spacing:-.02em}
.stat .k{font-size:.66rem;color:var(--faint);font-weight:500;margin-top:1px}
.upC{color:var(--up)}.downC{color:var(--down)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.35rem;
padding:.52rem 1rem;border-radius:12px;border:none;background:var(--fill);
color:var(--text);font-weight:600;font-size:.85rem;cursor:pointer;font-family:inherit;
transition:transform .18s var(--ease),background .18s var(--ease),opacity .15s ease;
-webkit-tap-highlight-color:transparent}
.btn:hover{background:var(--fill2)}
.btn:active{transform:scale(.96)}
.btn.primary{background:var(--accent);color:#04120a}
.btn.primary:hover{background:#2ec452}
table{width:100%;border-collapse:collapse;font-size:.86rem}
th{color:var(--faint);font-size:.68rem;font-weight:600;text-align:left;
padding:.45rem .5rem;border-bottom:.5px solid var(--sep)}
td{padding:.55rem .5rem;border-bottom:.5px solid var(--sep);white-space:nowrap}
tr:last-child td{border-bottom:none}
.scrollx{overflow-x:auto;-webkit-overflow-scrolling:touch}
details{background:var(--surface);border-radius:var(--r-card);margin-bottom:.75rem;
overflow:hidden}
details summary{cursor:pointer;padding:.95rem 1.1rem;font-weight:600;font-size:.94rem;
list-style:none;display:flex;justify-content:space-between;align-items:center;
transition:opacity .15s ease}
details summary::-webkit-details-marker{display:none}
details summary:active{opacity:.6}
details summary::after{content:"\203A";color:var(--faint);font-size:1.25rem;
transform:rotate(90deg);transition:transform .25s var(--ease);line-height:1}
details[open] summary::after{transform:rotate(-90deg)}
details .inside{padding:.1rem 1.1rem 1.05rem}
/* ---------- hero ---------- */
.hero{padding:1.15rem 1.15rem 1.25rem;background:
 radial-gradient(130% 130% at 88% -30%,rgba(48,209,88,.16),transparent 52%),
 #0d0d0f;border-radius:24px;margin-bottom:.4rem}
.hero-top{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem}
.hero .gw-label{font-size:.74rem;font-weight:600;color:var(--muted);
letter-spacing:.08em;text-transform:uppercase}
.hero .gw{font-size:2.9rem;font-weight:800;letter-spacing:-.04em;line-height:1.02;
margin-top:.1rem}
.countdown{font-weight:700;font-size:1.02rem;letter-spacing:-.01em;margin-top:.35rem;
color:var(--text)}
.hero-status{display:flex;flex-direction:column;gap:.42rem;align-items:flex-end}
.statusline{display:inline-flex;align-items:center;gap:.42rem;color:var(--muted);
font-size:.8rem;font-weight:500}
/* ---------- next move ---------- */
.action-word{font-size:2rem;font-weight:800;letter-spacing:-.035em;line-height:1.05;
margin:.45rem 0 .1rem}
.movecards{display:flex;align-items:stretch;gap:.6rem;margin-top:.75rem;flex-wrap:wrap}
.tcard{flex:1 1 132px;background:var(--surface2);border-radius:14px;
padding:.65rem .75rem;min-width:122px}
.tcard .cl{color:var(--accent);font-size:.64rem;font-weight:700;letter-spacing:.09em}
.tcard.out .cl{color:var(--down)}
.tcard .nm{font-weight:700;font-size:.98rem;letter-spacing:-.01em;margin-top:2px}
.tcard .sub{font-size:.73rem}
.tcard .xp{font-size:.95rem;font-weight:700;margin-top:.3rem}
.arrow{align-self:center;color:var(--faint);font-size:1.3rem}
.metrics{display:flex;gap:1.5rem;flex-wrap:wrap;margin-top:.9rem}
/* ---------- pitch ---------- */
.pitch{position:relative;border-radius:22px;padding:1.1rem .6rem;overflow:hidden;
background:
 radial-gradient(90% 60% at 50% 0%,rgba(255,255,255,.05),transparent 60%),
 repeating-linear-gradient(180deg,#0b1f13 0 44px,#0a1c11 44px 88px);
border:.5px solid rgba(255,255,255,.09)}
.pitch::before{content:"";position:absolute;left:50%;top:54%;width:76px;height:76px;
transform:translate(-50%,-50%);border:1.5px solid rgba(255,255,255,.11);border-radius:50%}
.pitch::after{content:"";position:absolute;left:8%;right:8%;top:54%;
height:1.5px;background:rgba(255,255,255,.11)}
.pitch .row{display:flex;justify-content:center;gap:.4rem;margin:.44rem 0;
position:relative;z-index:1}
.pcard{position:relative;flex:1 1 0;max-width:104px;background:rgba(18,26,20,.82);
backdrop-filter:blur(6px);border:.5px solid rgba(255,255,255,.12);
border-radius:13px;padding:.4rem .18rem;text-align:center;cursor:pointer;
font-family:inherit;color:inherit;
transition:transform .2s var(--ease),border-color .2s var(--ease),background .2s ease;
-webkit-tap-highlight-color:transparent}
.pcard:hover{transform:translateY(-2px);background:rgba(28,40,31,.9)}
.pcard:active{transform:scale(.95)}
.pcard .nm{font-size:.71rem;font-weight:600;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
.pcard .mt{font-size:.6rem;color:rgba(235,235,245,.55);display:flex;
justify-content:center;gap:.3rem}
.bench{display:flex;gap:.5rem;overflow-x:auto;padding:.55rem .1rem .2rem;
-webkit-overflow-scrolling:touch;scrollbar-width:none}
.bench::-webkit-scrollbar{display:none}
.bench .pcard{flex:0 0 102px}
.cbadge{position:absolute;top:-6px;right:-3px;background:var(--warn);color:#201a00;
font-size:.56rem;font-weight:700;border-radius:7px;padding:.06rem .3rem}
/* ---------- drawer ---------- */
.drawer{position:fixed;inset:0;z-index:70;display:none}
.drawer.open{display:block}
.drawer .veil{position:absolute;inset:0;background:rgba(0,0,0,.55)}
.drawer .panel{position:absolute;background:#1c1c1e;left:0;right:0;bottom:0;
border-radius:22px 22px 0 0;max-height:88vh;overflow-y:auto;overscroll-behavior:contain;
padding:.4rem 1.15rem calc(1.6rem + env(safe-area-inset-bottom));transform:translateY(100%)}
.drawer.open .panel{transform:translateY(0)}
@media(min-width:720px){.drawer .panel{left:auto;right:1.1rem;top:4.8rem;bottom:1.1rem;
width:430px;border-radius:22px;transform:translateX(24px);opacity:0;
transition:transform .38s var(--ease),opacity .3s var(--ease)}
.drawer.open .panel{transform:translateX(0);opacity:1}}
.dclose{float:right;background:var(--fill);border:none;color:var(--muted);width:30px;
height:30px;border-radius:50%;font-size:1.15rem;cursor:pointer;line-height:1;
margin-left:.5rem;transition:transform .18s var(--ease)}
.dclose:active{transform:scale(.9)}
.kv{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem .8rem;margin:.75rem 0}
.kv .stat .v{font-size:1rem}
.why{border-radius:14px;padding:.7rem .85rem;background:var(--surface2);
color:var(--muted);font-size:.87rem;margin-top:.7rem;line-height:1.5}
.why b{color:var(--text)}
/* ---------- segmented control ---------- */
.seg{display:flex;background:var(--fill);border-radius:12px;padding:.22rem;gap:.2rem;
margin:.6rem 0}
.seg button{flex:1;border:none;background:transparent;color:var(--muted);font-weight:600;
padding:.5rem .4rem;border-radius:9.5px;cursor:pointer;font-size:.83rem;
font-family:inherit;transition:background .25s var(--ease),color .25s var(--ease),
transform .15s var(--ease)}
.seg button:active{transform:scale(.96)}
.seg button[aria-selected="true"]{background:#5a5a5e;color:#fff;
box-shadow:0 2px 8px rgba(0,0,0,.4)}
.plan{display:none}.plan.active{display:block;animation:fadeup .3s var(--ease)}
@keyframes fadeup{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
/* ---------- market / lists ---------- */
.mgrid{display:grid;gap:.6rem;grid-template-columns:1fr}
@media(min-width:720px){.mgrid{grid-template-columns:1fr 1fr}}
.mcard{display:flex;justify-content:space-between;gap:.7rem;align-items:center;
background:var(--surface);border-radius:15px;padding:.7rem .85rem;width:100%;
border:none;color:inherit;font-family:inherit;text-align:left;cursor:default;
transition:transform .18s var(--ease)}
button.mcard{cursor:pointer}
button.mcard:active{transform:scale(.97)}
.mcard .nm{font-weight:600;font-size:.93rem;letter-spacing:-.01em}
.mcard .sub{font-size:.71rem}
.toolbar{display:flex;gap:.5rem;flex-wrap:wrap;margin:.5rem 0 .9rem}
.toolbar input,.toolbar select{background:var(--surface);border:none;color:var(--text);
border-radius:12px;padding:.5rem .65rem;font-size:.86rem;font-family:inherit;
appearance:none;-webkit-appearance:none}
.toolbar input[type=search]{flex:1 1 150px}
.feeditem{display:flex;gap:.75rem;padding:.65rem 0;border-bottom:.5px solid var(--sep)}
.feeditem:last-child{border-bottom:none}
.comparebar{position:fixed;left:50%;transform:translateX(-50%) translateY(80px);
bottom:calc(76px + env(safe-area-inset-bottom));z-index:55;
background:rgba(44,44,46,.92);backdrop-filter:blur(20px) saturate(180%);
border-radius:16px;padding:.55rem .85rem;display:flex;gap:.6rem;align-items:center;
box-shadow:0 10px 34px rgba(0,0,0,.5);opacity:0;
transition:transform .35s var(--ease),opacity .3s var(--ease)}
.comparebar.show{transform:translateX(-50%) translateY(0);opacity:1}
@media(min-width:920px){.comparebar{bottom:1.3rem}}
.legendrow{display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.5rem}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>"""


def _icon(key: str) -> str:
    return (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden=true><path d="{_ICONS[key]}"/></svg>'
    )


def _esc(value: Any) -> str:
    return escape(str(value))


def _ago_display(minutes: int | None) -> str:
    if minutes is None:
        return "age unknown"
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 36:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _freshness_line(freshness: dict[str, Any]) -> str:
    level = freshness.get("level") or "old"
    dot_class = level if level in ("fresh", "stale") else "old"
    label = freshness.get("label") or "age unknown"
    title = (
        "Predictions come from scheduled ingestion runs; market fields from the "
        "half-hourly market poll."
    )
    return (
        f'<span class=statusline title="{_esc(title)}">'
        f'<span class="dot {dot_class}"></span>{_esc(label)}</span>'
    )


def _provenance_chip(kind: str) -> str:
    definitions = {
        "OBSERVED": "Official FPL data as captured by our ingestion.",
        "CALCULATED": "Arithmetic derived from official observations.",
        "MODELLED": "Engine estimate - not an observed fact.",
        "APPROXIMATED": "Best available reconstruction; treat as approximate.",
        "VERIFIED": "Confirmed exact from official endpoints.",
        "RECONSTRUCTED": "Rebuilt rule-by-rule from official history.",
        "USER-SUPPLIED": "Provided by you; takes precedence.",
    }
    css = {
        "OBSERVED": "info",
        "CALCULATED": "",
        "MODELLED": "info",
        "APPROXIMATED": "warn",
        "VERIFIED": "ok",
        "RECONSTRUCTED": "",
        "USER-SUPPLIED": "ok",
    }
    cls = css.get(kind, "")
    hint = definitions.get(kind, "")
    return f'<span class="chip {cls}" title="{_esc(hint)}">{_esc(kind)}</span>'


def _pressure_badge(row: dict[str, Any]) -> str:
    direction = row.get("pressure_direction") or "FLAT"
    level = row.get("pressure_level") or "LOW"
    arrow = {"UP": "\u2191", "DOWN": "\u2193"}.get(direction, "\u2192")
    cls = {"UP": "up", "DOWN": "down"}.get(direction, "")
    title = MARKET_PRESSURE_NOTE
    return (
        f'<span class="chip {cls}" title="{_esc(title)}">PRESSURE {arrow} '
        f"{_esc(level)}</span>"
    )


MARKET_PRESSURE_NOTE = (
    "Experimental pressure indicator from observed transfer velocity and "
    "ownership movement. Not the official FPL price-change threshold."
)


def _shell(route: str, body_html: str, model_version: str = "") -> str:
    primary_links = "".join(
        f'<a href="/site/{key}"{_active(route, key)}>{_icon(key)}<span>{_esc(label)}</span></a>'
        for key, label in ROUTES
        if key in MOBILE_PRIMARY
    )
    more_button = (
        f'<button id=moresheet-open aria-haspopup=dialog>{_icon("more")}'
        "<span>MORE</span></button>"
    )
    desktop_links = "".join(
        f'<a href="/site/{key}"{_active(route, key)}>{_esc(label)}</a>'
        for key, label in ROUTES
    )
    more_items = "".join(
        f'<a href="/site/{key}">{_esc(label)}</a>'
        for key, label in ROUTES
        if key not in MOBILE_PRIMARY
    )
    script = """
(function(){
document.getElementById('moresheet-open').addEventListener('click',function(){
 document.getElementById('moresheet').classList.add('open');});
var sheet=document.getElementById('moresheet');
sheet.addEventListener('click',function(e){
 if(e.target.hasAttribute('data-close')||e.target.closest('a')){sheet.classList.remove('open');}});
var cd=document.getElementById('countdown');
if(cd&&cd.dataset.deadline){var dl=new Date(cd.dataset.deadline);
 function tick(){var d=dl-new Date();if(isNaN(d)){cd.textContent='';return;}
  if(d<=0){cd.textContent='deadline passed';return;}
  var s=Math.floor(d/1000),dd=Math.floor(s/86400),h=Math.floor(s%86400/3600),
  m=Math.floor(s%3600/60),sec=s%60;
  cd.textContent=(dd?dd+'d ':'')+h+'h '+String(m).padStart(2,'0')+'m '
  +String(sec).padStart(2,'0')+'s';}
 tick();setInterval(tick,1000);}
})();
"""
    return (
        f"{_STYLE}<header class=top><div class=\"logo\">FPL<span>ENGINE</span></div>"
        f"<span class=\"chip info\">{_esc(model_version)}</span><nav>{desktop_links}</nav></header>"
        f"<main>{body_html}</main>"
        f"<footer>FPL Engine &middot; decisions before deadlines &middot; "
        f'<a href="/site/model" style="color:var(--cyan)">provenance &amp; methodology</a></footer>'
        f'<nav class=bottom aria-label="Primary">{primary_links}{more_button}</nav>'
        f'<div class=sheet id=moresheet role=dialog aria-modal=true aria-label="More sections">'
        f'<div class=veil data-close></div><div class="panel grabber">{more_items}</div></div>'
        f"<script>{script}</script></body></html>"
    )


def _active(route: str, key: str) -> str:
    return ' aria-current="page"' if route == key else ""


def _stat(label: str, value: str, extra_class: str = "") -> str:
    return (
        f'<div class=stat><div class="v num {_esc(extra_class)}">{value}</div>'
        f'<div class=k>{_esc(label)}</div></div>'
    )


def _fmt_signed(value: Any, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "&ndash;"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "&ndash;"
    css = "upC" if number > 0 else ("downC" if number < 0 else "")
    sign = "+" if number > 0 else ""
    return f'<span class="{css} num">{sign}{number:.{digits}f}{suffix}</span>'


def render_page(route: str, payload: dict[str, Any]) -> str:
    """Render one website route from an assembled cockpit payload."""
    renderers = {
        "home": _render_home,
        "myteam": _render_myteam,
        "transfers": _render_transfers,
        "captain": _render_captain,
        "players": _render_players,
        "market": _render_market,
        "changes": _render_changes,
        "fixtures": _render_fixtures,
        "premier": _render_premier,
        "model": _render_model,
    }
    renderer = renderers.get(route, _render_home)
    body = renderer(payload)
    meta = payload.get("metadata") or {}
    return _shell(route, body, str(meta.get("model_version") or ""))


# --------------------------------------------------------------------------
# HOME
# --------------------------------------------------------------------------

def _hero(payload: dict[str, Any]) -> str:
    meta = payload.get("metadata") or {}
    season = payload.get("season") or {}
    freshness = payload.get("freshness") or {}
    deadline = season.get("deadline_utc")
    countdown_data = f' data-deadline="{_esc(deadline)}"' if deadline else ""
    countdown_text = "deadline n/a" if not deadline else ""
    warnings = payload.get("warnings") or []
    warn_dots = "".join(
        f'<span class=statusline title="{_esc(w)}"><span class="dot stale"></span>'
        "notice</span>"
        for w in warnings[:1]
    )
    return (
        '<section class=hero aria-label="Gameweek status">'
        '<div class=hero-top>'
        "<div>"
        f'<div class=gw-label>Gameweek</div>'
        f'<div class="gw num">{_esc(meta.get("target_event"))}</div>'
        f'<div class="countdown num" id=countdown{countdown_data}>{countdown_text}</div>'
        "</div>"
        f'<div class=hero-status>{_freshness_line(freshness)}'
        f'<span class=statusline>{_esc(meta.get("model_version"))}</span>'
        f"{warn_dots}</div>"
        "</div></section>"
    )


def _player_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Name -> compact player record, used to enrich IN/OUT transfer cards."""
    index: dict[str, dict[str, Any]] = {}
    for row in payload.get("all_players") or []:
        name = str(row.get("player_name") or "")
        if name:
            index.setdefault(name.lower(), row)
    return index


def _transfer_card(record: dict[str, Any] | None, direction: str) -> str:
    if not record:
        return ""
    club = _esc(record.get("team") or "")
    position = _esc(record.get("position") or "")
    price = record.get("price")
    xp = record.get("expected_points")
    mins = record.get("expected_minutes")
    detail_bits = [club, position]
    if isinstance(price, (int, float)):
        detail_bits.append(f"\u00a3{price:.1f}m")
    css_class = "tcard out" if direction == "OUT" else "tcard"
    return (
        f'<div class={css_class}><div class=cl>{direction}</div>'
        f'<div class=nm>{_esc(record.get("player_name") or record.get("name"))}</div>'
        f'<div class=sub>{" &middot; ".join(b for b in detail_bits if b)}</div>'
        '<div class="xp num">'
        + (f"{xp:.1f} xP" if isinstance(xp, (int, float)) else "xP n/a")
        + (f' <span style="color:var(--faint)">&middot;</span> {mins:.0f}m'
           if isinstance(mins, (int, float)) else "")
        + "</div></div>"
    )


def _move_cards(payload: dict[str, Any], ins: list[str], outs: list[str]) -> str:
    index = _player_index(payload)
    pairs = max(len(ins), len(outs))
    if not pairs:
        return '<p class=sub style=margin:.4rem 0>No transfers - squad stays as it is.</p>'
    cards = []
    for index_num in range(pairs):
        in_name = ins[index_num] if index_num < len(ins) else None
        out_name = outs[index_num] if index_num < len(outs) else None
        in_card = _transfer_card(index.get(str(in_name or "").lower()), "IN")
        out_card = _transfer_card(index.get(str(out_name or "").lower()), "OUT")
        arrow = '<span class=arrow>&rarr;</span>' if in_card and out_card else ""
        cards.append(f"<div class=movecards>{in_card}{arrow}{out_card}</div>")
    return "".join(cards)


def _plan_ins_outs(payload: dict[str, Any], plan: dict[str, Any]) -> str:
    ins = plan.get("transfers_in") or []
    outs = plan.get("transfers_out") or []
    if not ins and not outs:
        return '<p class=sub>No transfers - the squad stays exactly as it is.</p>'
    return _move_cards(payload, list(ins), list(outs))


def _next_move_card(payload: dict[str, Any]) -> str:
    next_gw = payload.get("next_gw") or {}
    rec = next_gw.get("recommendation") or {}
    if not rec:
        return '<div class=card><h2>Your next move</h2><p class=sub>Personal decision engine unavailable.</p></div>'
    plan = rec.get("recommended_plan") or {}
    state_label = rec.get("state_label") or "APPROXIMATE"
    provenance = _provenance_chip(
        "VERIFIED" if state_label == "VERIFIED_INPUTS" else "APPROXIMATED"
    )
    manager_state = payload.get("manager_state") or {}
    ft_value = (manager_state.get("free_transfers") or {}).get("value")
    bank_value = (manager_state.get("bank") or {}).get("value")
    gain = rec.get("best_gain_over_roll")
    action_css = "upC" if str(rec.get("action")).startswith("ROLL") else ""
    details = "".join(
        f'<details><summary>See why<span class=sub>{_esc(rec.get("reason"))[:90]}</span></summary>'
        f'<div class=inside><p>{_esc(rec.get("reason"))}</p>'
        f'<p class=sub>Every candidate was compared against rolling with hit costs '
        f"included. State inputs carry their own labels below.</p></div></details>"
    )
    return (
        '<div class=card><div class=spread><h2 style=margin:0>Your next move</h2>'
        f"{provenance}</div>"
        f'<div class="action-word {action_css}" style=margin-top:.35rem>'
        f"{_esc(rec.get('action'))}</div>"
        f'<div class=movecards>{_plan_ins_outs(payload, plan)}</div>'
        '<div class=metrics>'
        + _stat("gain vs roll", _fmt_signed(gain, 2))
        + _stat("hit cost", f"{plan.get('hit_cost', 0)} pts")
        + _stat("free transfers", _esc(ft_value))
        + _stat("bank", f"&pound;{_esc(bank_value)}")
        + "</div>" + details + "</div>"
    )


def _captain_home_card(payload: dict[str, Any]) -> str:
    my_team_rows = ((payload.get("my_team") or {}).get("players")) or []
    captain = next((row for row in my_team_rows if row.get("is_captain")), None)
    vice = next((row for row in my_team_rows if row.get("is_vice_captain")), None)
    candidates = payload.get("captains") or []
    alt = candidates[0] if candidates else None
    if not captain:
        return (
            '<div class=card><h2>Captain</h2>'
            '<p class=sub>Captain data unavailable for this gameweek.</p></div>'
        )
    range_lo, range_hi = (captain.get("range") or [0, 0])
    alt_html = ""
    if alt and alt.get("name") != captain.get("name"):
        alt_html = (
            f'<p class=sub style=margin-top:.5rem>Strongest alternative outside your '
            f"squad: <b>{_esc(alt['name'])}</b> at {alt['expected_points']:.2f} xP.</p>"
        )
    vice_html = (
        f"<p class=sub>Vice: <b>{_esc(vice['name'])}</b></p>" if vice else ""
    )
    return (
        '<div class=card><div class=spread><h2 style=margin:0>Captain</h2>'
        f"{_provenance_chip('MODELLED')}</div>"
        f'<div class="action-word upC" style=margin-top:.3rem>{_esc(captain.get("name"))}</div>'
        '<div class=metrics>'
        + _stat("xP", f"{captain.get('expected_points', 0):.2f}")
        + _stat("xMins", f"{captain.get('expected_minutes', 0):.0f}")
        + _stat("range", f"[{range_lo:.1f}, {range_hi:.1f}]")
        + _stat("risk", f"{captain.get('risk', 0):.2f}")
        + _stat("owned", f"{captain.get('ownership_percent', 0):.1f}%")
        + "</div>" + vice_html + alt_html
        + '<p style=margin-bottom:0><a class=btn href=/site/captain>Compare captains</a></p></div>'
    )


def _price_watch_card(payload: dict[str, Any]) -> str:
    market = payload.get("market") or {}
    if not market.get("available"):
        note = market.get("reason") or "market history is still filling up"
        return (
            "<div class=card><h2>Price watch</h2>"
            f'<p class=sub>Unavailable - {note}. Market observations build up over '
            "the coming hours once polling starts.</p></div>"
        )
    owned_ids = {
        row["player_id"] for row in ((payload.get("my_team") or {}).get("players") or [])
    }
    rows = market.get("players") or []
    watch = [row for row in rows if row["player_id"] in owned_ids]
    movers = sorted(
        rows,
        key=lambda item: abs(item.get("net_transfers_6h") or 0),
        reverse=True,
    )[:4]
    watch.extend(row for row in movers if row not in watch)
    watch = watch[:8]

    def line(row: dict[str, Any]) -> str:
        six = row.get("net_transfers_6h")
        six_txt = _fmt_signed(six, 0) if six is not None else '&ndash;'
        delta = row.get("price_change_24h")
        return (
            f'<tr><td><b>{_esc(row.get("name"))}</b></td>'
            f'<td class=num>&pound;{row.get("price", 0):.1f}m</td>'
            f'<td class=num>{six_txt}</td>'
            f"<td>{_pressure_badge(row)}</td></tr>"
        )

    table_rows = "".join(line(row) for row in watch)
    return (
        '<div class=card><div class=spread><h2 style=margin:0>Price watch</h2>'
        f'<span class=sub>{_esc(market.get("captured_at"))}</span></div>'
        '<div class=scrollx><table><thead><tr><th>Player</th><th>Price</th>'
        f"<th>Net 6h</th><th>Pressure</th></tr></thead><tbody>{table_rows}</tbody></table></div>"
        '<p style=margin:.5rem 0 0><a class=btn href=/site/market>Full market</a></p></div>'
    )


def _fixtures_target_card(payload: dict[str, Any]) -> str:
    fixtures = payload.get("fixtures") or []
    upcoming = [
        row
        for row in fixtures
        if not row.get("note") and not row.get("finished")
    ][:6]
    if not upcoming:
        return (
            '<div class=card><h2>Fixtures to target</h2>'
            '<p class=sub>Next gameweek fixtures are not published yet.</p></div>'
        )
    items = "".join(
        f'<li><b>{_esc(row["home"])} v {_esc(row["away"])}</b>'
        f'<span class=sub> - {_esc(row.get("kickoff_utc") or "")[:16].replace("T", " ")}</span></li>'
        for row in upcoming
    )
    return (
        '<div class=card><h2>Fixtures to target</h2>'
        f"<ul style='margin:.3rem 0 .5rem;padding-left:1.1rem'>{items}</ul>"
        "<p class=sub>Pair these with the Premier League attack/defence ratings "
        "to spot favourable matchups.</p>"
        '<a class=btn href=/site/premier>Model ratings</a></div>'
    )


def _changes_home_card(payload: dict[str, Any]) -> str:
    changes = payload.get("changes_since_previous_snapshot") or {}
    items = []
    if changes.get("available"):
        for row in (changes.get("price_moves") or [])[:3]:
            sign = "+" if row["price_change"] > 0 else ""
            items.append(("PRICE", f"{row['name']} {sign}{row['price_change']:.1f}m"))
        for row in (changes.get("availability_or_news_changes") or [])[:3]:
            news = (row.get("news") or "").strip() or "availability changed"
            items.append(("NEWS", f"{row['name']}: {news[:70]}"))
    if not items:
        items.append(("INFO", "No material movement recorded between ingests yet."))
    feed = "".join(
        f'<div class=feeditem><span class=feedtime>{kind}</span>'
        f"<span>{_esc(detail)}</span></div>"
        for kind, detail in items[:6]
    )
    return (
        '<div class=card><h2>What changed</h2>'
        f"{feed}"
        '<p style=margin:.5rem 0 0><a class=btn href=/site/changes>Full feed</a></p></div>'
    )


def _render_home(payload: dict[str, Any]) -> str:
    report = payload
    picks_rows = "".join(
        f"<tr><td>{row['rank']}</td><td><b>{_esc(row['player_name'])}</b></td>"
        f"<td>{_esc(row['team'])}</td><td class=num>&pound;{row['price']:.1f}</td>"
        f"<td class=num>{row['expected_points']:.2f}</td>"
        f"<td class=num>{row['expected_minutes']:.0f}</td>"
        f"<td class=num>{row['ownership_percent']:.1f}%</td></tr>"
        for row in (report.get("rankings") or [])[:10]
    )
    differentials = "".join(
        f"<span class=chip style='margin:.15rem'>{_esc(row['player_name'])} "
        f"{row['expected_points']:.1f} xP</span>"
        for row in (report.get("differentials") or [])[:10]
    )
    return (
        _hero(payload)
        + '<h2>The decision</h2><div class=grid>'
        + _next_move_card(payload)
        + _captain_home_card(payload)
        + "</div><h2>Market signals</h2><div class=grid>"
        + _price_watch_card(payload)
        + "</div><h2>Context</h2><div class=grid>"
        + _fixtures_target_card(payload)
        + _changes_home_card(payload)
        + "</div>"
        + f'<details><summary>Top picks this gameweek<span class=sub>engine ranking</span></summary>'
        + '<div class=inside><div class=scrollx><table><thead><tr><th>#</th><th>Player</th>'
        "<th>Team</th><th>Price</th><th>xP</th><th>xMins</th><th>Own%</th></tr></thead>"
        f"<tbody>{picks_rows}</tbody></table></div></div></details>"
        + ('<details><summary>Differentials<span class=sub>low ownership upside</span></summary>'
           f'<div class=inside><div class=rowflex>{differentials}</div></div></details>')
    )


# --------------------------------------------------------------------------
# MY TEAM
# --------------------------------------------------------------------------

def _formation_rows(
    payload: dict[str, Any], players: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    """Group the starting XI into pitch rows using each player's real position."""
    starters = sorted(
        (row for row in players if row.get("role") == "starter"),
        key=lambda row: row["position_slot"],
    )
    position_by_id = {
        int(row.get("player_id")): str(row.get("position") or "")
        for row in payload.get("all_players") or []
    }

    def position_of(row: dict[str, Any]) -> str:
        known = position_by_id.get(int(row.get("player_id")), "")
        if known in ("GK", "DEF", "MID", "FWD"):
            return known
        slot = row["position_slot"]
        if slot == 1:
            return "GK"
        if 2 <= slot <= 5:
            return "DEF"
        if 6 <= slot <= 10:
            return "MID"
        return "FWD"

    order = ("GK", "DEF", "MID", "FWD")
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in order}
    for row in starters:
        buckets.setdefault(position_of(row), []).append(row)
    return [buckets[key] for key in order if buckets[key]]


def _pitch_player_card(row: dict[str, Any]) -> str:
    badge = ""
    if row.get("is_captain"):
        badge = '<span class=cbadge>C</span>'
    elif row.get("is_vice_captain"):
        badge = '<span class=cbadge>V</span>'
    status_flag = "" if (row.get("availability_status") or "a") == "a" else \
        '<span class="chip bad" style=padding:0 .25rem>!</span>'
    xp = row.get("expected_points")
    mins = row.get("expected_minutes")
    metrics = (
        f"{xp:.1f} xP" if isinstance(xp, (int, float)) else "no xP"
    )
    minutes_text = f"{mins:.0f}m" if isinstance(mins, (int, float)) else ""
    return (
        f'<button class=pcard data-player-id="{row["player_id"]}">{badge}'
        f'<div class=nm>{_esc(row.get("name"))}</div><div class=mt>'
        f"{status_flag}<span>{metrics}</span>{minutes_text}</div></button>"
    )


def _render_myteam(payload: dict[str, Any]) -> str:
    team = payload.get("my_team") or {}
    if "error" in team:
        return _hero(payload) + (
            f'<div class=card style=margin-top:1rem><p class=sub>'
            f"{_esc(team.get('error'))}</p></div>"
        )
    players = team.get("players") or []
    formation = _formation_rows(payload, players)
    pitch_rows = "".join(
        "<div class=row>" + "".join(_pitch_player_card(row) for row in group) + "</div>"
        for group in formation
    )
    bench = [
        row for row in sorted(players, key=lambda r: r["position_slot"])
        if row.get("role") == "bench"
    ]
    bench_html = "".join(_pitch_player_card(row) for row in bench)
    weak_spots = team.get("weak_spots") or []
    weak_items = "".join(
        f'<li><b>{_esc(item["name"])}</b> - {_esc(item["reason"])}</li>'
        for item in weak_spots[:6]
    )
    state_cards = []
    for field in ("bank", "free_transfers", "selling_prices"):
        entry = (payload.get("manager_state") or {}).get(field) or {}
        kind = str(entry.get("classification") or "UNKNOWN")
        chip = _provenance_chip(
            kind if kind in ("VERIFIED", "RECONSTRUCTED", "APPROXIMATED", "USER-SUPPLIED")
            else "APPROXIMATED"
        )
        state_cards.append(
            '<div class=card><div class=spread><b style=text-transform:capitalize>'
            f"{_esc(field.replace('_', ' '))}</b>{chip}</div>"
            f'<div class="num" style=font-size:1.15rem;font-weight:800;margin-top:.3rem>'
            f"{_esc(entry.get('value'))}</div>"
            f'<p class=sub style=margin:.3rem 0 0>{_esc(entry.get("note"))}</p></div>'
        )
    drawer_json = json.dumps(
        _drawer_entries(payload), separators=(",", ":"), ensure_ascii=False
    ).replace("</", "<\\/")
    header = (
        f'<div class=spread style=margin-top:.4rem><h1>{_esc(team.get("team_name") or "My Team")}'
        f"</h1><span class=chip info>entry {_esc(team.get('entry_id'))}</span></div>"
        f'<p class=sub>Squad verified from official GW{team.get("picks_verified_event")} picks.'
        " Tap any player for the full picture.</p>"
    )
    return (
        _hero(payload) + header
        + f'<div class=pitch role=list aria-label="Starting XI">{pitch_rows}</div>'
        + '<h2>Bench</h2><div class=bench>' + bench_html + "</div>"
        + ("<h2>Weak spots</h2><ul class=sub>" + weak_items + "</ul>" if weak_items else "")
        + "<h2>Manager state provenance</h2><div class=grid g3>" + "".join(state_cards) + "</div>"
        + '<div class=drawer id=pdrawer role=dialog aria-modal=true aria-label="Player detail">'
        + '<div class=veil data-close></div><div class="panel grabber" id=pd-panel></div></div>'
        + "<script>window.FPL_DRAWER=" + drawer_json + ";</script>"
        + _drawer_script()
    )


_COMPONENT_LABELS = {
    "appearance": "secure minutes outlook",
    "goals": "goal threat",
    "assists": "chance creation",
    "clean_sheet": "clean-sheet outlook",
    "saves": "shot-stopping volume",
    "bonus": "bonus-points potential",
    "goals_conceded": "expected defensive concessions",
    "cards": "discipline risk",
    "defensive_contribution": "defensive-contribution scoring",
}


def _why_sentence(components: dict[str, float]) -> str:
    drivers = sorted(components.items(), key=lambda kv: kv[1], reverse=True)
    positive = [kv for kv in drivers if kv[1] >= 0.15]
    negative = [kv for kv in reversed(drivers) if kv[1] <= -0.1]
    parts = []
    if positive:
        top = _COMPONENT_LABELS.get(positive[0][0], positive[0][0])
        second = _COMPONENT_LABELS.get(positive[1][0], positive[1][0]) if len(positive) > 1 else None
        parts.append(
            f"Most of the projection comes from {top}"
            + (f" together with {second}" if second else "")
        )
    else:
        parts.append("The projection is modest across every component")
    if negative:
        worst = _COMPONENT_LABELS.get(negative[0][0], negative[0][0])
        parts.append(f"partly offset by {worst}")
    sentence = parts[0]
    if len(parts) > 1:
        sentence += ", " + parts[1]
    return sentence + ". Values are model estimates from the xp-v0.2.0 component breakdown."


def _drawer_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-player records powering the shared detail drawer."""
    market_by_id = {}
    market = payload.get("market") or {}
    if market.get("available"):
        market_by_id = {row["player_id"]: row for row in market.get("players") or []}
    entries = []
    for row in (payload.get("my_team") or {}).get("players") or []:
        market_row = market_by_id.get(row["player_id"]) or {}
        entries.append(
            {
                "id": row["player_id"],
                "name": row.get("name"),
                "team": row.get("team"),
                "slot": row.get("position_slot"),
                "is_c": bool(row.get("is_captain")),
                "is_v": bool(row.get("is_vice_captain")),
                "fixture": " / ".join(
                    f"{f.get('venue')} {f.get('opponent')}" for f in row.get("fixture", [])
                ),
                "price": row.get("price"),
                "ownership": row.get("ownership_percent"),
                "status": row.get("availability_status"),
                "news": row.get("availability_news"),
                "chance": row.get("chance_of_playing"),
                "xp": row.get("expected_points"),
                "mins": row.get("expected_minutes"),
                "lo": (row.get("range") or [None])[0],
                "hi": (row.get("range") or [None, None])[1],
                "risk": row.get("risk"),
                "components": row.get("why_top_components") or {},
                "model": row.get("model_version") or "xp-v0.2.0",
                "net_gw": market_row.get("net_transfers"),
                "v6": market_row.get("velocity_per_hour_6h"),
                "pdir": market_row.get("pressure_direction"),
                "plvl": market_row.get("pressure_level"),
                "d24": market_row.get("price_change_24h"),
            }
        )
    return entries


def _drawer_script() -> str:
    return """
(function(){
var data=window.FPL_DRAWER||[];
var drawer=document.getElementById('pdrawer');
if(!drawer)return;
var panel=document.getElementById('pd-panel');
function fmt(v,suffix,dp){if(v===null||v===undefined)return'&ndash;';
 return (typeof v==='number'?v.toFixed(dp||1):v)+suffix;}
function open(id){var p=data.find(function(r){return String(r.id)===String(id)});
 if(!p)return;
 var prov=p.is_c?'CAPTAIN':(p.is_v?'VICE-CAPTAIN':'');
 panel.innerHTML=
  '<button class=dclose data-close aria-label="Close">&times;</button>'
  +'<h1 style=margin-right:1.4rem>'+p.name+'</h1>'
  +(prov?'<span class="chip warn">'+prov+'</span> ':'')
  +'<span class=chip info>'+p.team+'</span>'
  +'<span class=chip>'+(p.fixture||'fixture n/a')+'</span>'
  +(p.news?'<span class="chip bad">'+p.status+'</span>':'')
  +'<div class=kv>'
  +stat('Price','&pound;'+fmt(p.price,'m'))
  +stat('24h price',(p.d24===null||p.d24===undefined)?'&ndash;':(p.d24>0?'+':'')+p.d24.toFixed(1)+'m')
  +stat('Ownership',fmt(p.ownership,'%'))
  +stat('Net transfers',fmt(p.net_gw,'',0))
  +stat('Velocity 6h',p.v6===null||p.v6===undefined?'&ndash;':fmt(p.v6,'/h',0))
  +stat('Pressure',(p.plvl?p.plvl:'')+(p.pdir&&p.pdir!=='FLAT'?' '+(p.pdir==='UP'?'\u2191':'\u2193'):''))
  +stat('xP',fmt(p.xp,'',2))
  +stat('xMins',fmt(p.mins,'',0))
  +stat('Range',(p.lo===null?'':('['+p.lo.toFixed(1)+', '+p.hi.toFixed(1))+']'))
  +stat('Risk',fmt(p.risk,'',2))
  +'</div>'
  +(p.chance!==null&&p.chance!==undefined?'<p class=sub>Chance of playing: '+p.chance+'%</p>':'')
  +(p.news?'<p class="sub" style=color:var(--warn)>'+p.news+'</p>':'')
  +'<div class=why><b>Why:</b> '+window.fplWhyText(p.components)+'</div>'
  +'<p class=sub style=margin-bottom:0>Model '+p.model
  +' &middot; xP/xMins/range are MODELLED &middot; price, ownership and transfer counts are OBSERVED.</p>';
 drawer.classList.add('open');
 var closeBtn=panel.querySelector('[data-close]');
 if(closeBtn)closeBtn.addEventListener('click',close);}
function close(){drawer.classList.remove('open');}
function stat(k,v){return '<div class=stat><div class="v num">'+v+'</div><div class=k>'+k+'</div></div>';}
window.fplWhyText=function(components){
 var c=components||{};var labels={appearance:'secure minutes outlook',goals:'goal threat',
 assists:'chance creation',clean_sheet:'clean-sheet outlook',bonus:'bonus potential',
 saves:'shot-stopping volume',goals_conceded:'expected defensive concessions',
 cards:'discipline risk',defensive_contribution:'defensive-contribution scoring'};
 var pos=Object.keys(c).filter(function(k){return c[k]>=0.15})
  .sort(function(a,b){return c[b]-c[a];}).slice(0,2)
  .map(function(k){return labels[k]||k;});
 var neg=Object.keys(c).filter(function(k){return c[k]<=-0.1})
  .sort(function(a,b){return c[a]-c[b];}).map(function(k){return labels[k]||k;})[0];
 var s=pos.length?('Most of the projection comes from '+pos.join(' together with '))
  :'The projection is modest across every component';
 if(neg)s+=', partly offset by '+neg;
 return s+'. Component values are model estimates.';};
document.querySelectorAll('.pcard[data-player-id]').forEach(function(el){
 el.addEventListener('click',function(){open(el.getAttribute('data-player-id'));});});
drawer.addEventListener('click',function(e){
 if(e.target.hasAttribute('data-close'))close();});
document.addEventListener('keydown',function(e){
 if(e.key==='Escape'){close();
  var sh=document.getElementById('moresheet');if(sh)sh.classList.remove('open');}});}
})();
"""


# --------------------------------------------------------------------------
# TRANSFERS
# --------------------------------------------------------------------------

def _render_transfers(payload: dict[str, Any]) -> str:
    next_gw = payload.get("next_gw") or {}
    rec = next_gw.get("recommendation") or {}
    if not rec:
        return _hero(payload) + (
            '<div class=card style=margin-top:1rem><p class=sub>'
            "Transfer optimisation is unavailable right now.</p></div>"
        )
    state_label = rec.get("state_label") or "APPROXIMATE"
    action = rec.get("action") or ""
    chosen_by_action = {
        "ROLL": "roll",
        "TRANSFER (one)": "single",
        "TRANSFER (two)": "double",
    }
    chosen = chosen_by_action.get(str(action), "roll")
    plans = {
        "roll": ("ROLL", next_gw.get("roll_plan") or {}, 0.0),
        "single": ("ONE", next_gw.get("best_single_transfer") or {},
                   rec.get("gain_single_over_roll")),
        "double": ("TWO", next_gw.get("best_two_transfer") or {},
                   rec.get("gain_double_over_roll")),
    }
    tabs = []
    panels = []
    for key, (label, plan, gain) in plans.items():
        active = key == chosen
        tabs.append(
            f'<button role=tab{" aria-selected=true" if active else " aria-selected=false"}'
            f' id=t-{key} data-plan={key}>{label}</button>'
        )
        ins = plan.get("transfers_in") or []
        outs = plan.get("transfers_out") or []
        moves = _move_cards(payload, list(ins), list(outs))
        panels.append(
            f'<div class="plan{" active" if active else ""}" id=plan-{key} role=tabpanel '
            f'aria-labelledby=t-{key}><div class=metrics>'
            + _stat("projected", f"{plan.get('projected_points', 0):.2f}")
            + _stat("gain vs roll", _fmt_signed(gain, 2))
            + _stat("transfers used", str(len(ins)))
            + _stat("hit cost", f"{plan.get('hit_cost', 0)} pts")
            + _stat("captain", _esc(plan.get("captain") or "-"))
            + "</div>" + moves
            + ('<p class=sub style=margin:.5rem 0 0>Bench order: '
               + _esc(", ".join(plan.get("bench_order") or [])) + "</p>")
            + "</div>"
        )
    state_cards = []
    for field in ("bank", "free_transfers", "selling_prices"):
        entry = (payload.get("manager_state") or {}).get(field) or {}
        kind = str(entry.get("classification") or "").split(" ")[0]
        state_cards.append(
            f'<div class=mcard><div style=min-width:0><div class=nm>'
            f'{_esc(field.replace("_", " "))}</div>'
            f'<div class=sub>{_esc(str(entry.get("note"))[:110])}</div></div>'
            f"<div style=text-align:right>{_provenance_chip(kind)}"
            f'<div class="num" style="font-weight:800;margin-top:.3rem">'
            f"{_esc(entry.get('value'))}</div></div></div>"
        )
    concerns = "".join(
        f'<li><b>{_esc(row["name"])}</b> - {_esc(row.get("status"))} '
        f'{_esc(str(row.get("news") or "")[:70])}</li>'
        for row in (next_gw.get("injury_rotation_concerns") or [])[:5]
    )
    return (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>Roll or transfer?</h1>'
        + f'<p class=sub>{rec.get("reason")}</p>'
        + ('<p><span class="chip ok">' if state_label == "VERIFIED_INPUTS" else
           '<p><span class="chip warn">')
        + f"{_esc(state_label)}</span>"
        + f'<span class="chip up">{_esc(action)} recommended</span></p>'
        + '<div class=card><div class=seg role=tablist>' + "".join(tabs) + "</div>"
        + "".join(panels) + "</div>"
        + "<h2>Manager state behind these numbers</h2>"
        + '<div class=mgrid>' + "".join(state_cards) + "</div>"
        + (("<h2>Availability concerns</h2><ul class=sub>" + concerns + "</ul>")
           if concerns else "")
        + _PLAN_SWITCH_SCRIPT
    )


_PLAN_SWITCH_SCRIPT = """
(function(){
document.querySelectorAll('.seg [data-plan]').forEach(function(b){
 b.addEventListener('click',function(){
  var key=b.dataset.plan;
  document.querySelectorAll('.seg [data-plan]').forEach(function(x){
   x.setAttribute('aria-selected',String(x===b));});
  document.querySelectorAll('.plan').forEach(function(p){
   p.classList.toggle('active',p.id==='plan-'+key);});});});
})();
"""


# --------------------------------------------------------------------------
# CAPTAIN
# --------------------------------------------------------------------------

def _render_captain(payload: dict[str, Any]) -> str:
    candidates = payload.get("captains") or []
    if not candidates:
        return _hero(payload) + (
            '<div class=card style=margin-top:1rem><p class=sub>'
            "No captain candidates clear the minutes and risk thresholds yet.</p></div>"
        )
    cards = []
    ids = []
    for rank, row in enumerate(candidates[:5], 1):
        ids.append(rank)
        cards.append(
            '<div class=card id=cand-' + str(rank) + ' data-xp="' + str(row["expected_points"])
            + '" data-mins="' + str(row["expected_minutes"])
            + '" data-risk="' + str(row["risk"])
            + '" data-own="' + str(row["ownership_percent"])
            + '" data-ceiling="' + str(row.get("ceiling_upper_bound") or row.get("expected_points"))
            + '"><div class=spread><b>#' + str(rank) + " " + _esc(row["name"]) + "</b>"
            + '<span class="chip info">' + _esc(row.get("position") or "") + "</span></div>"
            + '<div class=sub>' + _esc(row.get("team")) + "</div>"
            + "<div class=metrics>"
            + _stat("xP", f"{row['expected_points']:.2f}")
            + _stat("xMins", f"{row['expected_minutes']:.0f}")
            + _stat("ceiling", f"{row.get('ceiling_upper_bound') or row['expected_points']:.1f}")
            + _stat("risk", f"{row['risk']:.2f}")
            + _stat("owned", f"{row['ownership_percent']:.1f}%")
            + "</div></div>"
        )
    selects = []
    defaults = {"A": 1, "B": 2}
    for side in ("A", "B"):
        default_rank = min(defaults[side], len(ids))
        options = "".join(
            f'<option value="{rank}"{" selected" if rank == default_rank else ""}>'
            f"#{rank} {_esc(candidates[rank - 1]['name'])}</option>"
            for rank in ids
        )
        selects.append(
            f'<label class=sub>Captain {side}: <select id=cmp-{side}>{options}</select></label>'
        )
    return (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>Captain decision</h1>'
        + '<p class=sub>Ranked by expected points after availability and risk filters. '
        "Ceilings are modelled upper bounds, not promises.</p>"
        + '<div class="grid g3" style=margin-top:.6rem>' + "".join(cards) + "</div>"
        + "<h2>Head-to-head</h2><div class=card>"
        + '<div class=rowflex>' + "".join(selects)
        + '<button class="btn primary" id=cmpgo>Compare</button></div>'
        + '<div id=cmpout style=margin-top:.7rem></div></div>'
        + """
<script>
(function(){
function get(n){return document.getElementById('cand-'+n);}
document.getElementById('cmpgo').addEventListener('click',function(){
 var a=get(document.getElementById('cmp-A').value);
 var b=get(document.getElementById('cmp-B').value);
 if(!a||!b)return;
 var fields=[['data-xp','xP'],['data-mins','xMins'],['data-ceiling','Ceiling'],
  ['data-risk','Risk'],['data-own','Owned %']];
 var rows=fields.map(function(f){return '<tr><td class=sub>'+f[1]+'</td><td class=num>'+
  (+a.getAttribute(f[0])).toFixed(2)+'</td><td class=num>'+
  (+b.getAttribute(f[0])).toFixed(2)+'</td></tr>';}).join('');
 var winner=(+a.getAttribute('data-xp'))>=(+b.getAttribute('data-xp'))?
  a.querySelector('b').textContent:b.querySelector('b').textContent;
 document.getElementById('cmpout').innerHTML='<div class=scrollx><table><thead><tr><th></th>'+
  '<th>'+a.querySelector('b').textContent+'</th><th>'+b.querySelector('b').textContent+
  '</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
  '<p class=sub>Engine leans toward <b>'+winner+'</b> on expected points.</p>';});
})();
</script>"""
    )


# --------------------------------------------------------------------------
# PLAYERS EXPLORER
# --------------------------------------------------------------------------

def _compact_players(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact full-squad records for client-side exploration."""
    market_by_id: dict[int, dict[str, Any]] = {}
    market = payload.get("market") or {}
    if market.get("available"):
        market_by_id = {row["player_id"]: row for row in market.get("players") or []}
    rows = []
    for row in payload.get("all_players") or []:
        market_row = market_by_id.get(row["player_id"]) or {}
        fixture_labels = "/".join(
            f"{f.get('venue')} {f.get('opponent')}" for f in row.get("fixtures") or []
        )
        rows.append(
            {
                "id": row["player_id"],
                "n": row["player_name"],
                "t": row["team"],
                "p": row["position"],
                "pr": row["price"],
                "x": round(float(row["expected_points"]), 2),
                "m": round(float(row["expected_minutes"])),
                "lo": row["lower_bound"],
                "hi": row["upper_bound"],
                "o": row["ownership_percent"],
                "nt": market_row.get("net_transfers"),
                "v6": market_row.get("velocity_per_hour_6h"),
                "plvl": market_row.get("pressure_level"),
                "pdir": market_row.get("pressure_direction"),
                "d24": market_row.get("price_change_24h"),
                "r": row["risk"],
                "fx": fixture_labels,
                "st": row.get("status") or "a",
                "nw": (row.get("news") or "")[:60],
                "diff": row.get("differential_score"),
                "val": row.get("value_score"),
            }
        )
    return rows


def _render_players(payload: dict[str, Any]) -> str:
    players = json.dumps(
        _compact_players(payload), separators=(",", ":"), ensure_ascii=False
    ).replace("</", "<\\/")
    return (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>Player explorer</h1>'
        + '<p class=sub>xP/xMins/risk are MODELLED &middot; price, ownership and net '
        "transfers are OBSERVED.</p>"
        + '<div class=toolbar role=search>'
        + '<input type=search id=q placeholder="Search player..." aria-label="Search player">'
        + '<select id=fpos aria-label="Position"><option value="">Pos</option><option>GK</option>'
        "<option>DEF</option><option>MID</option><option>FWD</option></select>"
        + '<select id=fclub aria-label="Club"><option value="">Club</option></select>'
        + '<input id=fmin type=number step=0.1 min=0 placeholder="Min xMins" style=max-width:96px '
        'aria-label="Minimum expected minutes">'
        + '<input id=frisk type=number step=0.05 min=0 max=1 placeholder="Max risk" '
        'style=max-width:88px aria-label="Maximum risk">'
        + '<label class=chip style=cursor:pointer><input id=fdiff type=checkbox '
        'style=margin-right:4px>Differential</label>'
        + '<select id=sortby aria-label="Sort by"><option value=x>xP</option>'
        "<option value=m>xMins</option><option value=pr>Price</option>"
        "<option value=o>Ownership</option><option value=nt>Net transfers</option>"
        "<option value=v6>Velocity</option><option value=r>Risk</option></select></div>"
        + '<div id=pcount class=sub style=margin-bottom:.5rem></div>'
        + '<div class=mgrid id=plist aria-live=polite></div>'
        + '<div class=comparebar id=cbar role=status><span class=sub id=clist></span>'
        + '<button class="btn primary" id=cgo>Compare</button>'
        + '<button class=btn id=cclear>Clear</button></div>'
        + '<div class=drawer id=pdrawer role=dialog aria-modal=true aria-label="Player detail">'
        + '<div class=veil data-close></div><div class="panel grabber" id=pd-panel></div></div>'
        + "<script>window.FPL_PLAYERS=" + players + ";</script>"
        + _EXPLORER_SCRIPT
    )


_EXPLORER_SCRIPT = r"""
(function(){
var P=window.FPL_PLAYERS||[];
var clubs={};P.forEach(function(r){clubs[r.t]=1;});
var clubSel=document.getElementById('fclub');
Object.keys(clubs).sort().forEach(function(c){
 var o=document.createElement('option');o.textContent=c;clubSel.appendChild(o);});
var list=document.getElementById('plist'),count=document.getElementById('pcount');
var chosen=[];
function fmt(v,d,suf){if(v===null||v===undefined)return'\u2013';
 return (typeof v==='number'?v.toFixed(d):v)+(suf||'');}
function sgn(v,d){if(v===null||v===undefined)return'\u2013';
 var c=v>0?'upC':(v<0?'downC':'');
 return '<span class="'+c+'">'+(v>0?'+':'')+Number(v).toFixed(d||0)+'</span>';}
function card(r){return '<button class=mcard data-id="'+r.id+
 '" style="cursor:pointer;text-align:left">'+
 '<div><div class=nm>'+r.n+'</div><div class=sub>'+r.t+' '+r.p+
 (r.st&&r.st!=='a'?' \u26a0':'')+'</div>'+
 '<div class=sub>'+fmt(r.pr,1)+'m \u00b7 '+fmt(r.o,1)+'% own'+
 (r.fx?' \u00b7 '+r.fx:'')+(r.plvl&&r.plvl!=='LOW'?' \u00b7 pressure '+
 (r.pdir==='UP'?'\u2191':(r.pdir==='DOWN'?'\u2193':''))+r.plvl:'')+'</div></div>'+
 '<div style=text-align:right><div class=num style=font-weight:800>'+fmt(r.x,2)+' xP</div>'+
 '<div class="sub num">'+fmt(r.m,0)+' mins</div>'+
 '<div class="sub num">'+sgn(r.nt)+' net GW</div></div></button>';}
function render(){
 var q=(document.getElementById('q').value||'').toLowerCase();
 var pos=document.getElementById('fpos').value;
 var club=document.getElementById('fclub').value;
 var minm=parseFloat(document.getElementById('fmin').value)||0;
 var maxrRaw=document.getElementById('frisk').value;
 var maxr=maxrRaw===''?NaN:parseFloat(maxrRaw);
 var diff=document.getElementById('fdiff').checked;
 var sort=document.getElementById('sortby').value;
 var rows=P.filter(function(r){
  if(q&&r.n.toLowerCase().indexOf(q)<0)return false;
  if(pos&&r.p!==pos)return false;
  if(club&&r.t!==club)return false;
  if(minm&&r.m<minm)return false;
  if(!isNaN(maxr)&&r.r>maxr)return false;
  if(diff&&r.o>=15)return false;
  return true;});
 rows.sort(function(a,b){return (b[sort]||0)-(a[sort]||0);});
 count.textContent=rows.length+' of '+P.length+' players';
 list.innerHTML=rows.slice(0,80).map(card).join('')||
  '<p class=sub>No players match these filters.</p>';
 renderCompare();}
document.querySelectorAll('.toolbar input,.toolbar select').forEach(function(el){
 el.addEventListener('change',render);el.addEventListener('input',render);});
var bar=document.getElementById('cbar');
list.addEventListener('click',function(e){
 var b=e.target.closest('[data-id]');
 if(b)toggleCompare(b.getAttribute('data-id'));});
function toggleCompare(id){id=String(id);
 var i=chosen.indexOf(id);
 if(i>=0)chosen.splice(i,1);else if(chosen.length<3)chosen.push(id);
 renderCompare();}
function renderCompare(){
 bar.classList.toggle('show',chosen.length>0);
 document.getElementById('clist').textContent=chosen.map(function(id){
  var r=P.find(function(x){return String(x.id)===String(id);});
  return r?r.n:id;}).join(' vs ');
 list.querySelectorAll('[data-id]').forEach(function(el){
  el.style.borderColor=chosen.indexOf(el.getAttribute('data-id'))>=0?'var(--accent)':'';});}
document.getElementById('cclear').addEventListener('click',function(){chosen=[];renderCompare();});
document.getElementById('cgo').addEventListener('click',compareModal);
function compareModal(){
 var picked=chosen.map(function(id){
  return P.find(function(x){return String(x.id)===String(id);});}).filter(Boolean);
 if(picked.length<2)return;
 var fields=[['x','xP',2],['m','xMins',0],['pr','Price',1],['o','Own %',1],
  ['nt','Net GW',0],['v6','Vel/h 6h',0],['d24','Price 24h',1],['r','Risk',2]];
 var head=picked.map(function(r){return '<th>'+r.n+'</th>';}).join('');
 var body=fields.map(function(f){
  return '<tr><td class=sub>'+f[1]+'</td>'+picked.map(function(r){
   return '<td class=num>'+((r[f[0]]===null||r[f[0]]===undefined)?'\u2013':
    r[f[0]].toFixed(f[2]))+'</td>';}).join('')+'</tr>';}).join('');
 drawerShow('<h1>Head to head</h1><div class=scrollx><table><thead><tr><th></th>'+head+
  '</tr></thead><tbody>'+body+'</tbody></table></div>');}
render();renderCompare();
var drawer=document.getElementById('pdrawer'),panel=document.getElementById('pd-panel');
function drawerShow(html){panel.innerHTML=
 '<button class=dclose data-close aria-label=Close>&times;</button>'+html;
 drawer.classList.add('open');}
drawer.addEventListener('click',function(e){
 if(e.target.hasAttribute('data-close'))drawer.classList.remove('open');});
document.addEventListener('keydown',function(e){
 if(e.key==='Escape'){drawer.classList.remove('open');}});}
})();
"""


# --------------------------------------------------------------------------
# MARKET PAGE
# --------------------------------------------------------------------------

_MARKET_SORTS = (
    ("net", "Net transfers"),
    ("velocity", "Velocity 6h"),
    ("pressure", "Pressure"),
    ("price", "Price"),
    ("ownership", "Ownership"),
)


def _market_rows_for_page(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """All market rows; sections and the client list apply their own limits.

    Truncating here would hide owned players from squad filters before the
    client-side list ever sees them.
    """
    market = payload.get("market") or {}
    if not market.get("available"):
        return []
    return sorted(
        market.get("players") or [],
        key=lambda item: abs(item.get("net_transfers") or 0),
        reverse=True,
    )


def _render_market(payload: dict[str, Any]) -> str:
    market = payload.get("market") or {}
    header = (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>Market intelligence</h1>'
        + f'<p class=sub>{MARKET_PRESSURE_NOTE}</p>'
    )
    if not market.get("available"):
        reason = market.get("reason") or "history still filling"
        return header + (
            '<div class=card style=margin-top:1rem><p class=sub>Market view unavailable: '
            f'{_esc(reason)}. The scheduled poll builds history over time; derived signals '
            "appear once at least two snapshots exist.</p></div>"
        )
    rows = _market_rows_for_page(payload)
    owned_ids = {
        row["player_id"] for row in ((payload.get("my_team") or {}).get("players") or [])
    }

    def section(title: str, subset: list[dict[str, Any]], note: str = "") -> str:
        if not subset:
            return ""
        cards = "".join(_market_card_html(r) for r in subset[:6])
        note_html = f' <span class=sub>{note}</span>' if note else ""
        return (
            f"<details><summary>{title}{note_html}"
            f"<span>top {min(6, len(subset))}</span></summary>"
            f'<div class=inside><div class=mgrid>{cards}</div></div></details>'
        )

    risers = sorted(
        (r for r in rows if (r.get("price_change_24h") or 0) > 0),
        key=lambda r: r.get("price_change_24h") or 0, reverse=True,
    )
    fallers = sorted(
        (r for r in rows if (r.get("price_change_24h") or 0) < 0),
        key=lambda r: r.get("price_change_24h") or 0,
    )
    hot = sorted(
        (r for r in rows if r.get("pressure_direction") == "UP"),
        key=lambda r: abs(r.get("net_transfers_6h") or 0), reverse=True,
    )[:12]
    selling = sorted(
        (r for r in rows if r.get("pressure_direction") == "DOWN"),
        key=lambda r: abs(r.get("net_transfers_6h") or 0), reverse=True,
    )[:12]
    watch = [r for r in rows if r["player_id"] in owned_ids]
    sort_options = "".join(
        f'<option value="{key}">{label}</option>' for key, label in _MARKET_SORTS
    )
    embed = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    script = r"""
(function(){
var R=window.FPL_MARKET||[];
var sort=document.getElementById('msort'),owned=document.getElementById('ownedonly');
var ownedIds=window.FPL_OWNED||[];
function keyOf(r){switch(sort.value){case 'velocity':
 return Math.abs(r.velocity_per_hour_6h||0);case 'pressure':
 return ({'VERY HIGH':4,'HIGH':3,'MEDIUM':2,'LOW':1})[r.pressure_level]||0;case 'price':
 return r.price||0;case 'ownership':return r.ownership_percent||0;default:
 return Math.abs(r.net_transfers||0);}}
function card(r){var dir=r.pressure_direction;
 var arrow=dir==='UP'?'\u2191':(dir==='DOWN'?'\u2193':'\u2192');
 var d24=r.price_change_24h;
 var d24txt=(typeof d24==='number'&&d24!==0)?((d24>0?'+':'')+d24.toFixed(1)):'\u2013';
 var v6=r.velocity_per_hour_6h;
 var v6txt=(typeof v6==='number')?((v6>0?'+':'')+Math.round(v6).toLocaleString()):'\u2013';
 var nt=(typeof r.net_transfers==='number')?
  ((r.net_transfers>0?'+':'')+r.net_transfers.toLocaleString()):'\u2013';
 return '<div class=mcard><div><div class=nm>'+r.name+'</div><div class=sub>'+r.team+' '
 +r.position+'</div></div><div style=text-align:right>'+
 '<div class="num" style=font-weight:800>\u00a3'+Number(r.price).toFixed(1)+'m '+d24txt+'</div>'+
 '<div class="sub num">'+nt+' net GW</div>'+
 '<div class="sub num">6h '+v6txt+'</div>'+
 '<span class="chip '+(dir==='UP'?'up':(dir==='DOWN'?'down':''))+'" title="'+
 window.FPL_NOTE+'">PRESSURE '+arrow+' '+r.pressure_level+'</span></div></div>';}
function render(){
 var rows=R.filter(function(r){
  return !owned.checked||ownedIds.indexOf(String(r.player_id))>=0;});
 rows.sort(function(a,b){return keyOf(b)-keyOf(a);});
 document.getElementById('mlist').innerHTML=rows.slice(0,60).map(card).join('')||
  '<p class=sub>Nothing matches.</p>';}
sort.addEventListener('change',render);owned.addEventListener('change',render);render();
})();
"""
    return (
        header
        + f'<p class=sub>Latest poll {market.get("captured_at")} &middot; '
        f"{market.get('poll_count')} snapshots retained &middot; windows "
        f"{', '.join(str(w) for w in market.get('windows_hours') or [])}h</p>"
        + section("Trending now", hot, "fastest recent buying")
        + section("Price risers", risers, "observed moves up")
        + section("Price fallers", fallers, "observed moves down")
        + section("Heavy selling", selling, "downward pressure")
        + section("My team watch", watch, "your squad")
        + '<div class=toolbar><select id=msort aria-label="Sort market list">'
        + sort_options
        + "</select><label class=chip style=cursor:pointer>"
        + '<input id=ownedonly type=checkbox style=margin-right:4px>My squad only</label></div>'
        + '<div class=mgrid id=mlist></div>'
        + "<script>window.FPL_MARKET=" + embed + ";"
        + "window.FPL_OWNED=" + json.dumps([str(i) for i in sorted(owned_ids)]) + ";"
        + "window.FPL_NOTE=" + json.dumps(MARKET_PRESSURE_NOTE) + ";</script>"
        + f"<script>{script}</script>"
    )


def _market_card_html(row: dict[str, Any]) -> str:
    delta = row.get("price_change_24h")
    six = row.get("net_transfers_6h")
    return (
        '<div class=mcard>'
        f'<div><div class=nm>{_esc(row.get("name"))}</div>'
        f'<div class=sub>{_esc(row.get("team"))} {_esc(row.get("position"))}</div></div>'
        '<div style=text-align:right>'
        f'<div class="num" style=font-weight:800>&pound;{row.get("price", 0):.1f}m '
        f"{_fmt_signed(delta, 1)}</div>"
        f'<div class="sub num">{_fmt_signed(row.get("net_transfers"), 0)} net GW</div>'
        f'<div class="sub num">6h {_fmt_signed(six, 0)}</div>'
        f"<div>{_pressure_badge(row)}</div></div></div>"
    )


# --------------------------------------------------------------------------
# CHANGES / FIXTURES / PREMIER / MODEL
# --------------------------------------------------------------------------

def _typed_changes(payload: dict[str, Any]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    changes = payload.get("changes_since_previous_snapshot") or {}
    if changes.get("available"):
        stamp = str(changes.get("latest_captured_at") or "")[:16].replace("T", " ")
        for row in changes.get("price_moves") or []:
            sign = "+" if row["price_change"] > 0 else ""
            events.append(
                {"type": "PRICE", "time": stamp,
                 "detail": f"{row['name']} moved {sign}{row['price_change']:.1f}m"}
            )
        for row in changes.get("ownership_risers") or []:
            events.append(
                {"type": "OWNERSHIP", "time": stamp,
                 "detail": f"{row['name']} +{row['ownership_change_pp']:.1f}pp owned"}
            )
        for row in changes.get("availability_or_news_changes") or []:
            news = (row.get("news") or "").strip() or "availability changed"
            events.append({"type": "NEWS", "time": stamp,
                           "detail": f"{row['name']}: {news[:90]}"})
    from .market import market_events

    market = payload.get("market") or {}
    if market.get("available"):
        names = {
            row["player_id"]: row.get("name") or f"#{row['player_id']}"
            for row in market.get("players") or []
        }
        for event in market_events(market, names, limit=40):
            # market_events() emits timestamp-keyed records; normalize to the
            # time/detail shape this feed renders.
            events.append(
                {
                    "type": str(event.get("type") or "MARKET"),
                    "time": str(event.get("timestamp") or "")[:16].replace("T", " "),
                    "detail": str(event.get("detail") or ""),
                }
            )
    return events


_EVENT_CLASS = {"PRICE": "warn", "NEWS": "bad", "OWNERSHIP": "info", "TRANSFER SURGE": "up"}


def _render_changes(payload: dict[str, Any]) -> str:
    events = _typed_changes(payload)
    chips = "".join(
        f'<button class=btn data-ev="{kind}" style=padding:.32rem .6rem;font-size:.72rem>'
        f"{kind}</button>"
        for kind in ("ALL", "PRICE", "NEWS", "OWNERSHIP", "TRANSFER SURGE")
    )
    items = "".join(
        '<div class=feeditem data-type="'
        + _esc(event["type"])
        + '"><span class=feedtime>'
        + _esc(event["time"][-5:])
        + '</span><span><span class="chip '
        + _EVENT_CLASS.get(event["type"], "")
        + '">'
        + _esc(event["type"])
        + "</span> "
        + _esc(event["detail"])
        + "</span></div>"
        for event in events[:40]
    )
    body = items or '<p class=sub>Nothing recorded yet - feed fills as ingests land.</p>'
    filter_script = """
(function(){
document.querySelectorAll('[data-ev]').forEach(function(b){
 b.addEventListener('click',function(){
  var k=b.getAttribute('data-ev');
  document.querySelectorAll('.feeditem').forEach(function(item){
   item.style.display=(k==='ALL'||item.getAttribute('data-type')===k)?'':'none';});});});
})();
"""
    return (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>What changed</h1>'
        + '<p class=sub>Chronological intelligence feed across ingests and polls.</p>'
        + f'<div class=toolbar role=group aria-label="Filter feed">{chips}</div>'
        + f'<div class=card>{body}</div>'
        + f"<script>{filter_script}</script>"
    )


def _render_fixtures(payload: dict[str, Any]) -> str:
    rows = []
    for fixture in payload.get("fixtures") or []:
        if fixture.get("note"):
            rows.append(
                "<tr><td colspan=4>Blank gameweek: "
                + _esc(", ".join(fixture.get("teams") or []))
                + "</td></tr>"
            )
            continue
        score = (
            f"{fixture['home_score']}-{fixture['away_score']}"
            if fixture.get("finished")
            else ""
        )
        state = (
            "FT" if fixture.get("finished")
            else ("live" if fixture.get("started") else "upcoming")
        )
        kickoff = str(fixture.get("kickoff_utc") or "")[:16].replace("T", " ")
        rows.append(
            f"<tr><td><b>{_esc(fixture['home'])}</b> v <b>{_esc(fixture['away'])}</b></td>"
            f"<td class=sub>{_esc(kickoff)}</td><td class=num>{score}</td>"
            f"<td>{_esc(state)}</td></tr>"
        )
    return (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>Fixtures</h1>'
        + '<div class="card scrollx" style=margin-top:.7rem><table><thead><tr><th>Match</th>'
        f"<th>Kickoff</th><th>Score</th><th>State</th></tr></thead><tbody>{''.join(rows)}"
        "</tbody></table></div>"
    )


def _render_premier(payload: dict[str, Any]) -> str:
    report = payload.get("team_strength") or {}
    if not report:
        return (
            _hero(payload)
            + '<div class=card style=margin-top:1rem><p class=sub>'
            "No fitted Premier League backtest found on this server yet.</p></div>"
        )
    summary = report.get("summary", {})
    attack_rows = "".join(
        f"<tr><td>{_esc(team)}</td><td class=num>{value:+.3f}</td></tr>"
        for team, value in (report.get("final_fit_top_attack") or [])[:10]
    )
    examples = "".join(
        f"<li>{_esc(p['home'])} v {_esc(p['away'])}: xG {p['expected_home_goals']} - "
        f"{p['expected_away_goals']} &middot; P(H/D/A) "
        f"{p['probabilities']['home_win']:.0%}/{p['probabilities']['draw']:.0%}/"
        f"{p['probabilities']['away_win']:.0%}</li>"
        for p in (report.get("example_predictions") or [])[:6]
    )
    return (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>Premier League strength model</h1>'
        + f'<p class=sub>walk-forward holdout log loss {summary.get("model_log_loss")} vs '
        f'uniform {summary.get("uniform_log_loss")} &middot; evaluated '
        f"{summary.get('evaluated')} matches &middot; MODELLED ratings</p>"
        + '<div class="card scrollx" style=margin-top:.7rem><table><thead>'
        "<tr><th>Strongest attacks</th><th>Rating</th></tr></thead><tbody>"
        f"{attack_rows}</tbody></table></div>"
        + ('<div class=card style=margin-top:.75rem><h2 style="margin-top:0;margin-bottom:.4rem">'
           "Example forecasts</h2><ul class=sub>" + examples + "</ul></div>"
           if examples else "")
    )


def _render_model(payload: dict[str, Any]) -> str:
    meta = payload.get("metadata") or {}
    notes = "".join(
        f"<li>{_esc(note)}</li>" for note in (payload.get("uncertainty_notes") or [])
    )
    legend = [
        ("OBSERVED", "Official FPL data captured by scheduled ingestion: prices, ownership, transfer counters, status/news, results."),
        ("CALCULATED", "Deterministic arithmetic on observations: net-transfer velocity, ownership deltas, acceleration."),
        ("MODELLED", "Engine estimates: expected points/minutes, ranges, risk, price-pressure heuristic, team ratings. Never presented as observed facts."),
        ("APPROXIMATED", "Manager state public data cannot establish exactly (bank timing, selling prices) - always labelled where used."),
    ]
    legend_rows = "".join(
        f'<div class=mcard><div><div class=nm>{kind}</div><div class=sub>{text}</div></div>'
        f"<div>{_provenance_chip(kind)}</div></div>"
        for kind, text in legend
    )
    pipeline = [
        "Six-hourly ingestion stores observations plus a versioned prediction run in Neon.",
        "Half-hourly market poll stores compact official market snapshots (7-day window).",
        "Page views read persisted runs only; no page load reruns the model.",
        "Personal sections read small official entry endpoints, cached per TTL.",
        "Entry 7181076 is the standing end-to-end verification account.",
    ]
    steps = "".join(f"<li>{step}</li>" for step in pipeline)
    return (
        _hero(payload)
        + '<h1 style=margin-top:.6rem>Model &amp; methodology</h1>'
        + f'<p class=sub>Active model <b>{meta.get("model_version")}</b> over '
        f"{meta.get('player_count')} players. xp-v0.2.0 is unchanged here: transparent "
        "prior-informed component xP with variance-based ranges.</p>"
        + '<h2>Provenance legend</h2><div class=mgrid>' + legend_rows + "</div>"
        + '<h2>Data pipeline</h2><div class=card><ul class=sub>' + steps + "</ul></div>"
        + '<h2>Known limitations</h2><div class=card><ul class=sub>' + notes + "</ul></div>"
        + ('<div class=card style=margin-top:.75rem><h2 style="margin-top:0">Price pressure'
           "</h2><p class=sub>" + MARKET_PRESSURE_NOTE + " Once several weeks of intraday "
           "snapshots accumulate, each real price change becomes a labelled event so future "
           "work can evaluate precision, recall, Brier score and calibration before any "
           "probability claim is ever shown.</p></div>")
    )

