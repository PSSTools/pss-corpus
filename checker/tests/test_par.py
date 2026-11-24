"""Stage 2 with open order and choice (P2): par, schedule, select and the
joins. A trace passes when some legal way of matching it has SAT data, and
fails when none has."""

import json

import pytest

from pss_corpus import ERROR, FAIL, PASS, check_run
from pss_corpus.model import Test

ATOM = {"kind": "action", "atomic": True, "fields": {"x": "u8"}}


def _test(activity, constraints=()):
    types = {n: dict(ATOM) for n in "ABCP"}
    types["T"] = {"kind": "action", "atomic": False, "fields": {},
                  "constraints": [{"pss": c, "smt": s} for c, s in constraints],
                  "activity": activity}
    return Test(path="/nonexistent", model={
        "schema": "pss-corpus/model/1.0", "id": "t.par", "sources": [],
        "run": {"root": "T"}, "types": types})


def _run(tmp_path, t, recs):
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE act {r}\n" for r in recs))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(d))


def _do(t, label=None):
    return {"do": t, "label": label} if label else {"do": t}


LT = ("a.x < b.x", "(bvult |a.x| |b.x|)")
PAR_AB = {"par": [_do("A", "a"), _do("B", "b")]}


@pytest.mark.parametrize("recs", [["A x=1", "B x=2"], ["B x=2", "A x=1"]])
def test_par_branches_pass_in_either_order(tmp_path, recs):
    v = _run(tmp_path, _test(PAR_AB, [LT]), recs)
    assert v.verdict == PASS, v.reason
    assert sorted(v.occurrences) == ["A", "B"]


@pytest.mark.parametrize("recs,why", [
    (["B x=2"], "trace ended after 1"),
    (["A x=1", "B x=2", "A x=1"], "unexpected occurrence"),
    (["A x=1", "C x=2"], "expected act 'B'"),
    (["B x=1", "A x=2"], "a.x < b.x"),
])
def test_par_with_a_missing_extra_or_wrong_branch_fails(tmp_path, recs, why):
    v = _run(tmp_path, _test(PAR_AB, [LT]), recs)
    assert v.verdict == FAIL
    assert why in v.reason


def test_schedule_is_any_order(tmp_path):
    act = {"schedule": [_do("A", "a"), _do("B", "b")]}
    assert _run(tmp_path, _test(act, [LT]), ["B x=9", "A x=1"]).verdict == PASS


def test_same_type_branches_try_both_assignments(tmp_path):
    """par {a: A; b: A} with a.x < b.x: the record that came first may be b."""
    act = {"par": [_do("A", "a"), _do("A", "b")]}
    t = _test(act, [LT])
    assert _run(tmp_path, t, ["A x=5", "A x=3"]).verdict == PASS
    v = _run(tmp_path, t, ["A x=4", "A x=4"])
    assert v.verdict == FAIL and "a.x < b.x" in v.reason


def test_branches_interleave_but_keep_their_own_order(tmp_path):
    act = {"par": [{"seq": [_do("A"), _do("B")]}, _do("C")]}
    t = _test(act)
    for recs in (["A x=0", "C x=0", "B x=0"], ["C x=0", "A x=0", "B x=0"]):
        assert _run(tmp_path, t, recs).verdict == PASS
    v = _run(tmp_path, t, ["B x=0", "A x=0", "C x=0"])
    assert v.verdict == FAIL and "expected one of act 'A', act 'C'" in v.reason


def test_select_takes_exactly_one_branch(tmp_path):
    act = {"select": [{"body": _do("A")}, {"body": _do("B")}]}
    t = _test(act)
    assert _run(tmp_path, t, ["A x=0"]).verdict == PASS
    assert _run(tmp_path, t, ["B x=0"]).verdict == PASS
    assert _run(tmp_path, t, ["A x=0", "B x=0"]).verdict == FAIL
    assert _run(tmp_path, t, []).verdict == FAIL


def test_a_select_branch_may_be_empty(tmp_path):
    act = {"select": [{"body": _do("A")}, {"body": {"seq": []}}]}
    assert _run(tmp_path, _test(act), []).verdict == PASS


def test_select_guard_must_hold_on_the_branch_taken(tmp_path):
    act = {"seq": [_do("P", "p"), {"select": [
        {"guard": {"pss": "p.x > 5", "smt": "(bvugt |p.x| #x05)"}, "body": _do("A")},
        {"guard": {"pss": "p.x <= 5", "smt": "(bvule |p.x| #x05)"}, "body": _do("B")}]}]}
    t = _test(act)
    assert _run(tmp_path, t, ["P x=7", "A x=0"]).verdict == PASS
    assert _run(tmp_path, t, ["P x=3", "B x=0"]).verdict == PASS
    v = _run(tmp_path, t, ["P x=7", "B x=0"])
    assert v.verdict == FAIL and "p.x <= 5" in v.reason


def test_select_in_a_repeat_chooses_per_iteration(tmp_path):
    act = {"repeat": {"count": 2},
           "body": {"select": [{"body": _do("A")}, {"body": _do("B")}]}}
    assert _run(tmp_path, _test(act), ["B x=0", "A x=0"]).verdict == PASS


def _joined(join):
    return {"seq": [{"par": [_do("A", "l1"), _do("B", "l2")], "join": join}, _do("C")]}


@pytest.mark.parametrize("join,legal,illegal", [
    ("all", [["A", "B", "C"], ["B", "A", "C"]], [["A", "C", "B"], ["C", "A", "B"]]),
    ("none", [["C", "A", "B"], ["A", "C", "B"], ["B", "A", "C"]], [["A", "B"]]),
    ("branch:l1", [["A", "C", "B"], ["B", "A", "C"]], [["B", "C", "A"], ["C", "A", "B"]]),
    ("first:1", [["A", "C", "B"], ["B", "C", "A"]], [["C", "A", "B"]]),
    ("select:2", [["A", "B", "C"]], [["A", "C", "B"]]),
])
def test_join_decides_what_the_next_statement_waits_for(tmp_path, join, legal, illegal):
    t = _test(_joined(join))
    for order in legal:
        v = _run(tmp_path, t, [f"{n} x=0" for n in order])
        assert v.verdict == PASS, (order, v.reason)
    for order in illegal:
        assert _run(tmp_path, t, [f"{n} x=0" for n in order]).verdict == FAIL, order


def test_join_branch_must_name_a_branch(tmp_path):
    v = _run(tmp_path, _test(_joined("branch:nope")), ["A x=0", "B x=0", "C x=0"])
    assert v.verdict == ERROR and "join_branch" in v.reason


def test_an_open_activity_over_the_record_budget_is_an_error(tmp_path):
    act = {"repeat": {"count": 40}, "body": {"par": [_do("A"), _do("B")]}}
    v = _run(tmp_path, _test(act), ["A x=0", "B x=0"] * 40)
    assert v.verdict == ERROR and "at most 64" in v.reason


def test_a_flat_activity_has_no_record_budget(tmp_path):
    act = {"repeat": {"count": 80}, "body": _do("A")}
    assert _run(tmp_path, _test(act), ["A x=0"] * 80).verdict == PASS
