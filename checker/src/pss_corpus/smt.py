"""The oracle: SMT-LIB2 terms from the model, decided by an SMT solver (§7).

Every ``where`` term, constraint and symbolic ``repeat`` count in a model is an
SMT-LIB2 string over the names in scope (action fields, a record's fields,
``$<index>`` loop indices). The checker never evaluates PSS itself: it binds
each name to a literal (observed) or a fresh constant (unobserved), renames so
that names from different scopes cannot collide, and hands the closed problem to
the solver.

Only the ``z3`` Python API is wired today. The problem is built as SMT-LIB2 text
so a second solver is a transport, not a rewrite (§7.2).
"""

import dataclasses as dc
import re
from typing import Dict, List, Optional, Tuple, Union

Sexp = Union[str, List["Sexp"]]

_TOKEN = re.compile(r"\s*(?:(\()|(\))|(\|[^|]*\|)|([^\s()|]+))")


class ModelError(Exception):
    """The model itself is wrong -- an ERROR verdict, never a tool FAIL."""


# --------------------------------------------------------------------------- #
# Sorts
# --------------------------------------------------------------------------- #

@dc.dataclass(frozen=True)
class Sort:
    """``bool``, or an N-bit vector read as signed or unsigned when printed."""

    kind: str               # "bool" | "bv"
    width: int = 0
    signed: bool = False

    def smt(self) -> str:
        return "Bool" if self.kind == "bool" else f"(_ BitVec {self.width})"

    def literal(self, v) -> str:
        if self.kind == "bool":
            return "true" if v else "false"
        return f"(_ bv{v & ((1 << self.width) - 1)} {self.width})"

    def admits(self, v) -> bool:
        """Is observed value *v* a value of this sort (no silent wrap)?"""
        if self.kind == "bool":
            return isinstance(v, bool)
        if isinstance(v, bool) or not isinstance(v, int):
            return False
        if self.signed:
            return -(1 << (self.width - 1)) <= v < (1 << (self.width - 1))
        return 0 <= v < (1 << self.width)


_SORT_NAME = re.compile(r"([us])([0-9]+)\Z")
_BV_TEXT = re.compile(r"\(_\s+BitVec\s+([0-9]+)\)\Z")


def resolve_sort(name: str, sorts: Optional[Dict[str, str]] = None) -> Sort:
    """A model sort name (``u8``, ``s32``, ``bool``, or one from ``sorts``)."""
    if name == "bool":
        return Sort("bool")
    m = _SORT_NAME.match(name)
    if m:
        return Sort("bv", int(m.group(2)), m.group(1) == "s")
    text = (sorts or {}).get(name)
    if text is not None:
        if text.strip() == "Bool":
            return Sort("bool")
        m = _BV_TEXT.match(text.strip())
        if m:
            return Sort("bv", int(m.group(1)), False)
    raise ModelError(f"unknown sort {name!r}")


# --------------------------------------------------------------------------- #
# S-expressions
# --------------------------------------------------------------------------- #

def parse(text: str) -> Sexp:
    toks = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise ModelError(f"cannot tokenize SMT term {text!r} at {pos}")
        pos = m.end()
        toks.append(m.group(1) or m.group(2) or m.group(3) or m.group(4))
    it = iter(toks)

    def build(tok):
        if tok == "(":
            out = []
            for t in it:
                if t == ")":
                    return out
                out.append(build(t))
            raise ModelError(f"unbalanced SMT term {text!r}")
        if tok == ")":
            raise ModelError(f"unbalanced SMT term {text!r}")
        return tok

    try:
        first = next(it)
    except StopIteration:
        raise ModelError("empty SMT term")
    res = build(first)
    if next(it, None) is not None:
        raise ModelError(f"trailing text in SMT term {text!r}")
    return res


def unparse(s: Sexp) -> str:
    if isinstance(s, list):
        return "(" + " ".join(unparse(x) for x in s) + ")"
    return s


