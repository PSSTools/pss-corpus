"""The checker (§6.4): decide whether one run's log is a legal execution.

Stage 1 (outcome) and stage 2 (structure) cover activities built from
traversals, ``seq``, ``par`` and ``schedule`` (with any join), ``select``,
activity ``constraint`` statements and constant ``repeat``/``replicate``,
and atomic ``body`` patterns (§6.7) built from ``seq``, ``repeat`` and
``chk`` leaves. An observer (``"role": "observer"``) prints an ``obs``
record; a ``"traced": false`` action prints none. Where order or choice is
open, stage 2 enumerates every way the activity can produce the trace
(which branch each occurrence belongs to, which ``select`` branch was
taken) and stage 3 solves each until one is SAT; no SAT match is a FAIL
with the first match's reason. Such a trace is checked up to 64
occurrences (§6.4's budget); beyond that, or when the matches are too many,
the verdict is ERROR.

Stage 3 is one SMT problem per run over the observed values. It walks the
activity again: a traversal's ``label`` binds the handle to that occurrence,
and entering a block or a loop iteration unbinds the handles traversed in it
(LRM 13.4.8). A compound's constraints, a traversal's ``with`` and an
activity ``constraint`` are asserted whenever every handle they name is
bound, once per distinct set of occurrences. A compound's fields, and an
untraced action's, are unobserved constants. A run whose leaves are all exact
(``eq``) and whose actions have no constraints never starts the solver.

A ``select`` branch's ``guard`` is asserted on the branch taken; its
``weight`` is not checked.

Flow objects (Rule C, §6.5): an action's ``refs`` (``{"o": {"dir": "output",
"type": T, "pool"?: P}}``, T a ``buffer``/``stream``/``state`` type) add
its object fields as record keys ``o.<field>``, under T's constraints.
Every input of a traced occurrence must be fed by an output of T on the same
pool (default: T's name) and reads that output's values: a buffer by an
earlier occurrence not parallel with it; a stream by one in a par/schedule
with it, each stream output feeding exactly one input; a state by the
latest earlier writer, or the pool's initial state when there is none (only
the state type's ``"initial": [smt...]`` constraints hold for it). A state
type's ``"prev": [smt...]`` constraints, over ``|f|`` and ``|prev.f|``, hold
on each output relative to the pool's object before it. An activity ``bind`` (``[["p.o", "c.i"]]``) pins the producer;
otherwise the solver picks among the legal ones. Producer order is trace
order.

Resources (§6.4, §6.5): a ref ``{"dir": "lock"|"share", "type": R,
"pool"?: "<comp>.<pool>"}`` of a ``resource`` type R adds the record key
``r.instance_id`` (and R's fields), which must be below the pool's ``size``
(``components.<comp>.pools.<pool>``; default the one pool of type R; no
size = 1). Two occurrences in different ``par`` branches never lock the same
instance of a pool, nor lock and share it; ``schedule`` branches may have been
serialized, so they are not checked.

Inference (§6.4 stage 2, §6.5 Rule J): when the model says ``"inference":
{"allowed": true}``, a record the activity does not account for may be an
inferred action that feeds a needed input; otherwise it fails the run. A
``{"seq": [...], "atomic": true}`` node is an ``atomic`` block (11.3.7): no
inferred action may run between its first and last occurrence.
"""

import dataclasses as dc
import itertools
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
COVERAGE_SCHEMA = "pss-corpus/coverage/1.0"

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
    #: with ``check --plan``: PASS, PLAN-FAIL (the plan is not a legal run) or
    #: REALISE-FAIL (a legal plan the trace did not carry out); None without one
    plan: Optional[str] = None
    #: the run's structure (`structure_key`), for the enumeration oracle
    structure: Optional[tuple] = None

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
    if test.expect != "ok" and test.expect_diagnostics:
        # a rejection, or an expected run-time error (CF-err), must say where
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
    except ProtocolError as e:
        v.verdict = FAIL
        v.reason = f"protocol violation: {e}"
        return v
    return judge_records(test, records, v, run_dir)


def judge_records(test: Test, records: List[Record], v: Verdict,
                  run_dir: Optional[str] = None) -> Verdict:
    """Stages 2-4 on *records* (a log's, or a plan's rendered as records):
    *v* filled in and returned. Coverage is checked when *run_dir* is given."""
    try:
        groups = _segment(records)
        res, first = None, None
        for n, (occs, assign) in enumerate(_match(test, groups)):
            if n >= SOLVE_CAP:
                raise ModelError(f"no legal match among the first {SOLVE_CAP} ways "
                                 f"to match the trace; the test is too ambiguous to check")
            try:
                problem = Problem()
                _Walk(test, groups, problem, assign).root()
                got = smt.solve(problem)
            except _Fail as e:
                first = first or e
                continue
            if got.sat:
                res = got
                v.occurrences = occs
                v.structure = structure_key(assign)
                break
            first = first or _Fail("observed values violate: " + "; ".join(got.core))
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

    if res is None:
        # Every way to match failed: report the first (in a flat activity,
        # the only one).
        v.verdict = FAIL
        v.reason = str(first)
        return v
    v.witness = res.witness
    if test.expect_coverage and run_dir is not None:
        return _check_coverage(test, run_dir, v)
    v.verdict = PASS
    return v


#: The text of a record `enumerate_structures` makes: its values are free.
_ENUMERATED = "<enumerated>"


def _free(rec: Record) -> bool:
    return rec.text == _ENUMERATED


def structure_key(assign: Dict[tuple, Any]) -> tuple:
    """A run's structure, from stage 2's match: the type of each activity
    occurrence and the branch each ``select`` took, plus the inferred types
    as a multiset. Not the order, so the interleavings of a ``par`` are one
    structure."""
    # Stage 3 adds ("occ", ("inf", gi)) entries for the inferred ones.
    fixed = sorted((repr(k), v[0] if k[0] == "occ" else v) for k, v in assign.items()
                   if k[0] != "inf" and not (k[1] and k[1][0] == "inf"))
    inferred = sorted(v for k, v in assign.items() if k[0] == "inf")
    return tuple(fixed), tuple(inferred)


