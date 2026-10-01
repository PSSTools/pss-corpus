# pss-corpus: the Executable (Compliance) Tier — Design

**Status:** Draft for review. D-1–D-10 decided 2026-09-24; procedural tier and yield ladders added 2026-09-24; data matrix, memory/register taps and host library added 2026-09-24; D-11 decided and D-12 deferred 2026-09-24 (memory observed by a pure-PSS executor tap; D-13, D-14 open). **Executor tap running 2026-09-24:** `lib/pct_tap.pss`, `acc` leaves and `F8` in the checker, the four L0-P tests, passing on pssc `op-model-py` (§13, P3 "Platform"). **First slice running 2026-09-24:** 58 procedural and L0 tests, the P1 checker, and the `pssc-bc` adapter (see §13, "P1 progress")
**Date:** 2026-09-23 (revised 2026-09-24)
**Location:** `pss-corpus/compliance/` (data), `pss-corpus/checker/` (code, see §11 and `D-1`)
**Normative reference:** PSS 3.1 Public Review Draft, 2026-08-28 (cited as *LRM §n*)
**Related:** `PLAN.md` (the corpus contract), `pssc/docs/design/generic-constraints-system-tests.md`
§9 (construct-level tests)

---

## 0. Summary

The suite is a set of **tests**. Each test is:

- one or more **`.pss` files**, instrumented so that the scenario reports what it did as text lines
  written with `message(NONE, …)`;
- one **`.json` reference model**, which describes *what is legal* for that PSS. It does not
  describe *what should be printed*.

A tool under test is wrapped in a small **adapter**. The adapter runs the `.pss` and returns a text
log and an outcome. The **checker** pulls the trace records out of the log and decides whether they
describe a legal execution of the model:

- **Structure:** does the trace parse against the activity, including inferred actions?
- **Data:** does one satisfiable assignment explain every observed value? An SMT solver decides
  this.
- **Binding:** does some flow-object and resource binding explain the observed values and the
  observed order?

Tests cover **two kinds of behaviour** with the same protocol and the same checker:

- **Scenario behaviour:** which actions are traversed and in what order, random attribute values,
  flow-object and resource binding, and inference.
- **Procedural behaviour:** what `exec` blocks and functions compute, including locals, control flow,
  function calls, collections, run-time integer semantics and exec ordering. This is the simpler
  case. Procedural code is deterministic given its inputs, so the legal set for a checkpoint is
  usually a single value, and checking is mostly equality (§4.8, §6.7).
- **Platform behaviour:** every data type, initialization form and parameter-passing mode
  (§4.11), memory and register accesses (§4.12), and values crossing the foreign-language boundary
  (§4.13). Suite-owned code, never the tool, captures the accesses and feeds the values that are
  read.

Three more things sit on top of the pass/fail verdicts:

- a **feature taxonomy** keyed to LRM clauses and Annex B productions, so we can say what the suite
  covers, alone and in combination;
- a **distribution layer**, built in from v1 and switched on in phase 2, that aggregates samples
  across seeds or iterations and tests them against distributions the oracle computes;
- a **backend × feature matrix**, which is the tool pssc uses to align its pipelines.

The central design choice is **legality checking rather than golden output**. A random scenario has
many correct traces, so a golden file can only test one tool against itself. A legality model can
test any tool, any seed, and any backend against the LRM.

---

## 1. Goals and non-goals

### Goals

- **G1. Tool-neutral.** The only thing the suite asks of a tool is that it can run a scenario and
  print `message()` output. Nothing depends on pssc, pssparser or dv-solve internals.
- **G2. Semantic, not syntactic.** The suite checks what a construct *means* (LRM), observed at run
  time. This lifts the construct-level test category in pssc
  (`generic-constraints-system-tests.md` §9) from a single vehicle, bc, to every backend.
- **G3. Randomness-aware.** Any seed may produce any legal trace. The verdict is the same for every
  legal choice the tool makes.
- **G4. An independent oracle.** Verdicts come from the reference model plus an off-the-shelf SMT
  solver (Z3, Bitwuzla, cvc5 or Boolector), never from the pipeline under test. dv-solve is never
  the judge of dv-solve.
- **G5. Measurable coverage.** For every LRM feature, and for chosen feature combinations, the suite
  can say which tests exercise it and how each tool or backend does on those tests.
- **G6. Distribution-ready.** Assessing random distribution is phase 2. The v1 trace format, adapter
  contract and checker output are designed so phase 2 adds to them and changes nothing (§8).
- **G7. Usable by others.** A third-party vendor can run the suite with an adapter of about 30 lines
  and get a compliance profile.

### Non-goals

- **Checking generated code.** SV, C and Python text is never inspected. Goldens and the
  `tests/progseq` conformance checks keep doing that.
- **Checking diagnostic text.** Negative tests check the *outcome category* and the error's
  *location* (file and line), never the wording of the message.
- **Performance.**
- **Replacing pssc's unit, lowering and golden tests.** The suite is the outermost ring.
- **Checking target-side time.** PSS has no portable notion of time, so concurrency checks rest on
  the scenario's *logical* structure (§6.4), not on the clock.

---

## 2. What exists today

### 2.1 `pss-corpus`

- 92 frozen `.pss` files in 7 buckets.
- `manifest.toml` holds facts about the files only, chiefly `parses`.
- `PROVENANCE.md`, and an Apache-2.0-only rule.
- Explicitly *data only*: "there is nothing to build".
- Consumers are `pssfmt`, `pygments-pss` and `pssparser`. All check the **parse level**; nothing
  checks semantics.

The suite reuses this repo's contract habits:

- discovery via `$PSS_CORPUS`;
- absent means fail, not skip;
- no consumer defects in the corpus;
- the licence policy.

It does need one amendment, because a checker is code (`D-1`).

**Licensing consequence.** LRM examples are © Accellera, so they cannot be vendored verbatim. A test
derived from an LRM example is a **rewrite** that cites the clause. The `pssc/tests/patterns/README.md`
already records this practice.

### 2.2 pssc pipelines

| Vehicle | Runs scenarios | `message` | Activities | Flow objects / pools / inference |
|---|---|---|---|---|
| `sv-native` (+ `sv-dpi*`) | Verilator / VCS / Questa | `$display` | full; `schedule` as staged fork/join | yes; inference SIMPLE at runtime, COMPLEX deferred |
| `python` (be-py) | in-process | Python `%` | full | buffer and state inference; **inferred stream producers raise an error** |
| `c-host*` / `c-embedded*` | gcc + run | `fprintf(…"\n")` | **par/schedule serialized; non-const `repeat` → nothing; `select` → first branch; other nodes silently dropped** | none |
| bc oracle / `zuspec-rt-eng` | API only (`_bc_harness.py`); `pssc-bc` adapter | builtin IMPORT, formatted per §21.1.1 by the interpreter (2026-09-24; rt-eng not yet) | seq/par/select/repeat/foreach/if/match; `schedule`≈`par` | none (`UnsupportedConstructError`) |
| `op-model-*` | via the root action's `exec body` (D-10) | `pssc_message` / imports seam | — | — (procedural tier; memory and registers through the executor tap once the backend delegates, D-11) |

Findings that shape this design:

1. **Silent drops exist.** The C lowering drops constructs it does not know, and `select` always
   takes branch 0. A suite that only checked that a run "completed and printed something" would pass
   these. This is the strongest argument for a legality model over smoke tests.
2. **Formatting already diverges.**
   - SV `%d` pads to width, while the LRM `%d` does not pad.
   - C `print` appends `\n`, while the LRM `print` does not.
   - `%h` is not PSS, and only SV accepts it.
   - Escape handling differs between C and Python.

   The trace protocol therefore needs its own conformance tier, L0 (§4.6). Adapters must not
   normalize these differences away, because they are exactly what L0 is there to find.
3. **Existing traces are internal and incompatible.** bc has a JSONL orchestration trace with no
   action names or values. be-py has `ActivityTracer` hooks. The SV runtime has `ZSP_TRACE*` macros,
   mostly unused. None of them is portable. We define a new portable one on top of `message`, and
   let tools emit it natively as an optional extra (§4.7).
4. **Cross-backend comparison does not exist.** Today's differential tests are bc versus legacy be-py
   (import sequences) and rt-eng versus the bc oracle (hand-written bytecode). `tests/patterns/*.pss`
   runs only on SV/VCS and checks only for the string "TEST PASSED".
5. **Existing harnesses are useful as adapters.** `_bc_harness.py`, the Verilator helpers in
   `tests/sim/sv/_verilator.py` and the gcc paths in `test_target_sw.py` already do the
   "run it end to end" part.

### 2.3 Other assets

- **LRM.** Annex B (the normative BNF, B.1–B.21) and Annex E (the solution-space procedure) give us a
  feature-taxonomy spine and a written algorithm for the checker's inference validation.
- **LRM probability statements.** The LRM is normative about probability in only two places: `dist`
  (§13.1.13) and `select` weights (§11.4). It also requires **random stability** (§13.4.6.2). §8
  depends on this.
- **z3-solver.** It is already in the shared venv (used by `zuspec-be-fv`). Bitwuzla ships on PyPI
  with Python bindings.
- **pssparser.** It exposes a CST (`pssparser.cst`, whose nodes carry `rule_name`) and a generated
  AST visitor. Both are good for *coverage accounting* (§9). They are never used for *verdicts*
  (G4).

---

## 3. Architecture

```
            ┌──────────────── compliance/<area>/<test>/ ─────────────────┐
            │  test.pss (+ lib .pss)        test.json (reference model)  │
            └──────┬──────────────────────────────┬──────────────────────┘
                   │                              │
          ┌────────▼────────┐                     │
          │ adapter (per    │  seed, root action  │
          │ tool/backend)   │◄──── runner ────────┤
          └────────┬────────┘                     │
         log text + outcome                       │
                   │                              │
          ┌────────▼────────┐   ┌─────────────────▼───────────┐
          │ extractor       │──►│ checker                     │
          │ (@@PSS-TRACE)   │   │  1 outcome  2 structure     │
          └─────────────────┘   │  3 data/binding (SMT oracle)│
                                │  4 sample extraction (§8)   │
                                └───────┬─────────────────────┘
                                        │ per-run result JSON
                   ┌────────────────────┼────────────────────┐
          ┌────────▼───────┐   ┌────────▼────────┐  ┌────────▼────────┐
          │ verdict report │   │ distribution    │  │ coverage report │
          │ (tool × test)  │   │ aggregator (§8) │  │ (feature × tool)│
          └────────────────┘   └─────────────────┘  └─────────────────┘
```

Separation of concerns:

- **Tests** are data, versioned with the corpus.
- **Adapters** belong to whoever owns the tool. pssc's adapters live in pssc.
- **The checker, runner and reports** are one small Python package named after the repository:
  distribution `pss-corpus`, import root `pss_corpus`, command `pss-corpus` (D-8). It lives in
  `checker/` (D-1).
  - Verdict dependencies: the stdlib, a JSON-schema validator and an SMT solver. It does not use
    pssparser, pssc or dv-solve for verdicts.
  - Authoring aids (lint, feature detection) *may* use pssparser, under a separate entry point.

---

## 4. The PSS trace protocol (v1)

### 4.1 Constraints on the design

- `message()` is the only uniform output channel. It is a **target** function, called from `exec
  body` and from any function that target code calls (LRM §21.1.3). `print` runs at solve time and backends treat it inconsistently, so the
  protocol does not use it.
- `exec body` exists only on **atomic** actions (LRM §20.1). Compound actions, flow objects,
  resources and components cannot report for themselves; atomic bodies report on their behalf.
- A tool may decorate a message line, for example with UVM prefixes, timestamps or `[ZSP]`. It may
  also interleave lines from concurrent bodies. It will not split a single message line.
- The LRM gives the verbosity `NONE` as always issued.

### 4.2 Record format

A **record** is the part of any log line that follows the first occurrence of the sentinel `@@PSS-TRACE `.
The sentinel is deliberately brand-neutral. It is embedded in every instrumented `.pss` file and in
other people's adapters, so it must never change when a project or package is renamed.
Anything before the sentinel is ignored.

```
@@PSS-TRACE <kind> <tag> [<key>=<value> ...]
```

- `kind` is one of the record kinds below.
- `tag` is an author-chosen token that names what is reporting, normally the qualified action type
  (`pss_top::produce`). It is a literal in the format string, so tools never have to produce type
  names.
- `key` is a path relative to the reporting action, for example `mode`, `out.tag`, `r.instance_id`,
  `comp.id` or `arr[3]` (§4.10).
- `value` is one of:
  - a decimal integer, which may be negative, from `%d`;
  - `0x`-prefixed hex, from `%x` with a literal `0x` in the format string, for widths above 64 bits;
  - `true`/`false`;
  - an enum item name, from `%n`, or an integer from `%d` applied to `(int)e`;
  - a string token with no spaces, from `%s`.

  Values are **strict**: `a=   3` is a protocol violation, not `3` (see §2.2, the SV padding
  finding).

**Each record is emitted by a single `message` call, and each atomic `exec body` emits exactly one
`act` record as its first statement.** Single-call records are atomic under concurrent execution,
so the extractor never has to join fragments. Any number of `chk` records may follow the `act`
record, from the body itself or from functions it calls (§4.8). They belong to that occurrence.

| kind | Emitted by | Meaning |
|---|---|---|
| `act` | every atomic action's `exec body` | this action occurrence executed; carries its observed fields and those of its flow/resource refs |
| `obs` | an *observer* action (§4.4) | reports values of an enclosing compound action or component |
| `chk` | target procedural code: an `exec body` after its `act` record, a function called from it, or `run_start`/`run_end` | named procedural checkpoint (`chk sum_to.step i=3 acc=6`); matched against the owning occurrence's `body` pattern (§6.7) |
| `end` | the last action of the root activity (optional) | explicit end-of-scenario marker; guards against truncated logs |
| `acc` | the suite's executor tap only (§4.12) | one memory or register access: operation, address and data |
| `imp` | suite-owned host library only (§4.13; deferred, D-12) | a value received by an imported function |

### 4.3 Instrumentation conventions

