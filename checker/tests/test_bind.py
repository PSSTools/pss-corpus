"""Rule C (§6.5): flow-object refs. Every input is fed by a legal producer
whose output values it read: a buffer by an earlier, non-parallel output; a
stream by exactly one parallel output; a state by the pool's latest writer
(or its initial state). An explicit ``bind`` pins the producer."""

import json

import pytest

from pss_corpus import FAIL, PASS, check_run
from pss_corpus.model import Test


def _ref(d, typ):
    return {"dir": d, "type": typ}


def _test(activity, kind="buffer", extra_types=None, obj_constraints=()):
    types = {
        "obj": {"kind": kind, "fields": {"v": "u8"},
                "constraints": [{"pss": c, "smt": s} for c, s in obj_constraints]},
        "P": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"o": _ref("output", "obj")}},
        "C": {"kind": "action", "atomic": True, "fields": {"k": "u8"},
              "refs": {"i": _ref("input", "obj")}},
        "N": {"kind": "action", "atomic": True, "fields": {"x": "u8"}},
        "T": {"kind": "action", "atomic": False, "fields": {}, "activity": activity},
    }
    types.update(extra_types or {})
    return Test(path="/nonexistent", model={
        "schema": "pss-corpus/model/1.0", "id": "t.bind", "sources": [],
        "run": {"root": "T"}, "types": types})


def _run(tmp_path, t, recs):
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE act {r}\n" for r in recs))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(d))


def _do(t, label=None):
    return {"do": t, "label": label} if label else {"do": t}


SEQ_PC = {"seq": [_do("P", "p"), _do("C", "c")]}


def test_buffer_consumer_reads_what_producer_wrote(tmp_path):
    v = _run(tmp_path, _test(SEQ_PC), ["P o.v=5", "C k=0 i.v=5"])
    assert v.verdict == PASS, v.reason


def test_buffer_consumer_reading_other_value_fails(tmp_path):
    v = _run(tmp_path, _test(SEQ_PC), ["P o.v=5", "C k=0 i.v=6"])
    assert v.verdict == FAIL
    assert "C.i (occurrence #2)" in v.reason


def test_ref_fields_are_record_keys(tmp_path):
    v = _run(tmp_path, _test(SEQ_PC), ["P o.v=5", "C k=0"])
    assert v.verdict == FAIL
    assert "missing ['i.v']" in v.reason


def test_unfed_buffer_input_fails(tmp_path):
    v = _run(tmp_path, _test({"seq": [_do("N"), _do("C")]}), ["N x=1", "C k=0 i.v=1"])
    assert v.verdict == FAIL
    assert "unfed input" in v.reason


def test_buffer_producer_after_consumer_fails(tmp_path):
    t = _test({"schedule": [_do("C", "c"), _do("P", "p")]})
    assert _run(tmp_path, t, ["P o.v=1", "C k=0 i.v=1"]).verdict == PASS
    v = _run(tmp_path, t, ["C k=0 i.v=1", "P o.v=1"])
    assert v.verdict == FAIL
    assert "ran after" in v.reason


def test_buffer_producer_in_parallel_branch_fails(tmp_path):
    v = _run(tmp_path, _test({"par": [_do("P"), _do("C")]}), ["P o.v=1", "C k=0 i.v=1"])
    assert v.verdict == FAIL
    assert "in parallel" in v.reason


def test_any_earlier_producer_may_feed(tmp_path):
    t = _test({"seq": [_do("P"), _do("P"), _do("C")]})
    assert _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=1"]).verdict == PASS
    assert _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=2"]).verdict == PASS
    assert _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=3"]).verdict == FAIL


def test_explicit_bind_pins_producer(tmp_path):
    act = {"seq": [_do("P", "p1"), _do("P", "p2"), _do("C", "c"),
                   {"bind": [["p1.o", "c.i"]]}]}
    t = _test(act)
    assert _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=1"]).verdict == PASS
    v = _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=2"])
    assert v.verdict == FAIL


def test_bind_before_traversals(tmp_path):
    act = {"seq": [{"bind": [["c.i", "p2.o"]]}, _do("P", "p1"), _do("P", "p2"), _do("C", "c")]}
    t = _test(act)
    assert _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=2"]).verdict == PASS
    assert _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=1"]).verdict == FAIL


def test_buffer_output_need_not_be_consumed(tmp_path):
    assert _run(tmp_path, _test({"seq": [_do("P")]}), ["P o.v=1"]).verdict == PASS


