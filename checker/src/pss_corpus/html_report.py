"""The HTML report: one self-contained file, rendered from ``report.json``.

The page has no external resources (no fonts, scripts or stylesheets fetched
from anywhere), because a report is mailed to vendors and opened offline. Every
string that came from a tool (reasons, details, trace lines, error messages) is
HTML-escaped: a returned bundle is another site's output, and a report is
opened in a browser. The page reads fully without JavaScript. The inline
script only adds filtering.
"""

import html
from typing import Any, Dict, List

from .report import tool_label, trust_text

#: Worst first: the order rows are listed and chips are shown in.
VERDICT_ORDER = ("FAIL", "UNLOCATED", "ERROR", "UNSUPPORTED", "MISSING", "STALE", "PASS")

#: The verdicts that are a finding against the tool.
_FAILING = ("FAIL", "UNLOCATED")

_VERDICT_HELP = {
    "PASS": "a legal execution, or a correct rejection at the right place",
    "FAIL": "an illegal trace, a wrong outcome, or a rejection at the wrong place",
    "UNLOCATED": "a negative test rejected, but no error named a file and line",
    "ERROR": "setup or adapter failure; says nothing about the tool",
    "UNSUPPORTED": "the tool declared a feature of the test unsupported",
    "MISSING": "no result came back for this run",
    "STALE": "the test changed since the bundle was exported",
}


def e(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _rank(v: str) -> int:
    return VERDICT_ORDER.index(v) if v in VERDICT_ORDER else len(VERDICT_ORDER)


def render_html(doc: Dict[str, Any]) -> str:
    results: List[Dict[str, Any]] = sorted(
        doc["results"], key=lambda r: (_rank(r["verdict"]), r.get("area") or "", r["job"]))
    counts = doc.get("counts", {})
    total = len(results)
    passed = counts.get("PASS", 0)
    tool = tool_label(doc)
    parts = [_HEAD.format(title=e(f"PSS compliance: {tool}"), css=_CSS),
             _header(doc, tool),
             _trust(doc),
             _summary(counts, total, passed),
             _areas(results),
             _results(results, counts),
             _excluded(doc),
             _footer(doc),
             f"<script>{_JS}</script>",
             "</body></html>\n"]
    return "\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def _header(doc, tool) -> str:
    b = doc.get("bundle") or {}
    sel = b.get("selection") or {}
    commit = (b.get("corpus") or {}).get("commit")
    meta = []
    if len(doc.get("tools", [])) > 1:
        meta.append(("Warning", "outcomes name more than one tool or target"))
    meta.append(("Source", "returned bundle (import)" if doc.get("source") != "run"
                 else "local run"))
    if b.get("created"):
        meta.append(("Exported", b["created"]))
    if commit:
        meta.append(("Corpus", commit[:12] + (" (dirty)" if commit.endswith("+dirty") else "")))
    meta.append(("Scope", f"PSS ≤ {sel.get('pss') or 'any'} · "
                          f"{doc.get('n_tests', '?')} tests · {len(doc['results'])} runs"))
    meta.append(("Generated", doc.get("generated", "")))
    dl = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in meta)
    return (f'<header class="top"><div class="eyebrow">PSS compliance report</div>'
            f"<h1>{e(tool)}</h1><dl class=\"meta\">{dl}</dl></header>")


def _trust(doc) -> str:
    t = doc.get("l0_trusted")
    state = "ok" if t else ("bad" if t is False else "warn")
    label = {"ok": "Trusted", "bad": "Untrusted", "warn": "Trust not established"}[state]
    return (f'<section class="trust trust-{state}" role="note"><strong>{label}.</strong> '
            f"{e(trust_text(doc))}</section>")


def _segments(counts: Dict[str, int], total: int) -> str:
    if not total:
        return ""
    return "".join(
        f'<span class="seg v-{v}" style="width:{100.0 * counts[v] / total:.3f}%" '
        f'title="{e(v)}: {counts[v]}"></span>'
        for v in VERDICT_ORDER[::-1] if counts.get(v))


