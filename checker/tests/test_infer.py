"""Rule J (§6.5): a record the activity does not account for is an inferred
action when the model allows inference. It must feed an input of an explicit
occurrence, or of an inferred one that is itself needed (ranks: no cycles),
and its own inputs are fed in turn (Rule C)."""

import json

from pss_corpus import FAIL, PASS, check_run
from pss_corpus.model import Test


def _ref(d, typ):
    return {"dir": d, "type": typ}


def _test(activity, allowed=True, kind="buffer"):
    types = {
        "obj": {"kind": kind, "fields": {"v": "u8"}},
        "obj2": {"kind": kind, "fields": {"v": "u8"}},
        "other": {"kind": kind, "fields": {"v": "u8"}},
        "P": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"o": _ref("output", "obj")}},
        "C": {"kind": "action", "atomic": True, "fields": {"k": "u8"},
              "refs": {"i": _ref("input", "obj")}},
        # obj -> obj2
        "Q": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"i": _ref("input", "obj"), "o": _ref("output", "obj2")}},
        "D": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"i": _ref("input", "obj2")}},
        # obj2 -> obj: X and Y can feed each other
        "Y": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"i": _ref("input", "obj2"), "o": _ref("output", "obj")}},
        # an output nobody consumes
        "U": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"o": _ref("output", "other")}},
        "N": {"kind": "action", "atomic": True, "fields": {"x": "u8"}},
        "T": {"kind": "action", "atomic": False, "fields": {}, "activity": activity},
    }
    model = {"schema": "pss-corpus/model/1.0", "id": "t.infer", "sources": [],
             "run": {"root": "T"}, "types": types}
    if allowed is not None:
        model["inference"] = {"allowed": allowed}
    return Test(path="/nonexistent", model=model)


def _run(tmp_path, t, recs):
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE act {r}\n" for r in recs))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(d))


DO_C = {"do": "C"}
DO_D = {"do": "D"}
DO_N = {"do": "N"}


def test_inferred_producer_feeds_explicit_consumer(tmp_path):
    v = _run(tmp_path, _test(DO_C), ["P o.v=5", "C k=0 i.v=5"])
    assert v.verdict == PASS, v.reason
    assert ("inf", 0) in v.occurrences


def test_inference_not_allowed_rejects_the_extra_record(tmp_path):
    for allowed in (False, None):
        v = _run(tmp_path, _test(DO_C, allowed), ["P o.v=5", "C k=0 i.v=5"])
        assert v.verdict == FAIL
        assert "P" in v.reason


def test_consumer_without_producer_is_unfed(tmp_path):
    v = _run(tmp_path, _test(DO_C), ["C k=0 i.v=5"])
    assert v.verdict == FAIL
    assert "unfed input" in v.reason


def test_inferred_producer_after_consumer_fails(tmp_path):
    v = _run(tmp_path, _test(DO_C), ["C k=0 i.v=5", "P o.v=5"])
    assert v.verdict == FAIL


def test_inferred_value_must_match(tmp_path):
    v = _run(tmp_path, _test(DO_C), ["P o.v=5", "C k=0 i.v=6"])
    assert v.verdict == FAIL
    assert "C.i" in v.reason


def test_padding_with_an_unneeded_producer_fails(tmp_path):
    # Two inferred producers, one buffer input: one of them is needed by nobody.
    v = _run(tmp_path, _test(DO_C), ["P o.v=5", "P o.v=5", "C k=0 i.v=5"])
    assert v.verdict == FAIL
    assert "inferred P" in v.reason


def test_inferred_action_with_no_consumer_fails(tmp_path):
    v = _run(tmp_path, _test(DO_N), ["P o.v=5", "N x=0"])
    assert v.verdict == FAIL
    assert "satisfies no demand" in v.reason


def test_type_nobody_consumes_is_not_inferable(tmp_path):
    v = _run(tmp_path, _test(DO_N), ["U o.v=1", "N x=0"])
    assert v.verdict == FAIL
    assert "U" in v.reason


def test_action_without_outputs_is_not_inferable(tmp_path):
    v = _run(tmp_path, _test(DO_N), ["N x=1", "N x=0"])
    assert v.verdict == FAIL


def test_inferred_chain_back_to_explicit(tmp_path):
    v = _run(tmp_path, _test(DO_D), ["P o.v=1", "Q i.v=1 o.v=2", "D i.v=2"])
    assert v.verdict == PASS, v.reason


def test_inferred_action_inputs_must_be_fed(tmp_path):
    v = _run(tmp_path, _test(DO_D), ["Q i.v=1 o.v=2", "D i.v=2"])
    assert v.verdict == FAIL
    assert "unfed input" in v.reason and "Q.i" in v.reason


