"""A state writer and a reader of its pool in parallel (LRM 13.3.1): the
write is in progress until the writer's last record, and the two never
overlap, so a reader runs wholly before or after the writer; yield-ladder ``chk <Action>.<rung>`` records
stay with their own occurrence when bodies interleave."""
import json

import pytest

from pss_corpus import FAIL, PASS, check_run, default_root, discover

T = {t.id: t for t in discover(default_root())}["flow.state.par_rw.001"]
RUNGS = ["chk SW.rung k=0", "chk SW.rung k=1"]


def _run(tmp_path, recs):
    d = tmp_path / "run"
    d.mkdir(exist_ok=True)
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE {r}\n" for r in recs))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(T, str(d))


@pytest.mark.parametrize("recs", [
    ["act pss_top::SW o.s=5", *RUNGS, "act pss_top::SR i.s=5"],    # after the write
    ["act pss_top::SR i.s=0", "act pss_top::SW o.s=5", *RUNGS],    # before it
])
def test_reader_sees_the_initial_state_or_the_completed_write(tmp_path, recs):
    v = _run(tmp_path, recs)
    assert v.verdict == PASS, v.reason


@pytest.mark.parametrize("recs", [
    ["act pss_top::SW o.s=5", "act pss_top::SR i.s=5", *RUNGS],    # a write in progress
    ["act pss_top::SW o.s=5", *RUNGS, "act pss_top::SR i.s=0"],    # misses the write
    ["act pss_top::SW o.s=5", "act pss_top::SR i.s=0", *RUNGS],    # during: old state
])
def test_reader_seeing_a_write_in_progress_or_missing_it_fails(tmp_path, recs):
    v = _run(tmp_path, recs)
    assert v.verdict == FAIL
    assert "initial state" in v.reason or "SW" in v.reason


T2 = {t.id: t for t in discover(default_root())}["flow.state.par_rw.002"]
SR_RUNGS = ["chk SR.rung k=0", "chk SR.rung k=1"]


@pytest.mark.parametrize("recs, ok", [
    (["act pss_top::SR i.s=0", *SR_RUNGS, "act pss_top::SW o.s=5"], True),
    (["act pss_top::SW o.s=5", "act pss_top::SR i.s=5", *SR_RUNGS], True),
    (["act pss_top::SR i.s=0", "act pss_top::SW o.s=5", *SR_RUNGS], False),
    (["act pss_top::SR i.s=0", "chk SR.rung k=0", "act pss_top::SW o.s=5",
      "chk SR.rung k=1"], False),
])
def test_writer_never_runs_inside_a_readers_body(tmp_path, recs, ok):
    """The reader is the ladder (flow.state.par_rw.002): a writer starting
    before its last rung overlaps it (13.3.1)."""
    d = tmp_path / "run"
    d.mkdir()
    (d / "log.txt").write_text("".join(f"@@PSS-TRACE {r}\n" for r in recs))
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    v = check_run(T2, str(d))
    assert v.verdict == (PASS if ok else FAIL), v.reason
    if not ok:
        assert "overlaps" in v.reason
