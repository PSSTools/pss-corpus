"""Plan adjudication (``check --plan``): judge a tool's ``plan.json``
(``schema/plan-1.0.json``) with no execution, and whether a run realised it.

A plan *is* an occurrence graph with values. Its traced occurrences are
rendered as the records a run of it would print, in start order, and judged
like a trace; the parts a trace cannot show (which output fed which input,
which instance each claim got, what ran before what) are checked against the
plan's own occurrences. A wrong plan is a ``PLAN-FAIL``: the generator decided
wrongly.

With a trace as well, a second, independent check matches every record of
the run to an occurrence of the plan with the same type and values, in an
order the plan allows. A legal plan the run did not carry out, or carried out
illegally, is a ``REALISE-FAIL``: the runtime executed a correct plan wrongly.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .check import (ERROR, FAIL, PASS, Verdict, _field_sort, _obj_fields, _object,
                    _segment, check_run, judge_records)
from .model import Test
from .smt import ModelError
from .trace import ProtocolError, Record, extract, parse_value

PLAN_FAIL, REALISE_FAIL = "PLAN-FAIL", "REALISE-FAIL"
PLAN_FORMAT, PLAN_VERSION = "pss-plan", "1.0"

#: Partial matches tried before the realisation check gives up (an ERROR).
MATCH_CAP = 100000


class _PlanFail(Exception):
    """The plan is not a legal run of the test."""


def check(test: Test, run_dir: Optional[str], plan_path: str,
          seed: Optional[int] = None) -> Verdict:
    """``check --plan``: the plan, then (when *run_dir* holds a log) the run
    and whether it realised the plan. With no log, the plan alone is judged."""
    try:
        with open(plan_path) as fp:
            doc = json.load(fp)
    except (OSError, ValueError) as e:
        return Verdict(test=test.id, rev=test.rev, seed=seed, verdict=ERROR,
                       reason=f"plan unreadable: {e}")
    log = os.path.join(run_dir, "log.txt") if run_dir else None
    if log is None or not os.path.exists(log):
        return check_plan(test, doc, seed)
    pv = check_plan(test, doc, seed)
    if pv.verdict != PASS:
        return pv
    v = check_run(test, run_dir, seed)
    v.plan = PASS
    if v.verdict == FAIL:
        v.plan = REALISE_FAIL
        v.reason = f"{REALISE_FAIL}: the plan is legal but the run is not: {v.reason}"
        return v
    if v.verdict != PASS:
        return v
    try:
        with open(log, errors="replace") as fp:
            records = extract(fp.read())
        realised(test, doc, records)
    except _PlanFail as e:
        v.verdict, v.plan = FAIL, REALISE_FAIL
        v.reason = f"{REALISE_FAIL}: {e}"
    except (ProtocolError, ModelError) as e:
        v.verdict, v.reason = ERROR, f"realisation check: {e}"
    return v


def check_plan(test: Test, doc: Dict[str, Any], seed: Optional[int] = None) -> Verdict:
    """Is *doc* a legal run of *test*? PASS, or FAIL with ``plan`` PLAN-FAIL."""
    v = Verdict(test=test.id, rev=test.rev, seed=seed, verdict=ERROR, outcome="ok")
    if test.expect != "ok":
        v.reason = f"a plan cannot be judged against a negative test (expect {test.expect!r})"
        return v
    try:
        records = render(test, doc)
        _consistent(test, doc)
    except _PlanFail as e:
        v.verdict, v.plan = FAIL, PLAN_FAIL
        v.reason = f"{PLAN_FAIL}: {e}"
        return v
    except ModelError as e:
        v.reason = f"model error: {e}"
        return v
    v = judge_records(test, records, v)
    if v.verdict == FAIL:
        v.plan = PLAN_FAIL
        v.reason = f"{PLAN_FAIL}: {v.reason}"
    elif v.verdict == PASS:
        v.plan = PASS
    return v


# --------------------------------------------------------------------------- #
# The plan as records
# --------------------------------------------------------------------------- #

def _occurrences(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    if doc.get("format") != PLAN_FORMAT or doc.get("version") != PLAN_VERSION:
        raise _PlanFail(f"not a {PLAN_FORMAT} {PLAN_VERSION} plan "
                        f"(format {doc.get('format')!r}, version {doc.get('version')!r})")
    occs = doc.get("occurrences")
    if not isinstance(occs, list):
        raise _PlanFail("plan has no occurrences list")
    for i, o in enumerate(occs):
        if not isinstance(o, dict) or o.get("id") != i:
            raise _PlanFail(f"occurrence #{i} does not have id {i}")
        if not isinstance(o.get("start"), int):
            raise _PlanFail(f"occurrence {i} has no start")
    return occs


def model_type(test: Test, qname: str) -> Optional[str]:
    """The model type a plan's qualified type names: the type itself, the
    type whose record tag it is, or the one type with its last name."""
    types = test.model.get("types", {})
    if qname in types:
        return qname
    for name in types:
        if test.record_tag(name) == qname:
            return name
    last = qname.rsplit("::", 1)[-1]
    hits = [n for n in types
            if n.rsplit("::", 1)[-1] == last or test.record_tag(n).rsplit("::", 1)[-1] == last]
    return hits[0] if len(hits) == 1 else None


def record_keys(test: Test, type_name: str) -> List[str]:
    """The keys an ``act`` record of *type_name* carries: its observed fields
    and those of its refs (``<ref>.<field>``), as stage 3 reads them."""
    t = test.type(type_name)
    fields = dict(t.get("fields", {}) or {})
    for rname, r in (t.get("refs", {}) or {}).items():
        for f, spec in _obj_fields(_object(test, r)).items():
            fields.setdefault(f"{rname}.{f}", spec)
    return [n for n, spec in fields.items() if _field_sort(test, spec)[1]]


def _token(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, str)):
        return str(v)
    return json.dumps(v, separators=(",", ":"))


def render(test: Test, doc: Dict[str, Any]) -> List[Record]:
    """The records a run of the plan prints, in start order. Each record's
    ``line`` is its occurrence id + 1, so a diagnostic names the occurrence."""
    occs = _occurrences(doc)
    root = [o for o in occs if o.get("site") is None]
    if len(root) != 1:
        raise _PlanFail(f"plan has {len(root)} root occurrences (site null); expected 1")
    if model_type(test, root[0]["type"]) != test.root:
        raise _PlanFail(f"plan's root is {root[0]['type']}, not the test's root {test.root}")
    out = []
    for o in sorted(occs, key=lambda o: o["start"]):
        if o.get("site") is None:
            continue
        name = model_type(test, o["type"])
        if name is None:
            raise _PlanFail(f"occurrence {o['id']} ({o.get('path')}): type {o['type']} "
                            f"is not in the model")
        t = test.type(name)
        if not t.get("atomic", False) or not test.traced(name):
            continue
        fields = o.get("fields", {}) or {}
        keys = [k for k in record_keys(test, name) if k in fields]
        text = " ".join([test.record_kind(name), test.record_tag(name)]
                        + [f"{k}={_token(fields[k])}" for k in keys])
        out.append(Record(kind=test.record_kind(name), tag=test.record_tag(name),
                          fields={k: _token(fields[k]) for k in keys},
                          line=o["id"] + 1, text=f"plan occurrence {o['id']} "
                                                 f"({o.get('path')}): {text}"))
    return out


# --------------------------------------------------------------------------- #
# What records cannot show: flow, resources, order
# --------------------------------------------------------------------------- #

def _before(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return a.get("end") is not None and a["end"] < b["start"]


def _overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return not (_before(a, b) or _before(b, a))


def _refs(test: Test, occ: Dict[str, Any], dirs: Tuple[str, ...], kind: str) -> List[str]:
    """The refs of *occ* that may hold a *kind* object: the model's, or, for
    a type that only lists ``<ref>.<field>`` leaves, every ``<ref>`` prefix in
    the plan's fields. Empty when nothing can be told: the check is skipped."""
    name = model_type(test, occ["type"])
    if name is None:
        return []
    refs = test.type(name).get("refs", {}) or {}
    if not refs:
        return sorted({k.rsplit(".", 1)[0] for k in (occ.get("fields", {}) or {}) if "." in k})
    return [r for r, spec in refs.items()
            if spec.get("dir") in dirs and _object(test, spec).get("kind") == kind]


