"""Access records and the executor tap's platform model (§4.12, §6.8)."""

import json

import pytest

from pss_corpus import FAIL, PASS
from pss_corpus.check import check_run
from pss_corpus.model import Test
from pss_corpus.tap import f8, tap_read


def test_f8_matches_its_definition():
    """The XOR of the address's eight bytes, XOR 0x5A. The bytes at
    0xa0000000.. are pinned in COMPLIANCE-DESIGN §4.12's worked example."""
    assert [f8(0xa0000000 + k) for k in range(4)] == [0xfa, 0xfb, 0xf8, 0xf9]
    assert f8(0) == 0x5a
    assert f8(0x0102030405060708) == 0x01 ^ 0x02 ^ 0x03 ^ 0x04 ^ 0x05 ^ 0x06 ^ 0x07 ^ 0x08 ^ 0x5a


def test_a_read_puts_the_first_byte_in_the_low_bits():
    """LRM 21.13.9.1."""
    assert tap_read(0xa0000000, 32) == 0xf9f8fbfa
    assert tap_read(0xa0000000, 8) == 0xfa
    assert tap_read(0xa0000000, 64) & 0xffffffff == tap_read(0xa0000000, 32)


def test_a_read_wraps_at_the_top_of_the_address_space():
    top = (1 << 64) - 1
    assert tap_read(top, 16) == f8(top) | (f8(0) << 8)


# --- the acc leaf --------------------------------------------------------------

A = 0xa0000010
V = tap_read(A, 32)


def _test(body, fields=None):
    return Test(path="/nonexistent", model={
        "schema": "pss-corpus/model/1.0", "id": "t.acc", "sources": [],
        "run": {"root": "T"}, "types": {"T": {
            "kind": "action", "atomic": True, "fields": fields or {},
            "body": {"seq": body}}}})


def _check(tmp_path, t, recs):
    (tmp_path / "log.txt").write_text(
        "".join(f"@@PSS-TRACE {r}\n" for r in ["act T"] + recs))
    (tmp_path / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(tmp_path))


RMW = [
    {"acc": "r32", "as": "rd", "eq": {"addr": A}},
    {"acc": "w32", "eq": {"addr": A},
     "where": [{"pss": "data == rd | 1", "smt": "(= data (bvor rd #x00000001))"}]},
]


def test_a_read_modify_write_passes(tmp_path):
    v = _check(tmp_path, _test(RMW), [f"acc r32 addr=0x{A:x} data=0x{V:x}",
                                      f"acc w32 addr=0x{A:x} data=0x{V | 1:x}"])
    assert v.verdict == PASS, v.reason


def test_a_write_that_ignored_the_read_fails(tmp_path):
    """A tool that skipped the read and assumed 0 writes a visibly wrong
    value: F8 is non-zero almost everywhere."""
    v = _check(tmp_path, _test(RMW), [f"acc r32 addr=0x{A:x} data=0x{V:x}",
                                      f"acc w32 addr=0x{A:x} data=0x1"])
    assert v.verdict == FAIL
    assert "data == rd | 1" in v.reason


def test_read_data_that_is_not_the_taps_fails(tmp_path):
    """Whatever the leaf says: a tool that miscompiled the tap must not feed
    its own values to the test."""
    v = _check(tmp_path, _test([{"acc": "r32", "eq": {"addr": A}}]),
               [f"acc r32 addr=0x{A:x} data=0x{V ^ 0x100:x}"])
    assert v.verdict == FAIL
    assert "executor tap" in v.reason


def test_the_wrong_operation_fails(tmp_path):
    v = _check(tmp_path, _test([{"acc": "w32", "eq": {"addr": A, "data": 1}}]),
               [f"acc w16 addr=0x{A:x} data=0x1"])
    assert v.verdict == FAIL


def test_an_access_the_body_does_not_expect_fails(tmp_path):
    v = _check(tmp_path, _test([]), [f"acc w32 addr=0x{A:x} data=0x1"])
    assert v.verdict == FAIL
    assert "unexpected acc record" in v.reason


def test_an_access_before_any_action_fails(tmp_path):
    t = _test([])
    (tmp_path / "log.txt").write_text(
        f"@@PSS-TRACE acc w32 addr=0x{A:x} data=0x1\n@@PSS-TRACE act T\n")
    (tmp_path / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    v = check_run(t, str(tmp_path))
    assert v.verdict == FAIL
    assert "before any act" in v.reason


def test_a_missing_or_extra_field_fails(tmp_path):
    t = _test([{"acc": "w32", "eq": {"addr": A, "data": 1}}])
    assert _check(tmp_path, t, [f"acc w32 addr=0x{A:x}"]).verdict == FAIL
    assert _check(tmp_path, t, [f"acc w32 addr=0x{A:x} data=0x1 i=0"]
                  ).verdict == FAIL


def test_data_wider_than_the_access_fails(tmp_path):
    t = _test([{"acc": "w8", "where": []}])
    assert _check(tmp_path, t, [f"acc w8 addr=0x{A:x} data=0x100"]).verdict == FAIL


def test_a_byte_list_read_is_checked_per_byte(tmp_path):
    """rb: one record per byte; the byte at addr + i is F8(addr + i)."""
    t = _test([{"acc": "rb", "eq": {"addr": A, "i": k, "n": 2}} for k in range(2)])
    good = [f"acc rb addr=0x{A:x} i={k} n=2 data=0x{f8(A + k):x}" for k in range(2)]
    assert _check(tmp_path, t, good).verdict == PASS
    bad = [good[0], f"acc rb addr=0x{A:x} i=1 n=2 data=0x{f8(A):x}"]
    assert _check(tmp_path, t, bad).verdict == FAIL


def test_an_unknown_operation_is_a_model_error(tmp_path):
    from pss_corpus.check import ERROR
    v = _check(tmp_path, _test([{"acc": "r128"}]), ["acc r128 addr=0x0 data=0x0"])
    assert v.verdict == ERROR