```pss
import std_pkg::*;

component pss_top {
  pool data_b data_p;
  bind data_p *;

  action produce {
    output data_b out;
    rand bit[4] mode;
    constraint mode < 3;
    exec body {
      message(NONE, "@@PSS-TRACE act pss_top::produce mode=%d out.tag=%d out.len=%d",
              mode, out.tag, out.len);
    }
  }
  ...
}
```

- **Observe everything checkable.** Every `rand` field of an atomic action, and every field of every
  flow or resource ref it declares, is observed. `instance_id` is observed for resources. Fields left
  unobserved are **existentially** quantified by the checker (§6.3). That keeps verdicts sound but
  weakens them, so `pss-corpus lint` warns about any unobserved `rand` field unless the JSON marks it
  `"observe": false`.
- **Component identity.** Only multi-instance tests need it. Every component gets an attribute
  `int pct_id`, assigned in `exec init_down` by its parent. Actions report it as `comp.pct_id=%d`.
  PSS has no portable instance name, so this is the only way to tell *which* `dma_c` ran an action.
  Because it exercises `exec init_down`, it is kept out of tests that do not need it.

### 4.4 Observer actions

A compound action has no body, so its own `rand` fields and constraints are observed through an
**observer**: a dedicated atomic action traversed within its activity, whose fields are tied to the
parent by an inline constraint.

```pss
action obs_top { rand bit[8] n; exec body { message(NONE, "@@PSS-TRACE obs top n=%d", n); } }
action top {
  rand bit[8] n; constraint n in [2..5];
  activity { repeat (n) { do leaf; }  do obs_top with { n == this.n; }; }
}
```

The reference model knows `obs_top` is an observer: it is declared in the JSON with `"role":
"observer"`. It still takes part in structural matching like any action, but reports exclude it from
the feature under test.

### 4.5 What is and is not observable

| Observable | How |
|---|---|
| which atomic actions ran, how many, and in what order | `act` records and their order |
| random attribute values of actions and flow/resource objects | keys in the record |
| binding (which output a given input consumed) | not printed; a **witness** is inferred from values plus order (§6.3) |
| resource instance chosen | `instance_id` |
| compound attributes | observers |
| component attributes and hierarchy | `pct_id` and observers |
| values computed by target procedural code, and the path taken through it | `chk` records, in order (§4.8) |
| values computed at solve time (`pre_solve`, `post_solve`, `pre_body`, `init_down`/`init_up`, solve functions) | stored in non-rand attributes and reported by a later `act`/`chk` record (§4.8) |
| order of solve-time exec blocks | an order signature accumulated in an attribute (§4.8) |
| compile rejection, solve failure, runtime error | the adapter's outcome (§5), never a trace |
| interleaving of concurrent bodies on one executor | yield ladders (§4.9) |
| aggregate, string, `chandle` and reference values | reduced to scalar leaves by fixed conventions (§4.10) |
| memory and register accesses: address, width, data, order | `acc` records from the executor tap (§4.12) |
| values crossing the foreign-language boundary | `imp` records from the reference host library, plus `chk` records on the PSS side (§4.13; deferred, D-12) |
| symbolic register names in generated code | **not observable**; link-level only (§4.12) |
| wall-clock concurrency | **not observable**; logical concurrency otherwise comes from structure (§6.4) |

### 4.6 L0: the protocol conformance tier

Every other result relies on `message` formatting, so the first tier tests the protocol itself:

- `%d` for negative values, zero and 64-bit extremes;
- `%x`, `%s`, and `%n`/`(int)` for enums and bool;
- no padding;
- exactly one newline;
- a literal `@@PSS-TRACE` survives;
- a message from a deeply nested atomic action;
- messages from `parallel` branches arrive whole;
- a `message` from inside a called function, including a recursive one, emits in call order;
- a rejected test is reported as `compile_error`, with a `diagnostics.json` error at the offending
  line (`L0.diag.location.001`, an unresolved type name). This is the error-marker half of the
  protocol.

If a tool fails L0, the report marks every other result for that tool **untrusted** rather than
FAIL. Those results are still computed, but they are not scored.

### 4.7 Native mode (optional)

A tool that cannot print from a body can still take part. So can a tool that wants to certify
without the instrumentation cost, such as a solve-only tool that produces a scenario file. In either
case the adapter translates the tool's own trace into trace records, and the report labels the result
`native`. Instrumented mode stays the reference. Native mode exists to include tools, not to
certify them.

### 4.8 Instrumenting procedural code

Procedural code is tested through the same protocol. Its scope:

- exec blocks and functions (LRM §20.1–20.3, §20.7): scoped blocks, local variables, assignment and
  compound assignment, `return`, `repeat`/`repeat-while`/`foreach`, `if`/`match`, `break`/`continue`;
- function parameters: direction, `const`, defaults, generic and varargs (§20.2), and parameter
  passing (§20.3.2), pure functions, recursion;
- run-time expression evaluation (§8.7): width, signedness and truncation on assignment;
- collections operations (§7.9) and string formatting (§21.1);
- the `randomize` statement (§20.7.12);
- exec evaluation order and exec inheritance/extension with `super` (§20.1.4–20.1.5).

The instrumentation rules depend on *where* the code runs.

**Target code** (`exec body`, functions called from it, and component `run_start`/`run_end`) emits
`chk` records directly, anywhere, any number of times: inside loops, in each branch, in recursive
calls. The *sequence* of `chk` records is the observation. It shows both the values computed and the
path taken through the code.

```pss
import std_pkg::*;

function int sum_to(int n) {          // package scope: callable from any exec
  int acc = 0;
  repeat (i : n) {
    acc += i;
    message(NONE, "@@PSS-TRACE chk sum_to.step i=%d acc=%d", i, acc);
  }
  return acc;
}

component pss_top {
  action A {
    rand bit[4] n;
    exec body {
      message(NONE, "@@PSS-TRACE act pss_top::A n=%d", n);
      int r = sum_to(n);
      message(NONE, "@@PSS-TRACE chk result r=%d", r);
    }
  }
}
```

**Solve-time code** (`pre_solve`, `post_solve`, `pre_body`, `init_down`/`init_up`, solve functions)
cannot call `message`, which is a target function. It is observed by **compute at solve time, report
at run time**: the code stores its results in non-rand attributes of the action, object or
component, and the action's `act` record or a later `chk` record reports them. Two patterns:

- **Result attributes.** `post_solve { total = a + b; }` is observed as `total=` in the `act`
  record.
- **Order signatures.** For exec ordering (§20.1.5, and `init_down`/`init_up` across a component
  tree), each exec block folds a distinct small code into one integer attribute:
  `sig = sig * 16 + k;`. The final value encodes the complete evaluation order without needing
  collections, and the model states the legal signature, or a set of them where the LRM leaves
  order open.

`print` is never used, for the reasons in §4.1.

**Concurrency.** In sequential code, `chk` records belong to the most recent `act` record. Code that
can run concurrently with another body carries an occurrence key on every record, and records are
attributed by that key instead (§4.9, `D-9`).

**Why this tier is simpler.** Apart from `randomize`, procedural code is deterministic given its
inputs. Checking needs no binding search and no inference, and usually no disjunction:

- With **constant inputs**, every expected value is a constant. The legal set is a single trace, and
  the checker compares values directly without calling a solver (§6.7).
- With **random inputs** (fields of the owning action), expected values are *functions* of the
  observed inputs, stated as constraints. The same SMT problem as in §6.4 decides them.

It is the one place where the model can legitimately pin exact output. That is acceptable only
because the LRM makes the result unique. The model still states it as constraints, so the checker
has no second mode.

### 4.9 Observing concurrency: yield ladders (`D-9`, decided)

With only one record per body, concurrent execution is invisible: `parallel` and `sequence` produce
the same kind of trace. The `yield` statement (LRM §20.7.14) makes it observable, and the LRM gives
it a checkable rule:

> c) If other exec code is currently being executed in parallel, code in at least one other exec
> block will be executed before the statement after this one executes.

**The ladder.** A body under test for concurrency is a *yield ladder*: its `act` record, then *K*
rungs, each a `yield` followed by one `chk` record:

```pss
action A {
  rand bit[8] id;                      // occurrence key, set by the activity (below)
  exec body {
    message(NONE, "@@PSS-TRACE act pss_top::A occ=%d", id);
    repeat (k : 3) {
      yield;
      message(NONE, "@@PSS-TRACE chk A.rung occ=%d k=%d", id, k);
    }
  }
}
action top {
  activity {
    parallel {
      do A with { id == 1; };
      do A with { id == 2; };
    }
  }
}
```

Every statement between two yields emits a record, so any exec code that runs leaves a record behind.
That turns rule (c) into a property of the trace.

**Occurrence keys.** Once bodies interleave, "the most recent `act`" no longer identifies a `chk`
record's owner. So every record from code that can run concurrently carries `occ=`. That is a field
whose value the activity makes distinct among concurrently-live occurrences of the same type, by
`with { id == 1; }`, or `replicate (i : N) do A with { id == i; }`. Records are attributed by
(tag, `occ`). `pss-corpus lint` enforces the key on any `chk`-emitting action reachable from
`parallel`, `schedule` or `replicate`, and `pss-corpus validate` proves the activity makes the keys
distinct.

**What the checker derives.** An occurrence is **live** from its `act` record until its last
expected record. The `body` pattern (§6.7) fixes that count, which is why ladders have a constant *K*.

| Check | Rule | Verdict |
|---|---|---|
| **Yield rule (c).** When occurrence *X* yields while some other logically-concurrent occurrence on the same executor is live, at least one record from another occurrence appears before *X*'s next record | LRM §20.7.14(c): "will be executed" | FAIL if violated |
| **Sequencing.** Occurrences ordered by the activity (`seq`, buffer/state dependencies) never interleave, and a successor's `act` follows its predecessor's last record | LRM §11, §14 | FAIL if violated |
| **Realized concurrency.** In `parallel`, when every branch is a ladder, the branches' records interleave at least once | LRM §20.8: tools are "expected to enable concurrent execution" | FAIL for the feature `exec.concurrency.yield`. The LRM's wording is "expected", not "shall", so the report annotates this result |
| **Resource exclusion.** Two occurrences that `lock` the same resource instance, or one `lock`s and one `share`s it, never interleave | LRM §9.4, §12.4 | FAIL if violated |

These checks close the gap D-3 left open. In particular, a tool that runs `parallel` branches one
after the other passes every single-record test, but fails the realized-concurrency check. That is
the `c-host` behaviour found in §2.2. Wall-clock overlap remains unobservable. Interleaving under
cooperative scheduling is what these checks observe, and it is what the LRM's concurrency guarantees
are stated in.

**Scope.** All ladders in a test run on one executor, the default. Multi-executor concurrency
(§21.7) is L5. Ladder tests are otherwise ordinary L3/L4 tests, and the feature taxonomy gains
`exec.yield` and `exec.concurrency.*` entries.

### 4.10 Observing values of every type

The record format carries scalars only. Every other type is observed by reducing it to scalars,
using fixed conventions so that a record key always names one leaf value.

**Key paths.** A key is a path of `.`-separated segments, each optionally followed by `[<int>]`
indices: `s.a.b`, `arr[3]`, `grid[1][2]`, `l.size`. By default a key names the field or local of
the same path. Where that is not expressible, the model maps a key to a PSS expression: for
example `"m_a": "m[\"a\"]"` for a string-keyed map entry.

| Type (LRM) | Observed as |
|---|---|
| `bit[N]`/`int[N]`, N ≤ 64 (§7.2) | `%d` |
| N > 64 | `0x%x` (§4.2) |
| `bool` (§7.4) | `true`/`false` (§4.2) |
| enum (§7.5) | `(int)e` with `%d` (D-7) |
| `string` (§7.6) | `%s` when the test's strings are token-safe. Otherwise the test reports `size()`, sub-strings and comparisons with literals, as integers and bools |
| `chandle` (§7.7) | not printable. Observed by identity round trips through the host library (§4.13) and by equality comparisons printed as bools |
| struct (§7.8) | one key per leaf field: `s.a.b` |
| fixed array `T[N]`, `array<T,N>` (§7.9.2) | `a[i]` for every element, in one record when N ≤ 8. Otherwise, a dump loop as for lists |
| `list<T>` (§7.9.3) | `l.size`, then one `chk` record per element, `i=` and `v=`, from a `foreach`. Order is observed |
| `map<K,V>` (§7.9.4) | `m.size`, plus lookups of the keys the model names. The suite never depends on map iteration order |
| `set<T>` (§7.9.5) | `s.size`, plus membership (`k in s`) of the values the model names, as bools |
| `ref T` (§7.10) | aliasing: write through one name, read through the other. Null-ness as a bool |
| `addr_handle_t` (§21.13.3) | `addr_value(h)` as `0x%x`, in target code only |
| `float32`/`float64` (§7.3) | excluded from v1 (D-6) |

**Aggregate observation must not depend on the feature under test.** A dump loop depends on
`foreach`, and a tool that fails `foreach` would then fail every list test for the wrong reason. So
for aggregates of 8 or fewer leaves, generated tests unroll the keys into one record. Loop-based dumps
are used only where the aggregate is large, and the test then declares `proc.foreach` in
`features.uses`.

**Every leaf gets a distinct value.** Tests give each leaf of an aggregate a value that no other leaf
has. A field swap, a wrong index, a lost write or an aliasing bug then changes an observed value
instead of hiding behind a coincidence.

### 4.11 Data types, initialization and value passing

Hand-picked tests cannot show that the suite is comprehensive over data. The only way is to state
the space and enumerate it. The space has five axes:

