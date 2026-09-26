"""Reports: what import and run write, and that the HTML is safe to open.

A report is rendered from other sites' output, so every tool-supplied string
must arrive escaped. It is mailed and opened offline, so it must fetch nothing.
"""

import json
import os
import re
import sys

from pss_corpus import (PASS, Selection, default_root, discover, export, import_results,
                        load_report, render_html, select, write_report)
from pss_corpus import driver
from pss_corpus.cli import _matcher, main as cli_main

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = list(discover(default_root()))
PERFECT = [sys.executable, os.path.join(HERE, "perfect_tool.py")]
HOSTILE = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def _bundle(tmp_path, *patterns, no_l0=True):
    sel = Selection(patterns=patterns, no_l0=no_l0)
    tests, excluded = select(TESTS, sel, _matcher(patterns))
    b = str(tmp_path / "b")
    export(tests, b, sel, excluded=excluded)
    driver.run_jobs(b, PERFECT, echo=lambda *_: None)
    return b


def _job_dir(b, job):
    return os.path.join(b, "results", *job.split("/"))


def test_import_writes_json_md_and_html(tmp_path):
    b = _bundle(tmp_path, "proc.func.return.001")
    paths = write_report(import_results(b, TESTS), str(tmp_path / "rep"))
    assert sorted(os.path.basename(p) for p in paths.values()) == \
        ["report.html", "report.json", "report.md"]
    doc = load_report(paths["json"])
    r = doc["results"][0]
    assert (r["verdict"], r["area"], r["level"]) == (PASS, "proc", "L1")
    assert r["title"] and r["lrm"] == ["20.7.5", "20.2"]
    assert "evidence" not in r, "a PASS carries no evidence"


def test_a_failure_carries_its_evidence(tmp_path):
    b = _bundle(tmp_path, "proc.func.return.001", "neg.ref.undeclared.001")
    log = os.path.join(_job_dir(b, "proc.func.return.001/seed-1"), "log.txt")
    text = open(log).read()
    open(log, "w").write(text.replace("c=-4", "c=-7"))
    rep = import_results(b, TESTS).to_json()
    bad = {r["test"]: r for r in rep["results"]}
    ev = bad["proc.func.return.001"]["evidence"]
    assert ev["trace"][-1] == "@@PSS-TRACE chk max a=9 b=9 c=-7", "decoration stripped"
    assert "neg.ref.undeclared.001" in bad and bad["neg.ref.undeclared.001"]["verdict"] == PASS


def test_tool_strings_are_escaped_and_nothing_is_fetched(tmp_path):
    b = _bundle(tmp_path, "proc.func.return.001", "neg.ref.undeclared.001")
    d = _job_dir(b, "proc.func.return.001/seed-1")
    oc = json.load(open(os.path.join(d, "outcome.json")))
    oc.update(outcome="infra_error", detail=HOSTILE, tool=HOSTILE)
    json.dump(oc, open(os.path.join(d, "outcome.json"), "w"))
    with open(os.path.join(_job_dir(b, "neg.ref.undeclared.001/seed-1"),
                           "diagnostics.json"), "w") as fp:
        json.dump({"schema": "pss-corpus/diagnostics/1.0", "diagnostics": [
            {"severity": "error", "file": HOSTILE, "line": 1, "message": HOSTILE}]}, fp)
    page = render_html(import_results(b, TESTS).to_json())
    assert HOSTILE not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert page.count("<script>") == 1, "only the report's own inline script"
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", page), "no external fetches"
    assert "@import" not in page and "url(" not in page


def test_the_page_names_every_verdict_and_run(tmp_path):
    b = _bundle(tmp_path, "proc.*")
    doc = import_results(b, TESTS).to_json()
    page = render_html(doc)
    for r in doc["results"]:
        assert f'<code>{r["test"]}</code>' in page
    for v, n in doc["counts"].items():
        assert f'data-v="{v}"' in page and f'<span class="n">{n}</span>' in page
    assert "Trust not established" in page, "no L0 in this bundle"


def test_report_rerenders_from_json(tmp_path, capsys):
    b = _bundle(tmp_path, "proc.func.return.001")
    assert cli_main(["import", b]) == 0
    src = os.path.join(b, "report", "report.json")
    out = str(tmp_path / "again.html")
    assert cli_main(["report", src, "--out", out]) == 0
    assert open(out).read().startswith("<!doctype html>")
    assert cli_main(["report", src, "--md", "--out", str(tmp_path / "a.md")]) == 0


def test_run_writes_the_same_report(tmp_path, capsys):
    out = str(tmp_path / "run")
    rc = cli_main(["run", "--adapter", " ".join(PERFECT), "--out", out, "proc.func.return.001"])
    assert rc == 0
    doc = load_report(os.path.join(out, "report", "report.json"))
    assert doc["source"] == "run" and doc["counts"] == {PASS: 1}
    assert doc["tools"] == [{"tool": "perfect_tool", "tool_version": "1", "target": "synth"}]
    assert os.path.isfile(os.path.join(out, "report", "report.html"))
