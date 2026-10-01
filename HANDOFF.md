# Running the executable tier on a tool you cannot run here

The executable tier (`compliance/`, design in `COMPLIANCE-DESIGN.md`) judges a
PSS tool by its output: the trace records its `message()` calls print, and the
errors it reports. When you can run the tool yourself, `pss-corpus run
--adapter` does everything in one place. When you can't, because the tool is
licensed, installed at another site, or run by its vendor, the work splits in
two:

```
 here                               there (the tool's site)                 here
┌─────────────────────┐  bundle   ┌──────────────────────────────┐  bundle  ┌──────────────────────┐
│ pss-corpus export   │ ────────► │ run_jobs.py --adapter "<cmd>"│ ───────► │ pss-corpus import    │
│  tests + jobs, no   │  .tar.gz  │  runs the tool once per job, │ +results │  checks every run    │
│  legality models    │           │  fills results/<job>/        │          │  against the models  │
└─────────────────────┘           └──────────────────────────────┘          └──────────────────────┘
```

* **Export** writes a *bundle*: the PSS sources of the selected tests, the list
  of *jobs* to run (a job is one run: root action, seed and sources), and a
  small job driver.
* **The tool's site** runs the tool once per job and writes what it printed and
  how it ended into `results/<job>/`. It needs the tool, Python 3.8 or later for
  the driver (or any script that does the same job), and nothing else. No
  pss-corpus, no SMT solver, no network.
* **Import** checks every run against *this* corpus's legality models and
  writes a report.

The legality models (`test.json`) never leave. They aren't secret, since the
corpus is public, but keeping them back means the tool's site has nothing to
install and nothing to keep in step. It also means a verdict is always computed
by the checker, never by the site that ran the tool.

## 1. Export

```
pss-corpus export --pss 3.0 --out perspec-2026-09.tar.gz            # everything a 3.0 tool can run
pss-corpus export --pss 3.0 --out b.tar.gz 'proc/*' neg              # path globs and fragments
pss-corpus export --out b/ --profile op-model                        # the operation-model features
pss-corpus export --out b/ --level L1,L2 proc.func.*                 # id globs
```

`--out` is a directory (which must be empty or absent) or a `.tar.gz`, `.tgz`
or `.tar` file.

| Option | Selects |
|---|---|
| test patterns | tests whose id matches a glob (`proc.func.*`), whose directory matches a path glob (`proc/*`), or whose path contains a fragment (`neg`). None means all. |
| `--pss VERSION` | leaves out tests that need a newer PSS than the tool claims. Each is listed in the bundle and the report as "needs PSS 3.1". |
| `--level L1,L2` | only these levels |
| `--profile op-model` | only tests carrying this profile |
| `--no-l0` | do not add the L0 tier (see below) |

**L0 is always exported** unless you pass `--no-l0`. L0 checks the protocol
itself: the format specifiers, whole lines, and error locations. A tool whose
L0 run FAILs has every other result marked *untrusted* (§4.6). Without L0 in
the bundle, the report says trust was *not established*.

What a bundle holds:

| Path | Contents |
|---|---|
| `bundle.json` | schema `pss-corpus/bundle/1.0`: the corpus commit, the selection, each test (`id`, `rev`, `sha256` of its sources, `level`, `pss`, `lrm`, `root`, `sources`), each job (`job`, `test`, `root`, `seed`, `sources`), and the tests left out with the reason |
| `jobs.tsv` | the jobs again, one per line, for scripts that don't read JSON: `job ⇥ root ⇥ seed ⇥ sources…` |
| `tests/<id>/*.pss` | the sources, byte for byte |
| `run_jobs.py` | the job driver: a verbatim copy of `checker/src/pss_corpus/driver.py`, standard library only |
| `README.md` | the instructions below, for whoever runs the tool |
| `results/` | empty. The tool's site fills it in. |

A job is named `<test id>/seed-<n>`, and its output goes to `results/<test id>/seed-<n>/`.

