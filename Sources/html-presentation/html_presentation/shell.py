"""The frame of every presentation – written by the plugin, not by the AI, so it always works the same:

- always ONE slide on the screen, always 16:9 (a 1920×1080 stage), scaled to the largest size the window allows
- slide cursor at the top or bottom: a bar, the number (3 / 12) and a dot per slide (click to jump)
- ‹ › buttons, swipe on touch screens, #3 in the address keeps the slide; the arrow keys (and Page ↑/↓, Space, Home,
  End) if switched on
- light, dark – or both with a ☀/☾ switch (starting with the system's setting, remembered)
- several languages with a switch (remembered; ?lang=en in the address picks one)
- a slide whose content is too tall is shrunk until it fits (nothing is cut off)

The AI delivers the deck: per slide the HTML per language, the colours of the light and dark theme and the CSS of
its slide layouts (everything below ``.slide``).
"""

from __future__ import annotations

import html
import json
import re

DEFAULT_THEME = {
    "light": {"bg": "#ffffff", "fg": "#1b2430", "muted": "#5b6675", "accent": "#2563eb", "surface": "#f1f4f8",
              "border": "#d9dee5"},
    "dark": {"bg": "#0f141b", "fg": "#e8edf3", "muted": "#9aa6b5", "accent": "#60a5fa", "surface": "#18202b",
             "border": "#2a3442"},
}
VARS = ("bg", "fg", "muted", "accent", "surface", "border")
LANG_NAMES = {"de": "Deutsch", "en": "English", "fr": "Français", "es": "Español", "it": "Italiano",
              "nl": "Nederlands", "pl": "Polski", "pt": "Português", "tr": "Türkçe", "sv": "Svenska", "da": "Dansk",
              "cs": "Čeština", "ru": "Русский", "uk": "Українська", "ja": "日本語", "zh": "中文", "ar": "العربية"}
COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%deg]+\))$")


def _vars(theme: dict) -> str:
    return "".join(f"--{k}:{v};" for k, v in theme.items() if k in VARS and COLOR.match(str(v).strip()))


def _safe_css(css: str) -> str:
    """The AI's CSS – without what could break out of the <style> or load scripts."""
    css = re.sub(r"(?i)</\s*style", "", css or "")
    css = re.sub(r"(?i)expression\s*\(|javascript:", "", css)
    return css


def build(deck: dict, *, languages: list[str], theme: str, cursor: str, arrows: bool) -> str:
    """The finished presentation (one HTML file)."""
    langs = languages or ["en"]
    titles = deck.get("title") or {}
    title = titles.get(langs[0]) if isinstance(titles, dict) else str(titles)
    themes = {m: {**DEFAULT_THEME[m], **((deck.get("theme") or {}).get(m) or {})} for m in ("light", "dark")}
    modes = ["light", "dark"] if theme == "both" else [theme if theme in ("light", "dark") else "light"]
    slides = []
    total = len(deck.get("slides") or [])
    for i, s in enumerate(deck.get("slides") or [], 1):
        cls = " ".join(["slide"] + [c for c in re.split(r"\s+", str(s.get("layout") or "")) if
                                    re.fullmatch(r"[A-Za-z][\w-]{0,30}", c)])
        for lang in langs:   # one section per language: the deck's CSS applies to the slide itself, no wrapper
            body = (s.get("html") or {}).get(lang, "")
            slides.append(f'<section class="{cls}" data-n="{i}" lang="{html.escape(lang)}" '
                          f'aria-roledescription="slide" aria-label="{i} / {total}">{body}</section>')
    config = {"languages": langs, "names": {lng: LANG_NAMES.get(lng, lng.upper()) for lng in langs},
              "titles": titles if isinstance(titles, dict) else {}, "modes": modes, "arrows": bool(arrows)}
    font = deck.get("font_url") or ""
    font_link = (f'<link rel="stylesheet" href="{html.escape(font, quote=True)}">'
                 if re.match(r"^https://fonts\.(googleapis|bunny)\.net/", font) else "")
    return TEMPLATE.format(
        lang=html.escape(langs[0]), title=html.escape(title or "Presentation"), font_link=font_link,
        light=_vars(themes["light"]), dark=_vars(themes["dark"]), deck_css=_safe_css(deck.get("css") or ""),
        font_family=html.escape(str(deck.get("font_family") or "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"),
                                quote=False).replace(";", ""),
        cursor_class="cursor-top" if cursor == "top" else "cursor-bottom", mode=modes[0],
        slides="\n".join(slides), config=json.dumps(config, ensure_ascii=False).replace("</", "<\\/"))


TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}" data-mode="{mode}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="Theron · HTML Presentation">
<title>{title}</title>
{font_link}
<style>
:root {{ {light} }}
:root[data-mode="dark"] {{ {dark} }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; overflow: hidden; background: #000; }}
body {{ font-family: {font_family}; }}
.deck {{ position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; }}
.stage {{ position: relative; width: 1920px; height: 1080px; flex: none; transform-origin: center center;
  background: var(--bg); color: var(--fg); overflow: hidden; }}
.slide {{ position: absolute; inset: 0; padding: 96px 128px; display: block; overflow: hidden; }}
.cursor-top .slide {{ padding-top: 128px; }}
.cursor-bottom .slide {{ padding-bottom: 128px; }}
.slide h1, .slide h2, .slide h3 {{ margin: 0 0 .5em; line-height: 1.15; }}
.slide h1 {{ font-size: 88px; }}
.slide h2 {{ font-size: 64px; }}
.slide h3 {{ font-size: 44px; }}
.slide ul, .slide ol {{ padding-left: 1.2em; }}
.slide p, .slide li {{ font-size: 36px; line-height: 1.45; }}
.slide a {{ color: var(--accent); }}
.slide img {{ max-width: 100%; height: auto; }}
{deck_css}
/* the frame wins over the deck's CSS: only the current slide (in the current language) is there */
.slide:not(.active) {{ display: none !important; }}
.slide.active {{ visibility: visible !important; opacity: 1 !important; z-index: 1; }}
.bar {{ position: absolute; left: 0; right: 0; height: 72px; display: flex; align-items: center; gap: 24px;
  padding: 0 40px; font: 22px/1 system-ui, sans-serif; color: var(--muted); z-index: 10; }}
.cursor-top .bar {{ top: 0; }}
.cursor-bottom .bar {{ bottom: 0; }}
.progress {{ position: absolute; left: 0; height: 6px; background: var(--accent); transition: width .3s; }}
.cursor-top .progress {{ top: 0; }}
.cursor-bottom .progress {{ bottom: 0; }}
.dots {{ display: flex; gap: 10px; flex: 1; flex-wrap: wrap; }}
.dot {{ width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--muted); background: none; padding: 0;
  cursor: pointer; }}
