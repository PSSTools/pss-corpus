"""The checker (§6.4): decide whether one run's log is a legal execution.

P1 scope. Stage 1 (outcome) and stage 2 (structure) cover activities built
from traversals, ``seq`` and constant ``repeat``, and atomic ``body`` patterns
(§6.7) built from ``seq``, ``repeat`` and ``chk`` leaves. Stage 3 is one SMT
problem per run over the observed values; a run whose leaves are all exact
(``eq``) and whose actions have no constraints never starts the solver.
Binding, inference and interleaving (P2/P3) are not implemented, and a model
that needs them is an ERROR here rather than a silent PASS.
"""

import dataclasses as dc
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from . import smt
from .model import Test
from .smt import ModelError, Problem, Scope, Sort, resolve_sort
from .tap import ACC_OPS, BYTE_OPS, tap_read
from .trace import ProtocolError, Record, extract, parse_value, value_matches

PASS, FAIL, ERROR, UNSUPPORTED = "PASS", "FAIL", "ERROR", "UNSUPPORTED"
#: The tool rejected a negative test as it should, but said nowhere *where*:
#: no ``diagnostics.json``, or no error in it with a file and line. Not a PASS,
#: because a checked error location is what makes a rejection evidence, and not
#: a FAIL, because the tool may be right and only its adapter mute.
UNLOCATED = "UNLOCATED"

OUTCOMES = ("ok", "compile_error", "solve_fail", "runtime_error",
            "unsupported", "timeout", "infra_error")

OUTCOME_SCHEMA = "pss-corpus/outcome/1.0"
DIAGNOSTICS_SCHEMA = "pss-corpus/diagnostics/1.0"

#: Diagnostic severities that count as the tool reporting an error.
ERROR_SEVERITIES = ("error", "fatal")

#: Loop indices in body patterns are bound at this sort (PSS `int`).
INDEX_SORT = Sort("bv", 32, True)


@dc.dataclass
class Verdict:
    test: str
    rev: int
    seed: Optional[int]
    verdict: str
    reason: str = ""
    outcome: Optional[str] = None
    detail: str = ""
    #: the solver's model for unobserved values, when the verdict needed one
    witness: Dict[str, str] = dc.field(default_factory=dict)
    #: extracted samples (§6.4 stage 4); empty until distribution[] is used
    samples: List[Any] = dc.field(default_factory=list)
    occurrences: List[str] = dc.field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        return dc.asdict(self)


class _Fail(Exception):
    """The trace is not a legal execution: a FAIL, with the first divergence."""


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def check_run(test: Test, run_dir: str, seed: Optional[int] = None) -> Verdict:
    v = Verdict(test=test.id, rev=test.rev, seed=seed, verdict=ERROR)
    try:
        oc = _read_outcome(run_dir)
    except (OSError, ValueError) as e:
        v.reason = f"adapter output unreadable: {e}"
        return v
    v.outcome = oc.get("outcome")
    v.detail = oc.get("detail", "") or ""
    if oc.get("schema", OUTCOME_SCHEMA) != OUTCOME_SCHEMA:
        v.reason = f"outcome.json schema {oc.get('schema')!r} is not {OUTCOME_SCHEMA!r}"
        return v

    # Stage 1: outcome.
    if v.outcome not in OUTCOMES:
        v.reason = f"adapter reported unknown outcome {v.outcome!r}"
        return v
    if v.outcome == "infra_error":
        first = v.detail.strip().splitlines()[:1]
        v.reason = "adapter infrastructure error" + (f": {first[0]}" if first else "")
        return v
    if v.outcome == "unsupported":
        v.verdict = UNSUPPORTED
        first = v.detail.strip().splitlines()[:1]
        v.reason = "tool declared a feature of this test unsupported" + (
            f": {first[0]}" if first else "")
        return v
    if v.outcome != test.expect:
        v.verdict = FAIL
        v.reason = f"outcome {v.outcome!r}, expected {test.expect!r}"
        if v.outcome == "compile_error":
            try:
                first = _errors(_read_diagnostics(run_dir))[:1]
            except (OSError, ValueError, ModelError):
                first = []
            if first:
                v.reason += f" (first error: {_describe(first[0])})"
        return v
    if test.expect == "compile_error" and test.expect_diagnostics:
        return _check_diagnostics(test, run_dir, v)
    if test.expect != "ok":
        # P1: the negative expectation is asserted, not yet oracle-validated (§7.1 #2).
        v.verdict = PASS
        return v

    try:
        with open(os.path.join(run_dir, "log.txt"), errors="replace") as fp:
            log = fp.read()
    except OSError as e:
        v.reason = f"adapter wrote no log: {e}"
        return v

    try:
        records = extract(log)
        occs, problem = _match(test, records)
        v.occurrences = occs
        res = smt.solve(problem)
    except ProtocolError as e:
        v.verdict = FAIL
        v.reason = f"protocol violation: {e}"
        return v
    except _Fail as e:
        v.verdict = FAIL
        v.reason = str(e)
        return v
    except ModelError as e:
        v.verdict = ERROR
        v.reason = f"model error: {e}"
        return v

    if not res.sat:
        v.verdict = FAIL
        v.reason = "observed values violate: " + "; ".join(res.core)
        return v
    v.verdict = PASS
    v.witness = res.witness
    return v