## 2. At the tool's site

### The contract: three files per job

For each job, `results/<job>/` must end up holding:

**`log.txt`**: everything the tool printed while running the scenario,
**unedited**. The checker reads the text after `@@PSS-TRACE ` on each line, so
whatever a tool prints before it on the line (a timestamp, a UVM report header,
a severity tag) is ignored. What comes after the sentinel is not normalized:
padding, case, stray `\r` and split lines are all findings, on purpose (§4.2).
**Do not "fix" the log.**

**`outcome.json`**:

```json
{"schema": "pss-corpus/outcome/1.0",
 "outcome": "ok",
 "tool": "perspec", "tool_version": "…", "target": "c-host",
 "seed_honored": true,
 "detail": "free text; shown in reports, never used for a verdict"}
```

| `outcome` | when |
|---|---|
| `ok` | the scenario ran to completion |
| `compile_error` | the tool rejected the PSS: parse, link or semantic error |
| `solve_fail` | the tool found the constraints unsatisfiable |
| `runtime_error` | generated or interpreted code failed while running |
| `unsupported` | the tool rejected a feature *with a diagnostic saying so*. This is scored separately from FAIL. An honest "we don't do that" is not a wrong answer. |
| `timeout` | the run did not finish (the driver writes this itself) |
| `infra_error` | the setup failed, not the tool: a license, a path, a crash of the adapter. Scored ERROR, never FAIL. |

**`diagnostics.json`**, whenever the tool reported errors or warnings:

```json
{"schema": "pss-corpus/diagnostics/1.0",
 "diagnostics": [
   {"severity": "error", "file": "/abs/or/rel/path/tests/neg.ref.undeclared.001/test.pss",
    "line": 7, "column": 7, "message": "unknown identifier 'y'", "code": "E123"}]}
```

`severity` is `error`, `fatal`, `warning` or `note`, and only `error` and
`fatal` count. `file` may be absolute, relative, or a bare file name. It is
matched against the source's name by its trailing path. `column` and `code` are
optional. Negative tests are judged on this file (§4 below). A tool that
rejects them correctly but reports no location gets UNLOCATED, not PASS.

### The adapter

An adapter is any command that takes

```
<adapter> run --root <component::action> --seed <n> --out <dir> <file.pss>...
```

runs the tool on those files with that root action and seed, and writes the
three files into `<dir>`. The adapter is the only tool-specific code. In
practice it:

1. **Runs the tool.** It compiles or loads the sources and selects `--root` as
   the root action. It passes `--seed` to the tool's random seed and sets
   `seed_honored: false` if the tool has no seed. For a tool that generates
   code, it also builds and executes that code on whatever platform it targets
   (a host executable, a simulator), because the records are printed when the
   `exec body` *runs*, not when the test is generated.
2. **Routes `message()` to `log.txt`.** `message(NONE, …)` must be printed
   (LRM 21.1.3: `NONE` is always issued), one call per line.
3. **Classifies the ending** into one of the outcomes above.
4. **Parses the tool's error output** into `diagnostics.json`. This is usually
   a regular expression over the tool's error format.

`--platform` and `--iterations` are part of the §5 contract but not used by the
current tests. An adapter that doesn't support them may reject them.

### Running it

```
python run_jobs.py --adapter "<adapter command>" [-j N] [--timeout S] [--force] [job-glob...]
```

* `-j` defaults to **1**, because a licensed tool may have one seat. Raise it
  to what the licenses allow.
* A job that already has an `outcome.json` is skipped, so an interrupted run
  resumes where it stopped. `--force` reruns it.
* The adapter's own stdout and stderr go to `results/<job>/adapter.log`.
* An adapter that exits without writing `outcome.json` gets an `infra_error`
  written for it, naming its exit status. One that overruns `--timeout` gets a
  `timeout`. Every job that ran therefore has an outcome.

`run_jobs.py` is a convenience, not a requirement. A Tcl script, a Makefile or
a regression system that fills `results/` the same way is just as good.
`jobs.tsv` exists for exactly that.

