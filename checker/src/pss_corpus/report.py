"""Reports: one run's verdicts over many tests, as JSON, Markdown and HTML.

Both ways of running a tool produce the same :class:`Report`: ``import`` (a
returned bundle, HANDOFF.md) and ``run`` (an adapter driven here). A report is
written as ``report.json``, the source of truth, which ``pss-corpus report``
can re-render, and as ``report.md`` and ``report.html`` (:mod:`html_report`).

Each result row carries enough to be read without the corpus at hand: the
test's title, area and LRM clauses, and, for a run that did not PASS, its
*evidence*: the trace records it printed and the errors it reported.
"""

import dataclasses as dc
import datetime
import json
import os
from typing import Any, Dict, List, Optional

from . import __version__
from .check import FAIL, PASS, UNLOCATED, UNSUPPORTED, Verdict

REPORT_SCHEMA = "pss-corpus/report/1.0"

#: Evidence limits: enough to see the divergence, not the whole log.
MAX_TRACE_LINES = 60
MAX_LOG_TAIL = 20
MAX_DIAGNOSTICS = 10
MAX_TEXT = 4000

SENTINEL = "@@PSS-TRACE "


@dc.dataclass
class Report:
    #: the bundle's ``bundle.json`` for ``import``; ``{}`` for ``run``
    bundle: Dict[str, Any]
    results: List[Dict[str, Any]]
    #: every tool/target identity the outcomes named
    tools: List[Dict[str, Any]]
    #: False when an L0 run FAILed: the tool's output is not what the protocol
    #: says, so nothing else it printed can be read (§4.6). True when every
    #: other L0 run PASSed or was honestly UNSUPPORTED (L0 includes a recursive
    #: function, which a tool may lack). None when trust was not established:
    #: no L0 in the run, or L0 runs that ERRORed, went MISSING or STALE --
    #: facts about the setup, not the tool. An UNLOCATED L0 run does not
    #: withdraw trust; it only means every negative test will be UNLOCATED too.
    l0_trusted: Optional[bool]
    #: "import" or "run"
    source: str = "import"

    @property
    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for r in self.results:
            c[r["verdict"]] = c.get(r["verdict"], 0) + 1
        return c

    def to_json(self) -> Dict[str, Any]:
        b = self.bundle
        return {"schema": REPORT_SCHEMA,
                "generated": _now(), "checker_version": __version__, "source": self.source,
                "bundle": {k: b.get(k) for k in ("created", "corpus", "selection", "excluded")},
                "n_tests": len(b["tests"]) if "tests" in b else len({r["test"] for r in self.results}),
                "tools": self.tools, "l0_trusted": self.l0_trusted,
                "counts": self.counts, "results": self.results}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Building rows
# --------------------------------------------------------------------------- #

def row(v: Verdict, job: str, test=None, entry: Optional[Dict[str, Any]] = None,
        run_dir: Optional[str] = None) -> Dict[str, Any]:
    """A report row for verdict *v*: the verdict plus what a reader needs around it.

    *test* is the local :class:`Test`, when there is one; *entry* the bundle's
    record of it. Either supplies the title, level and clauses.
    """
    r = v.to_json()
    src = test.model if test is not None else (entry or {})
    r.update(job=job, untrusted=False,
             level=src.get("level"),
             title=src.get("title", ""),
             lrm=list(src.get("lrm", [])),
             area=_area(test, v.test))
    if v.verdict != PASS and run_dir:
        r["evidence"] = evidence(run_dir)
    return r


def _area(test, test_id: str) -> str:
    """The directory a test lives in below ``compliance/`` (``proc``, ``neg``, ...)."""
    if test is not None:
        rel = test.path.replace(os.sep, "/").rpartition("/compliance/")[2]
        if "/" in rel:
            return rel.split("/")[0]
    return test_id.split(".")[0]


def evidence(run_dir: str) -> Dict[str, Any]:
    """What a failed run printed: its trace records (or the log's tail) and its errors."""
    ev: Dict[str, Any] = {}
    try:
        with open(os.path.join(run_dir, "log.txt"), errors="replace") as fp:
            log = fp.read().splitlines()
    except OSError:
        log = None
    if log is not None:
        trace = [ln[ln.index(SENTINEL):] for ln in log if SENTINEL in ln]
        if trace:
            ev["trace"] = trace[:MAX_TRACE_LINES]
            ev["trace_truncated"] = len(trace) > MAX_TRACE_LINES
        elif log:
            ev["log_tail"] = [ln[:500] for ln in log[-MAX_LOG_TAIL:]]
    try:
        with open(os.path.join(run_dir, "diagnostics.json")) as fp:
            diags = json.load(fp).get("diagnostics", [])
        ev["diagnostics"] = [
            {k: d.get(k) for k in ("severity", "file", "line", "column", "message")}
            for d in diags[:MAX_DIAGNOSTICS] if isinstance(d, dict)]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(run_dir, "adapter.log"), errors="replace") as fp:
            tail = fp.read()[-MAX_TEXT:]
        if tail.strip():
            ev["adapter_log_tail"] = tail
    except OSError:
        pass
    return ev


