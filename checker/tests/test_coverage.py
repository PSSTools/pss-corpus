"""Functional coverage (CF-cov): a run passes only with the expected bin hits.

Every coverage model is linted (each expectation names a covergroup and one
of samples / coverpoint+bin / cross+bins), a synthesized export that meets it
must PASS, and each way of being wrong gets its own verdict: a wrong count, a
missing covergroup or no export at all is FAIL, a bad schema is ERROR.
"""

import copy
import json

import pytest

from pss_corpus import ERROR, FAIL, PASS, check_run, default_root, discover

from synth import synth, synth_coverage

TESTS = list(discover(default_root()))
COV = [t for t in TESTS if t.expect_coverage]


def test_the_corpus_has_coverage_tests():
    assert len(COV) >= 3
    assert any(any("cross" in w for w in t.expect_coverage) for t in COV)
    assert any(any("samples" in w for w in t.expect_coverage) for t in COV)


@pytest.mark.parametrize("t", COV, ids=lambda t: t.id)
def test_every_coverage_expectation_is_well_formed(t):
    assert t.expect == "ok"
    for w in t.expect_coverage:
        assert isinstance(w.get("covergroup"), str), w
        kinds = [k for k in ("samples", "coverpoint", "cross") if k in w]
        assert len(kinds) == 1, f"exactly one of samples/coverpoint/cross: {w}"
        if "coverpoint" in w:
            assert isinstance(w["bin"], str) and "hits" in w, w
        if "cross" in w:
            assert len(w["bins"]) >= 2 and "hits" in w, w


def _run(tmp_path, t, cov, name="r", schema=None):
    d = tmp_path / name
    d.mkdir()
    (d / "log.txt").write_text("\n".join(synth(t)) + "\n")
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    if cov is not None:
        if schema:
            cov = dict(cov, schema=schema)
        (d / "coverage.json").write_text(json.dumps(cov))
    return check_run(t, str(d))


@pytest.mark.parametrize("t", COV, ids=lambda t: t.id)
def test_a_matching_export_passes(tmp_path, t):
    v = _run(tmp_path, t, synth_coverage(t))
    assert v.verdict == PASS, v.reason


def _instances(cov):
    """The same counts, split over two instances of each covergroup."""
    out = copy.deepcopy(cov)
    out["covergroups"] = []
    for cg in cov["covergroups"]:
        a = copy.deepcopy(cg)
        b = {"name": cg["name"], "instance": "second", "samples": 0, "coverpoints": {}, "crosses": {}}
        for cp, bins in cg["coverpoints"].items():
            for bn, n in bins.items():
                a["coverpoints"][cp][bn] = n // 2
                b["coverpoints"].setdefault(cp, {})[bn] = n - n // 2
        out["covergroups"] += [a, b]
    return out


@pytest.mark.parametrize("t", COV, ids=lambda t: t.id)
def test_counts_add_up_over_instances(tmp_path, t):
    v = _run(tmp_path, t, _instances(synth_coverage(t)))
    assert v.verdict == PASS, v.reason


def _bumped(cov, which):
    out = copy.deepcopy(cov)
    cg = out["covergroups"][0]
    if which == "samples":
        cg["samples"] += 1
    elif which == "bin":
        cp = next(iter(cg["coverpoints"].values()))
        bn = next(iter(cp))
        cp[bn] += 1
    else:
        cg["crosses"][next(iter(cg["crosses"]))][0]["hits"] += 1
    return out


@pytest.mark.parametrize("t", COV, ids=lambda t: t.id)
def test_each_wrong_export_is_caught(tmp_path, t):
    good = synth_coverage(t)
    renamed = copy.deepcopy(good)
    for cg in renamed["covergroups"]:
        cg["name"] += "_other"
    cases = [
        ("no coverage.json", None, None, FAIL),
        ("covergroup missing", renamed, None, FAIL),
        ("unknown schema", good, "acme/cov/9", ERROR),
    ]
    first = good["covergroups"][0]
    for which in ("samples", "bin", "cross"):
        if any(w["covergroup"] == first["name"] and
               {"samples": "samples", "bin": "coverpoint", "cross": "cross"}[which] in w
               for w in t.expect_coverage):
            cases.append((f"wrong {which} count", _bumped(good, which), None, FAIL))
    for n, (what, cov, schema, want) in enumerate(cases):
        v = _run(tmp_path, t, cov, name=f"m{n}", schema=schema)
        assert v.verdict == want, f"{what}: {v.verdict} ({v.reason})"


def test_a_hit_range_accepts_counts_inside_it(tmp_path):
    t = COV[0]
    t2 = copy.copy(t)
    t2.model = copy.deepcopy(t.model)
    w = next(w for w in t2.model["expect"]["coverage"] if "coverpoint" in w)
    good = synth_coverage(t)
    w["hits"] = [w["hits"], w["hits"] + 2]
    cp = next(c for c in good["covergroups"] if c["name"] == w["covergroup"])["coverpoints"][w["coverpoint"]]
    cp[w["bin"]] += 2
    assert _run(tmp_path, t2, good, name="in").verdict == PASS
    cp[w["bin"]] += 1
    assert _run(tmp_path, t2, good, name="out").verdict == FAIL