def test_inferred_chain_value_break_fails(tmp_path):
    v = _run(tmp_path, _test(DO_D), ["P o.v=1", "Q i.v=3 o.v=2", "D i.v=2"])
    assert v.verdict == FAIL


def test_explicit_producer_and_inferred_producer(tmp_path):
    # The explicit P's output need not be consumed; the inferred one feeds C.
    act = {"seq": [{"do": "P"}, {"do": "C"}]}
    v = _run(tmp_path, _test(act), ["P o.v=1", "P o.v=2", "C k=0 i.v=2"])
    assert v.verdict == PASS, v.reason
    v = _run(tmp_path, _test(act), ["P o.v=1", "P o.v=2", "C k=0 i.v=3"])
    assert v.verdict == FAIL


def test_inferred_stream_cycle_is_not_justified(tmp_path):
    # Q (obj -> obj2) and Y (obj2 -> obj) feed each other's stream inputs, but
    # no explicit occurrence needs either: ranks cannot be well-founded.
    v = _run(tmp_path, _test(DO_N, kind="stream"),
             ["Q i.v=1 o.v=2", "Y i.v=2 o.v=1", "N x=0"])
    assert v.verdict == FAIL
    assert "is needed" in v.reason


def test_inferred_stream_producer_for_explicit_consumer(tmp_path):
    v = _run(tmp_path, _test(DO_C, kind="stream"), ["P o.v=4", "C k=0 i.v=4"])
    assert v.verdict == PASS, v.reason


def test_inferred_stream_chain(tmp_path):
    # Y feeds C; Y's stream input is fed by an inferred Q, whose input by P.
    v = _run(tmp_path, _test(DO_C, kind="stream"),
             ["P o.v=1", "Q i.v=1 o.v=2", "Y i.v=2 o.v=3", "C k=0 i.v=3"])
    assert v.verdict == PASS, v.reason


ATOMIC_N_C = {"seq": [{"do": "N"}, {"do": "C"}], "atomic": True}


def test_no_inferred_action_inside_an_atomic_block(tmp_path):
    # 11.3.7: P feeds C, but may not run between N and C.
    v = _run(tmp_path, _test(ATOMIC_N_C), ["N x=0", "P o.v=5", "C k=0 i.v=5"])
    assert v.verdict == FAIL
    v = _run(tmp_path, _test(ATOMIC_N_C), ["P o.v=5", "N x=0", "C k=0 i.v=5"])
    assert v.verdict == PASS, v.reason


def test_inferred_action_after_an_atomic_block(tmp_path):
    act = {"seq": [{"seq": [{"do": "N"}, {"do": "N"}], "atomic": True}, {"do": "C"}]}
    v = _run(tmp_path, _test(act), ["N x=0", "N x=1", "P o.v=5", "C k=0 i.v=5"])
    assert v.verdict == PASS, v.reason
    v = _run(tmp_path, _test(act), ["N x=0", "P o.v=5", "N x=1", "C k=0 i.v=5"])
    assert v.verdict == FAIL


def test_inferred_stream_consumer_for_explicit_producer(tmp_path):
    # UC5: `do P;` with a stream output; the consumer C is inferred.
    v = _run(tmp_path, _test({"do": "P"}, kind="stream"), ["P o.v=4", "C k=0 i.v=4"])
    assert v.verdict == PASS, v.reason
    v = _run(tmp_path, _test({"do": "P"}, kind="stream"), ["P o.v=4"])
    assert v.verdict == FAIL
    assert "no consumer" in v.reason
    v = _run(tmp_path, _test({"do": "P"}, kind="stream"), ["P o.v=4", "C k=0 i.v=5"])
    assert v.verdict == FAIL


def test_inferred_buffer_consumer_is_not_needed(tmp_path):
    v = _run(tmp_path, _test({"do": "P"}), ["P o.v=4", "C k=0 i.v=4"])
    assert v.verdict == FAIL


def test_inferred_state_writer_when_initial_state_does_not_fit(tmp_path):
    t = _test({"do": "C"}, kind="state")
    t.model["types"]["obj"]["initial"] = [{"pss": "v == 0", "smt": "(= |v| #x00)"}]
    t.model["types"]["C"]["constraints"] = [{"pss": "i.v == 5", "smt": "(= |i.v| #x05)"}]
    assert _run(tmp_path, t, ["C k=0 i.v=5"]).verdict == FAIL
    v = _run(tmp_path, t, ["P o.v=5", "C k=0 i.v=5"])
    assert v.verdict == PASS, v.reason
    t.model["types"]["C"]["constraints"] = []
    v = _run(tmp_path, t, ["C k=0 i.v=0"])
    assert v.verdict == PASS, v.reason