Then send the whole bundle directory back, for example as a `.tar.gz`.

## 3. Import

```
pss-corpus import perspec-2026-09-returned.tar.gz          # or a bundle directory
pss-corpus import b/ --results elsewhere/results --out report/ -v
```

Every job is checked against the local corpus, and a report is written to
`<bundle>/report/` for a directory, or next to the tarball as `<name>-report/`:

* **`report.html`**: the one to read or send. It opens with the tool, the
  trust verdict, the pass rate and a verdict breakdown, then a table per area,
  then every run, worst first, with its reason. A run that didn't PASS
  expands to show its evidence: the LRM clauses, the tool's own detail, the
  trace records it printed, the errors it reported and, for an ERROR, the
  adapter's output. Verdict chips, an area picker and a search box filter the
  runs. The page is one self-contained file that fetches nothing, so it can be
  mailed and opened offline. Every string from the tool is escaped, and it
  follows the reader's light or dark setting.
* **`report.json`**: the source of truth (schema `pss-corpus/report/1.0`).
  `pss-corpus report report.json [--out F] [--md]` re-renders the HTML or
  Markdown from it, without the bundle.
* **`report.md`**: the same summary as Markdown, for a PR or an issue.

`pss-corpus run` writes the same three files to `<out>/report/`, so a tool run
here and one run elsewhere read the same. The command exits 0 only if every run
PASSed, 1 if any didn't, and 2 if the bundle itself is unusable.

| Verdict | Meaning | About the tool? |
|---|---|---|
| PASS | a legal execution, or a correct rejection at the right place | yes |
| FAIL | an illegal trace, a wrong outcome, or a rejection at the wrong place | yes |
| UNSUPPORTED | the tool declared a feature of the test unsupported | yes, and reported apart from FAIL |
| UNLOCATED | a negative test was rejected, but no error named a file and line | partly: the tool may be right and only its adapter silent |
| ERROR | `infra_error`, unreadable output, or a checker/model problem | no |
| STALE | the test's sources or `rev` changed since the bundle was exported, so the run is not scored against a test it didn't run | no |
| MISSING | the bundle came back without an `outcome.json` for the job | no |

**Trust.** The report states whether L0 established trust:

* *passed*: no L0 run FAILed, and at least one PASSed. An L0 run that is
  UNSUPPORTED (L0 includes a recursive function) or UNLOCATED doesn't withdraw
  trust.
* *failed*: an L0 run FAILed. Every result outside L0 is flagged `untrusted`.
  It is still computed, but not scored (§4.6).
* *not established*: the bundle had no L0, or its L0 runs are ERROR, MISSING or
  STALE. Those are facts about the setup, so fix them and import again.

The report also names every `tool`/`tool_version`/`target` the outcomes
reported, and warns when there is more than one: a mixed bundle is a mistake
at the tool's site.

**Staleness.** Each test's sources are hashed at export. If the corpus has moved
on since then (an edited `.pss`, a bumped `rev`), those runs are STALE rather
than being checked against a test the tool never saw. Export a new bundle to
cover them.

**Archives are not trusted.** A returned tarball is extracted only if every
member is a plain file or directory under the bundle. Absolute paths, `..`,
links and devices are refused. Nothing in a returned bundle is executed at
import.

## 4. Negative tests

A test whose model says `"expect": {"outcome": "compile_error", …}` passes only
when the tool rejects it **and** reports an error at the right place:

```json
"expect": {
  "outcome": "compile_error",
  "diagnostics": [{"file": "test.pss", "line": 7}],
  "note": "why that line"
}
```

* `line` is exact. `lines: [lo, hi]` accepts a range. Use it where the LRM
  doesn't say which of two lines an error belongs to.
* Every expected location needs at least one `error`/`fatal` diagnostic in
  that file on that line. Extra errors elsewhere are allowed, since tools
  cascade.