def _summary(counts, total, passed) -> str:
    pct = f"{100.0 * passed / total:.0f}%" if total else "–"
    chips = "".join(
        f'<button type="button" class="chip" data-v="{v}" aria-pressed="true" '
        f'title="{e(_VERDICT_HELP.get(v, ""))}"><span class="dot v-{v}"></span>'
        f'{v}<span class="n">{counts[v]}</span></button>'
        for v in VERDICT_ORDER if counts.get(v))
    return (f'<section class="summary"><div class="rate"><span class="big">{pct}</span>'
            f'<span class="of">{passed} of {total} runs pass</span></div>'
            f'<div class="bar" aria-hidden="true">{_segments(counts, total)}</div>'
            f'<div class="chips" aria-label="Filter by verdict">{chips}</div></section>')


def _areas(results) -> str:
    by: Dict[str, Dict[str, int]] = {}
    for r in results:
        a = r.get("area") or "?"
        by.setdefault(a, {})
        by[a][r["verdict"]] = by[a].get(r["verdict"], 0) + 1
    order = sorted(by, key=lambda a: (not a.startswith("L0"), a))
    rows = []
    for a in order:
        c = by[a]
        n = sum(c.values())
        fail = sum(c.get(v, 0) for v in _FAILING)
        other = n - c.get("PASS", 0) - fail
        rows.append(
            f'<tr><td><button type="button" class="area-link" data-area="{e(a)}">{e(a)}</button></td>'
            f'<td class="num">{n}</td><td class="num">{c.get("PASS", 0)}</td>'
            f'<td class="num{" hot" if fail else ""}">{fail}</td>'
            f'<td class="num">{other}</td>'
            f'<td class="barcell"><div class="bar mini">{_segments(c, n)}</div></td></tr>')
    return ('<section><h2>By area</h2><div class="scroll"><table class="areas">'
            '<thead><tr><th>Area</th><th class="num">Runs</th><th class="num">Pass</th>'
            '<th class="num" title="FAIL or UNLOCATED">Fail</th>'
            '<th class="num" title="UNSUPPORTED, ERROR, MISSING or STALE">Other</th>'
            '<th>Verdicts</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>')


def _results(results, counts) -> str:
    areas = sorted({r.get("area") or "?" for r in results}, key=lambda a: (not a.startswith("L0"), a))
    opts = "".join(f'<option value="{e(a)}">{e(a)}</option>' for a in areas)
    rows = "".join(_row(r) for r in results)
    return (
        '<section><h2>Results</h2>'
        '<div class="toolbar">'
        '<input type="search" id="q" placeholder="Filter by test, reason or clause…" '
        'aria-label="Filter results">'
        f'<select id="area" aria-label="Area"><option value="">All areas</option>{opts}</select>'
        '<label class="toggle"><input type="checkbox" id="hidepass"> Hide passing</label>'
        '<span id="shown" class="muted" aria-live="polite"></span></div>'
        '<div class="scroll"><table class="results"><thead><tr>'
        '<th>Verdict</th><th>Test</th><th class="num">Seed</th><th>Area</th><th>Reason</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>'
        '<p id="empty" class="muted" hidden>No runs match.</p></section>')


