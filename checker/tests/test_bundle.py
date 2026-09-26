"""Export and import (HANDOFF.md): what leaves, what the tool side needs, what comes back.

The end-to-end cases run ``perfect_tool.py`` -- an adapter that is always right
-- through the bundle's own ``run_jobs.py``, so the export -> run -> import path
is exercised exactly as another site would use it.
"""

import ast
import json
import os
import shutil
import sys
import tarfile

import pytest

from pss_corpus import (MISSING, PASS, STALE, UNSUPPORTED, BundleError, Selection,
                        default_root, discover, export, import_results, select)
from pss_corpus import driver
from pss_corpus.cli import _matcher, main as cli_main

from synth import synth

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = list(discover(default_root()))
PERFECT = [sys.executable, os.path.join(HERE, "perfect_tool.py")]


def _pick(*patterns, **kw):
    sel = Selection(patterns=patterns, **kw)
    return select(TESTS, sel, _matcher(patterns)), sel


def _export(tmp_path, *patterns, name="b", **kw):
    (tests, excluded), sel = _pick(*patterns, **kw)
    out = str(tmp_path / name)
    export(tests, out, sel, excluded=excluded)
    return out


def _run(bundle, **kw):
    return driver.run_jobs(bundle, PERFECT, echo=lambda *_: None, **kw)


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

def test_l0_is_always_exported():
    (tests, _), _ = _pick("proc.func.return.001")
    ids = {t.id for t in tests}
    assert "proc.func.return.001" in ids
    assert {t.id for t in TESTS if t.level == "L0"} <= ids


def test_no_l0_exports_only_what_was_asked():
    (tests, _), _ = _pick("proc.func.return.001", no_l0=True)
    assert [t.id for t in tests] == ["proc.func.return.001"]


def test_a_pss_ceiling_excludes_newer_tests_and_says_why():
    (tests, excluded), _ = _pick("sync.*", pss="3.0")
    assert not any(t.id.startswith("sync.") for t in tests)
    assert {e["id"] for e in excluded} == {t.id for t in TESTS if t.id.startswith("sync.")}
    assert all(e["reason"] == "needs PSS 3.1" for e in excluded)
    (tests, _), _ = _pick("sync.*", pss="3.1")
    assert any(t.id.startswith("sync.") for t in tests)


def test_level_and_profile_filters():
    (tests, _), _ = _pick(levels=["L2"], no_l0=True)
    assert tests and all(t.level == "L2" for t in tests)
    (tests, _), _ = _pick(profiles=["op-model"], no_l0=True)
    assert tests and all("op-model" in t.profiles for t in tests)


# --------------------------------------------------------------------------- #
# The bundle
# --------------------------------------------------------------------------- #

def test_a_bundle_holds_sources_and_jobs_but_no_models(tmp_path):
    b = _export(tmp_path, "proc.rand.input.001", no_l0=True)
    doc = json.load(open(os.path.join(b, "bundle.json")))
    assert doc["schema"] == "pss-corpus/bundle/1.0"
    assert [j["job"] for j in doc["jobs"]] == [f"proc.rand.input.001/seed-{s}"
                                              for s in range(1, 9)]
    for j in doc["jobs"]:
        assert j["root"] == "pss_top::A"
        for s in j["sources"]:
            assert os.path.isfile(os.path.join(b, s))
    names = {f for _, _, fs in os.walk(b) for f in fs}
    assert "test.json" not in names, "the oracle must not travel with the bundle"
    assert {"bundle.json", "jobs.tsv", "run_jobs.py", "README.md", "test.pss"} <= names
    tsv = [ln for ln in open(os.path.join(b, "jobs.tsv")) if not ln.startswith("#")]
    assert len(tsv) == 8 and tsv[0].split("\t")[:3] == ["proc.rand.input.001/seed-1",
                                                       "pss_top::A", "1"]


def test_export_refuses_a_non_empty_directory(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "x").write_text("")
    with pytest.raises(BundleError):
        _export(tmp_path, "proc.func.return.001")


def test_the_driver_needs_only_the_standard_library():
    src = open(driver.__file__).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "run_jobs.py is copied out alone; no relative imports"
            mods = [node.module]
        elif isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        else:
            continue
        for m in mods:
            top = m.split(".")[0]
            assert top in sys.stdlib_module_names, f"run_jobs.py imports {m}"
    assert "f\"" not in src and "f'" not in src.replace("if'", ""), \
        "keep run_jobs.py runnable on old interpreters: no f-strings needed"


