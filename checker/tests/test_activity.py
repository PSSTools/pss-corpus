"""Activity constraints are judged on the occurrences they bind to (P1.7).

A constraint over sub-action handles (`a.val < b.val`), an inline `with` and an
activity `constraint` hold for the occurrences their handles name when they
hold at all (13.4.8): a handle is bound when it is traversed and reset on entry
to a block or loop iteration that traverses it again. Each committed act.*
model gets a legal trace that must PASS and mutants that must FAIL, with the
unsat core naming the constraint broken -- a model whose checker cannot tell a
broken constraint from a kept one is a defective model (§6.5).
"""

import copy
import json

import pytest

from pss_corpus import ERROR, FAIL, PASS, check_run, default_root, discover

pytest.importorskip("z3")

TESTS = {t.id: t for t in discover(default_root())}


def _run(tmp_path, t, lines, name="run"):
    d = tmp_path / name
    d.mkdir()
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE {ln}\n" for ln in lines))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(d))


def _vals(tag, key, *vals):
    return [f"act {tag} {key}={v}" for v in vals]


A = "pss_top::A"

#: test id -> (legal trace, [(mutant, text the FAIL reason must contain)])
CASES = {
    "act.solve.order.001": (
        _vals(A, "val", 2, 4, 7), [
            (_vals(A, "val", 2, 2, 7), "a.val < b.val"),
            (_vals(A, "val", 2, 8, 7), "b.val < c.val"),
        ]),
    "act.lookahead.001": (
        _vals(A, "val", 13, 14, 15), [
            (_vals(A, "val", 14, 15, 15), "b.val < c.val"),
        ]),
    # The LRM's own breakout: the second iteration's b.x (9) need not be
    # less than the first's c.x (6), because b and c are reset on entry to it.
    "act.solve.reset.001": (
        _vals(A, "x", 3, 5, 6, 9, 13), [
            (_vals(A, "x", 3, 5, 6, 3, 13), "a.x < b.x"),
            (_vals(A, "x", 3, 5, 6, 9, 9), "b.x < c.x"),
            (_vals(A, "x", 3, 5, 5, 9, 13), "b.x < c.x"),
        ]),
    "act.lookahead.sub.001": (
        _vals(A, "val", 4, 4, 9, 12), [
            (_vals(A, "val", 5, 4, 9, 12), "s1.a.val == v.val"),
            (_vals(A, "val", 9, 9, 9, 12), "a.val < b.val"),
        ]),
    "act.with.001": (
        ["act pss_top::A f=3 g=7", "obs pss_top::ObsB f=7 h=4"], [
            (["act pss_top::A f=4 g=7", "obs pss_top::ObsB f=7 h=4"], "f < h"),
            (["act pss_top::A f=3 g=6", "obs pss_top::ObsB f=7 h=4"], "g == this.f"),
        ]),
    "act.with.order.001": (
        _vals(A, "f", 9, 12, 12, 9), [
            (_vals(A, "f", 7, 12, 12, 7), "a1.f in [8..15]"),
            (_vals(A, "f", 9, 7, 7, 9), "f in [8..15]"),
            (_vals(A, "f", 9, 12, 11, 9), "f == a2.f"),
            (_vals(A, "f", 9, 12, 12, 10), "a1.f == a4.f"),
        ]),
    "act.constraint.001": (
        _vals(A, "val", 3, 4), [
            (_vals(A, "val", 4, 4), "b.val > a.val"),
        ]),
    "act.comp.random.001": (
        ["act my_comp_c::A_a comp.pct_id=3"], [
            (["act my_comp_c::A_a comp.pct_id=4"], "comp in {comp1, comp2, comp3}"),
        ]),
    "act.comp.steer.001": (
        ["act subc::A comp.pct_id=1 f=2 g=5", "obs pss_top::ObsB f=5 h=3"], [
            (["act subc::A comp.pct_id=2 f=2 g=5", "obs pss_top::ObsB f=5 h=3"],
             "comp == this.comp.sub1"),
            (["act subc::A comp.pct_id=1 f=3 g=5", "obs pss_top::ObsB f=5 h=3"], "f < h"),
        ]),
    # q prints nothing, but its w must fit between a.v and b.v.
    "act.traverse.bodiless.001": (
        _vals(A, "v", 3, 5), [
            (_vals(A, "v", 3, 4), "q.w"),
        ]),
    "act.compound.pre_post.001": (
        ["act pss_top::A v=2", "obs pss_top::ObsT sig=18 n=5 m=6"], [
            (["act pss_top::A v=2", "obs pss_top::ObsT sig=33 n=5 m=6"], "sig == 0x12"),
            (["act pss_top::A v=2", "obs pss_top::ObsT sig=18 n=5 m=5"], "m == n + 1"),
            (["act pss_top::A v=2", "obs pss_top::ObsT sig=18 n=3 m=4"], "n > 3"),
            (["act pss_top::A v=5", "obs pss_top::ObsT sig=18 n=5 m=6"], "v < this.n"),
        ]),
}


