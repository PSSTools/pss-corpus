"""The trace protocol (COMPLIANCE-DESIGN.md §4.2): pull records out of a log.

A record is the part of any log line after the first ``@@PSS-TRACE ``. Anything
before the sentinel is a tool's decoration and is ignored. Nothing after it is:
values are strict, so ``a=   3`` is a protocol violation, not ``3`` -- the whole
point of the L0 tier is to see formatting differences, and an extractor that
forgave them would hide exactly what L0 exists to find.
"""

import dataclasses as dc
import re
from typing import Dict, List, Optional, Union

SENTINEL = "@@PSS-TRACE "

KINDS = ("act", "obs", "chk", "end", "acc", "imp")

Value = Union[int, bool, str]

_DEC = re.compile(r"-?(0|[1-9][0-9]*)\Z")
_HEX = re.compile(r"0x(0|[1-9a-f][0-9a-f]*)\Z")
_KEY = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*(\[[0-9]+\])*(\.[A-Za-z_$][A-Za-z0-9_$]*(\[[0-9]+\])*)*\Z")


@dc.dataclass
class Record:
    kind: str
    tag: str
    #: key -> the raw value token, exactly as printed.
    fields: Dict[str, str]
    #: 1-based line number in the log, for diagnostics.
    line: int
    text: str

    def describe(self) -> str:
        return f"line {self.line}: {self.text}"


class ProtocolError(Exception):
    """A record that does not follow §4.2. The tool's fault, so a FAIL."""

    def __init__(self, msg: str, line: int, text: str):
        super().__init__(f"line {line}: {msg}: {text!r}")
        self.line = line
        self.text = text


def extract(log: str) -> List[Record]:
    """Every record in *log*, in order. Raises :class:`ProtocolError` on a bad one."""
    out: List[Record] = []
    for n, line in enumerate(log.split("\n"), start=1):
        at = line.find(SENTINEL)
        if at < 0:
            continue
        text = line[at + len(SENTINEL):]
        out.append(parse_record(text, n))
    return out


def parse_record(text: str, line: int = 0) -> Record:
    toks = text.split(" ")
    if any(t == "" for t in toks):
        raise ProtocolError("empty token (doubled or trailing space)", line, text)
    if len(toks) < 2:
        raise ProtocolError("a record needs a kind and a tag", line, text)
    kind, tag = toks[0], toks[1]
    if kind not in KINDS:
        raise ProtocolError(f"unknown record kind {kind!r}", line, text)
    fields: Dict[str, str] = {}
    for t in toks[2:]:
        k, eq, v = t.partition("=")
        if not eq or not v:
            raise ProtocolError(f"token {t!r} is not key=value", line, text)
        if not _KEY.match(k):
            raise ProtocolError(f"malformed key {k!r}", line, text)
        if k in fields:
            raise ProtocolError(f"duplicate key {k!r}", line, text)
        fields[k] = v
    return Record(kind=kind, tag=tag, fields=fields, line=line, text=text)


def parse_value(tok: str) -> Optional[Value]:
    """A value token as a Python value, or ``None`` if it is not a well-formed one.

    Decimal integers (no leading zeros or ``+``), ``0x`` lowercase hex with no
    padding, and ``true``/``false`` are typed. Anything else is a string token.
    """
    if _DEC.match(tok):
        return int(tok)
    if _HEX.match(tok):
        return int(tok, 16)
    if tok == "true":
        return True
    if tok == "false":
        return False
    if tok.startswith("0x") or tok.startswith("0X"):
        return None                     # hex that is padded, uppercase, or empty
    if re.match(r"[-+]?[0-9]", tok):
        return None                     # a number that is not strict (e.g. `007`, `+3`)
    return tok


def value_matches(tok: str, expected: Value) -> bool:
    """Does the printed *tok* denote exactly *expected*?

    A string expectation compares the token text itself: ``100%`` is a string
    token even though it starts with a digit.
    """
    if isinstance(expected, str):
        return tok == expected
    got = parse_value(tok)
    if got is None:
        return False
    if isinstance(expected, bool) or isinstance(got, bool):
        return type(got) is type(expected) and got == expected
    if isinstance(expected, int):
        return isinstance(got, int) and got == expected
    return tok == expected