def _row(r) -> str:
    v = r["verdict"]
    reason = r.get("reason") or ""
    lrm = r.get("lrm") or []
    q = " ".join([r["job"], r.get("title") or "", reason, " ".join(lrm), v]).lower()
    flag = '<span class="pill">untrusted</span>' if r.get("untrusted") else ""
    body = _details(r)
    if v == "PASS" and not body:
        cell = '<span class="muted">–</span>'
    else:
        head = e(reason) if reason else '<span class="muted">(no reason given)</span>'
        cell = (f'<details><summary>{head}</summary>{body}</details>' if body
                else f"<div>{head}</div>")
    title = f'<div class="ttl">{e(r.get("title"))}</div>' if r.get("title") else ""
    return (f'<tr data-v="{e(v)}" data-area="{e(r.get("area") or "?")}" data-q="{e(q)}">'
            f'<td class="vcell"><span class="badge v-{e(v)}">{e(v)}</span>{flag}</td>'
            f'<td class="test"><code>{e(r["test"])}</code>{title}</td>'
            f'<td class="num">{e(r.get("seed"))}</td>'
            f'<td><span class="area">{e(r.get("area"))}</span>'
            f'<div class="muted small">{e(r.get("level") or "")}</div></td>'
            f'<td class="reason">{cell}</td></tr>')


def _details(r) -> str:
    out = []
    facts = []
    if r.get("lrm"):
        facts.append(("LRM", ", ".join(r["lrm"])))
    if r.get("outcome"):
        facts.append(("Outcome", r["outcome"]))
    facts.append(("Run", r["job"]))
    if r["verdict"] == "PASS" and not r.get("evidence"):
        return ""
    out.append('<dl class="facts">' + "".join(
        f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in facts) + "</dl>")
    if r.get("detail"):
        out.append(_block("Tool detail", r["detail"], wrap=True))
    ev = r.get("evidence") or {}
    if ev.get("trace"):
        more = "\n… (truncated)" if ev.get("trace_truncated") else ""
        out.append(_block("Trace records printed", "\n".join(ev["trace"]) + more))
    elif ev.get("log_tail"):
        out.append(_block("End of log (no trace records)", "\n".join(ev["log_tail"])))
    if ev.get("diagnostics"):
        lines = [f"{d.get('severity') or '?'}: {d.get('file') or '?'}:{d.get('line') or '?'}"
                 f"  {d.get('message') or ''}" for d in ev["diagnostics"]]
        out.append(_block("Diagnostics reported", "\n".join(lines)))
    if ev.get("adapter_log_tail") and r["verdict"] in ("ERROR", "MISSING"):
        out.append(_block("Adapter output (tail)", ev["adapter_log_tail"], wrap=True))
    return "".join(out)


def _block(label: str, text: str, wrap: bool = False) -> str:
    """A labelled evidence block. Prose wraps; trace lines never do (§4.2: a
    record's layout is part of what is checked)."""
    cls = ' class="wrap"' if wrap else ""
    return f'<div class="ev"><div class="evl">{e(label)}</div><pre{cls}>{e(text)}</pre></div>'


def _excluded(doc) -> str:
    ex = (doc.get("bundle") or {}).get("excluded") or []
    if not ex:
        return ""
    rows = "".join(f"<tr><td><code>{e(x['id'])}</code></td><td>{e(x['reason'])}</td></tr>"
                   for x in ex)
    return ('<section><h2>Not exported</h2><p class="muted">Tests the tool was not asked '
            'to run, and why.</p><div class="scroll"><table><thead><tr><th>Test</th>'
            f'<th>Why</th></tr></thead><tbody>{rows}</tbody></table></div></section>')


def _footer(doc) -> str:
    legend = "".join(f'<div><span class="badge v-{v}">{v}</span> {e(h)}</div>'
                     for v, h in _VERDICT_HELP.items())
    return (f'<footer><div class="legend">{legend}</div><p class="muted">pss-corpus '
            f'{e(doc.get("checker_version", ""))} · {e(doc.get("schema", ""))} · '
            'the JSON beside this page is the source of truth</p></footer>')


# --------------------------------------------------------------------------- #
# Page furniture
# --------------------------------------------------------------------------- #

