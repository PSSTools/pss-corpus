"""Export a bundle for a tool we cannot run; import the results it comes back with.

The hand-off splits the §5 adapter contract across two sites (HANDOFF.md):

* **export** writes a *bundle*: the selected tests' PSS sources, the jobs to run
  (test, root action, seed), and ``run_jobs.py`` (:mod:`driver`, copied). It
  holds no legality models, so the site that runs the tool needs neither them
  nor an SMT solver -- only a Python 3.8 interpreter and the tool.
* **import** reads the bundle back with ``results/<job>/`` filled in, checks
  every run against *this* corpus's models, and returns a :class:`Report`.

A test's sources are hashed at export. Results for a test whose sources or
``rev`` have changed since are STALE, not checked: a verdict is only a fact
about the PSS the tool actually ran.
"""

import dataclasses as dc
import datetime
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .check import DIAGNOSTICS_SCHEMA, ERROR, OUTCOME_SCHEMA, Verdict, check_run
from .model import Test, pss_version
from .report import Report, apply_trust, row, tool_identity

BUNDLE_SCHEMA = "pss-corpus/bundle/1.0"

#: Import-only verdicts. STALE: the local test is not the one exported (its
#: sources or rev changed). MISSING: the bundle came back without a result for
#: the job. Neither says anything about the tool.
STALE, MISSING = "STALE", "MISSING"

_TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar")


class BundleError(Exception):
    """The bundle is malformed, unsafe, or does not match this corpus."""


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #

@dc.dataclass
class Selection:
    patterns: Sequence[str] = ()
    #: the newest PSS version the tool claims; tests needing more are excluded
    pss: Optional[str] = None
    levels: Sequence[str] = ()
    profiles: Sequence[str] = ()
    #: L0 establishes trust in every other result (§4.6), so it is always
    #: exported unless this is set
    no_l0: bool = False


def select(tests: Sequence[Test], sel: Selection,
           matches) -> Tuple[List[Test], List[Dict[str, str]]]:
    """The tests *sel* exports, and ``{id, reason}`` for each one it filtered out."""
    chosen, excluded = [], []
    for t in tests:
        is_l0 = t.level == "L0"
        if not (matches(t) or (is_l0 and not sel.no_l0)):
            continue
        if sel.pss is not None and pss_version(t.pss) > pss_version(sel.pss):
            excluded.append({"id": t.id, "reason": f"needs PSS {t.pss}"})
            continue
        if not is_l0 or sel.no_l0:
            if sel.levels and t.level not in sel.levels:
                excluded.append({"id": t.id, "reason": f"level {t.level}"})
                continue
            if sel.profiles and not set(sel.profiles) & set(t.profiles):
                excluded.append({"id": t.id, "reason": "profile not selected"})
                continue
        chosen.append(t)
    return chosen, excluded


def export(tests: Sequence[Test], out: str, sel: Selection,
           corpus_root: Optional[str] = None,
           excluded: Sequence[Dict[str, str]] = ()) -> Dict[str, Any]:
    """Write a bundle for *tests* (from :func:`select`) to *out*: a directory, or a tarball.

    *excluded* is recorded so the report can say what the tool was not asked to run.
    """
    if _is_tar(out):
        with tempfile.TemporaryDirectory() as tmp:
            name = _tar_stem(out)
            doc = _export_dir(tests, os.path.join(tmp, name), sel, corpus_root, excluded)
            mode = "w" if out.endswith(".tar") else "w:gz"
            with tarfile.open(out, mode) as tf:
                tf.add(os.path.join(tmp, name), arcname=name)
            return doc
    if os.path.exists(out) and os.listdir(out):
        raise BundleError(f"{out} exists and is not empty")
    return _export_dir(tests, out, sel, corpus_root, excluded)


