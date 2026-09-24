"""``where`` leaves go through the SMT oracle, including symbolic repeat counts."""

import json

import pytest

from pss_corpus import FAIL, PASS, check_run, default_root, discover

pytest.importorskip("z3")

RAND = next(t for t in discover(default_root()) if t.id == "proc.rand.input.001")
IDX = next(t for t in discover(default_root()) if t.id == "proc.repeat.index.001")


def _trace(n, bad=None):
    lines = [f"@@PSS-TRACE act pss_top::A n={n}"]
    acc = 0
    for i in range(n):
        acc += i
        if bad == i:
            acc += 1
        lines.append(f"@@PSS-TRACE chk sum_to.step i={i} acc={acc}")
    lines.append(f"@@PSS-TRACE chk result r={n * (n - 1) // 2}")
    return lines


def _run(tmp_path, t, lines):
    (tmp_path / "log.txt").write_text("\n".join(lines) + "\n")
    (tmp_path / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(tmp_path))


@pytest.mark.parametrize("n", [0, 1, 5, 15])
def test_legal_traces_pass(tmp_path, n):
    v = _run(tmp_path, RAND, _trace(n))
    assert v.verdict == PASS, v.reason


def test_a_wrong_accumulator_is_named_in_the_unsat_core(tmp_path):
    v = _run(tmp_path, RAND, _trace(5, bad=2))
    assert v.verdict == FAIL
    assert "acc ==" in v.reason and "i=2" in v.reason


def test_one_iteration_too_few(tmp_path):
    lines = _trace(5)
    del lines[5]
    v = _run(tmp_path, RAND, lines)
    assert v.verdict == FAIL


def test_a_value_outside_the_fields_sort(tmp_path):
    v = _run(tmp_path, RAND, _trace(16))       # n is bit[4]
    assert v.verdict == FAIL and "sort" in v.reason


def test_repeat_index(tmp_path):
    ok = ["@@PSS-TRACE act pss_top::A"] + [
        f"@@PSS-TRACE chk ri i={k} sq={k * k}" for k in range(5)]
    assert _run(tmp_path, IDX, ok).verdict == PASS
    bad = list(ok)
    bad[3] = "@@PSS-TRACE chk ri i=2 sq=5"
    assert _run(tmp_path, IDX, bad).verdict == FAIL
