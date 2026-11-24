"""Legal results synthesized from a model alone, for the checker's self-tests.

A positive test with only exact (``eq``) leaves gets the trace a correct tool
would print. A negative test gets its expected outcome with one error at each
expected location. :mod:`perfect_tool` wraps this as an adapter.
"""

import copy
import json
import os
import re
import tempfile

from pss_corpus import PASS, check_run
from pss_corpus.check import _field_sort, _obj_fields
from pss_corpus.model import Test as _Test
from pss_corpus.tap import ACC_OPS, BYTE_OPS, tap_read


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _body_lines(node, out):
    if node is None:
        return True
    if "seq" in node:
        return all(_body_lines(n, out) for n in node["seq"])
    if "repeat" in node:
        c = node["repeat"]["count"]
        if not isinstance(c, int):
            return False
        return all(_body_lines(node["body"], out) for _ in range(c))
    if "chk" in node:
        if node.get("fields"):
            return False
        kv = " ".join(f"{k}={_fmt(v)}" for k, v in node.get("eq", {}).items())
        out.append(f"@@PSS-TRACE chk {node['chk']}" + (f" {kv}" if kv else ""))
        return True
    if "acc" in node:
        # An access record as the executor tap prints it: addr and data in
        # 0x hex (`0x%x`). A read's data is the tap's value when the leaf
        # leaves it out.
        eq = node.get("eq", {})
        op = node["acc"]
        if node.get("where") or "addr" not in eq or op in BYTE_OPS:
            return False
        data = eq.get("data")
        if data is None:
            if not op.startswith("r"):
                return False
            data = tap_read(eq["addr"], ACC_OPS[op])
        out.append(f"@@PSS-TRACE acc {op} addr=0x{eq['addr']:x} data=0x{data:x}")
        return True
    return False


def _expand(t, name, out, values=None, free=None):
    ty = t.model["types"][name]
    if ty.get("atomic"):
        fields = ty.get("fields") or {}
        if free is not None:
            # Values left to the solver: an act record with none, noted.
            if t.traced(name):
                free.append((len(out), name))
            out.append(f"@@PSS-TRACE act {name}")
            return _body_lines(ty.get("body"), out)
        values = values or {}
        # Ref fields (an input's object) are never fixed by a `with`.
        if set(_record_fields(t, name)) - set(values) or ty.get("constraints"):
            return False
        kv = "".join(f" {f}={values[f]}" for f in fields)
        out.append(f"@@PSS-TRACE act {name}{kv}")
        return _body_lines(ty.get("body"), out)
    return _act_node(t, ty["activity"], out, free)


_EQ = re.compile(r"^\(= (\w+) #([xb])([0-9a-fA-F]+)\)$")


def _with_values(node):
    """Field values fixed by a traversal's ``with`` (each ``(= f #x..)``), or None."""
    vals = {}
    for c in node.get("with", []):
        m = _EQ.match(c.get("smt", ""))
        if not m:
            return None
        vals[m.group(1)] = int(m.group(3), 16 if m.group(2) == "x" else 2)
    return vals


def _act_node(t, node, out, free=None):
    if "do" in node:
        if free is not None:
            return _expand(t, node["do"], out, None, free)
        vals = _with_values(node)
        return vals is not None and _expand(t, node["do"], out, vals)
    if "seq" in node:
        return all(_act_node(t, n, out, free) for n in node["seq"])
    if free is not None:
        if "constraint" in node:
            return True
        # One legal interleaving of a par or schedule: each branch in turn.
        for kw in ("par", "schedule"):
            if kw in node and node.get("join", "all") == "all":
                return all(_act_node(t, n, out, free) for n in node[kw])
    for kw in ("repeat", "replicate"):
        if kw in node and isinstance(node[kw].get("count"), int):
            return all(_act_node(t, node["body"], out, free)
                       for _ in range(node[kw]["count"]))
    return False