def test_object_constraints_hold_on_refs(tmp_path):
    t = _test(SEQ_PC, obj_constraints=[("v > 2", "(bvugt v #x02)")])
    assert _run(tmp_path, t, ["P o.v=5", "C k=0 i.v=5"]).verdict == PASS
    v = _run(tmp_path, t, ["P o.v=1", "C k=0 i.v=1"])
    assert v.verdict == FAIL
    assert "v > 2" in v.reason


def test_hand_written_binding_constraints_still_work(tmp_path):
    t = _test(SEQ_PC)
    t.model["types"]["T"]["constraints"] = [{"pss": "c.k == p.o.v", "smt": "(= |c.k| |p.o.v|)"}]
    assert _run(tmp_path, t, ["P o.v=5", "C k=5 i.v=5"]).verdict == PASS
    assert _run(tmp_path, t, ["P o.v=5", "C k=4 i.v=5"]).verdict == FAIL


@pytest.mark.parametrize("recs", [["P o.v=3", "C k=0 i.v=3"], ["C k=0 i.v=3", "P o.v=3"]])
def test_stream_pair_runs_in_parallel(tmp_path, recs):
    v = _run(tmp_path, _test({"par": [_do("P"), _do("C")]}, kind="stream"), recs)
    assert v.verdict == PASS, v.reason


def test_stream_in_sequence_fails(tmp_path):
    v = _run(tmp_path, _test(SEQ_PC, kind="stream"), ["P o.v=3", "C k=0 i.v=3"])
    assert v.verdict == FAIL
    assert "in parallel" in v.reason


def test_stream_output_without_consumer_fails(tmp_path):
    v = _run(tmp_path, _test({"par": [_do("P"), _do("N")]}, kind="stream"),
             ["P o.v=3", "N x=0"])
    assert v.verdict == FAIL
    assert "has no consumer" in v.reason


def test_stream_output_with_two_consumers_fails(tmp_path):
    t = _test({"par": [_do("P"), _do("C"), _do("C")]}, kind="stream")
    v = _run(tmp_path, t, ["P o.v=3", "C k=0 i.v=3", "C k=0 i.v=3"])
    assert v.verdict == FAIL
    t = _test({"par": [_do("P"), _do("P"), _do("C"), _do("C")]}, kind="stream")
    v = _run(tmp_path, t, ["P o.v=3", "P o.v=4", "C k=0 i.v=4", "C k=0 i.v=3"])
    assert v.verdict == PASS, v.reason


def test_state_reads_latest_writer(tmp_path):
    t = _test({"seq": [_do("P"), _do("P"), _do("C")]}, kind="state")
    assert _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=2"]).verdict == PASS
    v = _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=1"])
    assert v.verdict == FAIL


def test_state_with_no_writer_reads_initial_state(tmp_path):
    t = _test({"seq": [_do("C")]}, kind="state")
    assert _run(tmp_path, t, ["C k=0 i.v=9"]).verdict == PASS


def test_pools_keep_objects_apart(tmp_path):
    t = _test(SEQ_PC)
    t.model["types"]["C"]["refs"]["i"]["pool"] = "other"
    v = _run(tmp_path, t, ["P o.v=1", "C k=0 i.v=1"])
    assert v.verdict == FAIL
    assert "unfed input" in v.reason


def _prev_test():
    t = _test({"seq": [_do("P"), _do("P"), _do("C")]}, kind="state")
    t.model["types"]["obj"]["initial"] = [{"pss": "v == 0", "smt": "(= |v| #x00)"}]
    t.model["types"]["obj"]["prev"] = [{"pss": "v == prev.v + 1",
                                        "smt": "(= |v| (bvadd |prev.v| #x01))"}]
    return t


def test_state_prev_constraint_relates_each_write_to_the_one_before(tmp_path):
    t = _prev_test()
    v = _run(tmp_path, t, ["P o.v=1", "P o.v=2", "C k=0 i.v=2"])
    assert v.verdict == PASS, v.reason


def test_state_prev_constraint_broken_fails(tmp_path):
    t = _prev_test()
    v = _run(tmp_path, t, ["P o.v=1", "P o.v=3", "C k=0 i.v=3"])
    assert v.verdict == FAIL
    assert "prev.v" in v.reason
    v = _run(tmp_path, t, ["P o.v=2", "P o.v=3", "C k=0 i.v=3"])
    assert v.verdict == FAIL                # the first write follows the initial state
