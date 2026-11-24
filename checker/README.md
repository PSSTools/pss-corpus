# pss-corpus checker

The code half of the corpus's executable tier (`../COMPLIANCE-DESIGN.md`, D-1).
`../compliance/` is data; this package reads it.

```
pss-corpus list                                   # the tests
pss-corpus run --adapter "<cmd>" --out results/   # run an adapter, check every run
pss-corpus check <test-dir> <run-dir>             # check one run
pss-corpus export --pss 3.0 --out b.tar.gz        # a bundle for a tool run elsewhere
pss-corpus import b-returned.tar.gz               # check the results it came back with
pss-corpus report report.json [--md]              # re-render a saved report
```

`run` and `import` both write `report/report.{html,json,md}`: the HTML is a
self-contained page (pass rate, per-area breakdown, every run with its reason
and, for a failure, its evidence).

`export`/`import` are the hand-off for a tool you cannot run here
(`../HANDOFF.md`). The bundle's `run_jobs.py` is `src/pss_corpus/driver.py`
copied verbatim, so that module imports only the standard library (a test holds
it to that). The live `run` invokes adapters through the same function.

| Module | Role |
|---|---|
| `trace.py` | the `@@PSS-TRACE` extractor and value syntax |
| `model.py` | loading `test.json`; `pss` version, expected diagnostics, source hash |
| `check.py` | one run's verdict: outcome, error locations, structure, SMT data check |
| `smt.py` | the SMT problem (z3) |
| `runner.py` | `run`: drive an adapter locally |
| `driver.py` | the adapter invocation and the bundle's job driver (stdlib only) |
| `bundle.py` | `export` and `import`, staleness |
| `report.py` | the report: rows with evidence, L0 trust, JSON and Markdown |
| `html_report.py` | the HTML page (self-contained; every tool string escaped) |

Verdicts: PASS, FAIL, UNSUPPORTED, UNLOCATED (a negative test rejected without
a located error), ERROR (not about the tool); `import` adds STALE and MISSING.

Verdicts depend on the standard library and an SMT solver (z3) only -- never on
pssparser, pssc or dv-solve. A run whose expectations are all exact (`eq`) never
starts the solver.

P1 scope: activities of traversals (with `label` and `with`), `seq`, activity
`constraint` statements and constant `repeat`/`replicate`; constraints of
compound actions over their handles, bound to the occurrences the handles name
(LRM 13.4.8); observers (`obs` records) and untraced (`"traced": false`)
actions; body patterns of `seq`, `repeat` and `chk` leaves (`eq`, or `fields` +
`where`). Inferred actions when the model says `"inference": {"allowed": true}`,
never inside an `atomic` block (`{"seq": [...], "atomic": true}`). Anything else
in a model is an ERROR, never a silent PASS.

Tests: `python -m pytest tests` from this directory. `tests/perfect_tool.py` is
an always-right adapter built from the models, used to round-trip bundles.

Plan files: `schema/plan-1.0.json` (JSON Schema 2020-12, id
`pss-corpus/plan/1.0`) is the optional `plan.json` an adapter may write per
test: the action occurrences that ran (type, component, solved fields, start
and end), flow objects (producer, consumers, values), resource instances per
claim, the realised order (transitively reduced `[before, after]` pairs) and
each `select`/`if`/`repeat` outcome. A tool that decides at run time writes the
plan it realised, so its plan is not independent of its trace. `pss-corpus check
TEST [RUN_DIR] --plan plan.json` judges a plan with no execution (`PLAN-FAIL`:
the generator decided wrongly) and, with a run, whether the run carried it out
(`REALISE-FAIL`); `src/pss_corpus/plan.py`, tests in `tests/test_plan.py`. `pssc test --plan-out DIR` writes this format.