* An error reported somewhere else is a FAIL, and the reason lists where the
  errors were. A rejection with no located error at all is UNLOCATED.
* A positive test that a tool rejects is a FAIL whose reason quotes the first
  error.

The expected outcome and location come from the LRM clause the test cites,
never from what a tool printed. `L0.diag.location.001` checks the diagnostics
protocol itself. The rest are in `compliance/neg/`.

Every compliance test parses (§11.2): the negative tests here are semantic
(they fail to link, resolve or type-check), so parser, formatter and
highlighter sweeps over `compliance/` still see valid syntax. A test about a
*syntax* error belongs in `curated/pathological/`.

## 5. PSS versions and clause numbers

A model may say `"pss": "3.1"`: the lowest PSS version the test is written in.
When it doesn't, 3.0 is assumed, because the protocol's format specifiers
(`%u`, `%x`, `%n`, LRM 21.1.1) are 3.0 features, so no test can run on less.
The tags so far are the `sync_pkg` channel tests (3.1-only). Other tags are
added when a 3.1-only construct is found in a test.
`pss-corpus export --pss 3.0` then leaves the tagged tests out and says so.

Clause numbers in a model's `lrm` list are **PSS 3.1** numbers. They shift
between versions: the procedural statements are §20.7 in 3.1 and §22.7 in 3.0.
When you send a 3.0 tool's report to its vendor, say so.

## 6. Before you publish anything

A report is a statement about someone's product. EDA licenses commonly restrict
publishing benchmark or comparison results. Read the tool's license before a
report leaves the people who ran it. Until then, treat reports as private to
you and the vendor.

## 7. First target: Cadence Perspec

What follows is a plan, not a record. The Perspec-specific points are questions
to settle with someone who has the tool.

1. **Smoke bundle.** Export `--pss 3.0` with L0 only (16 tests, including the
   diagnostics test). This answers the questions every later result depends on:
   * **Execution platform.** Perspec solves at generation time and emits target
     code (C, or SV/UVM). The records only appear when that code *runs*. So the
     adapter has to generate, build and execute, and the cheapest platform
     that prints `message()` output is the one to use for the procedural tier.
     Is there a host-executable C flow, or does it have to be a simulator?
   * **`message()`.** Is `std_pkg::message` supported with the 3.0 format
     specifiers? Does each call land on one line, and where (stdout, a UVM
     report, a log file)? L0 answers this in detail. The adapter only has to
     collect the lines.
   * **Seeds.** Which option sets the generation seed? Does one generation per
     job make sense, or should `--iterations` batch them?
   * **Error format.** The shape of Perspec's error messages, for the regular
     expression that writes `diagnostics.json`.
2. **Procedural tier**: `proc/`, `types/`, `comp/` and `neg/`, at `--pss 3.0`.
   These are L1 and L2, one feature per test, so a failure points at a feature.
3. **Later**: the memory and register tiers (§4.12, §4.13), once the reference
   platform exists. Only the executor tap is portable without linking suite C
   code into Perspec's generated test.

Keep Perspec's expected-failure list with its adapter, not in the corpus
(§11.4), as pssc does in `tests/compliance/expected/`.

## 8. How this path is tested

* `checker/tests/test_bundle.py` round-trips bundles through `perfect_tool.py`,
  an adapter that is always right: directory and tarball, the driver run
  standalone with no `PYTHONPATH`, staleness, missing results, the three trust
  states, unsafe archives, timeouts, a silent adapter and resuming. It also
  holds `run_jobs.py` to the standard library.
* `checker/tests/test_diagnostics.py` lints every negative model and requires
  each way of being wrong (wrong line, wrong file, no rejection, no location,
  warnings only) to get its own verdict.
* pssc's `tests/compliance/test_handoff_roundtrip.py` exports the whole corpus,
  runs pssc's bc adapter over it as a separate command through the bundle's
  own `run_jobs.py`, imports the results, and requires every verdict to equal
  the in-process run's. If the hand-off adds or hides anything, that test fails.