def enumerate_structures(test: Test, max_occ: int = 6, max_inferred: int = 2,
                         cap: int = 20000) -> Tuple[Dict[tuple, Tuple[str, ...]], bool]:
    """All-SAT over stage 3 (activity design §9.3): every structure of a
    legal run of *test* with at most *max_occ* traced occurrences, at most
    *max_inferred* of them inferred. Each order the activity allows is made
    into value-free records and solved; a structure is legal when one of its
    orders is SAT. Returns {`structure_key`: a legal order (type names)} and
    whether some run was cut off at *max_occ* (then the set is a lower bound).
    More than *cap* solves is a ModelError: the model is not tiny."""
    term, _ = _compile(test, test.root, (), 0)
    inferable = _inferable(test)
    found: Dict[tuple, Tuple[str, ...]] = {}
    truncated = False
    solves = 0

    def legal(order: Tuple[str, ...], assign: Dict[tuple, Any]) -> bool:
        groups = [[Record(test.record_kind(n), test.record_tag(n), {}, gi + 1, _ENUMERATED)]
                  for gi, n in enumerate(order)]
        try:
            problem = Problem()
            _Walk(test, groups, problem, assign).root()
            return smt.solve(problem).sat
        except _Fail:
            return False

    stack = [(term, (), ())]
    while stack:
        t, made, order = stack.pop()
        for n in (_nulls(t) if _nullable(t) else ()):
            assign = dict(made)
            assign.update(n)
            key = structure_key(assign)
            if key in found:
                continue
            solves += 1
            if solves > cap:
                raise ModelError(f"more than {cap} candidate runs; the model is too large to enumerate")
            if legal(order, assign):
                found[key] = order
        nexts = sorted(_firsts(t))
        n_inf = sum(1 for k, _ in made if k[0] == "inf")
        can_infer = inferable and n_inf < max_inferred and not _in_atomic(t)
        if len(order) >= max_occ:
            truncated = truncated or bool(nexts) or bool(can_infer)
            continue
        gi = len(order)
        for n in nexts:
            for rest, m in _step(t, lambda x, n=n: x == n):
                stack.append((rest, made + tuple((k, (v, gi) if k[0] == "occ" else v) for k, v in m),
                              order + (n,)))
        for n in (inferable if can_infer else ()):
            stack.append((t, made + ((("inf", gi), n),), order + (n,)))
    return found, truncated


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
# CF-cov: functional coverage
# --------------------------------------------------------------------------- #

def _read_coverage(run_dir: str) -> Optional[List[Dict[str, Any]]]:
    """The run's ``coverage.json`` covergroups, or None when the adapter wrote none.

    ``{"schema": COVERAGE_SCHEMA, "covergroups": [{"name", "instance"?, "samples",
    "coverpoints": {cp: {bin: hits}}, "crosses": {cx: [{"bins": [..], "hits"}]}}]}``.
    ``name`` is the covergroup type's qualified name; an inline covergroup's type
    is named after its instance in the enclosing type (``pss_top::A::cs``).
    """
    fn = os.path.join(run_dir, "coverage.json")
    if not os.path.isfile(fn):
        return None
    with open(fn) as fp:
        doc = json.load(fp)
    if not isinstance(doc, dict) or doc.get("schema") != COVERAGE_SCHEMA:
        raise ModelError(f"coverage.json schema is not {COVERAGE_SCHEMA!r}")
    cgs = doc.get("covergroups")
    if not isinstance(cgs, list) or not all(isinstance(c, dict) and isinstance(c.get("name"), str)
                                            for c in cgs):
        raise ModelError("coverage.json: 'covergroups' is not a list of named objects")
    return cgs