def _export_dir(tests, out, sel, corpus_root, excluded) -> Dict[str, Any]:
    os.makedirs(out, exist_ok=True)
    jobs, entries = [], []
    for t in tests:
        rel = [f"tests/{t.id}/{name}" for name in t.source_names]
        for name, src, dst in zip(t.source_names, t.sources, rel):
            os.makedirs(os.path.dirname(os.path.join(out, dst)), exist_ok=True)
            shutil.copyfile(src, os.path.join(out, dst))
        entries.append({"id": t.id, "rev": t.rev, "sha256": t.sha256,
                        "level": t.level, "pss": t.pss, "profile": t.profiles,
                        "lrm": t.model.get("lrm", []), "title": t.model.get("title", ""),
                        "root": t.root, "sources": rel})
        for seed in t.seeds:
            jobs.append({"job": f"{t.id}/seed-{seed}", "test": t.id, "rev": t.rev,
                         "root": t.root, "seed": seed, "sources": rel})
    doc = {
        "schema": BUNDLE_SCHEMA,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "corpus": {"checker_version": __version__, "commit": _git_commit(corpus_root)},
        "protocol": {"trace": "@@PSS-TRACE v1", "outcome": OUTCOME_SCHEMA,
                     "diagnostics": DIAGNOSTICS_SCHEMA,
                     "lrm_numbering": "PSS 3.1 (clause numbers in 'lrm')"},
        "selection": {"patterns": list(sel.patterns), "pss": sel.pss,
                      "levels": list(sel.levels), "profiles": list(sel.profiles),
                      "l0": not sel.no_l0},
        "tests": entries,
        "jobs": jobs,
        "excluded": list(excluded),
    }
    with open(os.path.join(out, "bundle.json"), "w") as fp:
        json.dump(doc, fp, indent=2)
    with open(os.path.join(out, "jobs.tsv"), "w") as fp:
        fp.write("# job\troot\tseed\tsources (space-separated, relative to the bundle)\n")
        for j in jobs:
            fp.write(f"{j['job']}\t{j['root']}\t{j['seed']}\t{' '.join(j['sources'])}\n")
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "driver.py")
    shutil.copyfile(driver, os.path.join(out, "run_jobs.py"))
    with open(os.path.join(out, "README.md"), "w") as fp:
        fp.write(_README.format(n_tests=len(entries), n_jobs=len(jobs),
                                outcome=OUTCOME_SCHEMA, diagnostics=DIAGNOSTICS_SCHEMA))
    os.makedirs(os.path.join(out, "results"), exist_ok=True)
    return doc


def _git_commit(root: Optional[str]) -> Optional[str]:
    if not root:
        return None
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True,
                           text=True, timeout=10, check=False)
        head = r.stdout.strip() or None
        if head:
            d = subprocess.run(["git", "-C", root, "status", "--porcelain", "--", "."],
                               capture_output=True, text=True, timeout=10, check=False)
            if d.stdout.strip():
                head += "+dirty"
        return head
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def import_results(bundle: str, tests: Sequence[Test],
                   results: Optional[str] = None) -> Report:
    """Check every job of *bundle* (a directory or tarball) against *tests*."""
    if _is_tar(bundle) and os.path.isfile(bundle):
        with tempfile.TemporaryDirectory() as tmp:
            return import_results(_safe_extract(bundle, tmp), tests, results)
    doc = _load_bundle(bundle)
    results = results or os.path.join(bundle, "results")
    by_id = {t.id: t for t in tests}
    exported = {e["id"]: e for e in doc["tests"]}
    out: List[Dict[str, Any]] = []
    tools: List[Dict[str, Any]] = []
    for job in doc["jobs"]:
        run_dir = os.path.join(results, *job["job"].split("/"))
        entry = exported[job["test"]]
        t = by_id.get(job["test"])
        v = Verdict(test=job["test"], rev=job["rev"], seed=job["seed"], verdict=ERROR)
        if t is None:
            v.verdict, v.reason = STALE, "the test is not in this corpus"
        elif t.rev != entry["rev"] or t.sha256 != entry["sha256"]:
            v.verdict = STALE
            v.reason = (f"exported at rev {entry['rev']}, corpus has rev {t.rev}"
                        if t.rev != entry["rev"] else "the test's sources changed since export")
        elif not os.path.isfile(os.path.join(run_dir, "outcome.json")):
            v.verdict, v.reason = MISSING, "no outcome.json for this job"
        else:
            v = check_run(t, run_dir, seed=job["seed"])
            ident = tool_identity(run_dir)
            if ident and ident not in tools:
                tools.append(ident)
        checked = v.verdict not in (STALE, MISSING)
        out.append(row(v, job["job"], test=t, entry=entry,
                       run_dir=run_dir if checked else None))
    return Report(bundle=doc, results=out, tools=tools, l0_trusted=apply_trust(out))


