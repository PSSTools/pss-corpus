"""Resource claims (§6.4, §6.5): a ``lock``/``share`` ref's ``instance_id``
is observed and below its pool's size; occurrences in different ``par``
branches never lock the same instance, nor lock and share it."""

import json

import pytest

from pss_corpus import ERROR, FAIL, PASS, check_run
from pss_corpus.model import Test


def _test(activity, size=2, pool=None, pools=None, res_constraints=()):
    ref = {"type": "R"}
    if pool:
        ref["pool"] = pool
    types = {
        "R": {"kind": "resource", "fields": {},
              "constraints": [{"pss": c, "smt": s} for c, s in res_constraints]},
        "L": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"r": dict(ref, dir="lock")}},
        "S": {"kind": "action", "atomic": True, "fields": {},
              "refs": {"r": dict(ref, dir="share")}},
        "N": {"kind": "action", "atomic": True, "fields": {"x": "u8"}},
        "T": {"kind": "action", "atomic": False, "fields": {}, "activity": activity},
    }
    if pools is None:
        pools = {"rp": {"type": "R", "bind": "*", "size": size}}
    return Test(path="/nonexistent", model={
        "schema": "pss-corpus/model/1.0", "id": "t.res", "sources": [],
        "run": {"root": "T"}, "types": types,
        "components": {"pss_top": {"pools": pools}}})


def _run(tmp_path, t, recs):
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE act {r}\n" for r in recs))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(d))


def _do(t, label=None):
    return {"do": t, "label": label} if label else {"do": t}


PAR_LL = {"par": [_do("L"), _do("L")]}


def test_instance_id_is_a_record_key(tmp_path):
    v = _run(tmp_path, _test({"seq": [_do("L")]}), ["L"])
    assert v.verdict == FAIL
    assert "missing ['r.instance_id']" in v.reason


@pytest.mark.parametrize("iid,verdict", [(0, PASS), (1, PASS), (2, FAIL), (7, FAIL)])
def test_instance_id_below_pool_size(tmp_path, iid, verdict):
    v = _run(tmp_path, _test({"seq": [_do("L")]}), [f"L r.instance_id={iid}"])
    assert v.verdict == verdict, v.reason
    if verdict == FAIL:
        assert "instance_id < 2" in v.reason


def test_pool_without_size_has_one_instance(tmp_path):
    t = _test({"seq": [_do("L")]}, pools={"rp": {"type": "R", "bind": "*"}})
    assert _run(tmp_path, t, ["L r.instance_id=0"]).verdict == PASS
    assert _run(tmp_path, t, ["L r.instance_id=1"]).verdict == FAIL


def test_named_pool_size_is_used(tmp_path):
    pools = {"a": {"type": "R", "size": 1}, "b": {"type": "R", "size": 4}}
    t = _test({"seq": [_do("L")]}, pool="pss_top.b", pools=pools)
    assert _run(tmp_path, t, ["L r.instance_id=3"]).verdict == PASS
    assert _run(tmp_path, t, ["L r.instance_id=4"]).verdict == FAIL


def test_ambiguous_or_missing_pool_is_a_model_error(tmp_path):
    pools = {"a": {"type": "R", "size": 1}, "b": {"type": "R", "size": 4}}
    v = _run(tmp_path, _test({"seq": [_do("L")]}, pools=pools), ["L r.instance_id=0"])
    assert v.verdict == ERROR
    assert "2 pools" in v.reason
    v = _run(tmp_path, _test({"seq": [_do("L")]}, pool="pss_top.zz"), ["L r.instance_id=0"])
    assert v.verdict == ERROR
    assert "'pss_top.zz'" in v.reason


def test_wrong_dir_for_resource_is_a_model_error(tmp_path):
    t = _test({"seq": [_do("L")]})
    t.model["types"]["L"]["refs"]["r"]["dir"] = "input"
    v = _run(tmp_path, t, ["L r.instance_id=0"])
    assert v.verdict == ERROR
    assert "lock or share" in v.reason


def test_parallel_locks_of_one_instance_fail(tmp_path):
    v = _run(tmp_path, _test(PAR_LL), ["L r.instance_id=1", "L r.instance_id=1"])
    assert v.verdict == FAIL
    assert "run in parallel" in v.reason


def test_parallel_locks_of_different_instances_pass(tmp_path):
    v = _run(tmp_path, _test(PAR_LL), ["L r.instance_id=1", "L r.instance_id=0"])
    assert v.verdict == PASS, v.reason


def test_parallel_lock_and_share_of_one_instance_fail(tmp_path):
    t = _test({"par": [_do("L"), _do("S")]})
    assert _run(tmp_path, t, ["S r.instance_id=0", "L r.instance_id=0"]).verdict == FAIL
    assert _run(tmp_path, t, ["S r.instance_id=0", "L r.instance_id=1"]).verdict == PASS


def test_parallel_shares_of_one_instance_pass(tmp_path):
    t = _test({"par": [_do("S"), _do("S")]})
    assert _run(tmp_path, t, ["S r.instance_id=0", "S r.instance_id=0"]).verdict == PASS


def test_sequential_locks_may_reuse_an_instance(tmp_path):
    t = _test({"seq": [_do("L"), _do("L")]})
    assert _run(tmp_path, t, ["L r.instance_id=0", "L r.instance_id=0"]).verdict == PASS


def test_schedule_is_not_checked(tmp_path):
    # A schedule may serialize its branches; a trace of points cannot tell.
    t = _test({"schedule": [_do("L"), _do("L")]})
    assert _run(tmp_path, t, ["L r.instance_id=0", "L r.instance_id=0"]).verdict == PASS


def test_nested_par_branch_excludes_only_concurrent_pairs(tmp_path):
    # a ; b in one branch, c in the other: a-c and b-c are concurrent, a-b not.
    t = _test({"par": [{"seq": [_do("L"), _do("L")]}, _do("L")]})
    ok = ["L r.instance_id=0", "L r.instance_id=0", "L r.instance_id=1"]
    assert _run(tmp_path, t, ok).verdict == PASS
    # Any record may be the lone branch's; with all three equal, every
    # assignment puts it on the same instance as a concurrent lock.
    bad = ["L r.instance_id=1", "L r.instance_id=1", "L r.instance_id=1"]
    assert _run(tmp_path, t, bad).verdict == FAIL


def test_three_parallel_locks_on_two_instances_fail(tmp_path):
    t = _test({"par": [_do("L"), _do("L"), _do("L")]})
    recs = ["L r.instance_id=0", "L r.instance_id=1", "L r.instance_id=0"]
    assert _run(tmp_path, t, recs).verdict == FAIL


def test_different_pools_do_not_exclude(tmp_path):
    pools = {"a": {"type": "R", "size": 2}, "b": {"type": "R", "size": 2}}
    t = _test(PAR_LL, pool="pss_top.a", pools=pools)
    t.model["types"]["M"] = {"kind": "action", "atomic": True, "fields": {},
                             "refs": {"r": {"dir": "lock", "type": "R", "pool": "pss_top.b"}}}
    t.model["types"]["T"]["activity"] = {"par": [_do("L"), _do("M")]}
    assert _run(tmp_path, t, ["L r.instance_id=0", "M r.instance_id=0"]).verdict == PASS


def test_resource_fields_and_constraints(tmp_path):
    t = _test({"seq": [_do("L")]}, size=4,
              res_constraints=[("instance_id != 2", "(not (= instance_id #x00000002))")])
    assert _run(tmp_path, t, ["L r.instance_id=3"]).verdict == PASS
    assert _run(tmp_path, t, ["L r.instance_id=2"]).verdict == FAIL
