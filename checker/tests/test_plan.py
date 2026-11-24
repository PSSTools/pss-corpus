"""Plan adjudication (``check --plan``): a tool's plan.json is judged with no
execution (PLAN-FAIL: the generator decided wrongly), and a run beside it is
checked to have carried the plan out (REALISE-FAIL: the runtime executed a
correct plan wrongly)."""

import copy
import json
import os

import pytest

from pss_corpus import FAIL, PASS, load
from pss_corpus import cli, plan
from pss_corpus.model import Test

from test_cheats import _test

CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "compliance")


def _occ(i, site, path, typ, fields, start, end):
    return {"id": i, "site": site, "path": path, "stim": f"s{i}", "type": typ,
            "comp": 0, "fields": fields, "start": start, "end": end, "completed": True}


def _plan(occs, flow=(), resources=(), order=()):
    return {"format": "pss-plan", "version": "1.0", "seed": 1, "occurrences": list(occs),
            "flow": list(flow), "resources": list(resources), "order": [list(p) for p in order],
            "control": []}


SEQ_PC = {"seq": [{"do": "P"}, {"do": "C"}]}
PAR_LL = {"par": [{"do": "L"}, {"do": "L"}]}


def _pc(pv=3, cv=3):
    """P then C over one buffer, as a generator plans it."""
    return _plan([_occ(0, None, "", "T", {}, 1, 6),
                  _occ(1, 0, "#0", "P", {"o.v": pv}, 2, 3),
                  _occ(2, 1, "#1", "C", {"k": 0, "i.v": cv}, 4, 5)],
                 flow=[{"id": 0, "kind": "buffer", "pool": None, "producer": 1,
                        "consumers": [2], "fields": {"v": pv}}],
                 order=[(1, 2)])


def _ll(i0=0, i1=1, ordered=False):
    """Two L in parallel; with *ordered*, the plan runs the first one first."""
    t = (2, 3, 4, 5) if ordered else (2, 4, 3, 5)
    return _plan([_occ(0, None, "", "T", {}, 1, 6),
                  _occ(1, 0, "#0", "L", {"r.instance_id": i0}, t[0], t[1]),
                  _occ(2, 1, "#1", "L", {"r.instance_id": i1}, t[2], t[3])],
                 resources=[{"pool": "rp@0", "instance": i, "claims": [{"occ": o, "lock": True}]}
                            for o, i in ((1, i0), (2, i1))],
                 order=[(1, 2)] if ordered else [])


def _run_dir(tmp_path, lines, name="run"):
    d = tmp_path / name
    d.mkdir()
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE act {l}\n" for l in lines))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return str(d)


def _check(tmp_path, t, doc, lines=None):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(doc))
    run = _run_dir(tmp_path, lines) if lines is not None else None
    return plan.check(t, run, str(p))


# --------------------------------------------------------------------------- #
# The plan alone
# --------------------------------------------------------------------------- #

def test_legal_plans_pass(tmp_path):
    for t, doc in ((_test(SEQ_PC), _pc()), (_test(PAR_LL), _ll())):
        v = _check(tmp_path, t, doc)
        assert (v.verdict, v.plan) == (PASS, PASS), v.reason


def _swap_pc(doc):
    o = doc["occurrences"]
    o[1]["start"], o[1]["end"], o[2]["start"], o[2]["end"] = 4, 5, 2, 3
    doc["order"] = [[2, 1]]


def _rebind(doc):
    doc["occurrences"][2]["fields"]["i.v"] = 4


def _misreport_flow(doc):
    doc["flow"][0]["fields"]["v"] = 9


def _bad_order(doc):
    doc["order"] = [[2, 1]]


def _foreign_type(doc):
    doc["occurrences"][2]["type"] = "pss_top::Nope"


def _wrong_root(doc):
    doc["occurrences"][0]["type"] = "C"


def _missing_occ(doc):
    doc["flow"][0]["consumers"] = [7]


