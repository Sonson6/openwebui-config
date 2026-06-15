"""
title: Plotly Visualizer
author: Classic298
version: 1.0.0
required_open_webui_version: 0.9.5
description: Renders a Plotly chart inline in chat from a declarative figure spec, with native vector SVG and PNG export (the modebar camera buttons). Vector SVG drops cleanly into Word / PowerPoint. Requires "iframe Sandbox Allow Same Origin" in Open WebUI Settings -> Interface. The model should call view_skill("plot") first for the figure-spec format.
"""

import json
import re
from typing import Literal

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# Build marker baked into the iframe (search DevTools for data-pv-build on
# <html>) so a stale cached iframe is easy to spot. Bump on protocol change.
_PV_BUILD = "1.0.0"

# Pinned Plotly bundle. plotly.js-dist-min ships a single self-contained
# plotly.min.js (no worker / no runtime fetch), which is what keeps the
# strict CSP's `connect-src 'none'` from interfering. Lives on a CDN that
# the CSP below already allowlists.
_PLOTLY_URL = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"

_KNOWN_CDNS = (
    "https://cdnjs.cloudflare.com"
    " https://cdn.jsdelivr.net"
    " https://unpkg.com"
)

# Hard ceiling on the inbound figure spec so a runaway model response can't
# bloat the chat document. ~2 MB of JSON is far more than any sane chart.
_MAX_FIGURE_CHARS = 2_000_000

# Forbidden srcdoc literals — same rule as the inline-visualizer: each script
# body may contain exactly its own wrapping <script>/</script> (here: zero,
# because the wrapping tags are added in _build_html), and never the comment
# / CDATA tokens that flip the HTML5 script-data tokenizer.
_FORBIDDEN_SRCDOC_LITERALS = ("<!--", "-->", "<![CDATA[", "]]>", "<script", "</script")


def _assert_srcdoc_safe(name: str, body: str) -> None:
    """Refuse to ship a script body that would confuse srcdoc parsing."""
    if "<script" in body or "</script" in body:
        raise RuntimeError(
            f"Plotly Visualizer: {name} contains a <script>/</script> literal; "
            "the wrapping tags are added in _build_html, so the body must have none."
        )
    for tok in ("<!--", "-->", "<![CDATA[", "]]>"):
        if tok in body:
            raise RuntimeError(
                f"Plotly Visualizer: {name} contains a literal {tok!r}, which "
                "breaks the iframe srcdoc parser. Concatenate it in JS instead."
            )


# ---------------------------------------------------------------------------
# Iframe CSS — minimal, theme-agnostic. Plotly paints its own colors; we only
# style the shell + modebar so it reads on both light and dark chat themes.
# ---------------------------------------------------------------------------

_STYLES = """
:root { color-scheme: light dark; }
html, body { margin: 0; padding: 0; background: transparent; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
#pv-plot { width: 100%; }
#pv-error {
  display: none; padding: 16px; border-radius: 10px; font-size: 13px; line-height: 1.5;
  background: rgba(239,68,68,0.10); color: #b91c1c; border: 1px solid rgba(239,68,68,0.30);
}
[data-theme="dark"] #pv-error { color: #fca5a5; }
/* Keep the modebar visible (Plotly hides it until hover by default). */
.modebar { opacity: 0.85 !important; }
.modebar-btn svg { vertical-align: middle; }
"""


# ---------------------------------------------------------------------------
# Iframe bootstrap JS (no <script> tags — those are added in _build_html).
# Injected tokens: __FIGURE_JSON__ (a {"data":..,"layout":..} object literal)
# and __HEIGHT__ (integer px). Runs AFTER plotly.min.js, so window.Plotly is
# already defined (both are parser-blocking <script> tags, in order).
# ---------------------------------------------------------------------------