def test_the_bundle_driver_is_the_package_driver(tmp_path):
    b = _export(tmp_path, "proc.func.return.001", no_l0=True)
    assert open(os.path.join(b, "run_jobs.py")).read() == open(driver.__file__).read()


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #

def test_round_trip_with_a_perfect_tool(tmp_path):
    b = _export(tmp_path)
    done = _run(b, jobs=os.cpu_count() or 1)
    assert set(done.values()) <= {"ok", "compile_error", "unsupported"}
    rep = import_results(b, TESTS)
    by_test = {}
    for r in rep.results:
        by_test.setdefault(r["test"], set()).add(r["verdict"])
    for t in TESTS:
        want = UNSUPPORTED if (t.expect == "ok" and synth(t) is None) else PASS
        assert by_test[t.id] == {want}, (t.id, [r["reason"] for r in rep.results
                                                if r["test"] == t.id])
    assert rep.l0_trusted is True
    assert rep.tools == [{"tool": "perfect_tool", "tool_version": "1", "target": "synth"}]


def test_the_bundle_script_runs_standalone(tmp_path):
    b = _export(tmp_path, "proc.func.return.001", no_l0=True)
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(b, "run_jobs.py"),
                        "--adapter", " ".join(PERFECT)], capture_output=True, text=True,
                       cwd=str(tmp_path), env={k: v for k, v in os.environ.items()
                                               if k != "PYTHONPATH"})
    assert r.returncode == 0, r.stderr
    assert "ok=1" in r.stdout
    assert import_results(b, TESTS).counts == {PASS: 1}