def _carries(occ: Dict[str, Any], ref: str, fields: Dict[str, Any]) -> bool:
    """Does *occ* show the object's *fields* through *ref*? Leaves the plan
    leaves out are not held against it, but at least one must be there."""
    of = occ.get("fields", {}) or {}
    shown = [k for k in fields if f"{ref}.{k}" in of]
    return (bool(shown) or not fields) and all(of[f"{ref}.{k}"] == fields[k] for k in shown)


def _occ(occs: List[Dict[str, Any]], i: Any, what: str) -> Dict[str, Any]:
    if not isinstance(i, int) or not 0 <= i < len(occs):
        raise _PlanFail(f"{what} names occurrence {i!r}, which is not in the plan")
    return occs[i]


def _consistent(test: Test, doc: Dict[str, Any]) -> None:
    occs = _occurrences(doc)
    for o in occs:
        if o.get("end") is not None and o["end"] < o["start"]:
            raise _PlanFail(f"occurrence {o['id']} ({o.get('path')}) ends before it starts")
    for pair in doc.get("order", []) or []:
        a = _occ(occs, pair[0], "an order pair")
        b = _occ(occs, pair[1], "an order pair")
        if not _before(a, b):
            raise _PlanFail(f"order says {a['id']} ({a.get('path')}) ran before "
                            f"{b['id']} ({b.get('path')}), but their times overlap or cross")
    for f in doc.get("flow", []) or []:
        kind, fields = f.get("kind"), f.get("fields", {}) or {}
        what = f"flow object {f.get('id')} ({kind}{', ' + f['pool'] if f.get('pool') else ''})"
        prod = f.get("producer")
        if prod is not None:
            p = _occ(occs, prod, what)
            outs = _refs(test, p, ("output",), kind)
            if outs and not any(_carries(p, r, fields) for r in outs):
                raise _PlanFail(f"{what}: producer {p['id']} ({p.get('path')}) has no "
                                f"{kind} output with the object's values {fields}")
        elif kind != "state":
            raise _PlanFail(f"{what} has no producer (only an initial state object may)")
        cons = f.get("consumers", []) or []
        if kind == "stream" and len(cons) != 1:
            raise _PlanFail(f"{what} has {len(cons)} consumers; a stream has exactly one")
        for ci in cons:
            c = _occ(occs, ci, what)
            ins = _refs(test, c, ("input",), kind)
            if ins and not any(_carries(c, r, fields) for r in ins):
                raise _PlanFail(f"{what}: consumer {c['id']} ({c.get('path')}) has no "
                                f"{kind} input with the object's values {fields}")
            if prod is None:
                continue
            p = occs[prod]
            if kind == "stream" and not _overlap(p, c):
                raise _PlanFail(f"{what}: stream producer {p['id']} and consumer "
                                f"{c['id']} do not run together")
            if kind != "stream" and not _before(p, c):
                raise _PlanFail(f"{what}: consumer {c['id']} ({c.get('path')}) starts "
                                f"before producer {p['id']} ({p.get('path')}) ends")
    for r in doc.get("resources", []) or []:
        what = f"resource {r.get('pool')}[{r.get('instance')}]"
        claims = r.get("claims", []) or []
        for cl in claims:
            o = _occ(occs, cl.get("occ"), what)
            refs = _refs(test, o, ("lock", "share"), "resource")
            if refs and not any(_carries(o, x, {"instance_id": r.get("instance")}) for x in refs):
                raise _PlanFail(f"{what}: claimant {o['id']} ({o.get('path')}) reports "
                                f"another instance_id")
        for i, a in enumerate(claims):
            for b in claims[i + 1:]:
                if not (a.get("lock") or b.get("lock")):
                    continue
                oa, ob = occs[a["occ"]], occs[b["occ"]]
                if oa is not ob and _overlap(oa, ob):
                    raise _PlanFail(f"{what}: occurrences {oa['id']} ({oa.get('path')}) and "
                                    f"{ob['id']} ({ob.get('path')}) hold it at once, "
                                    f"and one locks it")