def _solved(t):
    """The trace of a legal run whose action field values the solver picks.

    The skeleton (act records without values) is checked against a copy of
    the model in which every action field is unobserved, so the checker's
    own walk declares one constant per field of each occurrence, in trace
    order; its witness gives the values."""
    lines, free = [], []
    if not _act_node(t, {"do": t.root}, lines, free):
        return None
    model = copy.deepcopy(t.model)
    for ty in model["types"].values():
        if ty.get("kind") == "resource":
            ty["fields"] = dict(ty.get("fields") or {})
            ty["fields"].setdefault("instance_id", "u32")
        for f, spec in (ty.get("fields") or {}).items():
            spec = {"sort": spec} if isinstance(spec, str) else dict(spec)
            ty["fields"][f] = dict(spec, observe=False)
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "log.txt"), "w") as fp:
            fp.write("\n".join(lines) + "\n")
        with open(os.path.join(d, "outcome.json"), "w") as fp:
            json.dump({"outcome": "ok"}, fp)
        v = check_run(_Test(t.path, model), d)
    if v.verdict != PASS:
        return None
    # "|<type>.<field>#<n>|" -> value, per (type, field) in walk order.
    got = {}
    for sym, val in sorted(v.witness.items(), key=lambda kv: _serial(kv[0])):
        base = re.sub(r"#\d+$", "", sym.strip("|"))
        for name in model["types"]:
            if base.startswith(name + "."):
                got.setdefault((name, base[len(name) + 1:]), []).append(val)
    used = {}
    # Every action has its own uid: one the solver left free gets a value no
    # other uid has.
    uids = {int(v) for (_, f), vals in got.items() if f == "uid" for v in vals}
    for i, name in free:
        kv = ""
        for f, spec in _record_fields(t, name).items():
            sort, obs = _field_sort(t, spec)
            if not obs:
                continue
            k = used.get((name, f), 0)
            used[(name, f)] = k + 1
            vals = got.get((name, f), [])
            val = vals[k] if k < len(vals) else None
            if f == "uid" and val is None:
                val = next(n for n in range(1 << 16) if n not in uids)
                uids.add(val)
            kv += f" {f}={_render(val, sort)}"
        lines[i] += kv
    return lines


def _record_fields(t, name):
    """The keys of an act record of *name*: its fields, then ``<ref>.<field>``."""
    ty = t.model["types"][name]
    fields = dict(ty.get("fields") or {})
    for r, ref in (ty.get("refs") or {}).items():
        for f, spec in _obj_fields(t.type(ref["type"])).items():
            fields.setdefault(f"{r}.{f}", spec)
    return fields


def _serial(sym):
    m = re.search(r"#(\d+)\|?$", sym)
    return int(m.group(1)) if m else 0


def _render(val, sort):
    """A z3 model value (or None: unconstrained) as the trace prints it."""
    if sort.kind == "bool":
        return "true" if val == "True" else "false"
    n = int(val) if val is not None else 0
    if sort.signed and n >= 1 << (sort.width - 1):
        n -= 1 << sort.width
    return str(n)


def synth(t):
    """The trace lines of a legal run of positive test *t*, or None if not synthesizable."""
    if t.expect != "ok":
        return None
    return synth_exact(t) or _solved(t)


def synth_exact(t):
    """The trace of positive test *t* when the model fixes every value, or None."""
    if t.expect != "ok":
        return None
    lines = []
    return lines if _expand(t, t.root, lines) else None


def synth_diagnostics(t, file_prefix=""):
    """One error at each location negative test *t* expects."""
    out = []
    for d in t.expect_diagnostics:
        line = d["line"] if "line" in d else d["lines"][0]
        out.append({"severity": "error", "file": file_prefix + d["file"],
                    "line": line, "column": 1, "message": "synthesized"})
    return out


def synth_coverage(t):
    """A coverage export (CF-cov) that meets *t*'s ``expect.coverage``, or None."""
    if not t.expect_coverage:
        return None
    cgs = {}
    for w in t.expect_coverage:
        cg = cgs.setdefault(w["covergroup"], {"name": w["covergroup"], "samples": 0,
                                              "coverpoints": {}, "crosses": {}})
        hits = w["samples"] if "samples" in w else w["hits"]
        n = hits[0] if isinstance(hits, list) else hits
        if "coverpoint" in w:
            cg["coverpoints"].setdefault(w["coverpoint"], {})[w["bin"]] = n
        elif "cross" in w:
            cg["crosses"].setdefault(w["cross"], []).append({"bins": list(w["bins"]), "hits": n})
        else:
            cg["samples"] = n
    return {"schema": "pss-corpus/coverage/1.0", "covergroups": list(cgs.values())}