def _load_bundle(path: str) -> Dict[str, Any]:
    fn = os.path.join(path, "bundle.json")
    try:
        with open(fn) as fp:
            doc = json.load(fp)
    except (OSError, ValueError) as e:
        raise BundleError(f"{path}: no readable bundle.json ({e})")
    if doc.get("schema") != BUNDLE_SCHEMA:
        raise BundleError(f"{fn}: schema {doc.get('schema')!r} is not {BUNDLE_SCHEMA!r}")
    ids = {e["id"] for e in doc.get("tests", [])}
    for j in doc.get("jobs", []):
        if j.get("test") not in ids:
            raise BundleError(f"{fn}: job {j.get('job')!r} names an unlisted test")
        parts = j["job"].split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise BundleError(f"{fn}: job name {j['job']!r} is not a relative path")
    return doc


def _safe_extract(archive: str, dest: str) -> str:
    """Extract a returned bundle, refusing anything that could land outside *dest*.

    The archive comes from another site, so links, devices, absolute paths and
    ``..`` are refused outright rather than trusted.
    """
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        for m in members:
            p = m.name.replace("\\", "/")
            if p.startswith("/") or ".." in p.split("/") or not (m.isfile() or m.isdir()):
                raise BundleError(f"{archive}: refusing archive member {m.name!r}")
        if hasattr(tarfile, "data_filter"):            # 3.12+, and 3.8+ security releases
            tf.extractall(dest, members=members, filter="data")
        else:
            tf.extractall(dest, members=members)
    if os.path.isfile(os.path.join(dest, "bundle.json")):
        return dest
    subs = [d for d in os.listdir(dest) if os.path.isfile(os.path.join(dest, d, "bundle.json"))]
    if len(subs) != 1:
        raise BundleError(f"{archive}: expected one bundle.json at the top or one level down")
    return os.path.join(dest, subs[0])


def _is_tar(path: str) -> bool:
    return path.endswith(_TAR_SUFFIXES)


def _tar_stem(path: str) -> str:
    base = os.path.basename(path)
    for s in _TAR_SUFFIXES:
        if base.endswith(s):
            return base[: -len(s)]
    return base


_README = """\
# pss-corpus bundle

{n_tests} compliance tests, {n_jobs} runs. You run a PSS tool over them and
send this directory back; the verdicts are computed where it was exported.
Nothing here needs pss-corpus, an SMT solver or network access.

## Files

* `bundle.json`: the tests and the jobs. A job is one run: a root action,
  a seed and the PSS sources, which are under `tests/`.
* `jobs.tsv`: the same jobs, one per line, for scripts that don't read JSON:
  `job <TAB> root <TAB> seed <TAB> sources...`.
* `run_jobs.py`: runs an adapter over every job (Python 3.8+, stdlib only).
* `results/`: where each job's output goes, at `results/<job>/`.

## What a run must produce

For each job, `results/<job>/` must hold:

* `log.txt`: everything the tool printed while running the scenario,
  **unedited**. Records are the text after `@@PSS-TRACE ` on any line, so
  prefixes such as timestamps or report headers are fine. Changed spacing,
  padding or case is not. Those are checked on purpose.
* `outcome.json`:
  `{{"schema": "{outcome}", "outcome": "ok|compile_error|solve_fail|runtime_error|unsupported|timeout|infra_error",
  "tool": "...", "tool_version": "...", "target": "...", "seed_honored": true, "detail": "free text"}}`.
  Use `unsupported` when the tool rejects a feature with a diagnostic that
  says so. Use `infra_error` when the problem is the setup, not the tool.
* `diagnostics.json`, when the tool reported errors:
  `{{"schema": "{diagnostics}", "diagnostics": [{{"severity": "error", "file": "tests/.../test.pss", "line": 8, "column": 11, "message": "..."}}]}}`.
  Some tests are meant to be rejected, and those are passed only by an error on
  the right line. `file` may be absolute or relative, and is matched by its
  trailing path.

## Running

Write an *adapter*: a command that takes

    <adapter> run --root <component::action> --seed <n> --out <dir> <file.pss>...

runs the tool, and writes the files above into `<dir>`. Then run

    python run_jobs.py --adapter "<adapter command>" [-j N] [--timeout S]

`-j` defaults to 1, in case the tool is licensed per seat. Jobs that already
have an `outcome.json` are skipped, so an interrupted run resumes where it
stopped (`--force` reruns them). `run_jobs.py` is only a convenience. Any
process that fills `results/` the same way works just as well.

Return the whole directory, for example as a `.tar.gz`.
"""