def _read_outcome(run_dir: str) -> Dict[str, Any]:
    with open(os.path.join(run_dir, "outcome.json")) as fp:
        oc = json.load(fp)
    if not isinstance(oc, dict):
        raise ValueError("outcome.json is not a JSON object")
    return oc


# --------------------------------------------------------------------------- #
# Negative tests: where the error was reported
# --------------------------------------------------------------------------- #

def _read_diagnostics(run_dir: str) -> Optional[List[Dict[str, Any]]]:
    """The run's ``diagnostics.json``, or None when the adapter wrote none."""
    fn = os.path.join(run_dir, "diagnostics.json")
    if not os.path.isfile(fn):
        return None
    with open(fn) as fp:
        doc = json.load(fp)
    if not isinstance(doc, dict) or doc.get("schema") != DIAGNOSTICS_SCHEMA:
        raise ModelError(f"diagnostics.json schema is not {DIAGNOSTICS_SCHEMA!r}")
    diags = doc.get("diagnostics")
    if not isinstance(diags, list) or not all(isinstance(d, dict) for d in diags):
        raise ModelError("diagnostics.json: 'diagnostics' is not a list of objects")
    return diags


def _errors(diags: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The located errors: severity error/fatal, with a file and an integer line."""
    return [d for d in diags or []
            if d.get("severity") in ERROR_SEVERITIES
            and isinstance(d.get("file"), str) and isinstance(d.get("line"), int)]


def _describe(d: Dict[str, Any]) -> str:
    return f"{d.get('file')}:{d.get('line')}: {d.get('message', '')}".rstrip(": ")


def _same_file(reported: str, expected: str) -> bool:
    """A reported path names the expected source if it is it, or ends with it.

    Tools report absolute paths, paths relative to their working directory, or
    bare names; the model names a source relative to the test directory.
    """
    r = reported.replace("\\", "/")
    e = expected.replace("\\", "/")
    return r == e or r.endswith("/" + e)


def _on_line(d: Dict[str, Any], want: Dict[str, Any]) -> bool:
    if "lines" in want:
        lo, hi = want["lines"]
        return lo <= d["line"] <= hi
    return d["line"] == want["line"]


def _check_diagnostics(test: Test, run_dir: str, v: Verdict) -> Verdict:
    try:
        diags = _read_diagnostics(run_dir)
    except (OSError, ValueError) as e:
        v.reason = f"diagnostics.json unreadable: {e}"
        return v
    except ModelError as e:
        v.reason = str(e)
        return v
    errors = _errors(diags)
    if not errors:
        v.verdict = UNLOCATED
        v.reason = ("rejected as expected, but no error with a file and line was "
                    "reported" + ("" if diags is not None else " (no diagnostics.json)"))
        return v
    for want in test.expect_diagnostics:
        if not any(_same_file(d["file"], want["file"]) and _on_line(d, want)
                   for d in errors):
            where = (f"{want['file']}:{want['line']}" if "line" in want
                     else f"{want['file']}:{want['lines'][0]}-{want['lines'][1]}")
            v.verdict = FAIL
            v.reason = (f"no error reported at {where}; errors were at: "
                        + "; ".join(_describe(d) for d in errors[:5]))
            return v
    v.verdict = PASS
    return v


# --------------------------------------------------------------------------- #
# Stage 2 + 3: structure, then data
# --------------------------------------------------------------------------- #

def _match(test: Test, records: List[Record]) -> Tuple[List[str], Problem]:
    expected = _expand(test, test.root, depth=0)
    groups = _segment(records)

    tag_to_type = {test.record_tag(t): t for t in expected}
    got = [tag_to_type.get(g[0].tag, g[0].tag) for g in groups]
    for i, want in enumerate(expected):
        if i >= len(groups):
            raise _Fail(f"trace ended after {len(groups)} action occurrence(s); "
                        f"expected occurrence #{i + 1} of {want!r}")
        if got[i] != want:
            raise _Fail(f"occurrence #{i + 1} is {groups[i][0].describe()}; "
                        f"expected act {test.record_tag(want)!r}")
    if len(groups) > len(expected):
        raise _Fail(f"unexpected occurrence: {groups[len(expected)][0].describe()}")

    problem = Problem()
    for type_name, group in zip(expected, groups):
        _check_occurrence(test, type_name, group, problem)
    return expected, problem


def _expand(test: Test, type_name: str, depth: int) -> List[str]:
    """The atomic action occurrences a traversal of *type_name* must produce, in order."""
    if depth > 32:
        raise ModelError(f"activity nesting too deep at {type_name!r}")
    t = test.type(type_name)
    if t.get("atomic", False):
        return [type_name]
    act = t.get("activity")
    if act is None:
        raise ModelError(f"compound {type_name!r} has no activity")
    return _expand_node(test, act, depth + 1)


def _expand_node(test: Test, node: Dict[str, Any], depth: int) -> List[str]:
    if "do" in node:
        return _expand(test, node["do"], depth)
    if "seq" in node:
        out: List[str] = []
        for n in node["seq"]:
            out.extend(_expand_node(test, n, depth))
        return out
    if "repeat" in node:
        count = node["repeat"].get("count")
        if not isinstance(count, int):
            raise ModelError("P1 checker: activity repeat needs a constant count")
        return _expand_node(test, node["body"], depth) * count
    raise ModelError(f"P1 checker: activity node {sorted(node)} is not supported yet")


def _segment(records: List[Record]) -> List[List[Record]]:
    """Split records into occurrences: each ``act`` and the ``chk`` and ``acc``
    records after it (§4.12: in sequential code an access belongs to the most
    recent ``act``, as a checkpoint does)."""
    groups: List[List[Record]] = []
    for r in records:
        if r.kind == "act":
            groups.append([r])
        elif r.kind in ("chk", "acc"):
            if not groups:
                raise _Fail(f"{r.kind} record before any act record: {r.describe()}")
            groups[-1].append(r)
        elif r.kind == "end":
            continue
        else:
            raise _Fail(f"P1 checker does not accept {r.kind!r} records: {r.describe()}")
    return groups


def _field_sort(test: Test, spec) -> Tuple[Sort, bool]:
    """A model field entry: a sort name, or ``{"sort": ..., "observe": false}``."""
    sorts = test.model.get("sorts")
    if isinstance(spec, str):
        return resolve_sort(spec, sorts), True
    return resolve_sort(spec["sort"], sorts), bool(spec.get("observe", True))


def _check_occurrence(test: Test, type_name: str, group: List[Record],
                      problem: Problem) -> None:
    t = test.type(type_name)
    act, recs = group[0], group[1:]
    scope = Scope()

    fields = t.get("fields", {}) or {}
    observed = {}
    for name, spec in fields.items():
        sort, obs = _field_sort(test, spec)
        if obs:
            observed[name] = sort
        else:
            scope.bind_symbol(name, problem.fresh(f"{type_name}.{name}", sort))
    _check_keys(act, set(observed), f"act {act.tag}")
    for name, sort in observed.items():
        scope.bind_value(name, sort, _typed(act, name, sort))

    for c in t.get("constraints", []) or []:
        problem.add(c["smt"], scope, f"{type_name}: {c.get('pss', c['smt'])} ({act.describe()})")

    body = t.get("body")
    pos = _match_body(test, body, recs, 0, scope, problem) if body else 0
    if pos < len(recs):
        raise _Fail(f"unexpected {recs[pos].kind} record in {type_name}: "
                    f"{recs[pos].describe()}")


def _check_keys(rec: Record, want: set, what: str) -> None:
    got = set(rec.fields)
    if got != want:
        missing = sorted(want - got)
        extra = sorted(got - want)
        parts = []
        if missing:
            parts.append(f"missing {missing}")
        if extra:
            parts.append(f"unexpected {extra}")
        raise _Fail(f"{what}: keys {', '.join(parts)}: {rec.describe()}")


def _typed(rec: Record, key: str, sort: Sort):
    tok = rec.fields[key]
    v = parse_value(tok)
    if v is None or not sort.admits(v):
        raise _Fail(f"{rec.tag}.{key}={tok} is not a value of sort {sort.smt()}"
                    f"{' (signed)' if sort.signed else ''}: {rec.describe()}")
    return v


def _match_body(test: Test, node: Dict[str, Any], recs: List[Record], pos: int,
                scope: Scope, problem: Problem) -> int:
    if "seq" in node:
        for n in node["seq"]:
            pos = _match_body(test, n, recs, pos, scope, problem)
        return pos

    if "repeat" in node:
        spec = node["repeat"]
        count = spec.get("count")
        if isinstance(count, dict):
            count = smt.eval_int(count["smt"], scope)
        if not isinstance(count, int):
            raise ModelError(f"repeat count {count!r} is neither an int nor {{smt}}")
        index = spec.get("index")
        for k in range(count):
            inner = scope.child()
            if index:
                inner.bind_value("$" + index, INDEX_SORT, k)
            pos = _match_body(test, node["body"], recs, pos, inner, problem)
        return pos

    if "chk" in node:
        return _match_leaf(test, node, recs, pos, scope, problem)

    if "acc" in node:
        return _match_acc(test, node, recs, pos, scope, problem)

    raise ModelError(f"P1 checker: body node {sorted(node)} is not supported yet")


def _match_leaf(test: Test, node: Dict[str, Any], recs: List[Record], pos: int,
                scope: Scope, problem: Problem) -> int:
    tag = node["chk"]
    if pos >= len(recs):
        raise _Fail(f"missing chk {tag!r}: the occurrence's records ended "
                    f"after {len(recs)} record(s)")
    rec = recs[pos]
    if rec.kind != "chk" or rec.tag != tag:
        raise _Fail(f"expected chk {tag!r}, got {rec.describe()}")

    eq = node.get("eq", {}) or {}
    fields = node.get("fields", {}) or {}
    _check_keys(rec, set(eq) | set(fields), f"chk {tag}")

    for k, want in eq.items():
        if not value_matches(rec.fields[k], want):
            shown = json.dumps(want)
            raise _Fail(f"{tag}.{k}={rec.fields[k]}, expected {shown}: {rec.describe()}")

    if fields:
        leaf = scope.child()
        for k, spec in fields.items():
            sort, _ = _field_sort(test, spec)
            leaf.bind_value(k, sort, _typed(rec, k, sort))
        for w in node.get("where", []) or []:
            problem.add(w["smt"], leaf, f"{tag}: {w.get('pss', w['smt'])} ({rec.describe()})")
    return pos + 1


#: The fields of an ``acc`` record, by operation kind (§4.12).
_ADDR_SORT = Sort("bv", 64, False)
_COUNT_SORT = Sort("bv", 32, False)


def _match_acc(test: Test, node: Dict[str, Any], recs: List[Record], pos: int,
               scope: Scope, problem: Problem) -> int:
    """One ``acc`` leaf (§6.8): an access record of the named operation.

    A read's ``data`` is always checked against the executor tap's value for
    its address (``tap.tap_read``), whatever the leaf says: the tap is PSS the
    tool compiled, and a tool that miscompiles its arithmetic must fail here
    rather than feed its own values to the rest of the test.

    ``"as": name`` binds the record's ``data`` for later leaves' ``where``.
    """
    op = node["acc"]
    if op not in ACC_OPS:
        raise ModelError(f"acc leaf: unknown operation {op!r}; one of "
                         f"{', '.join(ACC_OPS)}")
    if pos >= len(recs):
        raise _Fail(f"missing acc {op!r}: the occurrence's records ended "
                    f"after {len(recs)} record(s)")
    rec = recs[pos]
    if rec.kind != "acc" or rec.tag != op:
        raise _Fail(f"expected acc {op!r}, got {rec.describe()}")

    width = ACC_OPS[op]
    sorts = {"addr": _ADDR_SORT, "data": Sort("bv", width, False)}
    if op in BYTE_OPS:
        sorts.update(i=_COUNT_SORT, n=_COUNT_SORT)
    _check_keys(rec, set(sorts), f"acc {op}")
    vals = {k: _typed(rec, k, sort) for k, sort in sorts.items()}

    if op.startswith("r"):
        at = vals["addr"] + vals.get("i", 0)
        want = tap_read(at, width)
        if vals["data"] != want:
            raise _Fail(f"acc {op}: read data 0x{vals['data']:x} at 0x{at:x} is "
                        f"not the executor tap's value 0x{want:x} (F8, §4.12): "
                        f"{rec.describe()}")

    eq = node.get("eq", {}) or {}
    bad = sorted(set(eq) - set(sorts))
    if bad:
        raise ModelError(f"acc leaf {op!r}: eq names {bad}, which an {op} record "
                         f"does not have")
    for k, want in eq.items():
        if not value_matches(rec.fields[k], want):
            raise _Fail(f"acc {op}.{k}={rec.fields[k]}, expected "
                        f"{json.dumps(want)}: {rec.describe()}")

    where = node.get("where", []) or []
    if where:
        leaf = scope.child()
        for k, sort in sorts.items():
            leaf.bind_value(k, sort, vals[k])
        for w in where:
            problem.add(w["smt"], leaf,
                        f"acc {op}: {w.get('pss', w['smt'])} ({rec.describe()})")

    name = node.get("as")
    if name:
        scope.bind_value(name, sorts["data"], vals["data"])
    return pos + 1