_BOOTSTRAP_JS = r"""
(function () {
  var FIG = __FIGURE_JSON__;
  var H = __HEIGHT__;
  var gd = document.getElementById('pv-plot');
  var errBox = document.getElementById('pv-error');

  function showError(msg) {
    try {
      errBox.textContent = msg || 'Could not load the plotting library. Check your network / CSP and try again.';
      errBox.style.display = 'block';
      reportHeight();
    } catch (e) {}
  }

  // --- height reporting (Open WebUI iframe contract) ---
  function reportHeight() {
    try {
      var h = Math.ceil(document.body.scrollHeight);
      parent.postMessage({ type: 'iframe:height', height: h }, '*');
    } catch (e) {}
  }
  window.addEventListener('load', reportHeight);
  try {
    new ResizeObserver(function () { requestAnimationFrame(reportHeight); }).observe(document.body);
  } catch (e) {}

  if (!window.Plotly) { showError(); return; }

  // --- theme detection: follow the parent Open WebUI page, fall back to OS ---
  function isDark() {
    // 1. An explicit theme on the parent Open WebUI page is authoritative —
    //    honor light AND dark so a dark OS doesn't override a light app.
    try {
      var r = parent.document.documentElement;
      var attr = r.getAttribute('data-theme');
      var cs = getComputedStyle(r).colorScheme;
      if (r.classList.contains('dark') || attr === 'dark' || cs === 'dark') return true;
      if (r.classList.contains('light') || attr === 'light' || cs === 'light') return false;
    } catch (e) {}
    // 2. No explicit signal (or no same-origin access): follow OS preference.
    try { return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches); } catch (e) {}
    return false;
  }
  function reflectTheme(dark) {
    var v = dark ? 'dark' : 'light';
    if (document.documentElement.getAttribute('data-theme') !== v) {
      document.documentElement.setAttribute('data-theme', v);
    }
  }

  // A solid (not transparent) themed background is deliberate: an exported
  // SVG/PNG must carry its own background so light-on-transparent text stays
  // legible when pasted onto a white Word page or a dark slide.
  function themeLayout(dark) {
    var text = dark ? '#E6E6E6' : '#1F2937';
    var grid = dark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.08)';
    var zero = dark ? 'rgba(255,255,255,0.22)' : 'rgba(0,0,0,0.16)';
    var line = dark ? 'rgba(255,255,255,0.18)' : 'rgba(0,0,0,0.18)';
    var bg = dark ? '#1B1B1D' : '#FFFFFF';
    return {
      paper_bgcolor: bg,
      plot_bgcolor: bg,
      font: { color: text, family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif' },
      colorway: ['#7C6CF0', '#14B8A6', '#F472B6', '#F59E0B', '#60A5FA', '#34D399', '#FB7185', '#A78BFA', '#FBBF24'],
      xaxis: { gridcolor: grid, zerolinecolor: zero, linecolor: line },
      yaxis: { gridcolor: grid, zerolinecolor: zero, linecolor: line },
      legend: { font: { color: text } },
      margin: { t: 48, r: 24, b: 56, l: 64 }
    };
  }
  // Flattened theme keys for relayout (nested objects don't merge cleanly
  // through relayout, so we target exact paths and never clobber user data).
  function flatTheme(dark) {
    var t = themeLayout(dark);
    return {
      paper_bgcolor: t.paper_bgcolor, plot_bgcolor: t.plot_bgcolor,
      'font.color': t.font.color,
      'xaxis.gridcolor': t.xaxis.gridcolor, 'xaxis.zerolinecolor': t.xaxis.zerolinecolor, 'xaxis.linecolor': t.xaxis.linecolor,
      'yaxis.gridcolor': t.yaxis.gridcolor, 'yaxis.zerolinecolor': t.yaxis.zerolinecolor, 'yaxis.linecolor': t.yaxis.linecolor,
      'legend.font.color': t.font.color
    };
  }
  function deepMerge(base, over) {
    if (over === null || typeof over !== 'object' || Array.isArray(over)) return over;
    var out = {};
    var k;
    for (k in base) out[k] = base[k];
    for (k in over) {
      if (out[k] && typeof out[k] === 'object' && !Array.isArray(out[k]) &&
          over[k] && typeof over[k] === 'object' && !Array.isArray(over[k])) {
        out[k] = deepMerge(out[k], over[k]);
      } else {
        out[k] = over[k];
      }
    }
    return out;
  }

  // --- filesystem-safe base name from the document title ---
  function fileBase() {
    var n = (document.title || 'plot').replace(/[<>:"\\/|?*]+/g, '-').replace(/\s+/g, ' ').trim();
    if (!n) n = 'plot';
    if (n.length > 200) n = n.substring(0, 200).trim();
    return n;
  }

  // --- robust blob download (desktop / Android / iOS), mirrors inline-visualizer ---
  var IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  function saveBlob(blob, fname) {
    var url = URL.createObjectURL(blob);
    if (IS_IOS) {
      setTimeout(function () {
        var a = document.createElement('a');
        a.style.display = 'none'; a.href = url; a.download = fname;
        document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 60000);
      }, 0);
    } else {
      var a = document.createElement('a');
      a.href = url; a.download = fname; a.target = '_blank'; a.style.display = 'none';
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 4000);
    }
  }
  // Plotly.toImage returns base64 for png/jpeg/webp and a URL-encoded
  // (non-base64) payload for svg. Handle both.
  function dataUrlToBlob(durl) {
    var comma = durl.indexOf(',');
    var meta = durl.substring(0, comma);
    var data = durl.substring(comma + 1);
    var mime = (meta.split(':')[1] || 'application/octet-stream').split(';')[0];
    if (meta.indexOf('base64') !== -1) {
      var bin = atob(data);
      var arr = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      return new Blob([arr], { type: mime });
    }
    return new Blob([decodeURIComponent(data)], { type: (mime || 'image/svg+xml') + ';charset=utf-8' });
  }
  function exportPlot(graphDiv, fmt) {
    var opts = { format: fmt };
    if (fmt === 'png') opts.scale = 2;  // crisp raster fallback
    Plotly.toImage(graphDiv, opts).then(function (durl) {
      saveBlob(dataUrlToBlob(durl), fileBase() + '.' + fmt);
    }).catch(function () { showError('Export failed. Try the other format.'); });
  }
  function makeBtn(fmt, title) {
    return { name: title, title: title, icon: Plotly.Icons.camera,
             click: function (graphDiv) { exportPlot(graphDiv, fmt); } };
  }

  // --- render ---
  var dark = isDark();
  reflectTheme(dark);
  var layout = deepMerge(themeLayout(dark), FIG.layout || {});
  if (!layout.height) layout.height = H;     // honor a model-set height, else default
  layout.autosize = true;
  var config = {
    displaylogo: false,
    responsive: true,
    displayModeBar: true,
    // Replace the default camera (PNG-only) with explicit SVG + PNG buttons.
    modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'lasso2d', 'select2d'],
    modeBarButtonsToAdd: [
      makeBtn('svg', 'Download SVG — vector, for Word / PowerPoint'),
      makeBtn('png', 'Download PNG')
    ]
  };

  Plotly.newPlot(gd, FIG.data || [], layout, config).then(function () {
    reportHeight();
  }).catch(function (e) {
    showError('Could not render this figure. ' + (e && e.message ? e.message : ''));
  });

  // Re-theme live when the user flips Open WebUI light/dark.
  try {
    var pr = parent.document.documentElement;
    new MutationObserver(function () {
      var d = isDark();
      reflectTheme(d);
      Plotly.relayout(gd, flatTheme(d));
    }).observe(pr, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
  } catch (e) {}

  // Keep Plotly sized to the iframe width.
  window.addEventListener('resize', function () {
    try { Plotly.Plots.resize(gd); } catch (e) {}
    reportHeight();
  });
})();
"""

