"""Tests on disk: a directory holding ``test.json`` (the model) and its sources."""

import dataclasses as dc
import hashlib
import json
import os
from typing import Any, Dict, Iterator, List, Optional

from .smt import ModelError

SCHEMA = "pss-corpus/model/1.0"

#: The published base of the inter-run seed plan (§8.3): seed i is BASE + i.
SEED_BASE = 1

#: The PSS version a test needs when its model does not say. The protocol's
#: format specifiers (%u, %x, %n; LRM 21.1.1) are PSS 3.0, so no test runs on less.
DEFAULT_PSS = "3.0"


def pss_version(text: str):
    """``"3.1"`` -> ``(3, 1)``, for comparing the ``pss`` field of a model."""
    try:
        return tuple(int(p) for p in str(text).split("."))
    except ValueError:
        raise ModelError(f"PSS version {text!r} is not of the form N.M")


@dc.dataclass
class Test:
    path: str
    model: Dict[str, Any]

    @property
    def id(self) -> str:
        return self.model["id"]

    @property
    def rev(self) -> int:
        return int(self.model.get("rev", 1))

    @property
    def root(self) -> str:
        return self.model["run"]["root"]

    @property
    def libs(self) -> List[str]:
        """The shared libraries the test compiles with, by name: ``pct_tap`` is
        ``compliance/lib/pct_tap.pss`` (the executor tap, §4.12)."""
        return list(self.model.get("libs", []))

    @property
    def sources(self) -> List[str]:
        """Every file the tool compiles: the test's own, then its libraries."""
        return ([os.path.join(self.path, s) for s in self.model["sources"]]
                + [find_lib(self.path, n) for n in self.libs])

    @property
    def source_names(self) -> List[str]:
        """The sources as the model names them, relative to the test
        directory; a library as ``lib/<name>.pss``, which is where a bundle
        puts its copy (§5.2)."""
        return list(self.model["sources"]) + [f"lib/{n}.pss" for n in self.libs]

    @property
    def sha256(self) -> str:
        """A digest of the sources: their names, in order, and their bytes.

        An exported bundle records it; an import refuses results for sources
        that have since changed (a STALE verdict), whatever ``rev`` says.
        """
        h = hashlib.sha256()
        for name, path in zip(self.source_names, self.sources):
            with open(path, "rb") as fp:
                data = fp.read()
            h.update(name.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
        return h.hexdigest()

    @property
    def pss(self) -> str:
        """The lowest PSS version this test is written in (``DEFAULT_PSS`` if unstated)."""
        return str(self.model.get("pss", DEFAULT_PSS))

    @property
    def profiles(self) -> List[str]:
        return list(self.model.get("profile", []))

    @property
    def seeds(self) -> List[int]:
        n = int(self.model.get("run", {}).get("seeds", {}).get("count", 1))
        return [SEED_BASE + i for i in range(n)]

    @property
    def expect(self) -> str:
        return self.model.get("expect", {}).get("outcome", "ok")

    @property
    def expect_diagnostics(self) -> List[Dict[str, Any]]:
        """Where a negative test's error must be reported: ``[{file, line | lines}]``."""
        return list(self.model.get("expect", {}).get("diagnostics", []))

    @property
    def level(self) -> Optional[str]:
        return self.model.get("level")

    def type(self, name: str) -> Dict[str, Any]:
        t = self.model.get("types", {}).get(name)
        if t is None:
            raise ModelError(f"{self.id}: type {name!r} is not in the model")
        return t

    def record_tag(self, type_name: str) -> str:
        rec = self.model.get("records", {}).get(type_name)
        return rec["tag"] if rec else type_name


def find_lib(test_path: str, name: str) -> str:
    """The file of library *name*: ``lib/<name>.pss`` in the nearest directory
    above the test that has one -- the corpus's ``compliance/lib``."""
    d = os.path.abspath(test_path)
    while True:
        d = os.path.dirname(d)
        fn = os.path.join(d, "lib", f"{name}.pss")
        if os.path.isfile(fn):
            return fn
        if os.path.dirname(d) == d:
            raise ModelError(f"{test_path}: library {name!r} not found "
                             f"(no lib/{name}.pss above the test)")


def load(path: str) -> Test:
    fn = os.path.join(path, "test.json")
    with open(fn) as fp:
        model = json.load(fp)
    if model.get("schema") != SCHEMA:
        raise ModelError(f"{fn}: schema {model.get('schema')!r} is not {SCHEMA!r}")
    for key in ("id", "sources", "run", "types"):
        if key not in model:
            raise ModelError(f"{fn}: missing {key!r}")
    pss_version(model.get("pss", DEFAULT_PSS))
    for n in model.get("libs", []):
        find_lib(path, n)
    return Test(path=os.path.abspath(path), model=model)


def discover(root: str) -> Iterator[Test]:
    """Every test under *root*, in a stable (path) order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        if "test.json" in filenames:
            yield load(dirpath)


def default_root() -> str:
    """The corpus's ``compliance/`` directory.

    The package ships inside the repository it searches, so it finds its own
    data first (§11.4); ``$PSS_CORPUS`` overrides for a working copy elsewhere.
    """
    env = os.environ.get("PSS_CORPUS")
    if env:
        return os.path.join(env, "compliance")
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.normpath(os.path.join(here, "..", "..", ".."))
    return os.path.join(repo, "compliance")
