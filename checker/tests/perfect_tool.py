"""A fake tool that is always right, as a §5 command-line adapter.

It finds its test from the source path it was given (a bundle's
``tests/<id>/<file>``, or the corpus's own path under ``pss-corpus run``), and writes the
result :mod:`synth` derives. What it cannot synthesize it reports as
``unsupported``. Behaviour switches, for exercising the driver:

* ``PERFECT_TOOL_MUTE=1``: exit without writing anything
* ``PERFECT_TOOL_SLEEP=<s>``: sleep first
* ``PERFECT_TOOL_BREAK=<test id>``: print a wrong trace for that test
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pss_corpus import default_root, discover  # noqa: E402
from synth import synth, synth_diagnostics      # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--root", required=True)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--out", required=True)
    r.add_argument("sources", nargs="+")
    a = p.parse_args(argv)
    print(f"perfect_tool: {a.root} seed={a.seed}")
    if os.environ.get("PERFECT_TOOL_SLEEP"):
        time.sleep(float(os.environ["PERFECT_TOOL_SLEEP"]))
    if os.environ.get("PERFECT_TOOL_MUTE"):
        return 3
    # A bundle passes tests/<id>/<file>; `pss-corpus run` passes the corpus's own path.
    src = os.path.abspath(a.sources[0])
    tests = list(discover(default_root()))
    t = next((t for t in tests if src in t.sources), None) or \
        {t.id: t for t in tests}[os.path.basename(os.path.dirname(src))]
    os.makedirs(a.out, exist_ok=True)
    oc = {"schema": "pss-corpus/outcome/1.0", "tool": "perfect_tool",
          "tool_version": "1", "target": "synth", "seed_honored": True}
    lines = synth(t)
    if t.expect == "compile_error":
        oc["outcome"] = "compile_error"
        prefix = os.path.dirname(a.sources[0]) + "/"
        with open(os.path.join(a.out, "diagnostics.json"), "w") as fp:
            json.dump({"schema": "pss-corpus/diagnostics/1.0",
                       "diagnostics": synth_diagnostics(t, prefix)}, fp)
        lines = []
    elif lines is None:
        oc["outcome"], lines = "unsupported", []
    else:
        oc["outcome"] = "ok"
        if os.environ.get("PERFECT_TOOL_BREAK") == t.id:
            lines = [ln.replace("@@PSS-TRACE ", "@@PSS-TRACE  ") for ln in lines]
    with open(os.path.join(a.out, "log.txt"), "w") as fp:
        fp.write("".join(f"[tool] {ln}\n" for ln in lines))
    with open(os.path.join(a.out, "outcome.json"), "w") as fp:
        json.dump(oc, fp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
