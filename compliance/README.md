# compliance/ — the executable tier

Every test here is a directory holding instrumented PSS (`test.pss`) and a
legality model (`test.json`). A tool runs the PSS through an adapter; the
checker in `../checker/` decides whether the log describes a legal execution.
The design is `../COMPLIANCE-DESIGN.md`; this page is the short version plus
the catalogue.

```
pss-corpus list                                        # the tests
pss-corpus run --adapter "<cmd>" --out results/ [ids]  # run a tool, check every run
pss-corpus check <test-dir> <run-dir>                  # check one run
pss-corpus export --pss 3.0 --out b.tar.gz [ids]       # a bundle for a tool run elsewhere
pss-corpus import b-returned.tar.gz                    # check the results it came back with
pss-corpus report <run>/report/report.json             # re-render the HTML report
```

`run` and `import` write `report/report.html`: pass/fail per run with the
reason, and the trace and errors behind each failure.

For a tool you cannot run here (a vendor's, a licensed one), export a bundle,
have it run at the tool's site, and import the results: `../HANDOFF.md`.

## The protocol in brief (§4)

A record is the text after `@@PSS-TRACE ` on any log line, printed by one
`message(NONE, ...)` call:

```
@@PSS-TRACE act <action type> [key=value ...]   first statement of every exec body
@@PSS-TRACE chk <tag> [key=value ...]           procedural checkpoints, in order
@@PSS-TRACE acc <op> addr=0x.. data=0x..        one memory access, from the executor tap
```

`acc` records come only from `lib/pct_tap.pss`, the executor tap (§4.12): an
executor that overrides every memory primitive, logs each access and answers
each read with F8 of its address. A test compiles it by listing it in its model
(`"libs": ["pct_tap"]`), and a bundle carries a copy in each test's directory.

Values are strict: decimal with no padding (`%d`, `%u`), `0x` plus lowercase hex
(`0x%x`), `true`/`false` (`%n` on a bool), or a string token with no spaces. A tool that
pads, uppercases or adds a `\r` fails. Adapters must not "fix" the log.

A tool that rejects a test also writes `diagnostics.json`: `{severity, file,
line, column?, message}` per error. Negative tests pass only with an error on
the right line (`../HANDOFF.md` §4).

## The model (§6)

`types[<root>].body` is the legal sequence of `chk` and `acc` records for an
atomic action: `seq`, `repeat` (a constant count, or an SMT term over the
action's fields), `chk` leaves and `acc` leaves (`{"acc": "w32", "eq": {"addr":
…, "data": …}}`; `"as": "rd"` names a read's data for later leaves). A read's
data is always checked against the tap's value, whatever the leaf says. A leaf states its values exactly (`"eq": {"x": 3}`) or as
constraints (`"fields"` + `"where"` with hand-written SMT-LIB2, `$k` naming the
index of an enclosing `repeat`). A test with only `eq` leaves never starts the
solver. The expected values come from the LRM clause each test cites, never from
a tool's output. The L2 anchors carry their derivation in `"derivation"`.

## Catalogue: procedural code (first slice, 58 tests)

The first slice covers procedural code, the cheapest tier to write and the one
every backend can run (§10.1). **L0** checks the trace protocol itself; a tool
that fails it has its other results marked untrusted (§4.6). **L1** is the
procedural core. **L2** holds the run-time integer-semantics anchors (§8.7) and
the advanced function features.

| Area | Tests | LRM |
|---|---|---|
| **L0 protocol** | `act_single`, `dec_int32`, `dec_int64`, `udec`, `hex`, `bool_n`, `enum_n`, `str_s`, `no_padding`, `percent`, `multi_record`, `from_function`, `from_recursive` (L2 feature), `seq_bodies`, `nested_action` | 21.1.1, 21.1.3 |
| locals and scopes | `local_decl` (default values, initializers), `local_multi` (`int e = 1, f = e + 1, g;`), `scope_block`, `scope_shadow` (L2) | 20.7.1, 20.7.2 |
| assignment | `assign_basic`, `assign_compound` (every compound operator the LRM has: `+= -= <<= >>= \|= &=`) | 8.3, 20.7.3 |
| operators | `arith`, `bitwise`, `logic`, `cond_op`, `cast_precedence` | 8.4.1, 8.5 |
| if / match | `if_else`, `if_elseif`, `if_unbraced`, `match_ranges`, `match_values` | 20.7.9, 20.7.10 |
| loops | `repeat_count`, `repeat_index`, `repeat_zero`, `while`, `while_zero`, `repeat_while`, `break`, `continue`, `break_nested`, `break_while` | 20.7.6, 20.7.7, 20.7.11 |
| return | `return_exec` (return ends the exec) | 20.7.5 |
| functions | `func_return`, `func_void_return`, `func_param_byvalue`, `func_nested_calls`, `func_void_cast`, `func_component` (`comp.f()`), `func_default_param` (L2), `func_recursion` (L2) | 20.2, 20.3.2, 20.7.4 |
| action attributes | `field_rw`, `rand_input` (8 seeds; results checked as functions of the random input) | 20.1, 20.7 |
| **L2 run-time integer semantics** | `rt_trunc_assign`, `rt_extend_assign`, `rt_sign_compare` (Example 43), `rt_width_propagate` (Example 42), `rt_div_mod`, `rt_shift_signed` | 8.5.1, 8.5.2, 8.5.7, 8.7 |

Design rules the slice follows:

* **One feature per test.** Incidental dependencies are listed in
  `features.uses`, so a failure can be pinned on the feature it adjudicates.
* **The path is part of the observation.** A `chk` in each branch or iteration
  means a missing `break` or an extra iteration is an extra record, which fails.
  A record for a branch that must not run is tagged `*.wrong`.
* **Distinguishing values.** Each expected value is chosen so the plausible wrong
  answers differ from it. For example, `rt_width_propagate` prints `x + y` both
  as a 16-bit assignment (4320) and as a self-determined vararg (224).
  `cast_precedence` gives 108 when parsed right and 12 when the cast swallows the
  `+`.
* **No LRM-ambiguous cells.** `%d` on an unsigned value is "converted to signed
  type before being formatted" (21.1.1 c), which is ambiguous about the width.
  So unsigned values of 2^(N-1) or more are printed with `%u`, and no test
  depends on that reading.

## Catalogue: operation-model features (batch 1, 23 tests)

The features that operation models are written in (a PSS component whose functions are
a device's API, as in pssc's `examples/op_model/`), reached from an action's `exec body`
so that any PSS tool can run them. Their models carry `"profile": ["op-model"]`. The
features come from what the WB DMA model actually uses; each test pushes one feature past
the happy path (edge values, per-instance state, order, early exits). Memory and registers
are the next batch (§4.12).

| Area | Tests | LRM |
|---|---|---|
| component state | `comp/init_solve_fn` (a solve function called from `init_down` sets attributes), `comp/init_order` (Example 280 order, last writer wins), `comp/struct_attr` (struct attribute with field initializers, per-instance override) | 9.1.4.1, 20.1.2 |
| component structure | `comp/array` (array sized by a package constant, `foreach` order, runtime index), `comp/instances` (two instances, separate state down to sub-components) | 9.1.4, 20.7.8 |
| component functions | `comp/func_calls` (unqualified sibling calls, package function, early `return` on an attribute) | 20.2, 20.7.4 |
| enums | `types/enum_values` (default is the first item, casts to `int` and `bit`), `types/enum_match` | 7.5, 20.7.10 |
| structs | `types/struct_fields`, `types/struct_copy` (deep copy, `==`), `types/struct_param` (Example 298), `types/struct_return` | 7.8, 8.3, 20.3.2 |
| conversions | `types/bit_pack` (packing with and without casts: the target size reaches a shift's operand), `types/return_convert` | 7.12, 8.7 |
| constants and strings | `types/pkg_const`, `types/string_match` (`match` on a string; `return -1` as `bit[64]`) | 10, 20.7.10 |
| control shapes | `proc/poll_while_true`, `proc/poll_repeat_while` (start / check / poll), `proc/yield_single`, `proc/compile_if` (`compile has` on a missing constant) | 19, 20.7.6, 20.7.14 |
| channels | `sync/chan_try`, `sync/chan_depth` (FIFO, copy-in), `sync/chan_guard` (the in-flight guard, per instance) | 21.9.1 |

Not yet covered, because the P1 checker or protocol does not reach it:
`foreach` over collections, `randomize`, solve-time execs (`pre_solve`/
`post_solve` result attributes and order signatures), exec inheritance and
`super`, `yield` ladders (§4.9), `runtime_error` and `solve_fail` negative
tests, `parallel` branches arriving whole (L0).

## Catalogue: the executor tap, L0-P (4 tests)

One read and one write of each width through `lib/pct_tap.pss`, assigned with
`set_executor` in the root's `init_down`. A tool that fails these has its memory
and register results marked untrusted (§4.12). Each needs executor delegation
(21.13.9.5), so a tool without it reports UNSUPPORTED.

| Test | Access | LRM |
|---|---|---|
| `L0-tap/rw8`, `rw16`, `rw32`, `rw64` | `readN` at a region offset, then `writeN` of the value plus one | 21.7.2.6, 21.13.9.1, 21.13.9.2, 21.13.9.5 |

## Catalogue: negative tests (5 tests)

Each must be rejected (`compile_error`) with an error at a stated line. They
are semantic errors, so every file still parses (§11.2).

| Test | Error | LRM |
|---|---|---|
| `L0-protocol/diag_location` | an action field of an undeclared type: the diagnostics protocol itself | 18.3 |
| `neg/ref_undeclared` | assignment to a name declared nowhere | 18.3, 20.7.3 |
| `neg/ref_before_decl` | a local referenced before its declaration | 20.7.2 |
| `neg/call_undeclared` | a call to a function declared nowhere | 18.3, 20.2 |
| `neg/type_undeclared` | a local of an undeclared type | 18.3, 20.7.2 |

A model may carry `"pss": "3.1"` when the test needs PSS 3.1 (the
`sync/` channel tests do). Unstated means 3.0, and `export --pss` filters on it.

## Results

The per-tool expected-failure list lives with the tool, not here (§11.4).
pssc's are `pssc/tests/compliance/expected/bc.toml` and `op-model-py.toml`.

| Tool / target | PASS | not PASS |
|---|---|---|
| pssc / bc (2026-09-24) | 66 of 90 (all 5 negative tests pass, located) | 2 UNSUPPORTED (recursion: bc inlines functions); 18 UNSUPPORTED op-model tests (bc lacks structs, attribute paths, calls through component paths, `yield`); 4 UNSUPPORTED L0-P (no address handles) |
| pssc / op-model-py (2026-09-24), root action as the entry (`--export-action`) | 80 of 90 (all 5 negative tests and all 4 L0-P tests pass) | 4 not an operation-model entry (activity, action attributes, `rand`); 1 needs `--py-await async` (blocking channel); the rest are op-model-py gaps (match ranges and `as` patterns, package-constant typing, a register-offset name clash); see `pssc/tests/compliance/expected/op-model-py.toml` |