def test_a_tarball_goes_out_and_comes_back(tmp_path):
    (tests, excluded), sel = _pick("proc.func.return.001", no_l0=True)
    tgz = str(tmp_path / "perspec-job.tar.gz")
    export(tests, tgz, sel, excluded=excluded)
    work = tmp_path / "vendor"
    work.mkdir()
    with tarfile.open(tgz) as tf:
        tf.extractall(work, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    b = str(work / "perspec-job")
    _run(b)
    back = str(tmp_path / "returned.tgz")
    with tarfile.open(back, "w:gz") as tf:
        tf.add(b, arcname="perspec-job")
    assert import_results(back, TESTS).counts == {PASS: 1}


def test_an_unsafe_archive_is_refused(tmp_path):
    b = _export(tmp_path, "proc.func.return.001", no_l0=True)
    evil = str(tmp_path / "evil.tar.gz")
    with tarfile.open(evil, "w:gz") as tf:
        tf.add(b, arcname="b")
        tf.add(os.path.join(b, "README.md"), arcname="../escape.md")
    with pytest.raises(BundleError, match="refusing"):
        import_results(evil, TESTS)
    link = str(tmp_path / "link.tar.gz")
    with tarfile.open(link, "w:gz") as tf:
        tf.add(b, arcname="b")
        info = tarfile.TarInfo("b/results/x")
        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tf.addfile(info)
    with pytest.raises(BundleError, match="refusing"):
        import_results(link, TESTS)


# --------------------------------------------------------------------------- #
# What import refuses to score
# --------------------------------------------------------------------------- #

def _corpus_copy(tmp_path):
    root = str(tmp_path / "corpus")
    shutil.copytree(default_root(), root)
    return root


def test_changed_sources_or_rev_are_stale(tmp_path):
    root = _corpus_copy(tmp_path)
    local = list(discover(root))
    sel = Selection(patterns=("proc.func.*",), no_l0=True)
    tests, _ = select(local, sel, _matcher(sel.patterns))
    b = str(tmp_path / "b")
    export(tests, b, sel)
    _run(b)
    assert set(import_results(b, local).counts) == {PASS}

    t1, t2 = tests[0], tests[1]
    with open(t1.sources[0], "a") as fp:
        fp.write("// edited after export\n")
    m = json.load(open(os.path.join(t2.path, "test.json")))
    m["rev"] = t2.rev + 1
    json.dump(m, open(os.path.join(t2.path, "test.json"), "w"))
    rep = import_results(b, list(discover(root)))
    got = {r["test"]: r for r in rep.results}
    assert got[t1.id]["verdict"] == STALE and "sources changed" in got[t1.id]["reason"]
    assert got[t2.id]["verdict"] == STALE and "rev" in got[t2.id]["reason"]


def test_a_job_without_a_result_is_missing(tmp_path):
    b = _export(tmp_path, "proc.rand.input.001", no_l0=True)
    _run(b)
    shutil.rmtree(os.path.join(b, "results", "proc.rand.input.001", "seed-3"))
    rep = import_results(b, TESTS)
    assert rep.counts[MISSING] == 1
    assert rep.l0_trusted is None, "no L0 in the bundle: trust is not established"


def test_an_l0_failure_marks_the_rest_untrusted(tmp_path, monkeypatch):
    b = _export(tmp_path, "proc.func.return.001")
    monkeypatch.setenv("PERFECT_TOOL_BREAK", "L0.act.single.001")
    _run(b)
    rep = import_results(b, TESTS)
    assert rep.l0_trusted is False
    for r in rep.results:
        assert r["untrusted"] == (r["level"] != "L0")


# --------------------------------------------------------------------------- #
# The driver
# --------------------------------------------------------------------------- #

def test_a_mute_adapter_gets_an_infra_error_and_its_output_is_kept(tmp_path, monkeypatch):
    b = _export(tmp_path, "proc.func.return.001", no_l0=True)
    monkeypatch.setenv("PERFECT_TOOL_MUTE", "1")
    assert _run(b) == {"proc.func.return.001/seed-1": "infra_error"}
    d = os.path.join(b, "results", "proc.func.return.001", "seed-1")
    assert "perfect_tool: pss_top::A" in open(os.path.join(d, "adapter.log")).read()
    assert "exited 3" in json.load(open(os.path.join(d, "outcome.json")))["detail"]


def test_a_slow_adapter_times_out(tmp_path, monkeypatch):
    b = _export(tmp_path, "proc.func.return.001", no_l0=True)
    monkeypatch.setenv("PERFECT_TOOL_SLEEP", "5")
    assert _run(b, timeout=0.5) == {"proc.func.return.001/seed-1": "timeout"}


def test_a_rerun_keeps_finished_jobs_unless_forced(tmp_path, monkeypatch):
    b = _export(tmp_path, "proc.func.return.001", no_l0=True)
    monkeypatch.setenv("PERFECT_TOOL_MUTE", "1")
    _run(b)
    monkeypatch.delenv("PERFECT_TOOL_MUTE")
    assert _run(b) == {"proc.func.return.001/seed-1": "infra_error"}
    assert _run(b, force=True) == {"proc.func.return.001/seed-1": "ok"}


def test_an_unsupported_l0_feature_keeps_trust(tmp_path):
    b = _export(tmp_path, "proc.func.return.001")
    _run(b)
    d = os.path.join(b, "results", "L0.func.recursive.001", "seed-1")
    oc = json.load(open(os.path.join(d, "outcome.json")))
    oc["outcome"] = "unsupported"
    json.dump(oc, open(os.path.join(d, "outcome.json"), "w"))
    rep = import_results(b, TESTS)
    assert rep.counts[UNSUPPORTED] == 1
    assert rep.l0_trusted is True


def test_infrastructure_errors_in_l0_do_not_blame_the_tool(tmp_path, monkeypatch):
    b = _export(tmp_path, "proc.func.return.001")
    monkeypatch.setenv("PERFECT_TOOL_MUTE", "1")
    _run(b)
    rep = import_results(b, TESTS)
    assert rep.l0_trusted is None
    assert not any(r["untrusted"] for r in rep.results)
    assert all("exited 3 without writing outcome.json" in r["reason"] for r in rep.results)


def test_path_globs_select(tmp_path):
    m = _matcher(["proc/*"])
    got = {t.id for t in TESTS if m(t)}
    assert got and all(t.path.replace(os.sep, "/").split("/")[-2] == "proc"
                       for t in TESTS if t.id in got)


def test_a_fragment_is_matched_below_compliance_only():
    here = TESTS[0].path.replace(os.sep, "/").rpartition("/compliance/")[0]
    frag = here.rstrip("/").rsplit("/", 1)[-1]          # e.g. "pss-corpus"
    assert not any(_matcher([frag])(t) for t in TESTS)
    assert all(_matcher(["neg"])(t) == ("/neg/" in t.path.replace(os.sep, "/"))
               for t in TESTS)


def test_the_cli_round_trip(tmp_path, capsys):
    b = str(tmp_path / "b")
    assert cli_main(["export", "--out", b, "--pss", "3.0",
                     "proc.func.return.001", "sync.*"]) == 0
    _run(b)
    assert cli_main(["import", b]) == 0
    assert os.path.isfile(os.path.join(b, "report", "report.md"))
    md = open(os.path.join(b, "report", "report.md")).read()
    assert "L0 protocol tier passed" in md and "Not exported" in md