.dot.on {{ background: var(--accent); border-color: var(--accent); }}
.count {{ min-width: 90px; text-align: right; font-variant-numeric: tabular-nums; }}
.ctl {{ font: inherit; color: var(--fg); background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; height: 44px; min-width: 44px; padding: 0 12px; cursor: pointer; }}
.ctl:focus-visible, .dot:focus-visible {{ outline: 3px solid var(--accent); outline-offset: 2px; }}
select.ctl {{ padding-right: 8px; }}
@media print {{
  html, body {{ overflow: visible; background: none; }}
  .deck {{ position: static; display: block; }}
  .stage {{ transform: none !important; height: auto; width: 1920px; }}
  .slide {{ position: relative; height: 1080px; page-break-after: always; }}
  .stage .slide[lang="{lang}"] {{ display: block !important; }}
  .bar, .progress {{ display: none; }}
}}
</style>
</head>
<body>
<main class="deck">
<div class="stage {cursor_class}" id="stage">
{slides}
<div class="progress" id="progress"></div>
<nav class="bar" aria-label="Slides">
<button class="ctl" id="prev" aria-label="Previous slide">‹</button>
<div class="dots" id="dots"></div>
<span class="count" id="count"></span>
<select class="ctl" id="lang" aria-label="Language" hidden></select>
<button class="ctl" id="mode" aria-label="Light or dark" hidden></button>
<button class="ctl" id="next" aria-label="Next slide">›</button>
</nav>
</div>
</main>
<script>
(function () {{
  var C = {config};
  var stage = document.getElementById("stage");
  var sections = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var total = 0;
  sections.forEach(function (s) {{ total = Math.max(total, parseInt(s.getAttribute("data-n"), 10) || 0); }});
  var dots = document.getElementById("dots"), count = document.getElementById("count");
  var progress = document.getElementById("progress");
  var cur = 0, lang = C.languages[0];
  function store(k, v) {{ try {{ if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); }} catch (e) {{ return null; }} }}

  function scale() {{
    var s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    stage.style.transform = "scale(" + s + ")";
  }}
  function current() {{
    return sections.filter(function (s) {{ return s.getAttribute("data-n") === String(cur + 1) && s.lang === lang; }})[0];
  }}
  function fit() {{   // shrink a slide's content until it fits – nothing is cut off
    var s = current();
    if (!s) return;
    var kids = Array.prototype.slice.call(s.children), k = 1;
    kids.forEach(function (c) {{ c.style.zoom = ""; }});
    for (var round = 0; round < 4; round++) {{
      var over = Math.max(s.scrollHeight / s.clientHeight, s.scrollWidth / s.clientWidth);
      if (!(over > 1.005)) break;
      k = k / over * 0.98;
      kids.forEach(function (c) {{ c.style.zoom = String(k); }});
    }}
  }}
  function show(i) {{
    cur = Math.max(0, Math.min(total - 1, i));
    var on = current();
    sections.forEach(function (s) {{ s.classList.toggle("active", s === on); }});
    Array.prototype.forEach.call(dots.children, function (d, n) {{
      d.classList.toggle("on", n === cur); d.setAttribute("aria-current", n === cur ? "step" : "false");
    }});
    count.textContent = (cur + 1) + " / " + total;
    progress.style.width = (total > 1 ? (cur / (total - 1)) * 100 : 100) + "%";
    if (history.replaceState) history.replaceState(null, "", "#" + (cur + 1));
    fit();
  }}
  function setLang(l) {{
    lang = C.languages.indexOf(l) >= 0 ? l : C.languages[0];
    document.documentElement.lang = lang;
    if (C.titles[lang]) document.title = C.titles[lang];
    document.getElementById("lang").value = lang;
    store("deck-lang", lang);
    show(cur);
  }}
  function setMode(m) {{
    if (C.modes.indexOf(m) < 0) m = C.modes[0];
    document.documentElement.setAttribute("data-mode", m);
    var b = document.getElementById("mode");
    b.textContent = m === "dark" ? "☀" : "☾";
    b.setAttribute("aria-label", m === "dark" ? "Light" : "Dark");
    store("deck-mode", m);
  }}

  for (var n = 0; n < total; n++) (function (n) {{
    var d = document.createElement("button");
    d.className = "dot"; d.setAttribute("aria-label", String(n + 1));
    d.addEventListener("click", function () {{ show(n); }});
    dots.appendChild(d);
  }})(n);
  document.getElementById("prev").addEventListener("click", function () {{ show(cur - 1); }});
  document.getElementById("next").addEventListener("click", function () {{ show(cur + 1); }});
  if (C.languages.length > 1) {{
    var sel = document.getElementById("lang");
    C.languages.forEach(function (l) {{
      var o = document.createElement("option"); o.value = l; o.textContent = C.names[l] || l; sel.appendChild(o);
    }});
    sel.hidden = false;
    sel.addEventListener("change", function () {{ setLang(sel.value); }});
  }}
  if (C.modes.length > 1) {{
    var mb = document.getElementById("mode");
    mb.hidden = false;
    mb.addEventListener("click", function () {{
      setMode(document.documentElement.getAttribute("data-mode") === "dark" ? "light" : "dark");
    }});
  }}
  if (C.arrows) {{
    document.addEventListener("keydown", function (e) {{
      if (e.target && /^(SELECT|INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
      var k = e.key;
      if (k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || k === " ") {{ show(cur + 1); e.preventDefault(); }}
      else if (k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp") {{ show(cur - 1); e.preventDefault(); }}
      else if (k === "Home") {{ show(0); e.preventDefault(); }}
      else if (k === "End") {{ show(total - 1); e.preventDefault(); }}
    }});
  }}
  var x0 = null;
  stage.addEventListener("touchstart", function (e) {{ x0 = e.touches[0].clientX; }}, {{ passive: true }});
  stage.addEventListener("touchend", function (e) {{
    if (x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0; x0 = null;
    if (Math.abs(dx) > 50) show(cur + (dx < 0 ? 1 : -1));
  }});
  window.addEventListener("resize", function () {{ scale(); fit(); }});
  window.addEventListener("hashchange", function () {{
    var n = parseInt(location.hash.slice(1), 10); if (n) show(n - 1);
  }});

  var q = (location.search.match(/[?&]lang=([\\w-]+)/) || [])[1];
  cur = (parseInt(location.hash.slice(1), 10) || 1) - 1;
  setLang(q || store("deck-lang") || C.languages[0]);
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  setMode(store("deck-mode") || (dark ? "dark" : "light"));
  scale();
  show(cur);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
}})();
</script>
</body>
</html>
"""