# (what the generator got wrong, model, plan, mutation, words in the reason)
PLAN_FAILS = [
    ("consumer planned before producer", SEQ_PC, _pc, _swap_pc, "starts before producer"),
    ("bound value differs", SEQ_PC, _pc, _rebind, "no buffer input"),
    ("flow object values not the producer's", SEQ_PC, _pc, _misreport_flow, "no buffer output"),
    ("order contradicts the times", SEQ_PC, _pc, _bad_order, "overlap or cross"),
    ("type not in the model", SEQ_PC, _pc, _foreign_type, "not in the model"),
    ("wrong root", SEQ_PC, _pc, _wrong_root, "root"),
    ("dangling occurrence id", SEQ_PC, _pc, _missing_occ, "not in the plan"),
    ("two locks of one instance at once", PAR_LL, lambda: _ll(0, 0), None, "instance"),
    ("claimant reports another instance", PAR_LL, _ll,
     lambda d: d["occurrences"][1]["fields"].update({"r.instance_id": 1}), "another instance_id"),
    ("an occurrence the activity has no room for", SEQ_PC, _pc,
     lambda d: d["occurrences"].append(_occ(3, 2, "#2", "C", {"k": 0, "i.v": 3}, 7, 8)),
     "unexpected occurrence"),
]


@pytest.mark.parametrize("name,act,make,mutate,why", PLAN_FAILS, ids=[c[0] for c in PLAN_FAILS])
def test_wrong_plan_is_plan_fail(tmp_path, name, act, make, mutate, why):
    doc = make()
    if mutate:
        mutate(doc)
    v = _check(tmp_path, _test(act), doc)
    assert (v.verdict, v.plan) == (FAIL, plan.PLAN_FAIL), v.reason
    assert v.reason.startswith("PLAN-FAIL: ") and why in v.reason, v.reason


def test_plan_values_are_solved_against_constraints(tmp_path):
    # the corpus's bound buffer: t constrains p.o.v == c.i.v over flat leaves
    t = load(os.path.join(CORPUS, "flow", "buffer_bind"))
    doc = _pc()
    for o, typ in zip(doc["occurrences"], ("pss_top::t", "pss_top::P", "pss_top::C")):
        o["type"] = typ
        o["fields"].pop("k", None)
        o["path"] = {"pss_top::P": "p", "pss_top::C": "c"}.get(typ, "")
    assert plan.check_plan(t, doc).verdict == PASS
    doc["occurrences"][2]["fields"]["i.v"] = 4
    doc["flow"] = []                     # so only the model's constraint can tell
    v = plan.check_plan(t, doc)
    assert v.plan == plan.PLAN_FAIL and "violate" in v.reason, v.reason


# --------------------------------------------------------------------------- #
# The run beside the plan
# --------------------------------------------------------------------------- #

def test_run_that_follows_the_plan_passes(tmp_path):
    v = _check(tmp_path, _test(SEQ_PC), _pc(), ["P o.v=3", "C k=0 i.v=3"])
    assert (v.verdict, v.plan) == (PASS, PASS), v.reason


def test_run_of_unordered_branches_in_either_order_passes(tmp_path):
    v = _check(tmp_path, _test(PAR_LL), _ll(), ["L r.instance_id=1", "L r.instance_id=0"])
    assert (v.verdict, v.plan) == (PASS, PASS), v.reason


# (what the runtime got wrong, model, plan, legal-or-not run)
REALISE_FAILS = [
    ("other legal values", SEQ_PC, _pc, ["P o.v=5", "C k=0 i.v=5"], "no occurrence of the plan"),
    ("illegal run", SEQ_PC, _pc, ["P o.v=3", "C k=0 i.v=4"], "the run is not"),
    ("an occurrence left out", PAR_LL, _ll, ["L r.instance_id=0"], "the run is not"),
    ("plan's order not kept", PAR_LL, lambda: _ll(ordered=True),
     ["L r.instance_id=1", "L r.instance_id=0"], "may run there"),
]


