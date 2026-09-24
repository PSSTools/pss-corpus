"""The runner: drive an adapter over tests and seeds, check each run (§5).

An adapter is either a command line, invoked per the §5 contract::

    <adapter> run --root <action> --seed <n> --out <dir> <file.pss>...

or, for an in-process tool, a Python callable with the same parameters
(:data:`AdapterFn`). Either way it leaves ``log.txt`` and ``outcome.json`` in
``<dir>``, and the checker reads only those.

A command adapter is invoked by :func:`driver.invoke_adapter`, the same code a
bundle's ``run_jobs.py`` uses, so the live path and the export/import path
cannot disagree about the contract.
"""

import json
import os
import shlex
from typing import Callable, Iterable, List, Optional, Sequence

from .check import ERROR, Verdict, check_run
from .driver import invoke_adapter
from .model import Test

#: fn(sources, root, seed, out_dir) -> None
AdapterFn = Callable[[Sequence[str], str, int, str], None]


def run_command_adapter(cmd: Sequence[str], sources: Sequence[str], root: str,
                        seed: int, out_dir: str, timeout: float = 300.0) -> None:
    invoke_adapter(cmd, sources, root, seed, out_dir, timeout)


def run_test(test: Test, adapter, out_root: str,
             seeds: Optional[Iterable[int]] = None) -> List[Verdict]:
    """Run *test* once per seed and check each run. Results land in *out_root*."""
    out: List[Verdict] = []
    for seed in (seeds if seeds is not None else test.seeds):
        run_dir = os.path.join(out_root, test.id, f"seed-{seed}")
        os.makedirs(run_dir, exist_ok=True)
        try:
            if callable(adapter):
                adapter(test.sources, test.root, seed, run_dir)
            else:
                run_command_adapter(adapter, test.sources, test.root, seed, run_dir)
            v = check_run(test, run_dir, seed=seed)
        except Exception as e:           # the runner never takes the suite down
            v = Verdict(test=test.id, rev=test.rev, seed=seed, verdict=ERROR,
                        reason=f"runner: {type(e).__name__}: {e}")
        with open(os.path.join(run_dir, "result.json"), "w") as fp:
            json.dump(v.to_json(), fp, indent=2)
        out.append(v)
    return out


def parse_adapter(text: str):
    return shlex.split(text)
