"""The executor tap's platform model (COMPLIANCE-DESIGN.md §4.12).

`compliance/lib/pct_tap.pss` answers every read with a value computed from the
address alone, and this is the checker's own copy of that computation -- the
prediction a read record is checked against, and the value a read-modify-write
test builds its expected write from. It is independent of the tap: a tool that
compiles the tap wrongly disagrees with it.
"""

from typing import Dict

#: ``acc`` operations and the width of their ``data``, in bits. ``rb``/``wb``
#: are the byte-list functions, one record per byte (§4.12).
ACC_OPS: Dict[str, int] = {
    "r8": 8, "r16": 16, "r32": 32, "r64": 64,
    "w8": 8, "w16": 16, "w32": 32, "w64": 64,
    "rb": 8, "wb": 8,
}

#: The operations whose records carry the byte index ``i`` and count ``n``.
BYTE_OPS = ("rb", "wb")

_MASK64 = (1 << 64) - 1


def f8(addr: int) -> int:
    """The byte at *addr*: the XOR of the address's eight bytes, XOR 0x5A."""
    x = addr & _MASK64
    x ^= x >> 32
    x ^= x >> 16
    x ^= x >> 8
    return (x ^ 0x5A) & 0xFF


def tap_read(addr: int, width: int) -> int:
    """A *width*-bit read at *addr*: F8 of each byte, the first in bits [7:0]
    (LRM 21.13.9.1). Addresses wrap at 2**64, as a bit[64] sum does."""
    return sum(f8((addr + k) & _MASK64) << (8 * k) for k in range(width // 8))
