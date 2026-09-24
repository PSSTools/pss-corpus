"""Run a tool's adapter over the jobs of an exported bundle (HANDOFF.md).

This file is copied verbatim into every bundle as ``run_jobs.py``, so the side
that runs the tool needs a Python 3.8 interpreter and nothing else: no
pss-corpus, no SMT solver, no test models. It therefore imports only the
standard library, and ``test_bundle.py`` holds it to that.

::

    python run_jobs.py --adapter "<cmd>" [-j N] [--timeout S] [--force] [job-glob...]

For each job it invokes the adapter per the §5 contract::

    <cmd> run --root <action> --seed <n> --out results/<job> <file.pss>...

and leaves ``results/<job>/`` holding what the adapter wrote, plus
``adapter.log`` (the adapter's own stdout and stderr, for whoever debugs a
result). An adapter that exits without writing ``outcome.json`` gets an
``infra_error`` outcome written for it, and one that overruns ``--timeout`` a
``timeout`` outcome, so every job that ran has an outcome.

A job whose ``outcome.json`` already exists is skipped unless ``--force``:
a long vendor run can be stopped and resumed.
"""

import argparse
import concurrent.futures
import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys

OUTCOME_SCHEMA = "pss-corpus/outcome/1.0"

#: The files a run directory may hold; ``--force`` clears exactly these.
RUN_FILES = ("log.txt", "outcome.json", "diagnostics.json", "adapter.log")


def invoke_adapter(cmd, sources, root, seed, out_dir, timeout=300.0):
    """Run one adapter invocation into *out_dir* (§5). Never raises for a tool failure."""
    os.makedirs(out_dir, exist_ok=True)
    argv = list(cmd) + ["run", "--root", root, "--seed", str(seed),
                        "--out", out_dir] + list(sources)
    log = os.path.join(out_dir, "adapter.log")
    try:
        with open(log, "wb") as fp:
            proc = subprocess.run(argv, timeout=timeout, check=False,
                                  stdin=subprocess.DEVNULL, stdout=fp,
                                  stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        write_outcome(out_dir, "timeout", "no result within %gs" % timeout)
        return
    except OSError as e:
        write_outcome(out_dir, "infra_error", "cannot run adapter %r: %s" % (argv[0], e))
        return
    if not os.path.isfile(os.path.join(out_dir, "outcome.json")):
        write_outcome(out_dir, "infra_error",
                      "adapter exited %d without writing outcome.json "
                      "(see adapter.log)" % proc.returncode)


def write_outcome(out_dir, outcome, detail):
    with open(os.path.join(out_dir, "outcome.json"), "w") as fp:
        json.dump({"schema": OUTCOME_SCHEMA, "outcome": outcome,
                   "detail": detail}, fp, indent=2)


def load_jobs(bundle):
    with open(os.path.join(bundle, "bundle.json")) as fp:
        return json.load(fp)["jobs"]


def run_jobs(bundle, cmd, jobs=1, timeout=300.0, force=False, patterns=(),
             echo=print):
    """Run every selected job of *bundle*; returns ``{job: outcome}``."""
    bundle = os.path.abspath(bundle)
    selected = [j for j in load_jobs(bundle)
                if not patterns
                or any(fnmatch.fnmatch(j["job"], p) or fnmatch.fnmatch(j["test"], p)
                       for p in patterns)]

    def one(job):
        out_dir = os.path.join(bundle, "results", job["job"])
        if os.path.isfile(os.path.join(out_dir, "outcome.json")):
            if not force:
                return job["job"], _outcome(out_dir), True
            for f in RUN_FILES:
                p = os.path.join(out_dir, f)
                if os.path.exists(p):
                    os.remove(p)
        sources = [os.path.join(bundle, s) for s in job["sources"]]
        invoke_adapter(cmd, sources, job["root"], job["seed"], out_dir, timeout)
        return job["job"], _outcome(out_dir), False

    done = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for name, outcome, skipped in ex.map(one, selected):
            done[name] = outcome
            echo("%-14s %s%s" % (outcome, name, "  (kept)" if skipped else ""))
    return done


def _outcome(out_dir):
    try:
        with open(os.path.join(out_dir, "outcome.json")) as fp:
            return json.load(fp).get("outcome", "?")
    except (OSError, ValueError):
        return "?"


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="run_jobs.py",
        description="Run a tool adapter over the jobs of a pss-corpus bundle.")
    p.add_argument("--adapter", required=True,
                   help="adapter command line; invoked as <cmd> run --root ... --out ...")
    p.add_argument("--bundle", default=os.path.dirname(os.path.abspath(__file__)),
                   help="bundle directory (default: the one holding this script)")
    p.add_argument("-j", "--jobs", type=int, default=1,
                   help="adapter invocations to run at once (default 1: a licensed "
                        "tool may have one seat)")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="seconds per job before it is recorded as a timeout")
    p.add_argument("--force", action="store_true",
                   help="rerun jobs that already have an outcome")
    p.add_argument("patterns", nargs="*", help="job or test-id globs (default: all)")
    a = p.parse_args(argv)
    if a.adapter.strip() == "":
        p.error("--adapter is empty")
    cmd = shlex.split(a.adapter)
    if shutil.which(cmd[0]) is None and not os.path.exists(cmd[0]):
        p.error("adapter %r is not on PATH" % cmd[0])
    done = run_jobs(a.bundle, cmd, jobs=a.jobs, timeout=a.timeout,
                    force=a.force, patterns=a.patterns)
    counts = {}
    for o in done.values():
        counts[o] = counts.get(o, 0) + 1
    print(" ".join("%s=%d" % kv for kv in sorted(counts.items())) or "no jobs selected")
    print("results are in %s; return the bundle directory for import"
          % os.path.join(os.path.abspath(a.bundle), "results"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
