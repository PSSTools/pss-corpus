"""The cheat mutations of §6.5: each turns a legal trace into one a tool must
not get away with, and every one must FAIL.

The legal trace is synthesized by the solver from a small model (no corpus
model has flow-object refs yet); the trace must PASS first, so a FAIL is the
mutation's doing. Where synthesis cannot produce the legal trace (inferred
actions are outside the activity), it is written out and checked the same way.
"""

import json

import pytest

from pss_corpus import FAIL, PASS, check_run
from pss_corpus.model import Test

from synth import synth


def _test(activity, kind="buffer", allowed=None, size=2):
    types = {
        "obj": {"kind": kind, "fields": {"v": "u8"}},
        "R": {"kind": "resource", "fields": {}},
        "P": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"o": {"dir": "output", "type": "obj"}}},
        "C": {"kind": "action", "atomic": True, "fields": {"k": "u8"},
              "refs": {"i": {"dir": "input", "type": "obj"}}},
        "L": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"r": {"dir": "lock", "type": "R"}}},
        "T": {"kind": "action", "atomic": False, "fields": {}, "activity": activity},
    }
    model = {"schema": "pss-corpus/model/1.0", "id": "t.cheat", "sources": [],
             "expect": {"outcome": "ok"}, "run": {"root": "T"}, "types": types,
             "components": {"pss_top": {"pools": {"rp": {"type": "R", "bind": "*",
                                                         "size": size}}}}}
    if allowed is not None:
        model["inference"] = {"allowed": allowed}
    return Test(path="/nonexistent", model=model)


def _run(tmp_path, t, lines, name):
    d = tmp_path / name
    d.mkdir()
    (d / "log.txt").write_text("\n".join(lines) + "\n")
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(d))


def _do(n):
    return {"do": n}


def _idx(lines, typ, nth=0):
    return [i for i, l in enumerate(lines) if l.split(" ")[2] == typ][nth]


def _set(line, key, val):
    return " ".join(f"{key}={val}" if tok.startswith(key + "=") else tok
                    for tok in line.split(" "))


def _get(line, key):
    return next(tok.split("=", 1)[1] for tok in line.split(" ") if tok.startswith(key + "="))


def delete_producer(lines):
    i = _idx(lines, "P")
    return lines[:i] + lines[i + 1:]


def producer_after_consumer(lines):
    p, c = _idx(lines, "P"), _idx(lines, "C")
    m = list(lines)
    m.insert(c, m.pop(p))
    return m


def stream_two_consumers(lines):
    # The second consumer reads the first producer's output, whose own
    # producer is dropped: one stream output, two consumers.
    v = _get(lines[_idx(lines, "P")], "o.v")
    m = list(lines)
    c2 = _idx(m, "C", 1)
    m[c2] = _set(m[c2], "i.v", v)
    del m[_idx(m, "P", 1)]
    return m


def unneeded_inferred(lines):
    # After the last consumer, so it feeds no one. (Before it, either P could
    # be the explicit one, the other feeding C: a legal trace.)
    return lines + ["@@PSS-TRACE act P " + lines[_idx(lines, "P")].split(" ", 3)[3]]


def change_bound_value(lines):
    m = list(lines)
    c = _idx(m, "C")
    m[c] = _set(m[c], "i.v", (int(_get(m[c], "i.v")) + 1) % 256)
    return m


def same_lock_instance(lines):
    m = list(lines)
    a, b = _idx(m, "L"), _idx(m, "L", 1)
    m[b] = _set(m[b], "r.instance_id", _get(m[a], "r.instance_id"))
    return m


SEQ_PC = {"seq": [_do("P"), _do("C")]}

# (name, model, legal trace (None: synthesize), mutation)
CHEATS = [
    # The activity only orders C (inferred P) or schedules P and C freely,
    # so it is the flow rules, not the activity, that must catch these.
    ("delete a producer", _test(_do("C"), allowed=True), ["P o.v=3", "C k=0 i.v=3"],
     delete_producer),
    ("buffer producer after consumer", _test({"schedule": [_do("P"), _do("C")]}), None,
     producer_after_consumer),
    ("one stream output, two consumers", _test({"seq": [_do("C"), _do("C")]}, "stream", True),
     ["P o.v=1", "C k=0 i.v=1", "P o.v=2", "C k=0 i.v=2"], stream_two_consumers),
    ("inferred action no one needs", _test(SEQ_PC, allowed=True), None, unneeded_inferred),
    ("one bound value changed", _test(SEQ_PC), None, change_bound_value),
    ("concurrent locks of one instance", _test({"par": [_do("L"), _do("L")]}), None,
     same_lock_instance),
]


@pytest.mark.parametrize("name,t,legal,mutate", CHEATS, ids=[c[0] for c in CHEATS])
def test_cheat_mutation_fails(tmp_path, name, t, legal, mutate):
    lines = synth(t) if legal is None else ["@@PSS-TRACE act " + r for r in legal]
    assert lines is not None, "no legal trace synthesized"
    v = _run(tmp_path, t, lines, "legal")
    assert v.verdict == PASS, v.reason
    m = mutate(lines)
    v = _run(tmp_path, t, m, "cheat")
    assert v.verdict == FAIL, f"{name} was not detected:\n" + "\n".join(m)


def test_every_cheat_of_the_design_is_here():
    assert len(CHEATS) == 6
