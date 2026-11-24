"""The built-in ``uid`` (PSS 3.1): each action traversal in a run has its own.
An observed ``uid`` field that repeats one printed earlier in the run fails;
constraints read a ``uid`` like any other observed field."""

import json

from pss_corpus import FAIL, PASS, check_run
from pss_corpus.model import Test


def _test():
    types = {
        "A": {"kind": "action", "atomic": True, "fields": {"uid": "u32"}},
        "B": {"kind": "action", "atomic": True, "fields": {"t": "u32", "uid": "u32"}},
        "T": {"kind": "action", "atomic": False, "fields": {},
              "constraints": [{"pss": "b.t == a1.uid + 100",
                               "smt": "(= |b.t| (bvadd |a1.uid| #x00000064))"}],
              "activity": {"seq": [{"do": "A", "label": "a1"},
                                   {"repeat": {"count": 2}, "body": {"do": "A"}},
                                   {"do": "B", "label": "b"}]}},
    }
    return Test(path="/nonexistent", model={
        "schema": "pss-corpus/model/1.0", "id": "t.uid", "sources": [],
        "run": {"root": "T"}, "types": types})


def _run(tmp_path, recs):
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE act {r}\n" for r in recs))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(_test(), str(d))


def test_distinct_uids_pass(tmp_path):
    v = _run(tmp_path, ["A uid=2", "A uid=3", "A uid=5", "B t=102 uid=4"])
    assert v.verdict == PASS, v.reason


def test_a_repeated_uid_fails(tmp_path):
    v = _run(tmp_path, ["A uid=2", "A uid=3", "A uid=3", "B t=102 uid=4"])
    assert v.verdict == FAIL
    assert "uid 3" in v.reason


def test_a_constraint_on_a_uid_is_checked(tmp_path):
    v = _run(tmp_path, ["A uid=2", "A uid=3", "A uid=5", "B t=103 uid=4"])
    assert v.verdict == FAIL
