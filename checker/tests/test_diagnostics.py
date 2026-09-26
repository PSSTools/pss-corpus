"""Negative tests: a rejection passes only with an error at the right place.

Every negative model is linted (its expected locations exist in its sources),
a synthesized correct rejection must PASS, and each way of being wrong gets
its own verdict: wrong place or no rejection is FAIL, a rejection that names no
location is UNLOCATED, and malformed adapter output is ERROR.
"""

import json

import pytest

from pss_corpus import (ERROR, FAIL, PASS, UNLOCATED, check_run, default_root,
                        discover)

from synth import synth_diagnostics

TESTS = list(discover(default_root()))
NEG = [t for t in TESTS if t.expect == "compile_error"]


def test_the_corpus_has_negative_tests():
    assert len(NEG) >= 5
    assert any(t.level == "L0" for t in NEG), "L0 must check the diagnostics protocol"


@pytest.mark.parametrize("t", NEG, ids=lambda t: t.id)
def test_every_negative_test_says_where(t):
    assert t.expect_diagnostics, "a compile_error test must state where the error is"
    for d in t.expect_diagnostics:
        assert d["file"] in t.source_names, d
        assert ("line" in d) != ("lines" in d), f"exactly one of line/lines: {d}"
        n = len(open(t.sources[t.source_names.index(d["file"])]).read().splitlines())
        lo, hi = (d["line"], d["line"]) if "line" in d else d["lines"]
        assert 1 <= lo <= hi <= n, f"{d} is outside {d['file']} ({n} lines)"


def _run(tmp_path, t, outcome="compile_error", diags=None, name="r", schema=None):
    d = tmp_path / name
    d.mkdir()
    (d / "log.txt").write_text("")
    (d / "outcome.json").write_text(json.dumps({"outcome": outcome}))
    if diags is not None:
        (d / "diagnostics.json").write_text(json.dumps(
            {"schema": schema or "pss-corpus/diagnostics/1.0", "diagnostics": diags}))
    return check_run(t, str(d))


def _moved(diags, by):
    return [dict(d, line=d["line"] + by) for d in diags]


@pytest.mark.parametrize("t", NEG, ids=lambda t: t.id)
def test_a_located_rejection_passes(tmp_path, t):
    for prefix in ("", "/abs/path/to/", "tests/" + t.id + "/"):
        v = _run(tmp_path, t, diags=synth_diagnostics(t, prefix), name="r" + str(len(prefix)))
        assert v.verdict == PASS, (prefix, v.reason)


@pytest.mark.parametrize("t", NEG, ids=lambda t: t.id)
def test_each_wrong_rejection_is_caught(tmp_path, t):
    good = synth_diagnostics(t)
    far = 1000
    cases = [
        ("accepted", dict(outcome="ok"), FAIL),
        ("wrong outcome", dict(outcome="runtime_error", diags=good), FAIL),
        ("wrong line", dict(diags=_moved(good, far)), FAIL),
        ("wrong file", dict(diags=[dict(d, file="other.pss") for d in good]), FAIL),
        ("a file that merely ends the same", dict(diags=[dict(d, file="xtest.pss") for d in good]), FAIL),
        ("no diagnostics.json", dict(), UNLOCATED),
        ("only warnings", dict(diags=[dict(d, severity="warning") for d in good]), UNLOCATED),
        ("errors without a line", dict(diags=[{"severity": "error", "message": "x"}]), UNLOCATED),
        ("unknown schema", dict(diags=good, schema="acme/diag/9"), ERROR),
    ]
    for n, (what, kw, want) in enumerate(cases):
        v = _run(tmp_path, t, name=f"m{n}", **kw)
        assert v.verdict == want, f"{what}: {v.verdict} ({v.reason})"


def test_extra_cascade_errors_are_allowed(tmp_path):
    t = NEG[0]
    diags = _moved(synth_diagnostics(t), 1000) + synth_diagnostics(t)
    assert _run(tmp_path, t, diags=diags).verdict == PASS


def test_a_positive_test_rejected_names_the_first_error(tmp_path):
    t = next(t for t in TESTS if t.expect == "ok")
    v = _run(tmp_path, t, diags=[{"severity": "error", "file": "test.pss", "line": 3,
                                  "message": "boom"}])
    assert v.verdict == FAIL
    assert "test.pss:3: boom" in v.reason


def test_an_unknown_outcome_schema_is_an_error(tmp_path):
    t = TESTS[0]
    d = tmp_path / "r"
    d.mkdir()
    (d / "log.txt").write_text("")
    (d / "outcome.json").write_text(json.dumps({"schema": "acme/9", "outcome": "ok"}))
    v = check_run(t, str(d))
    assert v.verdict == ERROR and "schema" in v.reason
