"""Legal results synthesized from a model alone, for the checker's self-tests.

A positive test with only exact (``eq``) leaves gets the trace a correct tool
would print. A negative test gets a ``compile_error`` with one error at each
expected location. :mod:`perfect_tool` wraps this as an adapter.
"""

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


def _expand(t, name, out):
    ty = t.model["types"][name]
    if ty.get("atomic"):
        if ty.get("fields"):
            return False
        out.append(f"@@PSS-TRACE act {name}")
        return _body_lines(ty.get("body"), out)
    return _act_node(t, ty["activity"], out)


def _act_node(t, node, out):
    if "do" in node:
        return _expand(t, node["do"], out)
    if "seq" in node:
        return all(_act_node(t, n, out) for n in node["seq"])
    return False


def synth(t):
    """The trace lines of a legal run of positive test *t*, or None if not synthesizable."""
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