| Axis | Values (LRM) |
|---|---|
| **T: type** (§7) | integers at the widths that expose promotion and truncation: `bit`/`int` with no width, and 1, 7, 8, 31, 32, 33, 63, 64, 65 and 128 bits; domain-restricted integers (`bit[8] in [..]`); `bool`; enums with implicit, explicit, sparse and negative values, with a base type, and extended (§17); `string`; `chandle`; structs (flat, nested, inherited, templated, `packed_s` little- and big-endian); `T[N]` and `array<T,N>`, including multi-dimensional arrays; `list`, `map`, `set`, with scalar, struct and collection elements, nested at most 2 deep; `ref T`; `typedef` aliases of each |
| **S: storage** | local variable in an exec or function; action field (`rand` and non-`rand`); flow-object field; resource field; struct field; collection element; component attribute; `const` and `static const` at package and component scope; template value parameter; function parameter; function result |
| **I: initialization** | the implicit default value; a declaration initializer (constant, and non-constant for locals); aggregate literals: empty `{}`, value-list, map, struct with designators, nested (§4.8); copy from another variable; function result; `exec init_down`/`init_up` for component attributes; action attribute initialization in the activity (§11.3.1.2); assignment in `pre_solve`/`post_solve`; solving, including `default` value constraints (§13.1.11); the `randomize` statement (§20.7.12); an imported function's `output` parameter (§20.4.1) |
| **P: passing and return** | native functions: scalars by value, aggregates by handle (callee writes are visible), references as aliases that may be null (§20.3.2); a derived struct passed as its base type (§20.3.2); default parameter values (§20.2.4); generic and varargs parameters; return by value for each type, and `ref` return (§7.10); imported functions with `input`, `output` and `inout` over the §20.4.1(c) type list; exported functions (§20.4.2); static and instance functions; solve and target contexts; recursion |
| **O: operation** | assignment with value semantics (copy, then mutate the copy) (§8.3); `==`/`!=` on aggregates (§8.5.3); casts and conversions: widen, narrow, sign change, enum↔int, bool↔int (§7.12); string operators and methods (§7.6.2–7.6.3); each collection method (§7.9); `in`; indexing, including out-of-range where the LRM specifies the result; `sizeof_s` (§21.13.2) |

The full product is far too large and mostly meaningless, so coverage is defined on three
**projections**. Each is enumerated exhaustively over its legal cells:

- **storage:** T × S × I. Can a value of this type live here, initialized this way, and read back
  intact?
- **passing:** T × P. Does the value survive the call, with the direction and aliasing semantics
  the LRM states?
- **operations:** T × O.

**The legality table.** `compliance/data/legality.yaml` states, for each axis combination that the
LRM restricts, whether it is legal, and cites the clause. Examples are whether `rand` is permitted on
a `string` or a `map`, and which types an imported function may take (§20.4.1(c)). Each cell of a
projection is then one of:

- **legal:** a positive test;
- **illegal:** a negative test expecting `compile_error`;
- **lrm-silent:** no test. The cell is listed in the report as an LRM question, and the list is
  something we can hand to Accellera.

**The data-matrix generator** (`compliance/generators/data_matrix.py`, §10.3) emits every legal and
illegal cell. Expected values are written as `pss` expressions and reduced to `eq` constants by the
D-2 translator. They are never taken from a tool. Values are drawn from each type's edge set (0, 1,
−1, min, max, max−1 and an alternating bit pattern), with the distinct-leaf rule (§4.10). For
example, the passing cell (struct, native function) together with (int, native function):

```pss
import std_pkg::*;

struct pt_s { bit[8] a; int[16] b; }

function void bump(pt_s p, int[16] k) { p.b += k; k = 0; }

component pss_top {
  action A {
    exec body {
      message(NONE, "@@PSS-TRACE act pss_top::A");
      pt_s x = {.a = 7, .b = -3};
      pt_s y = x;               // value semantics: y is a copy
      int[16] k = 5;
      bump(x, k);               // aggregate by handle, scalar by value (§20.3.2)
      message(NONE, "@@PSS-TRACE chk pass x.a=%d x.b=%d y.b=%d k=%d", x.a, x.b, y.b, k);
    }
  }
}
```

The model is `"eq": {"x.a": 7, "x.b": 2, "y.b": -3, "k": 5}`. It catches three distinct mistakes:
a struct passed by value (`x.b=-3`), a scalar passed by reference (`k=0`), and a copy that aliases
(`y.b=2`).

**Batching.** One cell per test would mean thousands of builds, and an SV elaboration each. So the
generator groups the positive cells for one type into a single test, with one action and one `chk`
tag per cell, and the checker reports a verdict **per cell**. If a batch gets `compile_error`, the
runner splits it in half and reruns until each unsupported cell is isolated. The result per cell is
the same as one cell per test would give, at a fraction of the builds. Negative cells are never
batched, because one `compile_error` would hide the others.

**Completeness is by construction.** The report lists every cell of every projection with its
state: covered, uncovered (the generator has no template for it yet), negative or lrm-silent. The
target is no uncovered cells.

### 4.12 Memory and register access

Register and memory tests have to check more than the values PSS code sees. They have to check
the **accesses** themselves.

**What must be observed:**

- **Allocation (§21.11).** Claim size, alignment, trait matching, and non-overlap of claims whose
  lifetimes overlap (§21.11.6).
- **Handles (§21.13.4–21.13.5).** `make_handle_from_claim` and `make_handle_from_handle`, including
  offsets and `sub`, and `addr_value`.
- **Primitive accesses (§21.13.9.1–21.13.9.2).** Address, width and value, and the byte-order rule:
  the first byte goes to bits `[7:0]`.
- **Byte lists (§21.13.9.3).** `read_bytes` and `write_bytes`.
- **Packed structs (§21.13.1, §21.13.9.4).** The packing rule for both endiannesses, don't-care bits,
  `sized_addr_handle_s` fields, and the "shall" that an aligned struct of 8, 16, 32 or 64 bits is
  accessed with a single primitive of that size.
- **Registers (§21.14).**
  - The width of each access equals the register size (§21.14.5(a)).
  - The address is the region base plus the offset sum from `get_offset_of_instance`,
    `get_offset_of_instance_array` or `get_offset_of_path` (§21.14.5(b)).
  - Register-value types that are packed structs, `bit[N]` registers, and reserved bits.
  - `read`/`write` and `read_val`/`write_val`.
  - The read-modify-write operations (§21.14.1): `write_masked`, `write_val_masked`, `write_field`
    and `write_fields`.
  - Register arrays, nested groups and `reg_sized_c` lists.
  - `get_handle` with raw access (Example 363).
  - `set_handle` on the top-level group only.
  - The access-kind errors on `READONLY` and `WRITEONLY` registers.
- **Customization (§21.13.9.5).** Executor overrides and `mem_access_desc_s` extensions.

**Why read-back is not enough.** D-10 observed register effects by reading them back through the
model, which misses every *symmetric* error:

- a wrong offset used for both the write and the read-back;
- a byte swap applied on both paths;
- a packing error mirrored by the matching unpacking error;
- a read-modify-write that skips the read because the backing memory happens to be 0;
- a single aligned struct access split into two.

Read-back stays useful, but the accesses themselves become part of the trace.

**Access records.** A new record kind, `acc`, has one record per primitive operation:

```
@@PSS-TRACE acc w32 addr=0xa0000004 data=0x11223344
@@PSS-TRACE acc r8 addr=0x80001003 data=0x5a
@@PSS-TRACE acc wb addr=0x80001000 i=0 n=4 data=0xde
```

- The operations are `r8`, `r16`, `r32`, `r64`, `w8`, `w16`, `w32` and `w64`, plus `rb`/`wb` for
  `read_bytes`/`write_bytes`. Those emit one record per byte, with the index `i` and the count `n`.
  The distinction matters because §21.13.9.4 allows a struct access to be lowered to either
  primitives or byte lists.
- `data` is the integer as the access function received or returned it. **The executor does not
  encode byte order. The checker does**, from §21.13.9.1–21.13.9.2. So a tool that byte-swaps shows
  up as a wrong memory image.

`acc` records are emitted **only by suite-owned code**, never by the adapter or the tool. That is
what keeps them tool-neutral (D-11). The code is the **executor tap**, and it is plain PSS.

**The executor tap.** §21.13.9.5 makes memory access customizable *inside the language*. Primitive
reads and writes, and the byte-list functions, are delegated to the functions with the identical
prototype in the executor assigned to the action. Struct and register access are defined in terms
of the primitives, so they are delegated too. The suite ships `compliance/lib/pct_tap.pss`: an
executor that overrides every primitive, logs each access as an `acc` record, and answers each read
with a value computed from the address.

It holds **no state**. A component's attributes can be set only while the component tree is built
(`init_down`/`init_up`), so a target function cannot store what was written. That is the whole
platform model: **a read returns a fixed value per address, and a write is logged.** It is enough for
what the executable tier checks with pure PSS -- which accesses happen, at what width, address and
order, with what data -- and it needs no code outside PSS, so no adapter wiring and no linking.

```pss
// One byte per address: the XOR of the address's eight bytes, XOR 0x5A.
function bit[8] pct_f8(bit[64] a) {
  bit[64] x = a ^ (a >> 32);
  x = x ^ (x >> 16);
  x = x ^ (x >> 8);
  return (bit[8])(x ^ 0x5A);
}

component pct_tap_executor_c : executor_c<> {
  target function bit[32] read32(addr_handle_t h, mem_access_desc_s d = {}) {
    bit[64] a = addr_value(h);          // not overridden: address resolution stays the tool's
    bit[32] v = ((bit[32])pct_f8(a))
              | (((bit[32])pct_f8(a + 1)) << 8)
              | (((bit[32])pct_f8(a + 2)) << 16)
              | (((bit[32])pct_f8(a + 3)) << 24);
    message(NONE, "@@PSS-TRACE acc r32 addr=0x%x data=0x%x", a, v);
    return v;
  }

  target function void write32(addr_handle_t h, bit[32] data, mem_access_desc_s d = {}) {
    message(NONE, "@@PSS-TRACE acc w32 addr=0x%x data=0x%x", addr_value(h), data);
  }
  // read8..read64 and write8..write64 likewise; read_bytes/write_bytes log one record per byte
}
```

- **The read value.** A read of N bytes at `a` returns the bytes `F8(a) … F8(a+N-1)`, first byte in
  bits `[7:0]`. Neighbouring bytes differ, so an offset error or a byte swap changes the value; reads
  of different widths at one address agree, as they would on a byte-addressed memory; and `F8` is a
  simple term for the checker and for SMT.
- **Wiring.** The test's root component instantiates the tap and calls `set_executor` on it in
  `init_down`. Sub-components inherit their parent's executor, and an action uses its component's
  executor unless it claims another (§21.7.2.6), so one call covers the tree.
- **`addr_value` is not overridden.** Address resolution is the tool's, and stays under test.
- **Compiling it.** A test lists the tap in its model, `"libs": ["pct_tap"]`, which names
  `compliance/lib/pct_tap.pss`. The file is compiled after the test's own sources and is part of the
  test's source digest, so a change to the tap marks exported results STALE. A bundle carries a copy
  in each test's directory, as `lib/pct_tap.pss`.
- **The tap depends on as little as possible:** executor delegation, `set_executor`, `message`,
  shifts, XOR and explicit casts. No loops, no collections. The byte-list overrides need `foreach`
  over a `list`, so they are not in `pct_tap.pss`: they go in a separate library that only
  byte-list tests list, and a tool that cannot compile them loses only those tests. Each memory test lists the tap's
  features in `features.uses`, so a tool without delegation reports UNSUPPORTED, not FAIL. The
  procedural tier covers the operators the tap uses before any memory test relies on them.
- **L0-P.** A small tier -- one read and one write of each width through the tap -- checks the tap on
  each tool before its memory results are trusted. A tool that fails L0-P has its memory and register
  results marked UNTRUSTED. Its other results are unaffected.

**What the tap cannot show, and is deferred (D-12):**

- **Read-after-write.** A read never sees a write. The write records already say what was written.
- **A value that changes.** A status bit that sets after some polls needs state. A test can still
  poll an address whose fixed value already has the bit set, which checks that the loop reads once
  and exits.
- **Region behaviour:** read-only regions, unmapped addresses and faults.
- **The tool's own primitive** -- its built-in `read32`, and the connection to the world outside
  PSS. The tap replaces it by design.

Each of these needs a behavioural model behind `import` functions, and doing that in a tool-neutral
way is the open question D-12 records.

**Regions.** Tests that allocate declare the regions of their address space in the model's
`platform` section (§6.8): base, size and trait. The section is translated to `platform_cfg.pss`,
committed and currency-checked like `smt` (§6.6). It builds the address space, adds the regions in
`init_down`, instantiates the tap and assigns it, so the setup is stated once. Tests *of*
`add_region`, region traits or executor assignment write their own setup.

**Checking accesses.**

- **Claim addresses are ordinary random values.** The `act` record reports each claim
  (`c.addr=0x%x` from `addr_value(make_handle_from_claim(c))`, plus `c.size`), and stage 3 constrains
  them per §21.11: alignment, containment in a region with a matching trait, and non-overlap. An
  `acc` leaf then constrains `addr == |c.addr| + 4`.
- **`acc` leaves in body patterns.** `{"acc": "w32", "where": [...]}` matches an access record the
  way a `chk` leaf matches a checkpoint (§6.7). This **op mode** is the default, and it is required
  wherever the LRM fixes the operations:
  - register width and count (§21.14.5);
  - the single-primitive rule for aligned packed structs (§21.13.9.4);
  - read then write for read-modify-write (§21.14.1).
- **Read data is predicted.** The checker computes `F8` itself, so a read leaf's `data` is known
  before the trace is read, and a read-modify-write's expected write follows from it. `F8` is non-zero
  almost everywhere, so a tool that skips the read and assumes 0 writes a visibly wrong value.
- **Effect mode.** Where the LRM allows any decomposition, as in unaligned struct access (§21.13.9.4),
  the model instead states the resulting bytes (`"effect"`, §6.8). The checker replays the write
  records into a byte image, applying the LRM byte-order rule, and compares the final bytes. Any
  decomposition with the right effect passes.
- **Packing oracle.** The checker computes packed-struct layouts itself from §21.13.1, pinned by L2
  anchors that reproduce the LRM's Figures 54–57 bit for bit. The expected value of a
  `write(R)` is the packed register image of the observed field values.
- **Reserved and don't-care bits** (§21.14.1 note 4, §21.13.1.1) are masked out of comparisons,
  because the LRM leaves their value undefined.
- **Attribution.** In sequential code an `acc` record belongs to the most recent `act` record, as a
  `chk` record does. In concurrent tests it is attributed by address. Claims whose lifetimes overlap
  cannot overlap in memory (§21.11.6), so address containment identifies the owner. Concurrent
  register tests give each occurrence its own registers.
