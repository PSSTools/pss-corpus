"""``pss-corpus``: list tests, check one run, run an adapter over the suite,
export a bundle for another site's tool and import the results it returns, or
re-render a saved report."""

import argparse
import collections
import fnmatch
import json
import os
import sys

from .bundle import BundleError, Selection, export, import_results, select
from .check import PASS, check_run
from .html_report import render_html
from .model import default_root, discover, load
from .report import (Report, apply_trust, load_report, render_markdown, row,
                     tool_identity, write_report)
from .runner import parse_adapter, run_test


def _matcher(patterns):
    """A test matches an id glob (``proc.func.*``), a path glob (``proc/*``), or a
    path fragment (``neg``). Paths are taken below ``compliance/``, so a fragment
    that happens to occur in the checkout's own location matches nothing."""
    def one(t, p):
        rel = t.path.replace(os.sep, "/").rpartition("/compliance/")[2]
        return fnmatch.fnmatch(t.id, p) or p in rel or fnmatch.fnmatch(rel, p.rstrip("/"))
    def matches(t):
        return not patterns or any(one(t, p) for p in patterns)
    return matches


def _select(root, patterns):
    return [t for t in discover(root) if _matcher(patterns)(t)]


def _csv(text):
    return [x for x in (text or "").split(",") if x]


def cmd_list(args):
    for t in _select(args.root, args.tests):
        print(f"{t.id:40s} {t.level or '-':3s} {os.path.relpath(t.path, args.root)}")
    return 0


def cmd_check(args):
    t = load(args.test)
    v = check_run(t, args.run_dir, seed=args.seed)
    print(json.dumps(v.to_json(), indent=2))
    return 0 if v.verdict == "PASS" else 1


def cmd_run(args):
    adapter = parse_adapter(args.adapter)
    counts = collections.Counter()
    rows, tools = [], []
    for t in _select(args.root, args.tests):
        for v in run_test(t, adapter, args.out):
            counts[v.verdict] += 1
            run_dir = os.path.join(args.out, t.id, f"seed-{v.seed}")
            rows.append(row(v, f"{t.id}/seed-{v.seed}", test=t, run_dir=run_dir))
            ident = tool_identity(run_dir)
            if ident and ident not in tools:
                tools.append(ident)
            if v.verdict != "PASS" or args.verbose:
                print(f"{v.verdict:11s} {v.test} seed={v.seed}: {v.reason}")
    report = Report(bundle={}, results=rows, tools=tools, l0_trusted=apply_trust(rows),
                    source="run")
    paths = write_report(report, os.path.join(args.out, "report"))
    print(" ".join(f"{k}={counts[k]}" for k in sorted(counts)))
    print(f"report: {paths['html']}")
    return 0 if set(counts) <= {"PASS"} else 1


def cmd_export(args):
    sel = Selection(patterns=args.tests, pss=args.pss, levels=_csv(args.level),
                    profiles=_csv(args.profile), no_l0=args.no_l0)
    tests, excluded = select(list(discover(args.root)), sel, _matcher(args.tests))
    if not tests:
        print("no tests selected", file=sys.stderr)
        return 2
    try:
        doc = export(tests, args.out, sel, corpus_root=os.path.dirname(args.root),
                     excluded=excluded)
    except BundleError as e:
        print(f"export: {e}", file=sys.stderr)
        return 2
    print(f"exported {len(doc['tests'])} tests, {len(doc['jobs'])} runs to {args.out}"
          + (f"; {len(excluded)} excluded (listed in bundle.json)" if excluded else ""))
    return 0


def cmd_import(args):
    try:
        report = import_results(args.bundle, list(discover(args.root)), results=args.results)
    except BundleError as e:
        print(f"import: {e}", file=sys.stderr)
        return 2
    out = args.out or (os.path.join(args.bundle, "report") if os.path.isdir(args.bundle)
                       else os.path.splitext(args.bundle)[0].removesuffix(".tar") + "-report")
    paths = write_report(report, out)
    if args.verbose:
        print(render_markdown(report.to_json()))
    else:
        for r in report.results:
            if r["verdict"] != PASS:
                flag = " (untrusted)" if r["untrusted"] else ""
                print(f"{r['verdict']:11s} {r['job']}{flag}: {r['reason']}")
    print(" ".join(f"{k}={n}" for k, n in sorted(report.counts.items())))
    if report.l0_trusted is False:
        print("L0 did not pass: results outside L0 are untrusted")
    elif report.l0_trusted is None:
        print("trust not established: no L0 in the bundle, or L0 runs did not complete")
    print(f"report: {paths['html']}")
    return 0 if set(report.counts) <= {PASS} else 1


def cmd_report(args):
    try:
        doc = load_report(args.report)
    except (OSError, ValueError) as e:
        print(f"report: {e}", file=sys.stderr)
        return 2
    base = os.path.splitext(args.report)[0]
    out = args.out or base + (".md" if args.md else ".html")
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(render_markdown(doc) if args.md else render_html(doc))
    print(out)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="pss-corpus", description=__doc__)
    p.add_argument("--root", default=None,
                   help="compliance directory (default: this corpus's compliance/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="list tests")
    sp.add_argument("tests", nargs="*", help="id globs or path fragments")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("check", help="check one run directory against a test")
    sp.add_argument("test", help="test directory")
    sp.add_argument("run_dir", help="directory holding log.txt + outcome.json")
    sp.add_argument("--seed", type=int, default=None)
    sp.set_defaults(fn=cmd_check)

    sp = sub.add_parser("run", help="run an adapter over tests and check every run")
    sp.add_argument("--adapter", required=True, help="adapter command line")
    sp.add_argument("--out", required=True, help="results directory")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.add_argument("tests", nargs="*", help="id globs or path fragments")
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("export", help="write a bundle for a tool run elsewhere (HANDOFF.md)")
    sp.add_argument("--out", required=True,
                    help="bundle directory, or a .tar.gz/.tgz/.tar to write")
    sp.add_argument("--pss", default=None, metavar="VERSION",
                    help="newest PSS version the tool supports; tests needing more are left out")
    sp.add_argument("--level", default=None, help="comma-separated levels (L0 always included)")
    sp.add_argument("--profile", default=None, help="comma-separated profiles, e.g. op-model")
    sp.add_argument("--no-l0", action="store_true",
                    help="do not add the L0 protocol tier (results then carry no trust)")
    sp.add_argument("tests", nargs="*", help="id globs or path fragments (default: all)")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("import", help="check the results in a returned bundle")
    sp.add_argument("bundle", help="bundle directory or tarball, with results/ filled in")
    sp.add_argument("--results", default=None,
                    help="results directory, when not the bundle's results/")
    sp.add_argument("--out", default=None,
                    help="report directory (default: <bundle>/report)")
    sp.add_argument("-v", "--verbose", action="store_true", help="print the whole report")
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser("report", help="re-render a saved report.json as HTML (or Markdown)")
    sp.add_argument("report", help="a report.json written by import or run")
    sp.add_argument("--out", default=None, help="output file (default: beside the JSON)")
    sp.add_argument("--md", action="store_true", help="Markdown instead of HTML")
    sp.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    if args.root is None:
        args.root = default_root()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