_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style></head><body>"""

_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1c1f23;--muted:#5f6670;--line:#e3e4e1;--code:#f0f0ec;
--PASS:#1a7f37;--PASS-bg:#e6f4ea;--FAIL:#c62828;--FAIL-bg:#fdeaea;--UNLOCATED:#b35900;
--UNLOCATED-bg:#fdf0e1;--ERROR:#7b3fc4;--ERROR-bg:#f1eafb;--UNSUPPORTED:#3d6a99;
--UNSUPPORTED-bg:#e8f0f8;--MISSING:#6a7079;--MISSING-bg:#eeeff0;--STALE:#6a7079;
--STALE-bg:#eeeff0;--ok-bg:#e6f4ea;--bad-bg:#fdeaea;--warn-bg:#fdf5dc;--warn:#8a6100}
@media (prefers-color-scheme:dark){:root{--bg:#131518;--card:#1b1e22;--fg:#e6e7e9;
--muted:#9aa1ab;--line:#2c3036;--code:#23272d;--PASS:#4cc26a;--PASS-bg:#16301f;
--FAIL:#ff6b6b;--FAIL-bg:#3a1c1c;--UNLOCATED:#f0a04b;--UNLOCATED-bg:#3a2a15;
--ERROR:#b690f5;--ERROR-bg:#2c2140;--UNSUPPORTED:#7fb0e6;--UNSUPPORTED-bg:#1c2a3a;
--MISSING:#a0a6ae;--MISSING-bg:#2a2d31;--STALE:#a0a6ae;--STALE-bg:#2a2d31;
--ok-bg:#16301f;--bad-bg:#3a1c1c;--warn-bg:#352c12;--warn:#e7c35a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif;padding:32px 16px 48px}
body>*{max-width:1200px;margin-left:auto;margin-right:auto}
h1{font-size:28px;margin:4px 0 12px;letter-spacing:-.01em}
h2{font-size:17px;margin:0 0 12px}
section,header.top,footer{background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:20px 22px;margin-bottom:16px}
.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.meta{display:flex;flex-wrap:wrap;gap:6px 28px;margin:0}
.meta dt,.facts dt{font-size:12px;color:var(--muted)}
.meta dd,.facts dd{margin:0;font-variant-numeric:tabular-nums}
.trust{border-left-width:5px}
.trust-ok{background:var(--ok-bg);border-left-color:var(--PASS)}
.trust-bad{background:var(--bad-bg);border-left-color:var(--FAIL)}
.trust-warn{background:var(--warn-bg);border-left-color:var(--warn)}
.summary{display:grid;gap:14px}
.rate{display:flex;align-items:baseline;gap:12px}
.big{font-size:44px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.of{color:var(--muted)}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line)}
.bar.mini{height:10px;min-width:120px}
.seg{display:block;height:100%}
.seg.v-PASS,.dot.v-PASS{background:var(--PASS)}.seg.v-FAIL,.dot.v-FAIL{background:var(--FAIL)}
.seg.v-UNLOCATED,.dot.v-UNLOCATED{background:var(--UNLOCATED)}
.seg.v-ERROR,.dot.v-ERROR{background:var(--ERROR)}
.seg.v-UNSUPPORTED,.dot.v-UNSUPPORTED{background:var(--UNSUPPORTED)}
.seg.v-MISSING,.dot.v-MISSING,.seg.v-STALE,.dot.v-STALE{background:var(--MISSING)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);
background:var(--card);color:var(--fg);border-radius:999px;padding:5px 12px;font:inherit;
font-size:13px;font-weight:600;cursor:pointer}
.chip[aria-pressed=false]{opacity:.45}
.chip .n{font-weight:400;color:var(--muted);font-variant-numeric:tabular-nums}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:12px;font-weight:600;color:var(--muted);padding:8px 10px;
border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
.num{text-align:right;font-variant-numeric:tabular-nums}
td.hot{color:var(--FAIL);font-weight:600}
.barcell{width:40%}
.area-link{background:none;border:0;padding:0;font:inherit;color:inherit;cursor:pointer;
text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.03em;
padding:2px 8px;border-radius:5px;white-space:nowrap}
.badge.v-PASS{color:var(--PASS);background:var(--PASS-bg)}
.badge.v-FAIL{color:var(--FAIL);background:var(--FAIL-bg)}
.badge.v-UNLOCATED{color:var(--UNLOCATED);background:var(--UNLOCATED-bg)}
.badge.v-ERROR{color:var(--ERROR);background:var(--ERROR-bg)}
.badge.v-UNSUPPORTED{color:var(--UNSUPPORTED);background:var(--UNSUPPORTED-bg)}
.badge.v-MISSING,.badge.v-STALE{color:var(--MISSING);background:var(--MISSING-bg)}
.pill{display:inline-block;margin-left:6px;font-size:11px;border:1px solid var(--FAIL);
color:var(--FAIL);border-radius:999px;padding:0 7px}
.vcell{white-space:nowrap}
.test code{font-size:13px}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.ttl{color:var(--muted);font-size:13px;margin-top:2px}
.area{font-size:13px;white-space:nowrap}
.small{font-size:12px}
.muted{color:var(--muted)}
.reason{min-width:280px;max-width:560px;overflow-wrap:anywhere}
details summary{cursor:pointer}
details[open] summary{margin-bottom:8px}
.facts{display:flex;flex-wrap:wrap;gap:4px 22px;margin:0 0 8px}
.ev{margin-top:8px}
.evl{font-size:12px;color:var(--muted);margin-bottom:3px}
pre{margin:0;background:var(--code);border-radius:6px;padding:9px 11px;font-size:12px;
line-height:1.45;overflow-x:auto;white-space:pre}
pre.wrap{white-space:pre-wrap;overflow-wrap:anywhere}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
.toolbar input[type=search]{flex:1 1 260px;font:inherit;padding:7px 11px;border-radius:7px;
border:1px solid var(--line);background:var(--bg);color:var(--fg)}
.toolbar select{font:inherit;padding:7px 9px;border-radius:7px;border:1px solid var(--line);
background:var(--bg);color:var(--fg)}
.toggle{display:inline-flex;gap:6px;align-items:center;font-size:14px}
.legend{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:6px 20px;
font-size:13px;margin-bottom:10px}
footer p{margin:0;font-size:12px}
@media (max-width:640px){body{padding:16px}.big{font-size:34px}.barcell{display:none}
section,header.top,footer{padding:16px}}
@media print{body{background:#fff;padding:0}.toolbar,.chips{display:none}
section,header.top,footer{break-inside:avoid-page;border-color:#ccc}}
"""