# --------------------------------------------------------------------------- #
# Did the run realise the plan?
# --------------------------------------------------------------------------- #

def _same(rec: Record, want: Record) -> bool:
    if (rec.kind, rec.tag) != (want.kind, want.tag) or set(rec.fields) != set(want.fields):
        return False
    return all(parse_value(rec.fields[k]) == parse_value(want.fields[k]) for k in rec.fields)


def realised(test: Test, doc: Dict[str, Any], records: List[Record]) -> None:
    """Raise :class:`_PlanFail` unless each of the run's occurrences is one of
    the plan's (same type and values), all are, and in an order the plan's
    ``order`` allows."""
    occs = _occurrences(doc)
    planned = render(test, doc)
    heads = [g[0] for g in _segment(records)]
    if len(heads) != len(planned):
        raise _PlanFail(f"the run has {len(heads)} occurrence(s); the plan has {len(planned)}")
    # transitive predecessors over all occurrences, then kept to traced ones
    succ: Dict[int, List[int]] = {}
    for a, b in doc.get("order", []) or []:
        succ.setdefault(a, []).append(b)
    preds: Dict[int, set] = {o["id"]: set() for o in occs}
    for a in list(succ):
        stack, seen = list(succ[a]), set()
        while stack:
            b = stack.pop()
            if b in seen:
                continue
            seen.add(b)
            preds.setdefault(b, set()).add(a)
            stack.extend(succ.get(b, []))
    ids = [p.line - 1 for p in planned]
    traced = set(ids)
    need = [preds.get(i, set()) & traced for i in ids]

    used: List[bool] = [False] * len(planned)
    done: set = set()
    tries = [0]
    best = [0]

    def go(k: int) -> bool:
        best[0] = max(best[0], k)
        if k == len(heads):
            return True
        for j, want in enumerate(planned):
            if used[j] or not need[j] <= done or not _same(heads[k], want):
                continue
            tries[0] += 1
            if tries[0] > MATCH_CAP:
                raise ModelError(f"more than {MATCH_CAP} ways to match the run to the plan")
            used[j] = True
            done.add(ids[j])
            if go(k + 1):
                return True
            used[j] = False
            done.discard(ids[j])
        return False

    if not go(0):
        rec = heads[best[0]]
        raise _PlanFail(f"run occurrence #{best[0] + 1} ({rec.describe()}) is no "
                        f"occurrence of the plan that may run there")