def _bare(sym: str) -> str:
    return sym[1:-1] if sym.startswith("|") and sym.endswith("|") else sym


def substitute(s: Sexp, env: Dict[str, str]) -> Sexp:
    """Replace every symbol named in *env* (``|x|`` and ``x`` alike)."""
    if isinstance(s, list):
        return [substitute(x, env) for x in s]
    b = _bare(s)
    return env.get(b, s)


# --------------------------------------------------------------------------- #
# Problems
# --------------------------------------------------------------------------- #

@dc.dataclass
class Scope:
    """Names visible to one term: each maps to a literal or a declared constant."""

    bindings: Dict[str, str] = dc.field(default_factory=dict)

    def bind_value(self, name: str, sort: Sort, value) -> None:
        self.bindings[name] = sort.literal(value)

    def bind_symbol(self, name: str, symbol: str) -> None:
        self.bindings[name] = symbol

    def child(self) -> "Scope":
        return Scope(dict(self.bindings))


@dc.dataclass
class Problem:
    """A conjunction of closed assertions over some declared constants."""

    decls: Dict[str, Sort] = dc.field(default_factory=dict)
    #: (smt text after substitution, human label for the unsat report)
    asserts: List[Tuple[str, str]] = dc.field(default_factory=list)
    _n: int = 0

    def fresh(self, hint: str, sort: Sort) -> str:
        self._n += 1
        sym = "|%s#%d|" % (hint, self._n)
        self.decls[sym] = sort
        return sym

    def add(self, smt: str, scope: Scope, label: str) -> None:
        self.asserts.append((unparse(substitute(parse(smt), scope.bindings)), label))

    def script(self) -> str:
        """The problem as SMT-LIB2. Assertion *i* is guarded by the Boolean
        ``|$a<i>|`` so a core can name it (z3 folds a closed ``:named``
        assertion to ``false`` at parse time, which leaves the core empty)."""
        lines = [f"(declare-const {s} {sort.smt()})" for s, sort in self.decls.items()]
        for i, (a, _) in enumerate(self.asserts):
            lines.append(f"(declare-const |$a{i}| Bool)")
            lines.append(f"(assert (=> |$a{i}| {a}))")
        return "\n".join(lines)


@dc.dataclass
class Outcome:
    sat: bool
    #: labels of an unsat core (why the trace is illegal), when unsat
    core: List[str] = dc.field(default_factory=list)
    #: values of unobserved constants, when sat
    witness: Dict[str, str] = dc.field(default_factory=dict)


def solve(p: Problem) -> Outcome:
    if not p.asserts:
        return Outcome(sat=True)
    import z3
    s = z3.Solver()
    try:
        s.from_string(p.script())
    except z3.Z3Exception as e:
        raise ModelError(f"ill-formed SMT problem: {e}\n{p.script()}")
    guards = [z3.Bool(f"$a{i}") for i in range(len(p.asserts))]
    r = s.check(*guards)
    if r == z3.sat:
        m = s.model()
        return Outcome(sat=True, witness={str(d): str(m[d]) for d in m.decls()
                                          if not str(d).startswith("$a")})
    if r == z3.unsat:
        core = [p.asserts[int(str(c)[2:])][1] for c in s.unsat_core()]
        return Outcome(sat=False, core=sorted(core))
    raise ModelError(f"solver returned {r} (budget exceeded?)")


def eval_int(smt: str, scope: Scope) -> int:
    """Evaluate a closed bit-vector term to an unsigned integer (e.g. a repeat count)."""
    import z3
    text = unparse(substitute(parse(smt), scope.bindings))
    try:
        term = z3.parse_smt2_string(f"(assert (= {text} {text}))")[0].arg(0)
    except z3.Z3Exception as ex:
        raise ModelError(f"cannot evaluate {smt!r}: {ex}")
    val = z3.simplify(term)
    if not z3.is_bv_value(val):
        raise ModelError(f"term {smt!r} is not a closed bit-vector term: {val}")
    return val.as_long()
