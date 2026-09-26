"""Every committed model is self-consistent, and the checker can tell a cheat.

For each test, a legal trace is synthesized from the model alone and must PASS;
then fixed mutations of it must each FAIL (§6.5: checker sensitivity is tested,
not assumed). A model whose checker cannot tell a mutant from a legal trace is a
defective model.

P1 synthesis (``synth.py``) covers exact (``eq``) leaves. A leaf stated with
``where`` needs the solver to synthesize a value, so its test is only loaded and
linted here. Negative tests are covered by ``test_diagnostics.py``.
"""

import copy
import json
import os

import pytest

from pss_corpus import PASS, FAIL, check_run, default_root, discover

from synth import synth

TESTS = list(discover(default_root()))


def test_the_corpus_has_tests():
    assert len(TESTS) >= 50


def test_ids_are_unique():
    ids = [t.id for t in TESTS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("t", TESTS, ids=lambda t: t.id)
def test_sources_exist(t):
    for s in t.sources:
        assert os.path.isfile(s), s


SYNTH = [t for t in TESTS if synth(t) is not None]


def _run(tmp_path, t, lines, name="run"):
    d = tmp_path / name
    d.mkdir()
    (d / "log.txt").write_text("\n".join(lines) + "\n")
    (d / "outcome.json").write_text(json.dumps({"outcome": "ok"}))
    return check_run(t, str(d))


def test_most_models_are_synthesizable():
    assert len(SYNTH) >= 0.8 * len(TESTS)


@pytest.mark.parametrize("t", SYNTH, ids=lambda t: t.id)
def test_synthesized_trace_passes(tmp_path, t):
    v = _run(tmp_path, t, synth(t))
    assert v.verdict == PASS, v.reason


def _bump(val):
    """*val*, changed: a different value of the same kind where there is one."""
    if val in ("true", "false"):
        return "false" if val == "true" else "true"
    if val.lstrip("-").isdigit():
        return str(int(val) + 1)
    if val.startswith("0x"):
        return hex(int(val, 16) ^ 1)
    return val + "x"


def _mutants(lines):
    chk = [i for i, l in enumerate(lines) if " chk " in l or " acc " in l]
    for i in chk:
        yield f"drop line {i}", lines[:i] + lines[i + 1:]
        yield f"duplicate line {i}", lines[:i + 1] + [lines[i]] + lines[i + 1:]
        if "=" in lines[i]:
            head, _, val = lines[i].rpartition("=")
            yield f"change value on line {i}", lines[:i] + [f"{head}={_bump(val)}"] + lines[i + 1:]
        if " acc " in lines[i]:
            # Each field of an access, not only the last: an address that is
            # off by one is the bug the tap exists to see.
            toks = lines[i].split(" ")
            for k, t in enumerate(toks):
                if t.startswith("addr="):
                    m = list(toks)
                    m[k] = "addr=" + _bump(t[5:])
                    yield f"change addr on line {i}", lines[:i] + [" ".join(m)] + lines[i + 1:]
    for a, b in zip(chk, chk[1:]):
        if lines[a] != lines[b]:
            m = list(lines)
            m[a], m[b] = m[b], m[a]
            yield f"swap lines {a},{b}", m
    yield "extra chk", lines + ["@@PSS-TRACE chk zz.extra"]


@pytest.mark.parametrize("t", SYNTH, ids=lambda t: t.id)
def test_every_mutant_fails(tmp_path, t):
    lines = synth(t)
    for n, (what, m) in enumerate(_mutants(lines)):
        v = _run(tmp_path, t, m, name=f"m{n}")
        assert v.verdict == FAIL, f"{what} was not detected:\n" + "\n".join(m)


@pytest.mark.parametrize("t", TESTS[:1], ids=lambda t: t.id)
def test_a_negative_outcome_fails_a_positive_test(tmp_path, t):
    d = tmp_path / "r"
    d.mkdir()
    (d / "log.txt").write_text("")
    (d / "outcome.json").write_text(json.dumps({"outcome": "compile_error"}))
    assert check_run(t, str(d)).verdict == FAIL


def test_unsupported_is_its_own_verdict(tmp_path):
    t = TESTS[0]
    d = tmp_path / "r"
    d.mkdir()
    (d / "log.txt").write_text("")
    (d / "outcome.json").write_text(json.dumps({"outcome": "unsupported"}))
    assert check_run(t, str(d)).verdict == "UNSUPPORTED"