_JS = """
(function(){
var rows=[].slice.call(document.querySelectorAll('table.results tbody tr'));
var chips=[].slice.call(document.querySelectorAll('.chip'));
var q=document.getElementById('q'),area=document.getElementById('area'),
hide=document.getElementById('hidepass'),shown=document.getElementById('shown'),
empty=document.getElementById('empty');
function on(v){var c=document.querySelector('.chip[data-v="'+v+'"]');
return !c||c.getAttribute('aria-pressed')!=='false';}
function apply(){var t=q.value.trim().toLowerCase(),a=area.value,n=0;
rows.forEach(function(r){var v=r.getAttribute('data-v');
var ok=on(v)&&!(hide.checked&&v==='PASS')&&(!a||r.getAttribute('data-area')===a)
&&(!t||r.getAttribute('data-q').indexOf(t)>=0);r.hidden=!ok;if(ok)n++;});
shown.textContent=n+' of '+rows.length+' runs shown';empty.hidden=n>0;}
chips.forEach(function(c){c.addEventListener('click',function(){
c.setAttribute('aria-pressed',c.getAttribute('aria-pressed')==='false'?'true':'false');apply();});});
[].forEach.call(document.querySelectorAll('.area-link'),function(b){
b.addEventListener('click',function(){area.value=b.getAttribute('data-area');apply();
document.getElementById('q').scrollIntoView({behavior:'smooth',block:'center'});});});
q.addEventListener('input',apply);area.addEventListener('change',apply);
hide.addEventListener('change',apply);apply();
})();
"""
