# Corpus provenance

These files are **frozen test input**: do not reformat them, do not "fix" their
PSS, and re-vendor only deliberately. A corpus that changes under you is worse
than one that ages.

That rule is not a style preference. Three consumers read these exact bytes —
`pssfmt`'s round-trip gate, `pygments-pss`'s no-`Error` sweep, and `pssparser`'s
parse sweep — so editing a file here silently changes what those suites are
testing, without any of them going red to say so.

Remote URLs are given as `git.dvkit.org` paths; the self-hosted instance is
also reachable over the internal network, which must not be named in a tracked
file.

## Licensing

**This repository is Apache 2.0 throughout, and that is an acceptance criterion
for new material rather than a description of the current state: new material
is Apache 2.0 or it is not vendored.**

A corpus can hold that line more cheaply than most projects can, because a
corpus file is *test input* rather than a component. If a candidate file cannot
be taken under Apache 2.0, the near-always-correct answer is to decline it and
write an equivalent — `pss31/`, `lexical/` and `pathological/` were authored
exactly that way. The cost is a few hours; the cost of a mixed-licence data
repository that three projects depend on is unbounded.

> **Do not add SPDX or copyright headers to the corpus files themselves.** No
> file here carries one, and adding one would edit frozen vendored input — the
> same rule as above, with the same invisible consequences for the three
> consumers. If a file ever does need its own licence statement, it goes in a
> `REUSE.toml` at the repository root, which exists precisely for files that
> cannot carry a header, alongside a `LICENSES/` directory. Licence metadata
> lives *beside* the files, never inside them.

Neither `REUSE.toml` nor `LICENSES/` exists today, because a second licence does
not exist today.

## Buckets

| Directory | Source | Commit | Licence | What it contributes |
| --- | --- | --- | --- | --- |
| `curated/example2/` | `psstools/example` — `2/src/pss/` (working tree, not a git checkout) | n/a, vendored 2026-08-13 | Apache-2.0 ‡ | Hand-written idiomatic PSS: components, actions, activities, register/memory models. |
| `curated/stdlib/` | `zuspec/zuspec-fe-pss` — `src/stdlib/` | `62be6eeded41656a881bc6bafd58e9efc9474e96` | Apache-2.0 † | The PSS core library itself (`std_pkg`, `executor_pkg`, `addr_reg_pkg`, `sync_pkg`, `packed_s`). Substitutes for the plan's T2.2 source, `tests/patterns/`, which no longer exists in that repo. Higher value than what it replaces: it is the exact vocabulary a highlighter or formatter has to recognise. |
| `curated/peakrdl/` | `psstools/peakrdl-pss` — `tests/golden/expect/` | `f351df80bfe9b7a9ddaa0491310886eabb21bf23` | Apache-2.0 ✓ | Machine-generated, register-model idioms — a different style from anything hand-written. |
| `curated/language-ref/` | `psstools/pss-skills` — `skills/pss-language-ref/examples/` | `f1ed60279e4b3c7fa961e398b505563c101865f9` | Apache-2.0 † | Feature-targeted examples written against the LRM. |
| `curated/pss31/` | authored here | — | Apache-2.0 ✓ | PSS 3.1-only surface. |
| `curated/lexical/` | authored here | — | Apache-2.0 ✓ | Clause 4 lexical torture. |
| `curated/pathological/` | authored here | — | Apache-2.0 ✓ | Deliberately broken input. Excluded from the no-`Error` rule and from any "parses cleanly" sweep — see `manifest.toml`. |

**✓ verified** — the source carries an Apache 2.0 `LICENSE` file, or the
material was authored in this repository.

**† stated, not verified** — the upstream is not checked out alongside this
repository, so its `LICENSE` was not read when this table was written. Recorded
as an honest gap rather than an assumption; verify on the next re-vendor.

**‡ stated, source carries no LICENSE file** — `psstools/example` is a plain
working directory, not a git checkout, and has no `LICENSE`. The material is
Apache 2.0 by intent of its author. The fix belongs upstream — add a `LICENSE`
to `psstools/example` — rather than here, because asserting in the corpus a
licence the source does not state is precisely the move this section exists to
prevent. Tracked as `C-5b` in `PLAN.md`.

## Completing LRM examples

Material derived from the PSS standard's own examples must be **completed, not
transcribed**. The LRM's examples are illustrative fragments; most of them are
not compilable PSS, and a file that is copied faithfully will not parse.

Two things make them uncompilable, and both are easy to miss because the
examples look complete:

- **A bare `action` at package scope is a syntax error.** `package_body_item`
  (Annex B.1) admits only `abstract_action_declaration`. Around 204 action
  declarations in the 3.1 draft appear with no enclosing component. Others —
  Examples 10, 49 and 50 among them — *do* carry `component pss_top`, so the
  idiom is inconsistent across the document and cannot be assumed either way.
  Check each example. The same applies to `cover_stmt`, which B.7 admits only
  as a `component_body_item`, never as an `activity_stmt`.
- **Literal elision.** `...`, `{...}` and `{ ... };` appear throughout and are
  not PSS syntax anywhere.

The rule, in order:

1. **Wrap loose `action` declarations in a `component`** — prefer one the file
   already declares, else add `component pss_top`. Move any *monitor* that
   references those actions in with them, or its handles no longer resolve.
2. **Expand every elision** into something real, or delete the member.
3. **Declare every type the example references.** Drop `import`s of packages
   that are not in the file.
4. **Parse the file before committing it.** A bare wrapper is enough for a
   `parses = true` bucket — that bucket promises zero *syntax* errors, and an
   `input`/`output`/`lock`/`share` field links clean with no `pool` or `bind`.
   Do not add pools and binds the example does not need.

**Why this is a rule and not a note.** All three files in `curated/pss31/` were
authored in the example idiom and sat in the consumers' `KNOWN_UNPARSEABLE`
tables from the day they arrived, under two invented defect identifiers —
`U-8a` and `U-8c` — for parser gaps that never existed. The bucket that exists
to cover PSS 3.1 exercised none of it, and the misdiagnosis outlived several
passes over the corpus because a file with an xfail beside it reads as *known*
rather than as *wrong*. They are the worked example for this section; see
pssparser's `docs/design/pss31-prd-alignment-plan.md`, P7-C1.

Step 4 is the one that would have caught it on its own.

**On editing them at all.** The rule at the top of this file — frozen input, do
not "fix" their PSS — governs *vendored* material, whose value is being exactly
what upstream has. `pss31/` is `authored here`, and these three files were never
valid PSS, so there was no behaviour to preserve: the bytes the three consumers
were reading encoded a wrong answer. Repairing them is a coordinated change
across all three, not a local edit — `KNOWN_UNPARSEABLE` entries move in the
same commit in pssparser and in `pssfmt`, or the surviving strict xfails flip to
XPASS and fail the suite that was left behind.