@pytest.mark.parametrize("name,act,make,lines,why", REALISE_FAILS,
                         ids=[c[0] for c in REALISE_FAILS])
def test_run_that_strays_is_realise_fail(tmp_path, name, act, make, lines, why):
    v = _check(tmp_path, _test(act), make(), lines)
    assert (v.verdict, v.plan) == (FAIL, plan.REALISE_FAIL), v.reason
    assert v.reason.startswith("REALISE-FAIL: ") and why in v.reason, v.reason


def test_wrong_plan_is_reported_before_the_run(tmp_path):
    doc = _pc()
    _rebind(doc)
    v = _check(tmp_path, _test(SEQ_PC), doc, ["P o.v=3", "C k=0 i.v=3"])
    assert v.plan == plan.PLAN_FAIL, v.reason


# --------------------------------------------------------------------------- #
# pssc's plan, and the command line
# --------------------------------------------------------------------------- #

# `pssc test --plan-out` (seed 3) for: buffer buf_s { rand bit[8] v; };
# resource ch_r; pool [2] ch_r; P { output buf_s o; lock ch_r c; o.v < 50 };
# C { rand bit[8] k; input buf_s i; }; t_flow { P p; C c; activity { p; c; } }
PSSC_PLAN = {
    "format": "pss-plan", "version": "1.0", "seed": 3,
    "occurrences": [
        {"id": 0, "site": None, "path": "", "stim": "t_flow#0", "type": "p_f::t_flow", "comp": 0,
         "fields": {}, "start": 1, "end": 6, "completed": True},
        {"id": 1, "site": 0, "path": "p", "stim": "t_flow#0.p#0", "type": "p_f::P", "comp": 0,
         "fields": {"o.v": 34, "c.instance_id": 0}, "start": 2, "end": 3, "completed": True},
        {"id": 2, "site": 1, "path": "c", "stim": "t_flow#0.c#0", "type": "p_f::C", "comp": 0,
         "fields": {"k": 204, "i.v": 34}, "start": 4, "end": 5, "completed": True}],
    "flow": [{"id": 0, "kind": "buffer", "pool": "buf_p@0", "producer": 1, "consumers": [2],
              "fields": {"v": 34}}],
    "resources": [{"pool": "ch_p@0", "instance": 0, "claims": [{"occ": 1, "lock": True}]}],
    "order": [[1, 2]], "control": []}


def _pssc_model():
    t = _test(SEQ_PC)
    m = copy.deepcopy(t.model)
    m["types"]["P"]["refs"]["c"] = {"dir": "lock", "type": "R"}
    m["types"]["P"]["constraints"] = [{"pss": "o.v < 50", "smt": "(bvult |o.v| #x32)"}]
    m["types"]["t_flow"] = m["types"].pop("T")
    m["run"]["root"] = "t_flow"
    return Test(path="/nonexistent", model=m)


def test_pssc_plan_is_judged(tmp_path):
    v = _check(tmp_path, _pssc_model(), PSSC_PLAN,
               ["P o.v=34 c.instance_id=0", "C k=204 i.v=34"])
    assert (v.verdict, v.plan) == (PASS, PASS), v.reason


def test_cli_check_plan_without_a_run(tmp_path, capsys):
    p = tmp_path / "plan.json"
    doc = _pc()
    for o, typ in zip(doc["occurrences"], ("pss_top::t", "pss_top::P", "pss_top::C")):
        o["type"] = typ
        o["fields"].pop("k", None)
    p.write_text(json.dumps(doc))
    test_dir = os.path.join(CORPUS, "flow", "buffer_bind")
    assert cli.main(["check", test_dir, "--plan", str(p)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["verdict"], out["plan"]) == ("PASS", "PASS")
    _rebind(doc)
    p.write_text(json.dumps(doc))
    assert cli.main(["check", test_dir, "--plan", str(p)]) == 1
    assert json.loads(capsys.readouterr().out)["plan"] == "PLAN-FAIL"