def test_every_act_model_with_constraints_has_cases():
    """A model that states a constraint over handles is covered here."""
    for t in TESTS.values():
        if not t.id.startswith("act."):
            continue
        constrained = any(
            ty.get("constraints") or '"with"' in json.dumps(ty.get("activity", {}))
            or '"constraint"' in json.dumps(ty.get("activity", {}))
            for ty in t.model["types"].values())
        assert not constrained or t.id in CASES, t.id


@pytest.mark.parametrize("tid", sorted(CASES))
def test_the_legal_trace_passes(tmp_path, tid):
    v = _run(tmp_path, TESTS[tid], CASES[tid][0])
    assert v.verdict == PASS, v.reason


@pytest.mark.parametrize("tid", sorted(CASES))
def test_each_broken_constraint_fails_and_is_named(tmp_path, tid):
    for n, (lines, named) in enumerate(CASES[tid][1]):
        v = _run(tmp_path, TESTS[tid], lines, name=f"m{n}")
        assert v.verdict == FAIL, f"not detected: {lines}"
        assert named in v.reason, v.reason


def test_an_observer_prints_obs_not_act(tmp_path):
    t = TESTS["act.with.001"]
    v = _run(tmp_path, t, ["act pss_top::A f=3 g=7", "act pss_top::ObsB f=7 h=4"])
    assert v.verdict == FAIL and "expected obs 'pss_top::ObsB'" in v.reason


def test_an_untraced_action_consumes_no_record(tmp_path):
    t = TESTS["act.traverse.bodiless.001"]
    v = _run(tmp_path, t, ["act pss_top::A v=3", "act pss_top::Q w=4", "act pss_top::A v=5"])
    assert v.verdict == FAIL


def test_without_the_reset_ex180_would_be_rejected(tmp_path):
    """The same values with the loop unrolled into one block: b is traversed
    again with c still bound to the first iteration's, so `b.x < c.x` binds
    9 against 6. The reset is what makes the legal trace legal."""
    t = copy.deepcopy(TESTS["act.solve.reset.001"])
    t.model["types"]["pss_top::my_action"]["activity"] = {"seq": [
        {"do": A, "label": lb} for lb in ("a", "b", "c", "b", "c")]}
    v = _run(tmp_path, t, _vals(A, "x", 3, 5, 6, 9, 13))
    assert v.verdict == FAIL and "b.x < c.x" in v.reason


def test_a_name_that_is_nothing_in_scope_is_a_model_error(tmp_path):
    t = copy.deepcopy(TESTS["act.solve.order.001"])
    t.model["types"]["pss_top::my_action"]["constraints"].append(
        {"pss": "d.val < 3", "smt": "(bvult |d.val| #x3)"})
    v = _run(tmp_path, t, _vals(A, "val", 2, 4, 7))
    assert v.verdict == ERROR and "model error" in v.reason