- **Negative tests.** A write to a `READONLY` register or a read of a `WRITEONLY` one ("shall be an
  error", §21.14.1), `set_handle` on a non-top-level group (§21.14.3), and all three offset
  functions implemented (§21.14.2) expect `compile_error`.

Symbolic register names (§21.14.6) change only the text of generated code, so they are not
observable in a trace. They are covered at link level in v1.

### 4.13 The foreign-language boundary: the reference host library

> **Deferred (D-12).** This section is the draft of a suite-owned environment behind `import`
> functions. It is the same open question as a behavioural memory model: how to supply code outside
> PSS to every tool in a tool-neutral way. Until D-12 is decided, the executable tier is pure PSS, and
> `imp` records, the host library and the emit hook are not built.

Imported and exported functions (§20.4) are how PSS values cross into and out of the environment.
They are also a second feed channel, one that gives target code values without going through memory.
Both need an environment whose behaviour the suite defines. The suite provides it:

- `compliance/lib/pct_host.pss` declares package `pct_host` with the function prototypes and their
  `import` declarations.
- `checker/host/` implements them in C per Annex D.3, with a C++ wrapper (D.4), an SV DPI package
  (D.5), and a Python module for Python-based tools.

The catalogue has one family per type on the §20.4.1(c) list: integers of 1, 8, 32, 33 and 64 bits,
`bool`, enum, `string`, `chandle`, struct, arrays and lists.

| Function | Checks |
|---|---|
| `pct_in_<T>(T v)` | the host emits `imp in_<T> v=…` with the value it received, then **modifies its copy**. The PSS side reports its variable afterwards, which must be unchanged (§20.4.1(d)1) |
| `T pct_ret_<T>(int sel)` | returns the value selected from a table the suite fixes; the PSS side reports it |
| `pct_out_<T>(output T v, int sel)` | sets an `output` parameter (§20.4.1(d)2) |
| `pct_inout_<T>(inout T v)` | emits the value received, then writes back a fixed function of it (§20.4.1(d)3) |
| `chandle pct_new(int id)`, `int pct_id(chandle h)` | a `chandle` round trip: the identity survives storage in fields, collections and parameters |
| `bit[64] pct_next(int stream)` | the next value of a stream the model declares (§6.8): a feed for target code |
| `pct_call_<f>(…)` | calls back into an `export`ed PSS function (§20.4.2), from inside an import call |

`imp` records are matched by `{"imp": …}` leaves in body patterns, like `acc` records.

**Imports on the solve platform** (`import solve function`) need the host library loaded into the
tool's solver process. Whether that is possible is tool-specific, so those tests are a separate
feature group, `ffi.solve.*`. Adapters say whether they support it.

**One output stream.** The host library never writes to stdout itself. They call an **emit hook**, `pct_emit(const char *line)`, which the adapter routes into
the same stream as the tool's `message`:

- in C, the same `printf` the generated code uses;
- in SV, a DPI-exported task that calls `$display`;
- in Python, `print`.

Without the hook, C stdio buffering and the simulator's own output would reorder records, and
ordering is part of what is checked.

**Conformance of the suite's own code.** The host library is tested in pss-corpus CI with pytest
over ctypes. Each tool also runs each host function once, in the L0-P tier (§4.12). A tool that fails
it has its FFI results marked UNTRUSTED. Its other results are unaffected.

---

## 5. The adapter contract

An adapter is an executable, or a Python entry point, with this signature:

```
<adapter> run --root <qualified action> --seed <uint64> [--iterations N] \
              [--platform <platform.json>] --out <dir> <file.pss>...
```

- It writes `<dir>/log.txt`: the combined text output. The adapter must not rewrite it.
- It writes `<dir>/outcome.json`:

  ```json
  {"schema": "pss-corpus/outcome/1.0",
   "outcome": "ok|compile_error|solve_fail|runtime_error|unsupported|timeout|infra_error",
   "seed_honored": true, "tool": "pssc", "tool_version": "…", "target": "sv-native",
   "detail": "free text, ignored by verdicts"}
  ```

  `schema` may be omitted by in-house adapters. A value other than this one is
  an ERROR.
- When the tool reported errors, it writes `<dir>/diagnostics.json` (schema
  `pss-corpus/diagnostics/1.0`): `{severity, file, line, column?, message,
  code?}` per diagnostic. Negative tests are judged on it (§6.2 `expect`).
  Only `error`/`fatal` count, and `file` is matched by its trailing path.

- **`unsupported`** is its own outcome. A tool that rejects a feature *with a diagnostic saying so*
  is being honest, and the report shows that differently from FAIL. Silently producing a wrong trace
  is FAIL.
- **`--seed` is required from v1, even before phase 2.** This is §8's main "not an afterthought"
  lever. An adapter whose tool cannot take a seed reports `seed_honored: false`. Such a tool can
  still be checked for legality but cannot be scored on distribution or random stability.
- **`--iterations N`** is optional. It asks the adapter to run N independent scenarios in one
  invocation, which is cheap on SV. This supports inter-run sampling without N elaborations (§8.3).
- **Memory and register tests need nothing from the adapter.** The executor tap is PSS source the
  runner adds to the test's sources (§4.12); the tool compiles it like any other.
- **`--platform`** is reserved for the host library (§4.13), deferred with D-12. When it exists, the
  adapter connects the tool's imported-function calls to the suite's host library, configures it
  from the file, and routes its emit hook into the tool's `message` stream, reporting what it wired
  in `outcome.json` as `"platform": {"host": true, "host_solve": false}`. A test that needs something
  the adapter did not wire gets `unsupported`.

**A command adapter's own output is kept** in `<dir>/adapter.log`. An adapter
that exits without writing `outcome.json` has an `infra_error` written for it.

**Export and import (D-15).** For a tool that cannot be run where the corpus is
(licensed, remote, run by its vendor), the contract splits across two sites.
`pss-corpus export` writes a bundle holding the sources, the jobs (test, root,
seed) and a stdlib-only copy of the job driver, but no legality models. The
tool's site runs its adapter over the jobs. `pss-corpus import` checks the
returned `results/` against the local models. Sources are hashed at export, so
results for tests that have since changed are STALE rather than checked. The
live `run` and the bundle driver share one adapter-invocation function.
`HANDOFF.md` is the guide.

A tools file (`pss-corpus.toml`) lists the adapters. pssc ships adapters for `sv-native`, `python`,
`c-host` and `bc`. The bc and rt-eng adapters wait on `message` lowering (§12).

---

## 6. The reference model (`test.json`)

### 6.1 Principles

- **It says what is legal, not what to print.** The model is a declarative restatement of the PSS
  semantics that are relevant to the test: types, fields, domains, constraints, activity and flow
  topology. Given a trace, the checker decides whether it is legal. Nothing in the model is
  seed-specific.
- **Every constraint's meaning ends up in SMT-LIB2.** The committed `smt` string is what the oracle
  evaluates, and its semantics (widths, signedness, overflow) are fixed by a standard outside PSS.
  Z3, Bitwuzla, cvc5 and Boolector all read it. The `pss` string says what the constraint is in PSS.
  Authors write the `pss` string. `pss-corpus` translates it to `smt`, which is committed and
  reviewed, and a hand-written `smt` may override the translation (`D-2`, decided: §6.6).
- **Hand-written, or generated and then reviewed.** Never derived from pssc. A draft may come from a
  generator (§10.3), but the committed JSON is a reviewed artifact. **The JSON is the oracle, so it
  must not share a frontend with the thing it judges.**
- **It is flattened.** Inheritance, extension and templates are resolved by the author: each type
  lists its *effective* fields and constraints. The PSS side exercises those constructs; the model
  records what they mean. That gives an independent check of extension and override semantics.

### 6.2 Schema (v1, abridged)

```jsonc
{
  "schema": "pss-corpus/model/1.0",            // schema id + version
  "id": "flow.buffer.infer.001",              // stable, never reused
  "title": "Consumer with no explicit producer forces buffer inference",
  "lrm": ["14.1", "9.3.2", "12.3"],           // clauses this test adjudicates
  "features": {                               // §9
    "tests": ["flow.buffer.infer.implicit"],
    "uses":  ["exec.body", "std.message", "pool.bind.wildcard", "constraint.relational"]
  },
  "sources": ["test.pss"],
  "libs": [],                                 // shared libraries, e.g. "pct_tap" (§4.12)
  "run": { "root": "pss_top::entry", "seeds": { "count": 16 } },
  "pss": "3.0",                              // lowest PSS version the test is written in (default 3.0)
  "expect": { "outcome": "ok" },              // or compile_error | solve_fail (+ oracle check, §7);
                                              // compile_error adds "diagnostics": [{"file", "line" | "lines": [lo, hi]}]

  "sorts": { "u4": "(_ BitVec 4)", "u8": "(_ BitVec 8)" },
  "types": {
    "data_b": { "kind": "buffer",
      "fields": { "tag": "u8", "len": "u4" },
      "constraints": [ { "pss": "len > 0", "smt": "(bvugt len #x0)" } ] },

    "pss_top::produce": { "kind": "action", "atomic": true, "component": "pss_top",
      "fields": { "mode": "u4" },
      "refs":   { "out": { "dir": "output", "type": "data_b", "pool": "pss_top.data_p" } },
      "constraints": [ { "pss": "mode < 3", "smt": "(bvult mode #x3)" },
                       { "pss": "out.len <= mode*4",
                         "smt": "(bvule ((_ zero_extend 28) |out.len|) (bvmul ((_ zero_extend 28) mode) #x00000004))" } ] },

    "pss_top::consume": { "kind": "action", "atomic": true, "component": "pss_top",
      "fields": { "k": "u8" },
      "refs":   { "in": { "dir": "input", "type": "data_b", "pool": "pss_top.data_p" } },
      "constraints": [ { "pss": "k == in.tag + 1",
                         "smt": "(= ((_ zero_extend 24) k) (bvadd ((_ zero_extend 24) |in.tag|) #x00000001))" } ] },

    "pss_top::entry": { "kind": "action", "atomic": false, "component": "pss_top",
      "activity": { "do": "pss_top::consume", "label": "c" } }
  },

  "components": { "pss_top": { "pools": { "data_p": { "type": "data_b", "bind": "*" } } } },
  "inference":  { "allowed": true },                             // §6.5: completeness + justification always on

  "records": {                                   // how trace records map onto types
    "pss_top::produce": { "kind": "act", "tag": "pss_top::produce" },
    "pss_top::consume": { "kind": "act", "tag": "pss_top::consume" }
  },

  "properties": [],                              // extra named assertions (SMT over occurrences)
  "distribution": []                             // §8 — may be present in v1, evaluated in phase 2
}
```

Two points to note in this example:

- The `k == in.tag + 1` constraint rules out `in.tag == 255`, because the PSS `+` is evaluated at int
  width and so cannot wrap to 0. A tool that wraps at 8 bits produces `in.tag=255 k=0`. The SMT
  oracle rejects that trace; a naive checker that evaluated the constraint "in Python" might accept
  it.
- `produce` is never mentioned in the activity. It is legal in the trace only as a justified
  inferred action.

### 6.3 Activity grammar

Activity nodes in the model mirror LRM §11:

| Node | Form |
|---|---|
| traversal | `{"do": T, "label"?: L, "with"?: [smt…]}` |
| sequence | `{"seq": [...]}` |
| activity constraint | `{"constraint": [smt…]}` |
| parallel | `{"par": [...], "join"?: "all|none|first:N|branch:L"}` |
| schedule | `{"schedule": [...]}` |
| select | `{"select": [{"weight"?: smt, "guard"?: smt, "body": …}]}` |
| repeat | `{"repeat": {"count": smt}, "body": …}` |
| repeat-while | `{"repeat_while": {"cond": smt, "max": N}, "body": …}` |
| foreach | `{"foreach": {…}}` |
| replicate | `{"replicate": {…}}` |
| if / match | `{"if": …}`, `{"match": …}` |
| bind | `{"bind": [[a.out, b.in], …]}` |

Compound types expand through their own `activity`. `smt` terms may refer to fields of the enclosing
action and to labeled sub-actions, as `|c.k|`.

**Handles and when a constraint binds** (checker P1, 2026-10-01). A traversal's `label` is the
action handle it traverses (`a`, `arr[1]`). A compound type carries `fields` and `constraints` like
an atomic one; its fields are never observed directly, so they are unobserved constants unless an
observer (§4.4) ties them to a record. The checker walks the activity with the matched occurrences
and keeps, per compound occurrence, the occurrence each handle is bound to: a traversal binds it,
and entry to a block or to a loop iteration that traverses it unbinds it (LRM 13.4.8). A
constraint naming handles is asserted whenever all of them are bound, once per distinct set of
occurrences, and is vacuous before that. So Ex 180's `b.x < c.x` binds each iteration's `b` to
that iteration's `c`, never to the previous one's. In a `with`, an unqualified name is the
traversed action's when it has one and otherwise the enclosing action's, and `this.x` is the
enclosing action's (13.1.4). An activity `constraint` holds in its whole block (13.1.9).

**Occurrences without a record of their own.** An atomic type with no `exec body` is
`"traced": false` (O7): it takes part in the structure and the constraints and consumes no record;
its fields are unobserved. A type with `"role": "observer"` prints an `obs` record in place of
`act`. The checker's tests require a `"traced": false` type to have no `exec body` in the source.

**The same grammar describes procedural traces** (§6.7). An atomic action's `body` pattern uses
`seq`, `repeat`, `repeat_while`, `if` and `match` with a different leaf, `{"chk": <tag>, …}`, in
place of `do`. The matcher is the same code.

### 6.4 Checker semantics

The checker has four stages. Each stage can end the check with a verdict.

1. **Outcome.** Compare `outcome.json` with `expect`. For `solve_fail` and `compile_error`
   expectations, the oracle confirms the model really is UNSAT, or really violates the stated rule.
   A negative test is therefore validated as well as asserted (§7.2).
2. **Structural match.** Build the activity tree from the root type. Match the ordered sequence of
   records against it by backtracking:
   - `seq` requires record order.
   - `par` and `schedule` allow any interleaving of their branches (a shuffle match).
   - `select` chooses one branch.
   - `repeat` binds its count to a solver variable.

   Each atomic occurrence's `chk` records (§4.8) are matched against its type's `body` pattern
   (§6.7) with the same matcher. A `chk` record that the pattern does not account for is a FAIL.
   Extra checkpoints are not tolerated, because a missing `break` or an extra iteration shows up
   exactly as one.

   **Records left over are candidate inferred actions.** Each must be of a type able to satisfy a
   binding demand (Annex E). Whether it actually *does* satisfy one is decided in stage 3 under the
   completeness and justification rules (§6.5). Structural match yields one or more **occurrence
   graphs**. Each graph contains occurrences, the record for each, logical order edges, logical
   concurrency sets and unresolved binding demands.
3. **Data and binding, as one SMT problem per candidate graph.**
   - For each occurrence, declare fresh variables for its fields and refs.
   - Assert that each observed value equals its variable.
   - Assert the type constraints, inline `with` constraints, and the constraints between parent and
     sub-actions, including `repeat` counts and `select` guards.
   - For each binding demand (§6.5), **existentially choose exactly one supplier**. This is a
     disjunction over the legal candidates allowed by pool, type and order. "Unbound" is never one of
     the options:
     - buffer: the producer completes before the consumer;
     - stream: the producer is logically concurrent with the consumer and 1:1;
     - state: the most recent writer in the pool's state sequence, or the initial state.

     Then assert that the object's fields are equal on both sides.
   - Assert the justification ranks for inferred occurrences (§6.5).
   - **Resources:** the `instance_id` is in `[0, pool_size)`. Two occurrences that are *logically
     concurrent* (different branches of one `par`, or unordered in a `schedule`) never `lock` the
     same instance, and never `lock` and `share` the same instance. When the occurrences are yield
     ladders, the exclusion is also checked directly on the interleaving (§4.9).
   - **Interleaving checks** (§4.9) are evaluated on the records of any yield ladders in the
     candidate graph.

   A SAT result on any candidate graph is a **PASS**. The model returned by the solver is the
   *witness*, saved in the result for debugging: which producer fed which consumer, and the values of
   unobserved fields.
4. **Sample extraction.** Always run, from v1. From the witness, emit the quantities named in
   `distribution[]` (§8). This costs nothing when the list is empty.

The checker reports **FAIL** together with the closest candidate: the structural match that got
furthest, or the SMT unsat core mapped back to the `pss` strings. It reports **ERROR** when the log
is malformed and **UNTRUSTED** when the tool's L0 results failed.

**Scaling.** The shuffle match and binding disjunctions are exponential in the worst case. Tests are
meant to be small, so the default budget is at most 64 records per run and a checker time limit.
Blowing the budget gives ERROR, never PASS.

**Soft constraints (§13.1.12).** Legality is hard constraints only. A later level checks soft
constraints with MaxSMT (Z3 `Optimize`): "no solution satisfies a strictly higher-priority soft set
consistent with the observations". This is deferred (§13, L5).

### 6.5 Binding completeness and inference justification (`D-4`, decided)

Inference is where a tool can most easily look compliant without being so. Examples:

- Run the consumer with made-up input values and never traverse a producer.
- Infer an action whose own inputs are then left dangling.
- Pad the scenario with actions nobody needed.

Two rules close these off, and both are **always on**. The `inference.justify` switch is removed from
the schema; a test can only set `inference.allowed`.

**Rule C: completeness (every flow-object ref is fed).** Every occurrence, explicit or inferred,
contributes *binding demands*:

| Ref | Demand | Satisfied by |
|---|---|---|
| `input` buffer | always | exactly one `output` of that buffer type, on the same pool, in an occurrence that completes before this one |
| `input` stream | always | exactly one `output` of that stream type, on the same pool, in a logically concurrent occurrence; that output feeds no other input |
| `output` stream | always, because a stream has exactly one producer and one consumer | exactly one `input`, as above |
| `input` state | always | the most recent preceding writer in the pool's state sequence, or the pool's initial state when there is no writer |
| `output` buffer / state | none | consumption is optional |
| `lock` / `share` resource | always | an instance of the bound pool: `instance_id` observed and in `[0, pool_size)`; the concurrency rules of §6.4 apply |

A demand with no legal supplier makes the candidate graph UNSAT. So a consumer that ran with no
producer in the trace is a **FAIL (unfed input)**. It is never "the producer must have been
unobserved". Every atomic action is instrumented (§4.3), so an unobserved producer is itself a
defect.

**Rule J: justification (every inferred action is needed).** An inferred occurrence must satisfy at
least one demand. That demand must be owned by an explicit occurrence, or by an inferred occurrence
that is itself justified. The chain must be well-founded: two inferred actions cannot justify each
other in a cycle.

- In SMT this is a rank per occurrence: explicit occurrences have rank 0. An inferred occurrence `o`
  is justified if it supplies a demand of some `p` with `rank(p) < rank(o)`.
- Rule C also applies to inferred occurrences. An inferred producer that needs an input must have
  that input fed in turn, all the way back to explicit actions or initial state.

**Pool identity.** "Same pool" is only checkable when the pool can be identified. When an object type
is reachable through more than one pool, `pss-corpus lint` requires the records involved to carry
`comp.pct_id` (§4.3). The checker resolves the pool from the component instance, and never from the
type alone.

**Checker sensitivity is tested, not assumed.** `pss-corpus validate` uses the oracle to *synthesize* a
legal trace for each L3/L4 model: it solves the model and renders the records. It then applies a
fixed set of **cheat mutations**, and every one must FAIL:

- delete a producer record (unfed input);
- move a buffer producer after its consumer;
- give one stream output two consumers;
- add an inferred action that satisfies no demand;
- break one observed binding by changing a single value;
- make two concurrent `lock`s use the same `instance_id`.

A model whose checker cannot tell a cheat from a legal trace is a defective model. This mirrors the
mutant stubs in `pssc/src/pssc/testing/conformance.py`, applied to the oracle instead of the tool.

### 6.6 The constraint language (`D-2`, decided: hybrid)

The question is how an author states what a constraint means. Whatever is chosen, the oracle only
ever evaluates SMT-LIB2. The choice is about what humans write and review, and where PSS expression
semantics are implemented.

**Why the choice matters.** PSS expression semantics are not trivial:

- width extension of the operands;
- signed/unsigned mixing, and whether the result is signed;
- the int-width of literals;
- enum and bool conversions;
- `in` with ranges;
- the evaluation width of shifts, part-selects and division.

These are also where tools diverge most (LRM §8). The oracle has to encode them correctly *somewhere*.
The options differ in *where*, and in *how many times*.

**Options**

| | A. Hand-written SMT-LIB2 | B. PSS-subset expressions, translated by `pss-corpus` at check time | C. Structured JSON expression tree | D. Hybrid: author writes PSS subset; `pss-corpus` translates; the **SMT is committed** and reviewed; a hand-written `smt` overrides |
|---|---|---|---|---|
| **Where PSS semantics live** | in each author's head, once per constraint | once, in the `pss-corpus` translator | per constraint, as explicit `extend`/`cast` nodes | once, in the translator, with its output frozen |
| **Readability / review** | poor: `(bvule ((_ zero_extend 28) \|out.len\|) …)` for `out.len <= mode*4` | excellent: it *is* PSS | poor: verbose, and nobody reads JSON ASTs | good: review the `pss`; the committed `smt` shows exactly what it means |
| **Authoring error rate** | high: widths are fiddly (see below) | low | medium | low, and translator errors are visible in the diff |
| **Failure mode** | *scattered*: independent errors in individual tests | *systematic*: one translator bug silently misjudges every test that uses the construct, and a translator change silently changes old verdicts | scattered | systematic, but **visible and pinned**: a translator change shows up as a diff to committed `smt` and must be reviewed |
| **Independence from tools under test** | total | high: a second, independent implementation of LRM §8, not pssc's; but it still is one | total | high, as B, plus hand-written anchors (below) |
| **Accessibility to third parties** | low: vendors must read SMT to contest a verdict | high | low | high: contest the `pss`, inspect the `smt` |
| **Expressiveness cost** | everything is expressible; `foreach`/`unique`/arrays are unrolled by hand | translator must support each construct; gaps block tests | as A | gaps are covered by the hand-written override |
| **Build / maintenance** | none | a PSS expression parser and typer in `pss-corpus` (small: expressions only, no declarations) | a JSON schema | as B, plus a "committed `smt` is current" check in `pss-corpus validate` |
| **Distribution/oracle queries** | unaffected | unaffected | unaffected | unaffected |

**Evidence for "hand-written SMT is error-prone".** The first draft of the §6.2 example had a width
bug. `k == in.tag + 1` was zero-extended to 33 bits and added to a 32-bit constant, which is
ill-sorted SMT. It was caught on re-reading, not by any process. With A, an ill-sorted term at least
fails `pss-corpus validate`. The dangerous case is a *well-sorted but wrong* width, for example
zero-extending where the LRM says sign-extend. That passes silently, and turns into a mis-verdict
on exactly the promotion cases the suite most needs to judge.

**The risk that B and D add.** The translator becomes a single point of semantic truth. If it and a
tool share a misreading of LRM §8, the suite blesses the tool. Three measures contain that:

1. **Hand-written anchors.** The L2 integer-semantics tests (§13), one per promotion and conversion
   rule, *must* use hand-written `smt`. They are reviewed against the LRM text directly, and they
   also serve as the translator's test suite: each translation must match its anchor.
2. **Frozen output** (D only). A translator change cannot alter an existing test's meaning without a
   visible diff to its committed `smt`. This keeps SMT's main virtue, which is that the meaning is
   explicit and reviewable, without making anyone write it.
3. **Escape hatch.** Where the translator lacks a construct, or an author wants to pin semantics
   deliberately, a hand-written `smt` is used and marked `"smt_source": "hand"`.

**Recommendation: D.** Authors write and review PSS, which is readable and accessible to vendors, and
the meaning is still frozen as explicit SMT. PSS semantics are implemented once rather than N times.
The translator's bugs cannot silently change old verdicts, and its correctness is pinned by
hand-written anchors. D also works as a staging path: P1 can start with A only, while the translator
is built, because the schema is the same (`pss` plus `smt`) and only `smt_source` differs.

**What would argue for A instead.** A suite small enough that per-constraint review is cheap, or a
decision to make the suite's semantic claims maximally transparent to an external standards body.
In that case, keep A and give up readability.

**Decision (2026-09-24): D, the hybrid.** The translator is accepted as a single point of semantic
truth, a manageable risk given the containment strategy above. The rules that make it work:

- **Schema.** Every constraint, `where` term and `eq` derivation carries `pss` (the source, and
  what reviewers read) and `smt` (committed, and what the oracle evaluates). A third field,
  `smt_source`, is `"translated"` (the default) or `"hand"`.
- **Currency check.** `pss-corpus validate` re-translates every `"translated"` entry and fails if the
  committed `smt` differs. The only way to change it is `pss-corpus translate --update`, and the
  resulting diff is reviewed like any model change. A translator change that alters an existing
  test's meaning therefore always surfaces as a diff, and bumps that test's `rev` (§11.4).
- **Anchors pin the translator.** Every L2 integer-semantics and run-time-semantics anchor is
  `"hand"`, and each one cites its LRM rule. The translator's own test suite translates each
  anchor's `pss` and requires the result to be equivalent to the hand-written `smt`. Equivalence is
  checked by the oracle (`(not (= a b))` is UNSAT), not by comparing text. A translator construct
  without an anchor is not allowed.
- **Hand overrides are exceptional.** Outside anchors, `"hand"` is only for constructs the
  translator does not support yet. `pss-corpus lint` lists them, so each one is either a translator
  backlog item or a deliberate pin.
- **Independence.** The translator is its own implementation of the LRM §8 expression semantics,
  over a PSS *expression* subset only. It parses and types expressions itself and does not use
  pssparser, pssc or any tool under test (G4). Declarations come from the model's `sorts` and
  `fields`, not from the `.pss`.
- **Staging.** P1 uses `"hand"` everywhere, since the schema is the same. The translator and the
  anchors land together in P2. Any P1 entries that are not anchors are then converted to
  `"translated"`, and must translate to something equivalent. That doubles as the translator's first
  real test.

### 6.7 Procedural expectations

An atomic action type may carry a **`body` pattern**: the legal sequence of `chk` records its target
code emits. Each `chk` leaf declares its fields and states their legal values as constraints. The
constraints may refer to:

- the owning action's fields (random inputs);
- the index of each enclosing `repeat`, as `$<index>`;
- the same leaf's previous match, as `prev.<field>`, for recurrences with no closed form.

The model for the §4.8 example:

```jsonc
"pss_top::A": { "kind": "action", "atomic": true, "component": "pss_top",
  "fields": { "n": "u4" },
  "body": { "seq": [
    { "repeat": { "count": "n", "index": "i" },
      "body": { "chk": "sum_to.step", "fields": { "i": "s32", "acc": "s32" },
                "where": [ { "pss": "i == $i" },
                           { "pss": "acc == $i * ($i + 1) / 2" } ] } },
    { "chk": "result", "fields": { "r": "s32" },
      "where": [ { "pss": "r == n * (n - 1) / 2" } ] }
  ] } }
// smt strings elided; each is translated from its pss string and committed (§6.6)
```

**Exact form.** For tests with constant inputs, a leaf may use `"eq": {"r": 45}` instead of
`fields` plus `where`. That compares the printed integer (or `true`/`false`, or string token)
exactly. When every leaf of a test is in exact form and the test has no random fields, the checker
decides it **without calling a solver**. This is the fast path most procedural tests take. `eq`
is shorthand for an equality constraint, not a second mode: the verdict logic is the same.

**Where the expected values come from.** For procedural tests, the author's arithmetic *is* the
oracle. That is exactly where PSS run-time integer semantics (§8.7) bite: `bit[8]` truncation on
assignment, signed/unsigned mixing, shift widths, and division of negatives. It is also where pssc's
backends are most likely to diverge: C integer promotion, SV sizing and Python's unbounded `int`.
The measures from §6.6 therefore apply to `eq` constants too:

- L2 run-time-semantics tests are **anchors**: one rule per test, with the expected value derived in a
  comment that cites the LRM text.
- `pss-corpus validate` uses the translator to re-derive each `eq` constant from a `pss`
  expression, where one is given, and flags any disagreement.

**Solve-time code** is checked through the attributes it writes (§4.8). A `post_solve` that computes
`total = a + b` is a constraint on the `act` record, `total == a + b`, stated in `where` alongside
the type's constraints. An order signature is an `eq` (or a set of allowed values) on `sig`.

**Pure functions used in constraints** (§20.2.6) are modeled as SMT definitions in a
`"functions"` section, as `define-fun`, or translated from `pss` under D-2. They are expanded where
constraints use them. This is how a constraint-side function call gets an independent meaning.

**`randomize` statements** (§20.7.12) make target code non-deterministic again. The randomized
variables' `chk` fields are constrained like action fields: `where` states the `with` constraints
and the verdict is SAT. That puts `randomize` results in scope for the distribution layer (§8) at no
extra cost.

**Negative procedural tests** use outcomes, never traces:

- `compile_error` for type errors, bad parameter directions, assignment to `const`, or `break`
  outside a loop;
- `runtime_error` only where the LRM says an error *shall* be raised, for example an out-of-range
  array index or a missing map key, if and as the LRM specifies.

Where the LRM leaves run-time behaviour undefined, there is no test. A tool's behaviour there is not
a compliance question.

### 6.8 Platform expectations

Tests that touch memory or registers use `acc` leaves in their body patterns (§4.12). Tests that
allocate also carry a `platform` section stating their regions:

```jsonc
"platform": {
  "regions": [
    { "name": "ram0", "base": "0x80000000", "size": "0x10000",
      "space": "pss_top.mem", "trait": { "id": 0 } }
  ]
},
"types": {
  "pss_top::cfg_a": { "kind": "action", "atomic": true, "component": "pss_top",
    "fields": { "mode": "u4", "coeff": "u16" },
    "body": { "seq": [                          // write_fields({"mode","coeff"}, …) on CR at 0xa0000000
      { "acc": "r32", "as": "rd", "where": [ { "pss": "addr == 0xa0000000" } ] },
      { "acc": "w32", "where": [ { "pss": "addr == 0xa0000000" },
                                 { "pss": "data == (rd & 0x00000fff) | (coeff << 16) | (mode << 12)" } ] }
    ] } }
}
// `rd` names the data of the preceding r32 leaf. The tap fed it F8-bytes of 0xa0000000 (§4.12),
// which the checker computes itself, so a tool that skipped the read is caught.
```

- An `acc` leaf's fields are `addr`, `data`, `i` and `n`. A leaf may name its own record
  (`"as": "rd"`) so that later leaves can refer to it. A read record's `data` is always checked
  against `F8` for its address, so a tool that miscompiles the tap's own arithmetic fails rather than
  feeding its own values to the test.
- Where the LRM allows any decomposition, an action carries `"effect": [{"addr": <pss>, "bytes":
  [<pss>…]}]` instead of `acc` leaves. The checker replays the write records into a byte image and
  compares the resulting bytes (§4.12).
- The `platform` section is translated to `platform_cfg.pss`, which builds the address space and
  assigns the tap. The translation is committed and currency-checked, like `smt` (§6.6). A memory or
  register test with no `platform` section gets a `platform_cfg.pss` that only assigns the tap.
- Host-library feeds (`"streams"`, for `pct_next`) join this section with the host library (§4.13,
  deferred).

---

## 7. The oracle

### 7.1 Role

The SMT solver is the only judge of data legality. It serves four purposes:

1. **Per-trace legality** (§6.4, stage 3). Deciding a fully observed assignment would only need
   evaluation. Stage 3 also has existential unobserved fields and existential binding choices, so it
   needs satisfiability.
2. **Negative-expectation validation.** A test expecting `solve_fail` also passes only if the model's
   constraints are UNSAT. That catches a reference model that is wrong, as well as a tool that is
   wrong.
3. **Self-validation of the reference model** (`pss-corpus validate`, run in corpus CI). Every model is
   checked for:
   - well-formedness: sorts, symbols and the activity grammar;
   - satisfiability of each `ok` test;
   - satisfiability of each declared reachable set (§8);
   - UNSAT of each `solve_fail` test.
4. **Expected distributions** (§8.4). For small domains, exact model counting by enumeration with
   blocking clauses, projected onto the target.

### 7.2 Independence from a single solver

- The checker emits **SMT-LIB2 text** and talks to solvers through a narrow interface. The first two
  backends are the `z3` Python API and any SMT-LIB-speaking binary on stdin/stdout, which covers
  Bitwuzla, cvc5, Boolector and Yices.
- **In corpus CI, `pss-corpus validate` runs every model on two solvers** (Z3 and Bitwuzla) and fails if
  they disagree. That guards the oracle against a solver bug. It costs little, because the queries
  are tiny.
- At check time one solver is enough. Z3 is the default because the venv already has it.
- Theory: `QF_BV`, plus `QF_ABV` for fixed-size arrays and collections. Strings are constants only.
  No floating point in v1: models with `float32`/`float64` rand fields are rejected at validation
  until a `QF_FP` profile is added (`D-6`).

---

## 8. Distribution assessment (phase 2, designed in from v1)

### 8.1 What the LRM actually requires

This split decides how results are *scored*:

| Property | LRM | Scoring |
|---|---|---|
| `dist` weights: P(value) ∝ weight, absent conflicting constraints | §13.1.13 **normative** | **compliance** (pass/fail) |
| `select` branch weights | §11.4 **normative** | **compliance** |
| random stability: same description + seed → same result | §13.4.6.2 **normative** | **compliance** (needs `seed_honored`) |
| seed sensitivity: different seeds → different scenarios | implied | **quality** (report) |
| reachability: every feasible value in a declared set eventually appears | not stated | **quality** |
| uniformity over the solution space, or over each variable's domain | **not required** | **quality metric**: reported as a distance, never pass/fail |
| inference choice spread across candidate producers | not stated | **quality metric** |

A tool must never "fail compliance" for not sampling uniformly, because the LRM does not ask for it.
It may still score poorly on the quality dashboard, which is the thing pssc cares about when aligning
its backends. `dist` and `select` are the parts that can properly fail.

### 8.2 The `distribution[]` entry (schema v1, evaluated in phase 2)

```jsonc
"distribution": [
  { "id": "d1", "kind": "dist",                 // normative
    "target": { "occ": "pss_top::a", "expr": "x" },  // occurrence selector + SMT term
    "weights": [ {"range": [0,0], "w": 40}, {"range": [1,3], "w": 60, "per": "range"} ],
    "min_samples": 400 },

  { "id": "d2", "kind": "select",                // normative
    "target": { "select": "pss_top::entry/0" },   // path to a select node
    "min_samples": 300 },

  { "id": "d3", "kind": "stability" },           // normative: runs seed S twice, traces identical

  { "id": "d4", "kind": "reachable",             // quality
    "target": { "occ": "pss_top::a", "expr": "mode" }, "values": [0,1,2] },

  { "id": "d5", "kind": "uniformity",            // quality metric
    "target": { "occ": "pss_top::a", "expr": "x" }, "reference": "solution-projected" }
]
```

- The occurrence selector names *which* occurrences contribute a sample: all of them, the first one,
  or one by label path. Sampling from every `repeat` iteration is how a single run yields many
  samples (§8.3).
- For `dist`, `pss-corpus validate` uses the oracle to prove that the dist target is **unconstrained** by
  conflicting hard constraints on the whole of its dist_list. A test where constraints override the
  dist cannot claim the normative proportion. This is the LRM's own caveat, made machine-checked.

### 8.3 Sampling plans

- **Inter-run.** N runs with seeds `S0+i` from a fixed, published base. Samples are independent by
  construction. This is expensive on SV (N elaborations, unless the adapter supports `--iterations`).
- **Intra-run.** The PSS wraps the scenario in `repeat (K) { do sub; }` and every iteration
  contributes one sample. This is cheap, but independence between iterations is only as good as the
  tool's per-traversal seeding, so it is not a pure distribution test. The report labels such results
  `intra-run`. The `stability` and `reachable` kinds are always inter-run.

Both plans read the same records and use the same extraction (§6.4, stage 4). Phase 2 is an
**aggregation stage over existing per-run outputs**. It needs no new trace or protocol work.

### 8.4 Statistics

- **Categorical targets** (select branches; `dist` with few items): a chi-square goodness-of-fit
  test, or an exact multinomial test when any expected count is below 5.
- **Wide numeric targets:** bin by the model's own ranges. `dist` items are the bins for a `dist`
  target. Oracle-computed quantiles of the solution space are the bins for a uniformity metric.
- **Expected distributions for quality metrics** (`solution-projected`): the oracle enumerates
  solutions by blocking-clause enumeration, up to a cap (default 2^16 solutions). Above the cap the
  metric is `n/a`. Approximate model counting (ApproxMC-style) is noted as future work.
- **Multiple comparisons:** Holm–Bonferroni within one tool run of the suite.
- **Verdicts:** FAIL when p < 1e-4, SUSPECT when p < 1e-2, otherwise PASS. Quality metrics report
  total-variation distance and support coverage, never a verdict.
- **Reproducibility:** seeds are fixed, so a given tool version gives the same p-values. A
  "flaky distribution test" is therefore a real change in the tool.
- **Sample size:** `min_samples` is chosen by power analysis: effect size w=0.15 at α=1e-4 and power
  0.9, for k categories. `pss-corpus validate` warns when it is too small for the stated weights.

### 8.5 v1 obligations that make phase 2 additive

1. `--seed` is required in the adapter contract (§5), along with `seed_honored`.
2. Records carry values for every `rand` field by default (§4.3).
3. The checker writes a **witness** and the **extracted samples** into every per-run result, even
   when `distribution[]` is empty. Phase 2 then never has to re-run the checker.
4. The `distribution[]` schema exists in v1. `pss-corpus validate` validates it and the checker ignores it.
5. The runner's result store is keyed by (tool, target, test, seed, iteration).

---

## 9. Feature coverage

### 9.1 Taxonomy

`compliance/features.yaml` is a hierarchical list of feature IDs. Each ID carries:

- `lrm`: clause references;
- `bnf`: the Annex B productions that realize it;
- `level`: L0–L5 (§13);
- `observable`: whether a portable trace can see it at all. For example `exec.header` is not
  observable, so it is covered at parse level only.

```yaml
activity.select.weighted:
  lrm: ["11.4.1"]
  bnf: [select_branch, activity_select_stmt]
  level: L3
flow.buffer.infer.implicit:
  lrm: ["14.1", "Annex E"]
  level: L4
resource.lock.instance_id:
  lrm: ["9.4.2", "12.4"]
  level: L4
proc.repeat.index:
  lrm: ["20.7.6"]
  bnf: [procedural_repeat_stmt]
  level: L1
proc.func.param.inout:
  lrm: ["20.2.2", "20.3.2"]
  level: L2
proc.exec.order.init:            # semantic-only: init_down/init_up order across the tree
  lrm: ["20.1.2", "20.1.5"]
  level: L2
data.pass.aggregate.handle:      # one data-matrix cell family (§4.11)
  lrm: ["20.3.2"]
  level: L2
mem.struct.packed.single_op:     # aligned 8/16/32/64-bit packed struct → one primitive
  lrm: ["21.13.9.4"]
  level: L5
reg.rmw.write_fields:
  lrm: ["21.14.1", "21.14.5"]
  level: L5
ffi.import.inout:
  lrm: ["20.4.1"]
  level: L2
```

**Seeding the taxonomy.** One entry per Annex B production group gives the *syntactic* spine, about
360 grammar rules folded to about 150 features. Semantic sub-features are then added by hand from the
clauses that the grammar under-describes: inference, binding rules, scheduling semantics, randomization
order, exec ordering, parameter-passing semantics and run-time integer evaluation. Procedural features
live under `proc.*`, which keeps the procedural tier reportable on its own. Data-matrix cells live
under `data.*`, and platform features under `mem.*`, `reg.*` and `ffi.*`. Features have **no fixed axes**. Combinations are declared separately.

### 9.2 Declared versus detected

- **Declared.** Each test's JSON carries `features.tests`, what the test *adjudicates*, and
  `features.uses`, what it depends on incidentally.
- **Detected.** `pss-corpus features <test>` walks the pssparser CST (`CstNode.rule_name`) to find the
  grammar rules the `.pss` actually uses, and maps rules to features through `bnf`.
- **Lint rule.** Every detected syntactic feature must be declared, in either `tests` or `uses`. A
  declared `tests` feature with no matching detected syntax is flagged unless it is a
  semantic-only feature. This keeps declarations honest without letting pssparser into verdicts. If
  pssparser cannot parse a test (a pssparser gap), the lint degrades to declared-only and says so.

### 9.3 Combination coverage

A single feature proves little. Most real bugs are interactions, such as inference × stream ×
`schedule`, or resources × `replicate` × `select`. Combinations are specified as **interaction
groups** in `compliance/combinations.yaml`:

```yaml
flow-scheduling:
  axes:
    object:   [flow.buffer, flow.stream, flow.state]
    binding:  [flow.bind.explicit, flow.infer.implicit]
    context:  [activity.seq, activity.par, activity.schedule, activity.replicate]
  strength: 2          # pairwise; 3 for small, high-risk groups
  exclude:  [[flow.stream, activity.seq]]   # illegal by LRM — covered by a negative test instead
```

The report computes, for each group, the t-wise tuples covered by the union of `features.tests` over
all tests, and lists the uncovered tuples. **That list is the backlog for the generator** (§10.3).

### 9.4 Reports

- **Coverage matrix:** feature × {test count, tests-adjudicating count}, LRM clause roll-up, and
  per-group t-wise coverage percentage with the uncovered tuples.
- **Compliance profile, per tool and target:** feature × {PASS, FAIL, UNSUPPORTED, UNTRUSTED}. A
  feature is *supported* when every test that adjudicates it passes. It is *partial* when some pass.
  It is *unsupported* when the tool declares it so.
- **Alignment view, pssc only:** backend × feature, with cells where backends *disagree* highlighted.
  This is the work queue for pipeline alignment (§12).

All reports are JSON first. The HTML and markdown renderings are views of that JSON.

### 9.5 Comprehensiveness: the normative-statement index

Feature coverage says which features have tests. It cannot say whether the tests cover what the LRM
*requires* of each feature. The data matrix (§4.11) answers that for data. For everything else,
there is a second, orthogonal measure.

`compliance/shall-index.yaml` lists **every normative statement in the LRM**: each "shall", "shall
not", "it shall be an error" and "it shall be illegal". The 3.1 draft has about 740 occurrences of
"shall". Each entry has:

- a stable id: the clause plus an ordinal within it;
- a hash of the sentence, so an LRM revision flags the entries whose text changed. The index stores
  a short paraphrase, not LRM text, for the licensing reasons in §2.1;
- a status, which is one of:
  - `tested`: the ids of the tests that adjudicate it;
  - `syntax`: enforced by the grammar and covered by the parse tier;
  - `non-observable`, with the reason (for example, symbolic register names);
  - `lrm-question`, where the statement is ambiguous. These join the data matrix's lrm-silent cells as
    a list for Accellera.

`pss-corpus shall extract` builds the skeleton from the LRM markdown. Classifying the statements is
review work. The coverage report gives the percentage of normative statements that are `tested`, per
clause. **The suite is "comprehensive" when every statement is `tested`, `syntax` or
`non-observable`, and every data-matrix cell is covered.** That definition is stated in advance, not
judged afterwards.

---

## 10. Populating the suite

### 10.1 Sources, in priority order

1. **Tier L0 protocol tests** (§4.6). Hand-written, about 15 tests, before anything else.
2. **Hand-written construct tests, one feature per test**, walking the taxonomy clause by clause in
   L1→L4 order.
   - The LRM examples are the *checklist*: each numbered example should map to at least one test
     that covers the same semantic point, *rewritten* rather than copied (licensing, §2.1).
   - The `generic-constraints-system-tests.md` matrix (GC-1…GC-11) and pssc's existing construct-level
     tests port directly, since they already state LRM meaning per row.
   - **Procedural tests are the cheapest to write**: deterministic, usually exact-form (§6.7), with
     no binding or inference. §20.7 (one clause per statement kind), §20.2–20.3 (functions and
     parameter passing) and §8.7 (run-time evaluation) are walked first. That gives the suite early
     breadth on every backend.
3. **Port the existing models.** Port `pssc/tests/patterns/*.pss` (12 models; Apache-2.0/MIT, written
   from scratch) and the executable parts of `curated/example2`: instrument them and write their
   reference models. They are larger "integration" tests that cover combinations nobody designed on
   purpose.
4. **Generated combination tests** (§10.3) driven by the uncovered-tuple backlog, and the
   **data-matrix generator** (§4.11), which emits every storage, passing and operation cell.
5. **Regression tests from defects.** Every tool bug the suite finds becomes a minimal test. So does
   every defect found elsewhere (U-8, U-9 and so on) that is observable at run time.
6. **Randomized model fuzzing (later).** A random PSS+JSON generator for small, closed feature
   subsets, such as constraint expressions over bit vectors, with the oracle as ground truth. This is
   where PSS integer-promotion and overflow semantics will get beaten on.

### 10.2 Authoring workflow

```
pss-corpus new flow.buffer.infer.002       # scaffold test dir: test.pss, test.json, README stub
pss-corpus lint     compliance/flow/...     # instrumentation completeness + declared/detected features
pss-corpus validate compliance/flow/...     # schema + oracle self-checks, two solvers
pss-corpus run --tool pssc-sv --test ...    # try it against a tool
```

Review rules:

- **Whoever writes the reference model does not look at a tool's trace while writing it.** Traces are
  used afterwards, to find mistakes, and a disagreement is resolved by reading the LRM, never by
  "the tool does X".
- **A test enters the suite only when `pss-corpus validate` is green and at least one tool passes it.** A
  test that no tool passes is committed with status `provisional`. It is excluded from scores until a
  second person confirms the model against the LRM.

### 10.3 Generators

A generator is a Python program in `compliance/generators/`. It takes an interaction group and a
tuple, and emits **both** a `.pss` and its `.json` from one internal description, following fixed
idioms: producer/consumer templates, resource contention templates and activity shapes. Output is
**committed** (frozen), with `"generated_by": "<generator>@<version>"` in the JSON.

Having one description emit both files is acceptable, because the generator is independent of every
tool under test. Its risk is being consistently wrong in both files, and the oracle self-checks plus
the hand-written tests for the same features are the guard against that.

Generated tests live in their own subtree (`compliance/gen/`), so hand-written and generated counts
are always distinguishable in reports.

---

## 11. One corpus, graded promises

The executable tier is **not a second corpus**. It is the part of `pss-corpus` whose files make the
strongest promise. Every `.pss` file in the repository makes exactly one of three cumulative
promises:

| Promise | Meaning | Who relies on it | Recorded in |
|---|---|---|---|
| `parses` | syntactically valid PSS (or, for `pathological/`, deliberately not) | pssparser, pssfmt, pygments-pss sweeps | `manifest.toml`, per bucket (unchanged) |
| `links` | also resolves: names, types, extensions and imports are well formed | parser/linker sweeps, pssc frontend | `manifest.toml`, per bucket |
| `executes` | also has a legality model and a trace contract; running it on a tool yields a verdict | `pss-corpus run`, pssc adapters, third parties | the test's `test.json` |

This is the sv-tests model (one repo, where each file declares
`:type: parsing elaboration simulation`), adapted to our manifest.

### 11.1 Layout

```
pss-corpus/
├── curated/                     # unchanged: frozen byte-for-byte; promise parses (some: links)
├── compliance/                  # the executable tier; every test here parses and executes
│   ├── README.md                # protocol + schema in brief; links to this design
│   ├── schema/model-1.0.schema.json
│   ├── features.yaml            # §9.1
│   ├── combinations.yaml        # §9.3
│   ├── shall-index.yaml         # §9.5
│   ├── data/legality.yaml       # §4.11
│   ├── lib/                     # pct_tap.pss (§4.12); pct_host.pss (§4.13, deferred)
│   ├── L0-protocol/<test>/{test.pss,test.json}
│   ├── data/  constraint/  activity/  flow/  resource/  exec/  component/  ...
│   │          (area = top-level taxonomy group; level lives in features.yaml)
│   ├── gen/<group>/<test>/      # generated, committed
│   └── generators/
├── checker/                     # the pss-corpus Python package (import pss_corpus), own pyproject
│   └── host/                    # reference host library: C, C++, SV DPI, Python (§4.13, deferred)
├── manifest.toml
└── COMPLIANCE-DESIGN.md         # this file
```

### 11.2 Manifest changes

These are additive, so existing consumers keep working unchanged.

```toml
[bucket.example2]
parses = true
links  = true                  # new, optional; absent = not promised
description = "Hand-written idiomatic PSS"

[bucket.compliance]
path     = "compliance"        # new, optional; absent = "curated/<name>"
parses   = true
links    = "per-test"          # negative tests (expect compile_error) intentionally don't link
executes = true                # every test dir has a test.json
description = "Executable tier: instrumented PSS + legality models"
```

- **`parses` keeps its meaning**, and every compliance test must parse. A test about a *syntax*
  error belongs in `pathological/`, not here. The executable tier's negative tests are semantic:
  they fail to link or fail to solve.
- **Parse-level consumers get the compliance tests for free.** Once a consumer reads `path`, its sweep
  covers them, so every executable test is also parser, formatter and highlighter input. This is a
  small adoption item for each of the three consumers (`C-24`), in the pattern of Phase C3. Until a
  consumer reads `path`, it still sees exactly what it sees today.
- **Multi-file tests.** `parses` is per file. `links` and `executes` are per test, over the test's
  `sources`.

### 11.3 Promoting a curated file

A `curated/` file can gain an executable form, but **never in place**. Instrumentation changes the
bytes, and `curated/` is frozen byte-for-byte because other consumers test those exact bytes. The
executable form is an instrumented copy under `compliance/`. Its `test.json` records
`"derived_from": "curated/example2/<file>.pss"`, and `PROVENANCE.md` carries the bucket's provenance
forward. The same applies to material imported from elsewhere, such as `pssc/tests/patterns`: it
arrives as a new bucket or directly as compliance tests, never as both.

### 11.4 The contract rules, restated for the executable tier

- **Test identity.** Each test has a directory and a stable `id`. Changing what a test *means* gives
  it a new id. Fixing a model bug bumps `"rev"`, which is recorded in results so scores stay
  comparable over time.
- **Frozen, but per revision.** `curated/` is frozen byte-for-byte. `compliance/` tests are frozen
  per `rev`, and are edited only through the review rules in §10.2, never to make a tool pass.
- **The manifest rule holds.** Facts about files (promise, outcome, level, features) live in the
  manifest or the test JSON. Facts about a tool (known failures, xfails) live in the tool's
  repository. **pssc's per-backend expected-failure list lives in pssc**, just as `pssfmt`'s
  `KNOWN_UNPARSEABLE` lives in `pssfmt`.
- **Discovery is unchanged.** `$PSS_CORPUS`, then `packages/pss-corpus`, then a sibling checkout. A
  missing corpus fails the suite; it is never skipped. The `pss-corpus` package also finds its own
  data. That is the one place the "duplicate the path search" rule from `PLAN.md` §5.1 does not
  apply, because the package ships inside the repo it searches.

---

## 12. pssc integration and pipeline alignment

**Adapters** live in `pssc/tests/compliance/adapters/`, with a pytest front end that parametrizes
over (backend × test × seeds). A missing corpus fails the suite rather than skipping it, in line with
the corpus contract.

| Adapter | Status | Prerequisite work in pssc |
|---|---|---|
| `pssc-python` | first | none known; runs in-process and is fastest |
| `pssc-sv` (Verilator) | first | build on `tests/sim/sv/_verilator.py`; fix `%d` → no padding (emit `%0d`), since L0 will catch it; seed via plusarg |
| `pssc-c-host` | second | lowering must **reject** what it cannot do (non-const `repeat`, `select`, unknown nodes) instead of dropping it. That turns silent FAIL into honest UNSUPPORTED; C `print` newline fix |
| `pssc-bc` | **running** (2026-09-24, procedural tier) | done: `message` lowering, typed procedural lowering (§8.7 widths and signedness), inlined native functions. Open: `with` constraints, flow objects and pools; recursion (bc inlines functions) |
| `pssc-rt-eng` | third | the native engine formats `message` like the interpreter's builtin |

**The procedural tier is where the weaker backends get scored first.** `c-host` and bc/rt-eng have
the least activity, flow and inference support, but they do lower procedural code. Once they can
emit `message`, procedural tests give them meaningful results long before L3/L4 does. Run-time
integer semantics (§8.7) are also where these backends are most likely to diverge from each other:
C integer promotion, SV sizing, and whether the Python backend truncates on assignment to a sized
field. They should be compared early.

**Op-model targets run the procedural tier (D-10).** A compliance run's entry point is always an
action, and an action's `exec body` can call op-model methods. So an op-model test is an ordinary
procedural test: a root action whose body calls the component's operations and emits `chk` records.
The `op-model-*` adapter builds the generated API together with the root action's body and routes
`message` to stdout. A memory or register test also compiles the executor tap (§4.12), so every
primitive access -- including the ones inside register accessors -- reaches the tap rather than the
platform seam, and the adapter wires nothing for memory. Register effects are observed by the `acc`
records the tap emits, and a test may still read back through the model (`read_val()`) and `chk` the
result. The records catch the symmetric errors that read-back misses. Because suite-owned code emits
them, register tests stay tool-neutral (D-11). The adapter never formats records itself. An op-model
backend therefore needs executor delegation (§21.13.9.5) before it can run memory tests.

**The data matrix and the host library are pure procedural tests,** so every backend that can emit
`message` can run them. They are expected to find the most backend disagreements: integer widths
across C, SV and Python, struct copy versus alias, and `output`/`inout` across DPI and ctypes.

**Alignment loop.** Run the whole suite on every backend and read the §9.4 alignment view:

1. **Disagreement cells first.** If one backend passes and another fails, the frontend is probably
   right and the losing backend has a lowering gap.
2. **All-backends-fail cells next.** These are likely frontend (`ast2ir`) or shared-IR issues.
   Because the suite is backend-neutral, it points at the shared layer. This is the construct-level
   argument, now observed across N backends instead of assumed from one.
3. **Unsupported cells last.** These form a roadmap, not a bug list.

The pssc CI gate is **no regression on the pass set per backend**, with expected failures listed per
backend in pssc. Newly passing tests are reported, so stale xfails get removed; this is the
`xfail(strict=True)` idea applied at suite level.

---

## 13. Levels and phasing

### Levels

| Level | Content | First consumers |
|---|---|---|
| **L0** | protocol / `message` formatting | all |
| **L1** | atomic actions, scalar rand fields, basic constraints (relational, `in`, implication, if/else, foreach over fixed arrays), enums, structs. **Data matrix:** scalar, enum and struct cells of the storage projection (§4.11). **Procedural core:** locals, assignment and compound assignment, arithmetic and logic on `int`/`bit`, `if`/`match`, `repeat`/`repeat-while`/`foreach`, `break`/`continue`, functions with `return` | all four pssc backends |
| **L2** | integer semantics in constraints *and* at run time (width/sign promotion, truncation on assignment, overflow; hand-written anchors), `dist`, `unique`, collections (declaration and operations), static constraints, inheritance/extension/override. **Procedural advanced:** parameter directions, `const`, defaults, generic and varargs, recursion, pure functions (also in constraints), strings and `format`, `randomize` statement, solve-time execs (result attributes, order signatures), exec extension and `super`. **Data matrix:** the remaining storage cells (collections, strings, `chandle`, `ref`), and the passing and operation projections. **Host library:** imports and exports on the target platform (§4.13) | python, sv; c-host and bc for the procedural part |
| **L3** | activities: seq/par (all join kinds)/schedule/select (guards, weights)/repeat/repeat-while/replicate/foreach/if/match; labeled handles; inline `with`; compound constraints | python, sv, bc |
| **L4** | flow objects (buffer/stream/state), explicit bind, pools, inference, resources lock/share/`instance_id`, multi-instance components | python, sv |
| **L5** | soft-constraint priority (MaxSMT); **platform**: allocation and claims, handles, primitive, byte-list and packed-struct access, registers, executor customization (§4.12), imports on the solve platform (§4.13); multi-executor concurrency; coverage (not observable, so parse-only) | op-model targets first (D-10), then python, sv, c-host |

### Phases

**P1: protocol and walking skeleton.**

- `pss-corpus`: extractor, schema, a checker with structure for seq/par/select/repeat and SMT data checks
  (Z3 in-process and an SMT-LIB2 binary), and the runner.
- The checker also matches `body` patterns (§6.7), including the solver-free exact-form fast path.
- L0 (~15 tests) and ~30 L1 tests, about half of them procedural.
- `pssc-python` and `pssc-sv` adapters, plus `pssc-c-host` restricted to procedural tests, whose roots
  are single atomic actions or plain sequences.
- `--seed` in the contract from day one.
- Amend `README.md` and `PLAN.md` for `checker/` (D-1) and graded promises (§11); add the
  additive manifest keys (`links`, `path`, `executes`). Constraints use `"smt_source": "hand"` in P1 (§6.6 staging).

*Exit:* both backends report and every disagreement is triaged.

**P1 progress (2026-09-24).** The procedural slice runs end to end on pssc's bc
backend first, ahead of the python and sv adapters, because it needs no
activity, flow or binding support:

- `compliance/`: 58 tests (15 L0, 37 L1, 6 L2 anchors), catalogued in
  `compliance/README.md`.
- `checker/`: the extractor, P1 structure (traversal, `seq`, constant `repeat`),
  body patterns with the exact-form fast path, and `where` via z3 with named
  unsat cores. Self-tests synthesize a legal trace from each exact-form model,
  require it to PASS, and require every mutant of it to FAIL (the P1 form of the
  §6.5 cheat mutations).
- `pssc/tests/compliance/`: the `pssc-bc` adapter, the pytest front end, and
  `expected/bc.toml`.
- pssc/bc result: 55 PASS, 2 UNSUPPORTED (recursion), 1 FAIL (a pssparser
  cast-precedence defect).

Found on the way. The first four are fixed in pssc's `ast2ir`; the fifth is
open; the sixth is worked around in the adapter:
  1. unbraced `if`/`while`/`repeat` bodies crashed the translator;
  2. a nested `{ ... }` block and every statement in it were silently dropped;
  3. package-scope function definitions were dropped;
  4. a match range `[lo..hi]` matched only `lo`;
  5. pssparser parses `(T)a + b` as `(T)(a + b)`;
  6. every unconstrained `rand` field solved to 0 under bc's `NativeBlobBackend`.
     That is legal, so legality checking passed it. Only the phase-2 seed
     sensitivity and reachability checks (§8.1) would catch it. The adapter
     opts into `lower_module(solve_unconstrained=True)`; bc's default is
     unchanged.

**P2: activities, feature taxonomy, validation CI.**

- The full L3 activity grammar.
- `features.yaml`, seeded from Annex B.
- `pss-corpus lint` and `pss-corpus validate`, with the two-solver cross-check wired into pss-corpus CI.
- Coverage report.
- The PSS-expression→SMT translator with `translate --update` and the currency check, landing together
  with the L2 anchors that pin it; P1 non-anchor entries converted to `"translated"` (§6.6).
- L2 and L3 tests, including the procedural-advanced anchors; the `c-host` adapter over all tiers.
- bc/rt-eng `message` lowering (pssc), so the bc adapter can start on the procedural tier.
- Yield ladders: `occ` attribution and the four interleaving checks (§4.9), with their L3 tests.
- `op-model-py` and `op-model-c` adapters on the procedural tier, with register read-back tests (D-10).
- The data-matrix generator, `legality.yaml`, per-cell verdicts and batch bisection (§4.11), and the
  value conventions of §4.10.
- *Deferred (D-12):* the reference host library, `imp` records, the emit hook, and `--platform` in
  the adapter contract (§4.13).
- A seeded `shall-index.yaml` (§9.5), reported alongside feature coverage.

*Exit:* coverage report published and the alignment view in use.

**P3: flow, resources and inference.**

- Binding witness search, pools, the state sequence, lock/share, and the §6.5 completeness and
  justification rules.
- Oracle trace synthesis and cheat-mutation self-tests in `pss-corpus validate` (§6.5).
- L4 tests; `tests/patterns` ported.
- `C-24`: the three parse-level consumers read the manifest's `path`, so their sweeps include
  `compliance/`.
- **Platform (§4.12):**
  - `pct_tap.pss`, the executor tap, and `F8` in the checker -- **done 2026-09-24**
    (`checker/src/pss_corpus/tap.py`);
  - `acc` records and op-mode leaves (`eq`, `where`, `"as"`), with every read checked against
    `F8` -- **done 2026-09-24**; effect mode, and the packing oracle with its Figure 54–57 anchors,
    remain;
  - the L0-P tier -- **done 2026-09-24**, four tests (`L0-tap/rw8`..`rw64`);
  - the byte-list tap library (`read_bytes`/`write_bytes`);
  - memory, allocation and register tests on the executor tap;
  - `platform_cfg.pss` generated from the `platform` section (the L0-P tests write their own
    setup);
  - the op-model adapters moved from read-back only to `acc` capture.
- Executor delegation (§21.13.9.5) and `set_executor` in each backend that is to run memory tests.
  `op-model-py` delegates as of 2026-09-24, register accesses included. `op-model-c`, `-cpp` and
  `-sv` refuse a model whose executor overrides a primitive, rather than bypass it; bc has no
  address handles.

*Exit:* python and sv adjudicated on L4, and every backend with executor delegation scored on the
memory tier.

**P4: combinations and generators.**

- `combinations.yaml`, pairwise tuple accounting, the first generators, `compliance/gen/`.

**P5: distribution (the "second step").**

- An aggregator over the stored per-run samples.
- `dist`, `select` and `stability` as compliance checks; `reachable` and `uniformity` as quality
  metrics.
- Oracle model counting and power-analysis warnings.

*It needs no protocol, adapter or checker-core change. That is the test of whether §8.5 was honored.*

**P6: external readiness.**

- A `pss-corpus` release on PyPI, adapter author's guide, and an example third-party adapter.
- Native-mode trace translation (§4.7).
- Normative-statement index fully classified. Release gate: the §9.5 comprehensiveness definition
  holds, or the gaps are listed in the release notes.
- The bc and rt-eng adapters on the scenario tiers, as their activity and flow support grows.

---

## 14. Decisions

### Decided (review of 2026-09-24)

- **D-1: the checker lives inside `pss-corpus`**, as `checker/` with its own pyproject. The README
  and `PLAN.md` are amended so that `curated/` and `compliance/` stay data while `checker/` is code.
  Schema and checker version together.
- **D-2: the constraint language is the hybrid (option D).** Authors write a PSS expression subset.
  `pss-corpus` translates it to SMT-LIB2, which is committed, currency-checked and reviewed as diffs,
  and a hand-written `smt` may override the translation. Hand-written L2 anchors pin the translator by
  equivalence checking. The rules are in §6.6.
- **D-3: one `act` record per atomic `exec body`, as its first statement.** There are no begin/end
  records. Interleaving is observed through yield ladders (§4.9, D-9); wall-clock overlap is not.
  *Amended 2026-09-24 for procedural code:* any number of `chk` records may follow the `act` record,
  from the body or from functions it calls. Each record is still a single `message` call (§4.2,
  §4.8).
- **D-4: every inferred action must be justified, and every flow-object ref must be fed.** Both rules
  are always on, with no opt-out: see §6.5 (rules C and J, pool identity, and cheat-mutation
  self-tests).
- **D-5: statistical thresholds.** p < 1e-4 is FAIL and p < 1e-2 is SUSPECT, with Holm–Bonferroni
  correction within a tool's run of the suite (§8.4).
- **D-6: no floating point in v1.** Models with `float32`/`float64` rand fields are rejected by
  `pss-corpus validate` until a `QF_FP` profile is added.
- **D-7: enums are printed as `(int)` casts** with `%d` in L1–L4 instrumentation. `%n` is exercised only
  in L0.
- **D-8: naming. One identity: the repository.** No new repo and no new brand. A separate
  `pss-tests` repo would create a parallel corpus, and one corpus with graded promises (§11) is the
  point. Names:
  - the package, import root and command are `pss-corpus` / `pss_corpus` / `pss-corpus` (free on
    PyPI, checked 2026-09-24);
  - the executable tests are "the executable tier of pss-corpus";
  - the trace sentinel is `@@PSS-TRACE`, deliberately brand-neutral;
  - the model schema id is `pss-corpus/model/1.0`.

  Renaming the repo to `pss-tests`, for recognition by the sv-tests audience, remains possible later.
  It would be a coordinated change to three consumers' `ivpm.yaml`/CI, `$PSS_CORPUS` and the mirror.
  It would not change any test file.
- **D-9: concurrency is observed with yield ladders.** Bodies under test yield between records, and
  LRM §20.7.14(c) makes the interleaving checkable. Records from concurrently-runnable code carry an
  `occ=` key assigned by the activity. The checker adds four interleaving checks: the yield rule,
  sequencing, realized concurrency and resource exclusion. Details are in §4.9.
- **D-10: op-model targets run the procedural tier.** The entry point is always an action, whose
  `exec body` calls op-model methods. The adapter supplies the platform seam and memory, and register
  effects are observed by read-back `chk` records (§12). *Amended by D-11:* accesses are also
  captured as `acc` records, emitted by the executor tap.

- **D-11: accesses are observed by a pure-PSS executor tap** (decided 2026-09-24). Every test that
  accesses memory or registers compiles `pct_tap.pss` and assigns it at the root with
  `set_executor`. The tap overrides every memory primitive (§21.13.9.5), logs each access as an
  `acc` record, and answers each read with a fixed value computed from the address (`F8`, §4.12). It
  holds no state, because component attributes cannot change after the tree is built. This
  **amends D-10**: read-back alone misses symmetric errors, and the records are emitted by suite
  code, in PSS, so they stay tool-neutral and need no linking. It does not test the tool's own
  primitive or its connection to the outside world.
- **D-15: vendor tools are run through export/import** (decided 2026-09-24). A bundle carries
  sources and jobs out, and results come back in the same directory. The legality models never
  leave, so the tool's site needs only the tool and Python 3.8. Verdicts are computed where the
  corpus is. Negative tests are judged by outcome **and** error location (`diagnostics.json`).
  A located rejection is PASS, one at the wrong place is FAIL, and an unlocated one is its own
  verdict, UNLOCATED. Import adds STALE (the test changed since export) and MISSING (no result),
  neither of which is about the tool. Only an L0 FAIL withdraws trust: an L0 run that is
  UNSUPPORTED or UNLOCATED doesn't, and an L0 run that is ERROR, MISSING or STALE leaves trust
  *not established*. The first target is Cadence Perspec (`HANDOFF.md` §7).

### Open (proposed 2026-09-24)

- **D-12: behavioural models behind `import` functions** (deferred 2026-09-24). What the stateless
  tap cannot show -- read-after-write, a value that changes while it is polled, region faults, the
  tool's own primitive, and values crossing the foreign-language boundary (§4.13) -- needs code
  outside PSS: a memory model, or a host library, reached through imported functions. The open
  question is how to supply it to every tool in a tool-neutral way. One direction: a test requires a
  specific model to be connected to named `import` functions, and the adapter says whether it can.
  *Settled 2026-09-24:* whichever way it is supplied, the executor reaches the model **through
  dedicated imports** (`model_write32(addr, data)`, as in LRM Example 352), never through the
  platform's own primitive. The pure-PSS tap calls neither: it answers reads itself and only logs
  writes. So no test depends on a tool's built-in `read32`/`write32` or on what the default
  implementation does. The model's imports are declared in PSS, so the test stays tool-neutral; what
  remains open is how each tool links an implementation to them.
- **D-13: data coverage is three exhaustive projections**: storage (T × S × I), passing (T × P) and
  operations (T × O), over a cited legality table, generated, batched with per-cell verdicts and
  bisected on `compile_error` (§4.11). The alternative is t-wise sampling of the full product. It is
  cheaper, but it cannot claim completeness.
- **D-14: comprehensiveness has a stated definition**: every normative statement in the index is
  `tested`, `syntax` or `non-observable`, and every data-matrix cell is covered (§9.5).

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Reference models are wrong, and the oracle faithfully judges against a wrong model | two-solver validation; `provisional` status; the no-peeking authoring rule; hand-written and generated tests overlap on the same features |
| Instrumentation perturbs what is tested (it adds exec body, message, `std_pkg`) | L0 isolates the instrumentation's own features; `features.uses` records them; observers are marked in the model |
| Checker blow-up on large scenarios | a record budget; ERROR, never PASS, on timeout; tests kept small by policy |
| Tools print differently and adapters "helpfully" normalize | adapters must not rewrite logs; strict value syntax; L0 marks non-conforming tools UNTRUSTED instead of silently fixing them |
| Suite becomes a golden-file suite in disguise | the schema has no field for expected output text; `chk` records assert values through `properties`, never raw strings |
| Procedural expected values are wrong, because the author did the arithmetic (§6.7) | L2 run-time-semantics anchors cite the LRM per rule; the D-2 translator re-derives `eq` constants; a disagreement between backends is triaged against the LRM, never settled by majority |
| Distribution tests flake | fixed seed lists; verdicts deterministic per tool version; normative checks limited to `dist`, `select` and stability |
| The executor tap is wrong, and every tool is judged against it | it is small, stateless PSS; the checker computes `F8` and the byte-order and packing rules independently; L0-P per tool |
| The executor tap perturbs what it measures (it needs delegation, `set_executor`, shifts and casts) | no loops or collections outside byte lists; its features are in `features.uses` and covered by the procedural tier first; a tool without delegation is UNSUPPORTED, not FAIL; a read's `data` is checked against `F8`, so a miscompiled tap fails rather than passes |
| Host-library output is reordered against the tool's own output | the emit hook: the suite's code never writes stdout directly (§4.13) |
| The data matrix is too large to run | per-type batching with per-cell verdicts; exact-form checks with no solver; bisection only on `compile_error` |
| The shall-index goes stale as the LRM moves | sentence hashes flag changed entries on each LRM revision; the index is re-extracted, not hand-edited |
| Coverage numbers overstate | "adjudicates" is separate from "uses"; declared and detected are reconciled; unobservable features are marked and reported separately |