def _observed(cgs: List[Dict[str, Any]], want: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """Hits for one expectation, summed over the covergroup's instances.

    None when no instance of the covergroup was reported. A bin a tool leaves
    out of its export counts as never hit.
    """
    insts = [c for c in cgs if c["name"] == want["covergroup"]]
    if "coverpoint" in want:
        what = f"{want['covergroup']}.{want['coverpoint']}.{want['bin']}"
        n = sum(int(c.get("coverpoints", {}).get(want["coverpoint"], {}).get(want["bin"], 0))
                for c in insts)
    elif "cross" in want:
        what = f"{want['covergroup']}.{want['cross']}<{','.join(want['bins'])}>"
        n = sum(int(b.get("hits", 0)) for c in insts
                for b in c.get("crosses", {}).get(want["cross"], [])
                if list(b.get("bins", [])) == list(want["bins"]))
    else:
        what = f"{want['covergroup']} samples"
        n = sum(int(c.get("samples", 0)) for c in insts)
    return (n if insts else None), what


def _hits_ok(n: int, want) -> bool:
    if isinstance(want, list):
        return want[0] <= n <= want[1]
    return n == want


def _check_coverage(test: Test, run_dir: str, v: Verdict) -> Verdict:
    """Compare the run's coverage export with ``expect.coverage`` (CF-cov).

    Runs after the trace check passed: each expectation names a covergroup and
    either its ``samples``, a coverpoint ``bin`` or a cross's ``bins``, with
    ``hits`` (exact) or ``[lo, hi]``.
    """
    try:
        cgs = _read_coverage(run_dir)
    except (OSError, ValueError) as e:
        v.reason = f"coverage.json unreadable: {e}"
        return v
    except ModelError as e:
        v.reason = str(e)
        return v
    if cgs is None:
        v.verdict = FAIL
        v.reason = "the test expects functional coverage, but the run wrote no coverage.json"
        return v
    for want in test.expect_coverage:
        n, what = _observed(cgs, want)
        hits = want["samples"] if "samples" in want else want["hits"]
        if n is None and hits != 0 and hits != [0, 0]:
            v.verdict = FAIL
            v.reason = f"covergroup {want['covergroup']!r} not in coverage.json"
            return v
        if not _hits_ok(n or 0, hits):
            v.verdict = FAIL
            v.reason = f"{what}: {n or 0} hits, expected {hits}"
            return v
    v.verdict = PASS
    return v


# --------------------------------------------------------------------------- #
# Stage 2 + 3: structure, then data
# --------------------------------------------------------------------------- #

#: Stage 2 gives up (ERROR) beyond this many partial matches alive at once,
#: or this many candidate matches solved without a SAT one (§6.4: a test
#: whose trace is too ambiguous to check is a bad test, not a FAIL).
FRONTIER_CAP = 4096
SOLVE_CAP = 512
#: An activity with par/schedule/select is checked only up to this many
#: occurrences (§6.4's record budget).
RECORD_BUDGET = 64
#: Rule J ranks (§6.5): one per inferred occurrence, at most RECORD_BUDGET.
_RANK = Sort("bv", 8)

# Stage 2 terms: the traced occurrences an activity may still produce.
# ("leaf", path, type) | ("seq", items) | ("par", items) |
# ("sel", key, ((branch, term), ...)); key None records no choice;
# ("atom", (term,)) an atomic block not yet entered, ("open", (term,)) one
# entered and not finished: no inferred action may run inside it (11.3.7).
_EMPTY = ("seq", ())


def _mk(kind: str, items) -> tuple:
    items = tuple(i for i in items if i != _EMPTY)
    if not items:
        return _EMPTY
    if len(items) == 1:
        return items[0]
    if kind == "par":
        items = tuple(sorted(items, key=repr))  # par is unordered: dedupe states
    return (kind, items)


def _compile(test: Test, type_name: str, path: tuple, depth: int) -> Tuple[tuple, bool]:
    """A traversal of *type_name* at occurrence *path*, as a stage-2 term,
    and whether any order or choice in it is left open."""
    if depth > 32:
        raise ModelError(f"activity nesting too deep at {type_name!r}")
    t = test.type(type_name)
    if t.get("atomic", False):
        return (("leaf", path, type_name) if test.traced(type_name) else _EMPTY), False
    act = t.get("activity")
    if act is None:
        raise ModelError(f"compound {type_name!r} has no activity")
    return _compile_node(test, act, path, depth + 1)


def _compile_node(test: Test, node: Dict[str, Any], path: tuple, depth: int) -> Tuple[tuple, bool]:
    if "do" in node:
        return _compile(test, node["do"], path, depth)
    if "seq" in node:
        t, open_ = _compile_seq(test, node["seq"], path, 0, depth)
        if node.get("atomic", False) and t != _EMPTY:
            t = ("atom", (t,))
        return t, open_
    if "constraint" in node or "bind" in node:
        return _EMPTY, False
    for kw in ("par", "schedule"):
        if kw in node:
            # A schedule's members may run in any order or overlap (13.3.6):
            # in a trace, any interleaving, as for par.
            items = [_compile_node(test, n, path + (i,), depth) for i, n in enumerate(node[kw])]
            return _mk("par", [t for t, _ in items]), True
    if "select" in node:
        branches = []
        for i, br in enumerate(node["select"]):
            t, _ = _compile_node(test, br["body"], path + (i,), depth)
            branches.append((i, t))
        return ("sel", path, tuple(branches)), True
    # `replicate` in a sequential scope is its body `count` times in
    # sequence (LRM 11.5.1), which is what a constant `repeat` is. A model
    # uses it only where that holds: not directly in parallel/schedule, and
    # with no iteration label.
    for kw in ("repeat", "replicate"):
        if kw in node:
            count = node[kw].get("count")
            if not isinstance(count, int):
                raise ModelError(f"checker: activity {kw} needs a constant count")
            items = [_compile_node(test, node["body"], path + (k,), depth) for k in range(count)]
            return _mk("seq", [t for t, _ in items]), any(o for _, o in items)
    raise ModelError(f"checker: activity node {sorted(node)} is not supported yet")


def _join(node: Dict[str, Any]) -> Tuple[str, Any]:
    """A par/schedule's join (13.3.5): ``("all", None)``, ``("none", None)``,
    ``("first", N)`` (join_first and join_select: any N branches) or
    ``("branch", [labels])``."""
    j = node.get("join", "all")
    kind, _, arg = j.partition(":")
    if kind in ("all", "none") and not arg:
        return kind, None
    if kind in ("first", "select") and arg.isdigit():
        return "first", int(arg)
    if kind == "branch" and arg:
        return "branch", arg.split(",")
    raise ModelError(f"checker: unknown join {j!r}")


def _compile_seq(test: Test, nodes: List[Dict[str, Any]], path: tuple, start: int,
                 depth: int) -> Tuple[tuple, bool]:
    items: List[tuple] = []
    open_ = False
    for i in range(start, len(nodes)):
        n = nodes[i]
        kw = "par" if "par" in n else "schedule" if "schedule" in n else None
        kind = _join(n)[0] if kw else "all"
        if kind == "all" or i == len(nodes) - 1:
            t, o = _compile_node(test, n, path + (i,), depth)
            items.append(t)
            open_ = open_ or o
            continue
        # A join other than `all`: the statement after the block waits only
        # for the joined branches (13.3.5); the others run on beside the rest
        # of this sequence and end with it.
        kind, arg = _join(n)
        branches = [_compile_node(test, b, path + (i, k), depth)[0]
                    for k, b in enumerate(n[kw])]
        rest, _ = _compile_seq(test, nodes, path, i + 1, depth)
        if kind == "branch":
            labels = [b.get("label") for b in n[kw]]
            missing = [lb for lb in arg if lb not in labels]
            if missing:
                raise ModelError(f"join_branch names no top-level branch {missing}")
            subsets = [[k for k, lb in enumerate(labels) if lb in arg]]
        elif kind == "first":
            subsets = [list(c) for c in itertools.combinations(range(len(branches)), min(arg, len(branches)))]
        else:
            subsets = [[]]
        alts = []
        for sub in subsets:
            joined = _mk("seq", [_mk("par", [branches[k] for k in sub]), rest])
            alts.append(_mk("par", [b for k, b in enumerate(branches) if k not in sub] + [joined]))
        tail = alts[0] if len(alts) == 1 else ("sel", None, tuple(enumerate(alts)))
        items.append(tail)
        return _mk("seq", items), True
    return _mk("seq", items), open_


def _in_atomic(t: tuple) -> bool:
    if t[0] == "open":
        return True
    if t[0] in ("leaf", "atom"):
        return False
    if t[0] == "sel":
        return any(_in_atomic(b) for _, b in t[2])
    return any(_in_atomic(i) for i in t[1])


def _nullable(t: tuple) -> bool:
    if t[0] == "leaf":
        return False
    if t[0] == "sel":
        return any(_nullable(b) for _, b in t[2])
    return all(_nullable(i) for i in t[1])


def _nulls(t: tuple):
    """Each set of select choices that lets *t* produce nothing more."""
    if t[0] == "leaf":
        return
    if t[0] == "sel":
        for k, b in t[2]:
            for rest in _nulls(b):
                yield rest + (((("sel", t[1]), k),) if t[1] is not None else ())
        return
    acc = [()]
    for i in t[1]:
        acc = [a + b for a in acc for b in _nulls(i)]
        if not acc:
            return
    yield from acc


def _firsts(t: tuple) -> set:
    """The types *t* may produce next."""
    if t[0] == "leaf":
        return {t[2]}
    if t[0] == "sel":
        return set().union(*(_firsts(b) for _, b in t[2]))
    out = set()
    for i in t[1]:
        out |= _firsts(i)
        if t[0] == "seq" and not _nullable(i):
            break
    return out


def _step(t: tuple, want):
    """Each way *t* produces one occurrence of a type *want* accepts: the
    term left, and the choices made ((key, value) pairs)."""
    kind = t[0]
    if kind == "leaf":
        if want(t[2]):
            yield _EMPTY, ((("occ", t[1]), t[2]),)
        return
    if kind == "sel":
        for k, b in t[2]:
            for rest, made in _step(b, want):
                yield rest, made + (((("sel", t[1]), k),) if t[1] is not None else ())
        return
    items = t[1]
    if kind in ("atom", "open"):
        for rest, made in _step(items[0], want):
            yield (("open", (rest,)) if rest != _EMPTY else _EMPTY), made
        return
    if kind == "par":
        for i, it in enumerate(items):
            for rest, made in _step(it, want):
                yield _mk("par", items[:i] + (rest,) + items[i + 1:]), made
        return
    skipped = [()]
    for i, it in enumerate(items):
        for rest, made in _step(it, want):
            for s in skipped:
                yield _mk("seq", (rest,) + items[i + 1:]), s + made
        skipped = [s + n for s in skipped for n in _nulls(it)]
        if not skipped:
            return


def _describe_types(test: Test, types) -> str:
    want = sorted({(test.record_kind(n), test.record_tag(n)) for n in types})
    if len(want) == 1:
        return f"{want[0][0]} {want[0][1]!r}"
    return "one of " + ", ".join(f"{k} {g!r}" for k, g in want)


def _match(test: Test, groups: List[List[Record]]):
    """Stage 2: each way the activity can produce the trace's occurrences, as
    {("occ", path): type, ("sel", path): branch} plus the group order. A
    path is the occurrence's place in the activity tree: child indices and
    loop iterations, as `_Walk` counts them."""
    term, open_ = _compile(test, test.root, (), 0)
    inferable = _inferable(test)
    open_ = open_ or bool(inferable)
    if open_ and len(groups) > RECORD_BUDGET:
        raise ModelError(f"trace has {len(groups)} occurrences; the checker matches "
                         f"at most {RECORD_BUDGET} where order or choice is open")
    frontier = [(term, ())]
    for gi, group in enumerate(groups):
        head = group[0]

        def want(n, head=head):
            return (test.record_kind(n), test.record_tag(n)) == (head.kind, head.tag)

        nxt = []
        for t, made in frontier:
            for rest, m in _step(t, want):
                nxt.append((rest, made + tuple((k, (v, gi) if k[0] == "occ" else v)
                                               for k, v in m)))
            # Or an inferred action (§6.4 stage 2): the activity is unchanged;
            # stage 3 decides whether it was needed (Rule J). Never inside
            # an atomic block the trace has entered (11.3.7); in a par this
            # is conservative, as trace order is all the checker sees.
            for n in (inferable if not _in_atomic(t) else ()):
                if want(n):
                    nxt.append((t, made + ((("inf", gi), n),)))
        if not nxt:
            firsts = set().union(*(_firsts(t) for t, _ in frontier))
            if not firsts:
                raise _Fail(f"unexpected occurrence: {head.describe()}")
            raise _Fail(f"occurrence #{gi + 1} is {head.describe()}; "
                        f"expected {_describe_types(test, firsts)}")
        if len(nxt) > FRONTIER_CAP:
            raise ModelError(f"more than {FRONTIER_CAP} ways to match the first "
                             f"{gi + 1} occurrences; the test is too ambiguous to check")
        frontier = nxt
    done = [(t, m) for t, m in frontier if _nullable(t)]
    if not done:
        firsts = set().union(*(_firsts(t) for t, _ in frontier))
        raise _Fail(f"trace ended after {len(groups)} action occurrence(s); "
                    f"expected occurrence #{len(groups) + 1} of {_describe_types(test, firsts)}")
    for t, made in done:
        for n in _nulls(t):
            assign = dict(made)
            assign.update(n)
            order = [""] * len(groups)
            for k, v in made:
                if k[0] == "occ":
                    order[v[1]] = v[0]
                elif k[0] == "inf":
                    order[k[1]] = ("inf", k[1])
            yield order, assign


def _inferable(test: Test) -> List[str]:
    """The atomic types a tool may infer when the model allows inference: a
    traced action with an output that some input in the model could consume,
    or a stream input that some output needs consumed (§6.4: "of a type able
    to satisfy a binding demand")."""
    if not (test.model.get("inference", {}) or {}).get("allowed", False):
        return []
    types = test.model.get("types", {}) or {}
    wanted = {r["type"] for t in types.values() for r in (t.get("refs", {}) or {}).values()
              if r.get("dir") == "input"}
    streams_out = {r["type"] for t in types.values() for r in (t.get("refs", {}) or {}).values()
                   if r.get("dir") == "output" and (types.get(r["type"]) or {}).get("kind") == "stream"}
    out = []
    for n, t in sorted(types.items()):
        if t.get("kind") != "action" or not t.get("atomic", False) or not test.traced(n):
            continue
        refs = (t.get("refs", {}) or {}).values()
        if any((r.get("dir") == "output" and r["type"] in wanted)
               or (r.get("dir") == "input" and r["type"] in streams_out) for r in refs):
            out.append(n)
    return out


def _segment(records: List[Record]) -> List[List[Record]]:
    """Split records into occurrences: each ``act`` or ``obs`` and the ``chk``
    and ``acc`` records after it (§4.12: in sequential code an access belongs
    to the most recent ``act``, as a checkpoint does)."""
    groups: List[List[Record]] = []
    for r in records:
        if r.kind in ("act", "obs"):
            groups.append([r])
        elif r.kind in ("chk", "acc"):
            if not groups:
                raise _Fail(f"{r.kind} record before any act record: {r.describe()}")
            groups[_owner(groups, r)].append(r)
        elif r.kind == "end":
            continue
        else:
            raise _Fail(f"P1 checker does not accept {r.kind!r} records: {r.describe()}")
    return groups


def _owner(groups: List[List[Record]], r: Record) -> int:
    """The group a ``chk`` record belongs to: the most recent one, unless its
    tag is ``<Action>.<rung>`` (a yield ladder's, §4.9) and the most recent
    is another action's -- then the latest occurrence of ``<Action>``, whose
    body resumed after the others ran."""
    last = len(groups) - 1
    if r.kind != "chk" or "." not in r.tag:
        return last
    who = r.tag.split(".", 1)[0]
    for i in range(last, -1, -1):
        if groups[i][0].tag.rsplit("::", 1)[-1] == who:
            return i
    return last


def _field_sort(test: Test, spec) -> Tuple[Sort, bool]:
    """A model field entry: a sort name, or ``{"sort": ..., "observe": false}``."""
    sorts = test.model.get("sorts")
    if isinstance(spec, str):
        return resolve_sort(spec, sorts), True
    return resolve_sort(spec["sort"], sorts), bool(spec.get("observe", True))


def _labels(node: Dict[str, Any]) -> List[str]:
    """The handles traversed in activity *node* and the blocks nested in it
    -- not in the activities of the types it traverses."""
    if "do" in node:
        return [node["label"]] if node.get("label") else []
    out: List[str] = []
    for kw in ("seq", "par", "schedule"):
        for n in node.get(kw, []):
            out.extend(_labels(n))
    for br in node.get("select", []):
        out.extend(_labels(br["body"]))
    if "body" in node:
        out.extend(_labels(node["body"]))
    return out


#: A name that is a handle of the occurrence, not traversed (yet, or since its
#: block was entered): a constraint naming it is vacuous for now (13.4.8).
_UNBOUND = object()


@dc.dataclass
class _Occ:
    """One occurrence of an action: its fields' values (literals for observed
    ones, solver constants otherwise) and, for a compound, the occurrence each
    of its handles is bound to now."""

    type_name: str
    scope: Scope
    labels: set
    env: Dict[str, "_Occ"] = dc.field(default_factory=dict)

    def lookup(self, path: str):
        """*path*'s SMT term, ``_UNBOUND``, or None when it is not a name here."""
        if path in self.scope.bindings:
            return self.scope.bindings[path]
        head, dot, rest = path.partition(".")
        if head in self.labels:
            occ = self.env.get(head)
            if occ is None:
                return _UNBOUND
            if not dot:
                raise ModelError(f"{self.type_name}: handle {head!r} used as a value")
            return occ.lookup(rest)
        return None


@dc.dataclass
class _Constraint:
    """A constraint in force: a type's (``outer`` None) or a ``with`` (names
    resolve in the traversed occurrence, then ``outer``; ``this.`` is outer).
    It must hold for every set of occurrences its handles are bound to at
    once (13.4.8), so it is asserted once per distinct instance."""

    term: Dict[str, Any]
    occ: _Occ
    outer: Optional[_Occ]
    what: str
    seen: set = dc.field(default_factory=set)

    def resolve(self, name: str):
        if name.startswith("this."):
            return (self.outer or self.occ).lookup(name[5:])
        got = self.occ.lookup(name)
        if got is None and self.outer is not None:
            got = self.outer.lookup(name)
        return got


class _Walk:
    """Stage 3's walk: the activity again, now with each traced occurrence's
    records (stage 2 matched the structure). It binds handles as they are
    traversed, resets them on entry to a block or loop iteration (13.4.8),
    and asserts each constraint in force whenever its handles are all bound."""

    def __init__(self, test: Test, groups: List[List[Record]], problem: Problem,
                 assign: Dict[tuple, Any]):
        self.test = test
        self.groups = groups
        self.problem = problem
        #: stage 2's match: ("occ", path) -> (type, group), ("sel", path) -> branch
        self.assign = assign
        self.active: List[_Constraint] = []
        self.last: Optional[Record] = None
        #: every flow-object ref of a traced occurrence (Rule C)
        self.refs: List[_Ref] = []
        #: explicit `bind`s: (input ref, output ref)
        self.bound: List[Tuple[_Ref, _Ref]] = []
        #: path -> "par" | "schedule" for each concurrent block walked
        self.conc: Dict[tuple, str] = {}
        #: id(producer occurrence) -> [(selector, consumer ref)] (Rule J)
        self.supplies: Dict[int, List[Tuple[str, "_Ref"]]] = {}
        #: an observed ``uid`` -> the action it was printed by: each action
        #: traversal in a run has its own (PSS 3.1 built-in ``uid``)
        self.uids: Dict[int, str] = {}

    def root(self) -> None:
        self.occurrence(self.test.root, None, None, [], ())
        # Inferred occurrences (stage 2's ("inf", group) keys): outside the
        # activity, at path ("inf", group).
        inferred = []
        for k, n in sorted((k, v) for k, v in self.assign.items() if k[0] == "inf"):
            path = ("inf", k[1])
            self.assign[("occ", path)] = (n, k[1])
            inferred.append((self.occurrence(n, None, None, [], path), k[1]))
        self.feed()
        self.state_apart()
        self.prev()
        self.justify(inferred)
        self.exclude()

    def occurrence(self, type_name: str, outer: Optional[_Occ],
                   label: Optional[str], with_: List[Dict[str, Any]], path: tuple) -> _Occ:
        test, problem = self.test, self.problem
        t = test.type(type_name)
        atomic = t.get("atomic", False)
        group = None
        if atomic and test.traced(type_name):
            group = self.groups[self.assign[("occ", path)][1]]
            self.last = group[0]

        scope = Scope()
        observed = {}
        fields = dict(t.get("fields", {}) or {})
        refs = t.get("refs", {}) or {}
        for rname, r in refs.items():
            # A ref's object fields are the action's fields "<ref>.<field>".
            for f, spec in _obj_fields(_object(test, r)).items():
                fields.setdefault(f"{rname}.{f}", spec)
        for name, spec in fields.items():
            sort, obs = _field_sort(test, spec)
            if obs and group is not None and not _free(group[0]):
                observed[name] = sort
            else:
                scope.bind_symbol(name, problem.fresh(f"{type_name}.{name}", sort))
        if group is not None:
            act = group[0]
            _check_keys(act, set(observed), f"{act.kind} {act.tag}")
            for name, sort in observed.items():
                scope.bind_value(name, sort, _typed(act, name, sort))
            if "uid" in observed and not _free(act):
                u = _typed(act, "uid", observed["uid"])
                if u in self.uids:
                    raise _Fail(f"{type_name}: uid {u} is also {self.uids[u]}'s: "
                                f"each action has its own uid: {act.describe()}")
                self.uids[u] = act.tag

        occ = _Occ(type_name, scope,
                   set() if atomic else set(_labels(t.get("activity", {}))))
        if outer is not None and label:
            outer.env[label] = occ
        for rname, r in refs.items():
            obj = _object(test, r)
            for c in obj.get("constraints", []) or []:
                env = {f: scope.bindings[f"{rname}.{f}"] for f in _obj_fields(obj)}
                problem.assert_term(smt.unparse(smt.substitute(smt.parse(c["smt"]), env)),
                                    f"{type_name}.{rname}: {r['type']}: {c.get('pss', c['smt'])}")
            if obj["kind"] == "resource":
                # An instance of the bound pool (§6.5 table).
                size = _pool_size(test, r)
                sort, _ = _field_sort(test, _obj_fields(obj)["instance_id"])
                problem.assert_term(f"(bvult {scope.bindings[f'{rname}.instance_id']} "
                                    f"{sort.literal(size)})",
                                    f"{type_name}.{rname}.instance_id < {size} "
                                    f"(pool {r.get('pool', r['type'])!r})")
            if group is not None:
                self.refs.append(_Ref(occ, self.assign[("occ", path)][1], path, rname,
                                      r["dir"], r["type"], obj["kind"],
                                      r.get("pool", r["type"])))

        mark = len(self.active)
        for c in t.get("constraints", []) or []:
            self.active.append(_Constraint(c, occ, None, type_name))
        for c in with_:
            self.active.append(_Constraint(
                c, occ, outer, f"{outer.type_name if outer else '?'}: "
                               f"{label or type_name} with"))
        self.fire()

        if group is not None:
            recs = group[1:]
            body = t.get("body")
            pos = _match_body(test, body, recs, 0, scope, problem) if body and not _free(group[0]) else 0
            if pos < len(recs):
                raise _Fail(f"unexpected {recs[pos].kind} record in {type_name}: "
                            f"{recs[pos].describe()}")
        if not atomic:
            self.node(t["activity"], occ, path, top=True)
        del self.active[mark:]
        return occ

    def node(self, node: Dict[str, Any], occ: _Occ, path: tuple, top: bool = False) -> None:
        if "do" in node:
            self.occurrence(node["do"], occ, node.get("label"), node.get("with", []) or [], path)
            return
        if "seq" in node:
            if not top:
                self.reset(node, occ)
            mark = len(self.active)
            # An activity constraint holds in its whole block (13.1.9 b.3).
            for n in node["seq"]:
                for c in n.get("constraint", []) if "constraint" in n else []:
                    self.active.append(_Constraint(c, occ, None, f"{occ.type_name}: activity"))
            self.fire()
            for i, n in enumerate(node["seq"]):
                if "constraint" not in n and "bind" not in n:
                    self.node(n, occ, path + (i,))
            # A bind may come before or after the traversals it names.
            for n in node["seq"]:
                if "bind" in n:
                    self.bind(n, occ)
            del self.active[mark:]
            return
        if "bind" in node:
            self.bind(node, occ)
            return
        if "constraint" in node:
            mark = len(self.active)
            for c in node["constraint"]:
                self.active.append(_Constraint(c, occ, None, f"{occ.type_name}: activity"))
            self.fire()
            del self.active[mark:]
            return
        for kw in ("par", "schedule"):
            if kw in node:
                # Stage 2 fixed which records each branch's occurrences are;
                # the data does not depend on their order.
                if not top:
                    self.reset(node, occ)
                self.conc[path] = kw
                for i, n in enumerate(node[kw]):
                    self.node(n, occ, path + (i,))
                return
        if "select" in node:
            if not top:
                self.reset(node, occ)
            k = self.assign[("sel", path)]
            br = node["select"][k]
            mark = len(self.active)
            # Only a branch whose guard holds may be taken (13.4.6).
            if "guard" in br:
                g = br["guard"]
                self.active.append(_Constraint(g if isinstance(g, dict) else {"smt": g}, occ, None,
                                               f"{occ.type_name}: select branch {k} guard"))
            self.fire()
            self.node(br["body"], occ, path + (k,))
            del self.active[mark:]
            return
        for kw in ("repeat", "replicate"):
            if kw in node:
                for k in range(node[kw]["count"]):
                    self.reset(node["body"], occ)
                    self.node(node["body"], occ, path + (k,), top=True)
                return

    def bind(self, node: Dict[str, Any], occ: _Occ) -> None:
        """``{"bind": [["p.o", "c.i"], ...]}``: the input is fed by that
        output. A pair naming a handle not traversed (a ``select`` branch not
        taken) is vacuous."""
        for pair in node["bind"]:
            ends = []
            for name in pair:
                head, dot, rname = name.partition(".")
                if not dot or head not in occ.labels:
                    raise ModelError(f"{occ.type_name}: bind {name!r}: the checker binds "
                                     f"refs of traversed handles only (<label>.<ref>)")
                ends.append(occ.env.get(head) and next(
                    (r for r in self.refs if r.occ is occ.env[head] and r.name == rname), None))
            if not all(ends):
                continue
            ins = [r for r in ends if r.dir == "input"]
            outs = [r for r in ends if r.dir == "output"]
            if len(ins) != 1 or len(outs) != 1:
                raise ModelError(f"{occ.type_name}: bind {pair}: the checker binds one "
                                 f"output to one input")
            self.bound.append((ins[0], outs[0]))

    def prev(self) -> None:
        """A state type's ``"prev"`` constraints (LRM 13.3) hold on each
        written object, ``prev.<f>`` being the pool's object before it: the
        latest earlier writer's output, or the initial state (fresh values
        under the type's ``"initial"`` constraints). They are vacuous for
        the initial object itself."""
        for p in self.refs:
            if p.kind != "state" or p.dir != "output":
                continue
            obj = _object(self.test, {"type": p.type})
            if not obj.get("prev"):
                continue
            fields = _obj_fields(obj)
            env = {f: p.occ.scope.bindings[f"{p.name}.{f}"] for f in fields}
            before = [q for q in self.refs if q.dir == "output" and q.group < p.group
                      and (q.type, q.pool) == (p.type, p.pool)]
            if before:
                q = max(before, key=lambda q: q.group)
                env.update({f"prev.{f}": q.occ.scope.bindings[f"{q.name}.{f}"]
                            for f in fields})
            else:
                init = {f: self.problem.fresh(f"{p.pool}.initial.{f}",
                                              _field_sort(self.test, spec)[0])
                        for f, spec in fields.items()}
                for k in obj.get("initial", []) or []:
                    self.problem.assert_term(
                        smt.unparse(smt.substitute(smt.parse(k["smt"]), init)),
                        f"{p.pool}: the initial state: {k.get('pss', k['smt'])}")
                env.update({f"prev.{f}": v for f, v in init.items()})
            for k in obj["prev"]:
                self.problem.assert_term(
                    smt.unparse(smt.substitute(smt.parse(k["smt"]), env)),
                    f"{p.describe()}: {p.type}: {k.get('pss', k['smt'])}")

    def feed(self) -> None:
        """Rule C (§6.5): every input ref is fed by a legal producer, and a
        stream output by exactly one consumer. The values the producer wrote
        are the values the consumer read; which producer is left to the
        solver where more than one is legal."""
        forced: Dict[int, List["_Ref"]] = {}
        for i, o in self.bound:
            forced.setdefault(id(i), []).append(o)
        stream_out: Dict[int, List[str]] = {}
        for c in self.refs:
            if c.dir != "input":
                continue
            outs = [p for p in self.refs if p.dir == "output" and p.occ is not c.occ
                    and (p.type, p.pool) == (c.type, c.pool)]
            legal = [p for p in outs if self.may_feed(p, c)]
            if c.kind == "state":
                # The pool's most recent preceding writer, or its initial state.
                legal = sorted(legal, key=lambda p: p.group)[-1:]
            if id(c) in forced:
                bad = [p for p in forced[id(c)] if p not in legal]
                if bad:
                    raise _Fail(f"bound {bad[0].describe()} cannot feed {c.describe()}: "
                                f"{self.why_not(bad[0], c)}")
                legal = forced[id(c)]
            if not legal:
                if c.kind == "state":
                    # The initial state: the type's "initial" constraints
                    # (its `initial -> ...` constraints, 14.3) hold.
                    obj = _object(self.test, {"type": c.type})
                    env = {f: c.occ.scope.bindings[f"{c.name}.{f}"] for f in _obj_fields(obj)}
                    for k in obj.get("initial", []) or []:
                        self.problem.assert_term(
                            smt.unparse(smt.substitute(smt.parse(k["smt"]), env)),
                            f"{c.describe()} reads the initial state: {k.get('pss', k['smt'])}")
                    continue
                raise _Fail(f"unfed input: no {c.kind} output of {c.type!r} on pool "
                            f"{c.pool!r} can feed {c.describe()}"
                            + (f" ({self.why_not(outs[0], c)})" if outs else ""))
            sels = []
            for p in legal:
                eq = " ".join(f"(= {c.occ.scope.bindings[f'{c.name}.{f}']} "
                              f"{p.occ.scope.bindings[f'{p.name}.{f}']})"
                              for f in _object(self.test, {"type": c.type})["fields"])
                s = self.problem.fresh(f"bind.{c.name}", Sort("bool"))
                sels.append(s)
                self.problem.assert_term(f"(=> {s} (and true {eq}))",
                                         f"{c.describe()} reads what {p.describe()} wrote")
                self.supplies.setdefault(id(p.occ), []).append((s, c))
                if c.kind == "stream":
                    stream_out.setdefault(id(p), []).append(s)
                    # A stream output needs a consumer: an inferred one is
                    # justified by the producer it pairs with (Rule J).
                    self.supplies.setdefault(id(c.occ), []).append((s, p))
            self.problem.assert_term(f"(or false {' '.join(sels)})",
                                     f"{c.describe()} is fed by "
                                     + " or ".join(p.describe() for p in legal))
            for x, y in itertools.combinations(sels, 2):
                self.problem.assert_term(f"(not (and {x} {y}))",
                                         f"{c.describe()} is fed by exactly one output")
        for p in self.refs:
            if p.kind != "stream" or p.dir != "output":
                continue
            sels = stream_out.get(id(p), [])
            if not sels:
                raise _Fail(f"stream output {p.describe()} has no consumer")
            self.problem.assert_term(f"(or false {' '.join(sels)})",
                                     f"{p.describe()} has a consumer")
            for a, b in itertools.combinations(sels, 2):
                self.problem.assert_term(f"(not (and {a} {b}))",
                                         f"{p.describe()} has only one consumer")

    def justify(self, inferred: List[Tuple[_Occ, int]]) -> None:
        """Rule J (§6.5): an inferred occurrence feeds at least one input of
        an occurrence of lower rank; explicit occurrences have rank 0, so
        every chain ends at the activity and no two inferred actions justify
        each other."""
        rank: Dict[int, str] = {}
        for o, _ in inferred:
            rank[id(o)] = self.problem.fresh(f"rank.{o.type_name}", _RANK)
        for o, g in inferred:
            what = f"inferred {o.type_name} (occurrence #{g + 1})"
            sup = self.supplies.get(id(o), [])
            if not sup:
                raise _Fail(f"{what} satisfies no demand: no input could consume its outputs"
                            " and it consumes no stream that needs a consumer")
            alts = " ".join(f"(and {s} (bvult {rank.get(id(c.occ), _RANK.literal(0))} "
                            f"{rank[id(o)]}))" for s, c in sup)
            self.problem.assert_term(f"(or false {alts})",
                                     f"{what} is needed: it pairs with "
                                     + " or ".join(c.describe() for _, c in sup))

    def exclude(self) -> None:
        """Resource exclusion (§6.4): two occurrences in different branches
        of one ``par`` never lock the same instance of a pool, nor lock and
        share it. Branches of a ``schedule`` may have been serialized, which
        a trace of atomic points cannot tell apart, so they are not checked."""
        res = [r for r in self.refs if r.kind == "resource"]
        for a, b in itertools.combinations(res, 2):
            if (a.occ is b.occ or (a.type, a.pool) != (b.type, b.pool)
                    or "lock" not in (a.dir, b.dir) or self.lca(a, b) != "par"):
                continue
            self.problem.assert_term(
                f"(not (= {a.occ.scope.bindings[f'{a.name}.instance_id']} "
                f"{b.occ.scope.bindings[f'{b.name}.instance_id']}))",
                f"{a.describe()} ({a.dir}) and {b.describe()} ({b.dir}) run in parallel "
                f"on pool {a.pool!r}, so they claim different instances")

    def lca(self, a: "_Ref", b: "_Ref") -> Optional[str]:
        """"par"/"schedule" when the two occurrences are branches of one
        concurrent block, None when they are in sequence, and "inferred" when
        one was inferred (its place relative to the activity is unknown: only
        the trace order says anything)."""
        if a.path != b.path and "inf" in (a.path[:1] + b.path[:1]):
            return "inferred"
        n = 0
        while n < min(len(a.path), len(b.path)) and a.path[n] == b.path[n]:
            n += 1
        return self.conc.get(a.path[:n])

    def state_apart(self) -> None:
        """A state writer runs apart from every other reader or writer of
        its pool (13.3.1): their records do not interleave."""
        refs = [r for r in self.refs if r.kind == "state"]
        for w in refs:
            if w.dir != "output":
                continue
            ws = self.groups[w.group]
            for r in refs:
                if r.group == w.group or (r.type, r.pool) != (w.type, w.pool) or \
                        (r.dir == "output" and r.group < w.group):
                    continue
                rs = self.groups[r.group]
                if ws[0].line < rs[-1].line and rs[0].line < ws[-1].line:
                    raise _Fail(f"{w.describe()} overlaps {r.describe()}: a state "
                                f"writer runs apart from its pool's other readers "
                                f"and writers (13.3.1)")

    def may_feed(self, p: "_Ref", c: "_Ref") -> bool:
        return self.why_not(p, c) is None

    def why_not(self, p: "_Ref", c: "_Ref") -> Optional[str]:
        lca = self.lca(p, c)
        if c.kind == "stream":
            return None if lca else "a stream's producer and consumer must run in parallel"
        if p.group > c.group:
            return f"{p.describe()} ran after {c.describe()}"
        if c.kind == "state" and p.group != c.group and \
                self.groups[p.group][-1].line > self.groups[c.group][0].line:
            # The write is in progress until its writer's last record: a
            # reader starting earlier cannot see it (13.3.1).
            return f"{p.describe()} had not completed when {c.describe()} started"
        if lca == "par" and c.kind != "state":
            # A state writer and its pool's readers never overlap, even in
            # parallel (13.3.1): the trace order says which ran first.
            return f"{p.describe()} runs in parallel with {c.describe()}"
        return None

    def reset(self, node: Dict[str, Any], occ: _Occ) -> None:
        """Entry to an activity block: the handles traversed in it are
        uninitialized again (13.4.8)."""
        for lb in _labels(node):
            occ.env.pop(lb, None)

    def fire(self) -> None:
        """Assert each constraint in force whose handles are all bound, once
        per distinct instance."""
        for c in self.active:
            term = smt.parse(c.term["smt"])
            env: Dict[str, str] = {}
            vacuous = False
            for name in smt.symbols(term):
                got = c.resolve(name)
                if got is _UNBOUND:
                    vacuous = True
                    break
                if got is not None:
                    env[name] = got
            if vacuous:
                continue
            text = smt.unparse(smt.substitute(term, env))
            if text in c.seen:
                continue
            c.seen.add(text)
            where = f" ({self.last.describe()})" if self.last is not None else ""
            self.problem.assert_term(
                text, f"{c.what}: {c.term.get('pss', c.term['smt'])}{where}")


@dc.dataclass(eq=False)
class _Ref:
    """One flow-object ref of a traced atomic occurrence."""

    occ: _Occ
    group: int          # the occurrence's index in the trace
    path: tuple
    name: str
    dir: str            # "input" | "output" | "lock" | "share"
    type: str           # the object type
    kind: str           # "buffer" | "stream" | "state" | "resource"
    pool: str

    def describe(self) -> str:
        return f"{self.occ.type_name}.{self.name} (occurrence #{self.group + 1})"


def _object(test: Test, ref: Dict[str, Any]) -> Dict[str, Any]:
    obj = test.type(ref["type"])
    kind = obj.get("kind")
    if kind not in ("buffer", "stream", "state", "resource"):
        raise ModelError(f"ref type {ref['type']!r} is not a buffer, stream, state or resource")
    dirs = ("lock", "share") if kind == "resource" else ("input", "output")
    if "dir" in ref and ref["dir"] not in dirs:
        raise ModelError(f"a {kind} ref of {ref['type']!r} is {ref['dir']!r}, "
                         f"not {' or '.join(dirs)}")
    return obj


def _obj_fields(obj: Dict[str, Any]) -> Dict[str, Any]:
    """An object type's fields; a resource also has ``instance_id`` (u32)."""
    fields = dict(obj.get("fields", {}) or {})
    if obj["kind"] == "resource":
        fields.setdefault("instance_id", "u32")
    return fields


def _pool_size(test: Test, ref: Dict[str, Any]) -> int:
    """The size of the pool a resource ref claims from: ``components.<c>.pools.<p>``
    named ``"<c>.<p>"`` by the ref's ``pool``, else the one pool of its type.
    A pool without ``size`` has one instance."""
    pools = {f"{c}.{n}": p for c, comp in (test.model.get("components", {}) or {}).items()
             for n, p in (comp.get("pools", {}) or {}).items()}
    if "pool" in ref:
        p = pools.get(ref["pool"])
        if p is None:
            raise ModelError(f"resource pool {ref['pool']!r} is not in the model's components")
    else:
        of = [p for p in pools.values() if p.get("type") == ref["type"]]
        if len(of) != 1:
            raise ModelError(f"resource {ref['type']!r}: {len(of)} pools of that type in the "
                             f"model's components; name one with \"pool\"")
        p = of[0]
    return int(p.get("size", 1))


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