_assert_srcdoc_safe("_BOOTSTRAP_JS", _BOOTSTRAP_JS)


# ---------------------------------------------------------------------------
# CSP generation per security level
# ---------------------------------------------------------------------------


def _build_csp_tag(level: str) -> str:
    """Return a <meta> CSP tag for the given security level, or ''.

    Plotly.js needs: its CDN in script-src; 'unsafe-inline' for the bootstrap
    script and the inline styles Plotly injects; img-src data: for the PNG
    export path (it rasterizes an SVG via a data: URL); blob: for the download.
    It does NOT need 'unsafe-eval' or any network at runtime, so strict keeps
    connect-src 'none'.
    """
    if level == "none":
        return ""

    img = "'self' data: blob:" if level == "strict" else "* data: blob:"
    return (
        '<meta http-equiv="Content-Security-Policy" content="'
        "default-src 'self'; "
        f"script-src 'unsafe-inline' {_KNOWN_CDNS}; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'none'; "
        "form-action 'none'; "
        f"img-src {img}; "
        "font-src 'self' data:; "
        "media-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        '">'
    )


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------


def _escape_for_script(payload_json: str) -> str:
    """Make a JSON string safe to embed inside a <script> element.

    Escapes the three sequences that could either break out of the script
    element (</...) or terminate it, plus the two Unicode line separators
    that are invalid inside a JS string literal. json.dumps does not do this.
    """
    return (
        payload_json
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _build_html(figure: dict, title: str, security_level: str, height: int) -> str:
    payload = {"data": figure.get("data", []), "layout": figure.get("layout", {})}
    payload_json = _escape_for_script(json.dumps(payload, ensure_ascii=False))

    bootstrap = (
        _BOOTSTRAP_JS
        .replace("__FIGURE_JSON__", payload_json)
        .replace("__HEIGHT__", str(int(height)))
    )

    csp_tag = _build_csp_tag(security_level)
    safe_title = (title.replace("&", "&amp;").replace("<", "&lt;")
                       .replace(">", "&gt;").replace('"', "&quot;"))

    # The two <script> tags below are the ONLY script tags; the bootstrap body
    # is asserted to contain none of its own (see _assert_srcdoc_safe).
    return (
        f'<!DOCTYPE html><html data-pv-build="{_PV_BUILD}"><head>'
        f"<title>{safe_title}</title>"
        f"{csp_tag}"
        f"<style>{_STYLES}</style>"
        f'<script>try{{console.info("pv[build]","{_PV_BUILD}");}}catch(e){{}}</script>'
        f"</head><body>"
        f'<div id="pv-plot"></div>'
        f'<div id="pv-error" role="alert"></div>'
        f'<script src="{_PLOTLY_URL}"></script>'
        f"<script>{bootstrap}</script>"
        f"</body></html>"
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class Tools:
    """Plotly Visualizer — renders a Plotly figure inline in chat.

    The model passes a declarative Plotly figure spec (``data`` + optional
    ``layout``) and the chart is rendered complete — no streaming. The
    rendered chart's modebar carries native ``Download SVG`` and ``Download
    PNG`` buttons; the SVG is true vector and drops cleanly into Word /
    PowerPoint. Theme (light/dark) follows the Open WebUI page.

    Security is controlled by the ``security_level`` valve, which applies a
    Content Security Policy to the iframe (STRICT blocks outbound network).
    """

    class Valves(BaseModel):
        security_level: Literal["strict", "balanced", "none"] = Field(
            default="strict",
            description="Strict (default): blocks outbound fetch/XHR and forms; only the pinned Plotly CDN may load. Balanced: also allows external images. None: no CSP.",
        )
        default_height: int = Field(
            default=460,
            description="Default plot height in pixels when the figure's layout does not specify one.",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def plot(
        self,
        title: str = "Plot",
        figure: str = "",
        __event_call__=None,
    ) -> tuple:
        """
        Render a Plotly chart inline in the chat, with native vector SVG and PNG download.

        Use this tool ONLY when the user EXPLICITLY asks for a chart, plot, or graph of data
        (bar, line, scatter, pie, histogram, box, heatmap, etc.). Do NOT use it proactively
        and do NOT use it for diagrams, illustrations, or general UI — only data charts.

        IMPORTANT:
        BEFORE CALLING THIS TOOL, YOU MUST call view_skill("plot") FIRST to read the figure-spec
        format and chart-type examples. Never construct the `figure` argument without reading it.

        :param title: Short descriptive title; used for the window title and the download filename.
        :param figure: A JSON string of a Plotly figure spec: an object with a "data" array of
            traces and an optional "layout" object — e.g.
            {"data":[{"type":"bar","x":["A","B"],"y":[3,7]}],"layout":{"title":{"text":"Demo"}}}.
            Do NOT set paper_bgcolor / plot_bgcolor / font color — the tool themes the chart to
            match the chat automatically. Provide axis titles via layout.xaxis.title / yaxis.title.
        :return: An interactive Plotly chart rendered in the chat, with SVG/PNG export buttons.
        """
        if not isinstance(figure, str) or not figure.strip():
            return (
                "ERROR: `figure` was empty. Call plot(title=..., figure=<JSON string>) where "
                "figure is a Plotly spec like "
                '{"data":[{"type":"bar","x":["A","B"],"y":[3,7]}],"layout":{}}. '
                "Read view_skill(\"plot\") for the format, then retry."
            )

        if len(figure) > _MAX_FIGURE_CHARS:
            return (
                f"ERROR: `figure` is too large ({len(figure)} chars; limit {_MAX_FIGURE_CHARS}). "
                "Aggregate or sample the data to a smaller set of points and retry."
            )

        try:
            parsed = json.loads(figure)
        except json.JSONDecodeError as e:
            return (
                f"ERROR: `figure` is not valid JSON ({e.msg} at line {e.lineno} col {e.colno}). "
                "Emit a single well-formed JSON object for `figure` — no trailing commas, no "
                "comments, no Python None/True (use null/true). Then retry."
            )

        if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
            return (
                "ERROR: `figure` must be a JSON object with a \"data\" array of traces, e.g. "
                '{"data":[{"type":"bar","x":["A","B"],"y":[3,7]}],"layout":{}}. '
                "Read view_skill(\"plot\") and retry."
            )

        layout = parsed.get("layout") if isinstance(parsed.get("layout"), dict) else {}
        h = layout.get("height")
        if not isinstance(h, int) or h <= 0:
            h = self.valves.default_height

        html = _build_html(
            {"data": parsed["data"], "layout": layout},
            title,
            self.valves.security_level,
            h,
        )
        response = HTMLResponse(content=html, headers={"Content-Disposition": "inline"})
        result_context = (
            f'The Plotly chart "{title}" is now rendered in the chat with {len(parsed["data"])} '
            "trace(s). It is COMPLETE — do NOT re-emit the figure or describe the JSON. In your "
            "reply, describe what the chart shows. Tell the user they can download it as a vector "
            "SVG (best for Word/PowerPoint) or PNG using the camera buttons in the chart's toolbar."
        )
        return response, result_context