def apply_trust(results: List[Dict[str, Any]]) -> Optional[bool]:
    """Decide L0 trust (see :attr:`Report.l0_trusted`) and flag untrusted rows."""
    l0 = [r["verdict"] for r in results if r["level"] == "L0"]
    if FAIL in l0:
        trusted = False
    elif PASS in l0 and all(v in (PASS, UNSUPPORTED, UNLOCATED) for v in l0):
        trusted = True
    else:
        trusted = None
    if trusted is False:
        for r in results:
            if r["level"] != "L0":
                r["untrusted"] = True
    return trusted


def tool_identity(run_dir: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(run_dir, "outcome.json")) as fp:
            oc = json.load(fp)
    except (OSError, ValueError):
        return None
    if not isinstance(oc, dict):
        return None
    ident = {k: oc.get(k) for k in ("tool", "tool_version", "target") if oc.get(k)}
    return ident or None


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def write_report(report: Report, out_dir: str) -> Dict[str, str]:
    """Write report.json, report.md and report.html to *out_dir*; returns their paths."""
    from .html_report import render_html
    os.makedirs(out_dir, exist_ok=True)
    doc = report.to_json()
    paths = {ext: os.path.join(out_dir, f"report.{ext}") for ext in ("json", "md", "html")}
    with open(paths["json"], "w") as fp:
        json.dump(doc, fp, indent=2)
    with open(paths["md"], "w") as fp:
        fp.write(render_markdown(doc))
    with open(paths["html"], "w", encoding="utf-8") as fp:
        fp.write(render_html(doc))
    return paths


def load_report(path: str) -> Dict[str, Any]:
    with open(path) as fp:
        doc = json.load(fp)
    if doc.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"{path}: schema {doc.get('schema')!r} is not {REPORT_SCHEMA!r}")
    return doc


def tool_label(doc: Dict[str, Any]) -> str:
    return ", ".join(" ".join(str(v) for v in t.values()) for t in doc.get("tools", [])) \
        or "(tool not named)"


def trust_text(doc: Dict[str, Any]) -> str:
    t = doc.get("l0_trusted")
    if t is None:
        return ("not established: the run held no L0 tests, or L0 runs did not "
                "complete (ERROR, MISSING or STALE). Fix those first")
    if t:
        skipped = sum(1 for r in doc["results"] if r["level"] == "L0" and r["verdict"] != PASS)
        return ("L0 protocol tier passed; every result is scored"
                + (f" ({skipped} L0 run(s) not PASS, none a FAIL)" if skipped else ""))
    return "L0 failed: results outside L0 are UNTRUSTED (§4.6)"


def render_markdown(doc: Dict[str, Any]) -> str:
    """The report as Markdown, from :meth:`Report.to_json`'s document."""
    b = doc.get("bundle") or {}
    results = doc["results"]
    lines = ["# pss-corpus results", "", f"* Tool: {tool_label(doc)}"]
    if b.get("created"):
        lines.append(f"* Bundle: exported {b.get('created')} from corpus "
                     f"{(b.get('corpus') or {}).get('commit') or '(unknown commit)'}")
    sel = b.get("selection") or {}
    lines.append(f"* Scope: PSS <= {sel.get('pss') or 'any'}; {doc.get('n_tests')} tests, "
                 f"{len(results)} runs; {len(b.get('excluded') or [])} excluded")
    lines.append(f"* Trust: {trust_text(doc)}")
    if len(doc.get("tools", [])) > 1:
        lines.append("* **Warning:** outcomes name more than one tool or target")
    lines += ["", "| Verdict | Runs |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in sorted(doc["counts"].items())]
    bad = [r for r in results if r["verdict"] != PASS]
    if bad:
        lines += ["", "## Not PASS", "", "| Run | Verdict | Reason |", "|---|---|---|"]
        for r in bad:
            reason = (r.get("reason") or "").replace("|", "\\|").replace("\n", " ")
            flag = " (untrusted)" if r.get("untrusted") else ""
            lines.append(f"| `{r['job']}` | {r['verdict']}{flag} | {reason[:300]} |")
    ex = b.get("excluded") or []
    if ex:
        lines += ["", "## Not exported", "", "| Test | Why |", "|---|---|"]
        lines += [f"| `{e['id']}` | {e['reason']} |" for e in ex]
    return "\n".join(lines) + "\n"
