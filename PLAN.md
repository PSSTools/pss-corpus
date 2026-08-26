# `pss-corpus` — Collection and Adoption Plan

**Status:** Phases C1–C4 complete (2026-08-26) — seeded; all three consumers
adopted it, and the parser sweep found a defect on its first run
**Date:** 2026-08-26
**Repository:** `psstools/pss-corpus`
**Closes:** `pssfmt/PLAN.md` `Q-3`; unblocks `T-4`, `T-5`, milestone **M3**
**Related:** `pssfmt/PLAN.md` `R8` (corpus drift), `U-8` (parser gaps this
corpus found), `formatter.md` §7.8

> **Phase C4 done, and it paid for the project on its first run.** The sweep
> landed red, as predicted — but not on the five `U-8` gaps it was built to
> pin. Those it reproduced exactly, all six files, same causes. The unexpected
> failure was `pathological/lone_backslash.pss`, which `pssparser` **accepts**:
> the lexer reports `token recognition error` on stderr and the process still
> exits 0 with "0 errors". Recorded as **`U-9`** (§6, `C-19`). Exit status is
> the whole interface for an editor, a pre-commit hook or `pssfmt --check`, so
> a file containing untokenizable bytes is currently indistinguishable from a
> clean one to every caller that does not scrape stderr.
>
> That is the argument for this project, made concretely: the defect had been
> reachable from a corpus file for as long as the file has existed, and no
> consumer found it, because every *other* `pathological/` file also trips a
> parse error and so exits 1 regardless. `lone_backslash.pss` is the only one
> with no second error to mask the first.
>
> **Next:** Phase C5 (`C-21`–`C-23`), breadth — unsequenced and unowned, and
> genuinely optional. The higher-value follow-on is `U-9` itself, which is a
> `pssparser` fix and not a corpus item.
>
> **Durability: resolved 2026-08-26.** This repo is committed and pushed
> (`8bc3403`), and `pygments-pss` with it (`cbc1964`). The window where C3 had
> deleted the donor's copy against nothing but a staging area is closed.
> `pssfmt` remains uncommitted, but that predates this work and nothing here
> depends on it.
>
> **Blocked on you:** the GitHub mirror (`C-2a`) still returns *repository not
> found*, so `ivpm update` cannot resolve the corpus in `pssfmt`, whose
> `ivpm.yaml` names the mirror by convention. Nothing is broken today — the
> working copy was placed by hand — but a fresh checkout of `pssfmt` cannot
> currently get a corpus.

---

## 1. Why this is its own project

`pssfmt`'s `Q-3` framed this as a placement decision — *which repo owns the
files*. Doing the work makes it clear it is three jobs, and only the first is
about placement:

1. **Collect.** Seed the repo from the existing curated corpus, carrying its
   provenance intact.
2. **Contract.** Agree how a consumer *finds* the corpus and how it knows what
   each bucket promises. Three consumers currently answer both questions
   independently, in code, and the answers have already begun to diverge.
3. **Adopt.** Migrate three repos, each independently and each revertibly, and
   delete the copy that is being replaced — because a migration that leaves the
   old copy in place has not removed the drift, it has doubled it.

Job 2 is the one that makes this a project rather than a `git mv`. It is also
the one with the longest tail: every consumer that adopts before the contract
exists encodes its own version of the contract, and unpicking that later costs
more than agreeing it now.

**What triggered it.** `pssfmt`'s `P1` round-trip gate ran a *parser* over a
corpus built for a *lexer* and found five `pssparser` gaps for valid PSS
(`U-8`). That corpus is currently test data inside a syntax-highlighter repo,
so by construction no parser suite runs against it. The gaps were found by
accident. Making that a standing arrangement rather than an accident is most of
the value here — more than the drift argument that opened `Q-3`.

---

## 2. Current state

> **Superseded 2026-08-26 by Phase C1.** The repo now holds `curated/` (92
> files), `PROVENANCE.md`, `manifest.toml`, a data-repo `.gitignore` and this
> plan. The `.gitignore` hazard below is fixed and regression-checked; the
> `type: raw` omission is fixed. The URL question resolved differently than
> framed — see the note under it. Kept because §2 is what Phase C1's items
> refer back to.

**The repo existed and was empty.**

```
packages/pss-corpus/     # ivpm checkout, commit f9f6bd5 "Initial commit"
├── .gitignore           # GitHub Python template, verbatim
├── LICENSE              # Apache 2.0
└── README.md            # one line
```

**`pssfmt` already declares the dependency** (`ivpm.yaml`, `default-dev`), and
`tests/support.py` already resolves `packages/pss-corpus` ahead of the sibling
fallback. So the moment the repo has content, `pssfmt` picks it up with **no
code change** — that was the point of writing the resolver that way.

**Two things about the declaration need settling before anyone copies it**
(`C-2`):

- **URL convention differs between repos.** `pssfmt/ivpm.yaml` uses
  `https://github.com/psstools/…`; `pygments-pss/ivpm.yaml` uses
  `https://git.dvkit.org/psstools/…`. Both resolve today. They should not both
  be written down.

  > **Resolved 2026-08-26: `github.com`, per repo.** Probing the four URLs
  > reframed this. `pssparser` and `sphinx-pss` resolve on *both* forges, so
  > this is a convention choice, not an availability one: `git.dvkit.org` is
  > upstream (Forgejo) and `github.com` is its mirror. Prefer the mirror in
  > `ivpm.yaml`, because a dependency URL must be fetchable by a CI runner with
  > no access to the self-hosted instance, and prefer *per-repo consistency*
  > over a project-wide edict — `pssfmt`'s other two deps already name
  > `github.com`, `pygments-pss`'s already name `git.dvkit.org`, and neither is
  > wrong.
  >
  > **One gate:** `pss-corpus` was created on Forgejo and is not mirrored to
  > GitHub yet, so `https://github.com/psstools/pss-corpus.git` does **not**
  > resolve at the time of writing. `pssfmt/ivpm.yaml` names it anyway, which
  > is correct-in-advance rather than broken-now only because the mirror is in
  > flight. `C-2a` is the check that it landed. Note that a working copy hides
  > this completely: the checkout here was placed by hand.
- **No `type: raw`.** `pss-corpus` is data — nothing to build, nothing to
  install. `pygments-pss` marks its source-only `pssparser` dependency
  `type: raw` for exactly this reason. It works without it; it does not *say*
  anything without it.

**The `.gitignore` is a live hazard** (`C-3`). It is the GitHub Python
template, which ignores directories by name: `lib/`, `build/`, `dist/`,
`var/`, `parts/`, `env/`, `target/`, `instance/`, `sdist/`, `wheels/` and —
the one that matters — **`cover/`**. "Cover" is ordinary PSS vocabulary; a
`cover/` bucket for coverage constructs is a natural thing to add, and it
would be silently ignored on `git add`. A corpus repo has no business carrying
a Python build template.

---

## 3. What "the corpus" is

### 3.1 Curated — 92 files, ready to move

`pygments-pss/tests/corpus/`, already bucketed and already carrying a
`PROVENANCE.md` that records source and commit per bucket.

| Bucket | Files | Source | Contributes |
|---|---|---|---|
| `example2/` | 39 | `psstools/example` — `2/src/pss/` | Hand-written idiomatic PSS |
| `peakrdl/` | 25 | `psstools/peakrdl-pss` — `tests/golden/expect/` | Machine-generated register-model idioms |
| `language-ref/` | 9 | `psstools/pss-skills` — LRM examples | Feature-targeted, written against the LRM |
| `pathological/` | 7 | authored there | Deliberately broken input |
| `stdlib/` | 5 | `zuspec/zuspec-fe-pss` — `src/stdlib/` | The PSS core library |
| `lexical/` | 4 | authored there | Clause 4 lexical torture |
| `pss31/` | 3 | authored there | PSS 3.1-only surface |

This set is **not a lowest-common-denominator selection**. `pathological/` and
`lexical/` are worth more to a formatter than to a highlighter, and `pss31/` is
worth more to a parser than to either — it is where three of the five `U-8`
gaps live. Each consumer's most valuable bucket was contributed for a different
consumer's reasons, which is the argument for one shared corpus stated as a
fact rather than as a principle.

### 3.2 Breadth — ~265 files, needs triage first

| Source | Files | Note |
|---|---|---|
| `sav/pssc` | 168 | Archive directory; unknown how much is valid PSS |
| `sav/pssparser-linter` | 11 | Archive |
| `sav/pssparser` | 5 | Archive |
| `sav/pss-sv-if` | 1 | Archive |
| `example/2` | 40 | Superset of curated `example2/`; needs diffing, not re-vendoring |
| `example/1` | 4 | Older revision of the same material |
| `peakrdl-pss` | 36 | Superset of curated `peakrdl/` |

`formatter.md` §7.8's open question — *"how much of `sav/` is real?"* — is
unanswered and is a genuine unit of work: triage into *parses cleanly* /
*known-bad*, where the known-bad set has its own value as parser regression
material. **This does not block anything.** Curated moves first (`C-4`);
breadth is Phase C5, sequenced after adoption, and may never happen without
costing anyone anything.

### 3.3 Explicitly out of scope

`pssparser/src/stdlib/*.pss` (4 files) are **shipped product source**, not test
data. They are already represented in the corpus via `stdlib/` (5 files
vendored from `zuspec-fe-pss`). Do not move, symlink, or deduplicate them; a
consumer that wants the shipped copies has `pssparser.get_stdlib_files()`.

---

## 4. Target layout

```
pss-corpus/
├── README.md
├── LICENSE                # Apache 2.0, and the only licence (§5.4)
├── PROVENANCE.md          # C-5/C-5a — source + commit + licence, per bucket
├── manifest.toml          # C-6 — machine-readable bucket policy (see CQ-1)
│                          # REUSE.toml + LICENSES/ appear here only if a
│                          # second licence ever does (§5.4) — not now
├── curated/
│   ├── example2/  peakrdl/  language-ref/
│   ├── pathological/  stdlib/  lexical/  pss31/
└── breadth/               # Phase C5, later; absent until then
```

**Why `curated/` and `breadth/` are separate top-level directories** rather
than sibling buckets: they carry different promises. Every curated file has
recorded provenance and a bucket-level expectation; breadth files are bulk
input whose validity is unknown until triaged. A consumer must be able to sweep
one without the other with a path, not with a filter it maintains itself.

**Why bucket names are preserved verbatim** from `pygments-pss`: those names
are already written into `PROVENANCE.md`, into `PATHOLOGICAL_DIRS`, into
`pssfmt`'s `BROKEN_BUCKETS` and `KNOWN_UNPARSEABLE` keys, and into six xfail
reasons. Renaming buys nothing and invalidates all of it.

---

## 5. The consumer contract

The part worth agreeing before anyone adopts.

### 5.1 Discovery

Every consumer answers "where is the corpus?" the same way, in this order:

1. `$PSS_CORPUS` — an explicit path, for a developer pointing at a working copy
2. `<repo>/packages/pss-corpus` — the ivpm dependency; the normal answer
3. a sibling checkout — the fallback that keeps a bare working tree usable

`pssfmt` already implements exactly this (`tests/support.py`) under the name
`PSSFMT_CORPUS`. **Rename to `PSS_CORPUS`** (`C-7`): the variable names the
corpus, not the consumer, and three tools each honouring a differently-spelled
variable is precisely the divergence this project exists to stop.

This is ~20 lines per consumer and should be **duplicated, not shared**. A
`pss-corpus-py` package to hold one path search would add a build, a release
cadence and a version-skew failure mode to a repo whose entire value is that it
has none of those.

### 5.2 Absent means fail, not skip

A consumer whose corpus is missing must **fail loudly**. `pygments-pss` already
asserts this (*"corpus is empty — tests/corpus/ should be vendored, not
generated"*). `pssfmt` currently *skips*, which is the whole reason milestone
M3 is 🔶: a gate that skips in CI is not a gate.

One nuance that must survive the change (`C-8`): `pssfmt`'s corpus tests must
still **skip** when `pssparser` is absent, because `T-2` requires the layout
suite to collect without it. *Corpus missing* and *parser missing* are
different conditions and must not collapse into one `skipif`.

### 5.3 What the manifest carries — and what it must not

`manifest.toml` records facts about **the files**:

```toml
[bucket.pathological]
parses = false          # not valid PSS, by design
description = "Deliberately broken input"

[bucket.lexical]
parses = true
description = "Clause 4 lexical torture"
```

It must **not** record facts about a consumer's current bugs. `pssfmt`'s
`KNOWN_UNPARSEABLE` — six corpus files that fail because of the `U-8` gaps —
stays in `pssfmt`, because those entries describe *`pssparser` today*, not the
corpus. Moving them would mean a `pssparser` fix requires a commit to the
corpus repo, and would quietly turn a shared data repo into a place where one
consumer records its defects. See `CQ-1`; this is the decision most likely to
be got wrong in the direction of doing too much.

### 5.4 Licensing

**Policy: one Apache 2.0 licence for the whole repository.** Everything
vendored so far is Apache 2.0, and keeping it that way is a deliberate
acceptance criterion for new material, not merely a description of the current
state.

The corpus is unusually well placed to hold that line, because a corpus file is
*test input* rather than a component: if a candidate file cannot be taken under
Apache 2.0, the near-always-correct answer is **do not vendor it** — write an
equivalent, as `pss31/`, `lexical/` and `pathological/` already were. The cost
of declining a file here is a few hours of authoring, which is far below the
cost of a mixed-licence data repository that three projects depend on.

**Fallback, for when that is not possible.** Per-file licensing is documented
and ready rather than built, because building it before it is needed invites
its use:

- Record the divergence in `PROVENANCE.md` — the bucket table already carries
  source and commit, so a licence column (`C-5a`) is the natural place, and it
  is where a reader already looks.
- Where a licence applies to specific *files* rather than a whole bucket, add a
  `REUSE.toml` (the REUSE specification's mechanism for exactly this case:
  declaring licences for files that cannot carry a header) with path globs
  mapping to SPDX identifiers, plus a `LICENSES/` directory holding the licence
  texts. Standard, tool-checkable, and inert until a second licence exists.
- Keep the divergent material in **its own bucket**. A bucket is the smallest
  unit consumers already reason about, and a mixed-licence bucket is the shape
  that makes every later question hard.

> **SPDX headers must not go in the corpus files themselves.** No corpus file
> currently carries any copyright or SPDX text, and adding one would edit
> vendored input that `PROVENANCE.md` declares frozen — the same rule that
> forbids reformatting them. It would also silently change what the consumers
> are testing: `pssfmt`'s round-trip gate, `pygments-pss`'s no-`Error` sweep
> and `pssparser`'s parse sweep all read these bytes. Licence metadata lives
> *beside* the files, never inside them. This is the whole reason `REUSE.toml`
> exists and the reason to prefer it over the obvious alternative.

**One loose end in the current material** (`C-5b`): `psstools/example`, the
source of the 39-file `example2/` bucket, is a plain working directory with no
LICENSE file — it is not even a git checkout, so `PROVENANCE.md` already
records it as *"working tree, not a git checkout"* with no commit hash. The
material is Apache 2.0 by intent; the fix is to add a LICENSE to that source so
the provenance record can cite one, rather than to assert a licence in the
corpus that the source does not state.

---

## 6. Work items

### Phase C1 — Seed  (~half a day)  ✅ 2026-08-26

- [x] **`C-1`** — Move this file to `pss-corpus/PLAN.md`, and leave a one-line
      pointer in `pssfmt/PLAN.md` `Q-3`. First, not last.
      *Done. The pointer says the plan is deliberately not mirrored back. Also
      removed `pssfmt/docs/design/corpus_plan.md` and its toctree entry — that
      stub `{include}`d this file by relative path, so it could not survive the
      move, and a docs build with `-W` would have caught it if the toctree entry
      had been left behind.*
- [x] **`C-2`** — Settle the ivpm declaration (§2) and write it once:
      `git.dvkit.org` or `github.com`, and `type: raw`. Apply to
      `pssfmt/ivpm.yaml`; it becomes the template every other consumer copies.
      *Done: `type: raw` added, `github.com` kept. The URL half resolved
      differently than framed — see §2. Not "write it once" but "write it once
      per repo": both forges serve the other deps, so this is convention, and
      the two repos already have opposite, defensible conventions.*
- [~] **`C-2a`** — *(new)* Confirm `https://github.com/psstools/pss-corpus.git`
      resolves once the Forgejo→GitHub mirror lands, then run a **clean**
      `ivpm update` — not one in this working copy, whose `packages/pss-corpus`
      was placed by hand and would mask a broken URL entirely.
      *Checked 2026-08-26: still `repository not found`. The upstream is live
      and anonymously cloneable (`git clone https://git.dvkit.org/…` returns 92
      files at `8bc3403`), so this is purely the mirror. Blocked, not failing:
      the consequence is that a fresh `pssfmt` checkout cannot resolve a corpus,
      which `C-9a` now makes say so in as many words.*
- [x] **`C-9a`** — *(new, found while committing)* Answer the CI consequence of
      `C-8` in both consumers. Fail-rather-than-skip is only half a design: the
      other half is that every runner which was quietly getting away with no
      corpus now has to be given one, or it goes red for a reason that reads
      like a test bug.
      *Found by reading the workflows before pushing, not by watching a build
      fail. Two distinct shapes:*
      *`pygments-pss` — the test matrix deliberately skips `ivpm update` (the
      drift guard has its own job), so all twelve legs would have failed at
      collection. Fixed with a direct clone, which keeps the property the matrix
      was shaped around: test data has nothing to build, so resolving a graph to
      fetch it reintroduces exactly the cost that structure avoids. Verified
      both ways against a fresh checkout with no sibling to fall back on — 374
      passed with the step, collection error without it.*
      *`pssfmt` — same trap, but its `ivpm.yaml` names the mirror that `C-2a`
      says does not exist. So the step is written to fail **loudly and by
      name**: it prints that this is `C-2a` and not a fault in the workflow.
      Executed the extracted step to confirm the message renders as intended.
      A latent trap either way, since `pssfmt`'s CI has never run — but latent
      traps are cheapest to fix while you are already looking at them.*
      *Also dropped `--depth 1`: the transport in front of `git.dvkit.org` can
      fall back to dumb http, which has no shallow capability and errors out
      rather than degrading. Whole history is 324K.*
- [x] **`C-9b`** — *(new, found during `C-18`)* Two more instances of the same
      lesson, which is now the most productive single idea in this plan: **a
      check that passes only because its input is missing is not a check.**
      *`pssparser`'s CI — third repo, third shape. Both workflows run
      `ivpm update` against the `default` set, and `C-17` deliberately puts the
      corpus in `default-dev`, so neither would have fetched it. Direct clone
      again, placed after the dependency step so a corpus under `packages/`
      cannot be mistaken for a dependency by that job's origin check. Both
      workflows clone `git.dvkit.org`, including the GitHub one — between
      depending on a public forge that works today and a mirror that 404s
      (`C-2a`), the choice is not close. One-line switch when the mirror lands;
      `ivpm.yaml` already names it.*
      *`pssfmt`'s `tomllib` import — the sharper one, and self-inflicted.
      `tests/support.py` reads `manifest.toml` with `tomllib`, which is stdlib
      only from 3.11; `pssfmt` supports 3.9 and its CI matrix runs 3.9 and
      3.10. Those legs passed because `CORPUS_REPO` was `None` with no corpus,
      so the import was never reached — meaning `C-9a`, the fix that made CI
      fetch the corpus, is what would have turned them red. The same shape as
      the skip `C-8` removed, one level down: correct-looking behaviour resting
      on an absence. Fixed with a `tomli` fallback and a marked test extra;
      marker evaluated for 3.9–3.12 and the fallback branch exercised directly
      by hiding `tomllib` from the import system.*
- [x] **`C-3`** — Replace `.gitignore` with something a data repo wants — `.DS_Store`,
      `__pycache__/`, editor droppings. Nothing that ignores a directory by a
      name a PSS bucket might use. Verify with
      `git check-ignore -v curated/cover/x.pss` returning nothing.
      *Done; checked across 18 names — the 10 the template ignored plus all 7
      real bucket names. The reasoning is in the file's own header, where
      someone about to paste the template back will read it.*
- [x] **`C-4`** — Copy `pygments-pss/tests/corpus/{example2,peakrdl,language-ref,pathological,stdlib,lexical,pss31}`
      to `curated/`. **Byte-for-byte** — no reformatting, no line-ending
      normalisation, no "while I'm here". Verify with a checksum comparison
      against the source tree, not by eye.
      *Done: 92 files, sha256 manifests of source and destination diffed clean,
      so paths and contents both match. `cp -a`, so no mode or mtime drift.*
- [x] **`C-5`** — `PROVENANCE.md`: carry the existing table forward and keep
      the frozen-input paragraph verbatim — *"do not reformat them, do not
      'fix' their PSS, and re-vendor only deliberately"*. Keep the note that
      remote URLs are written as `git.dvkit.org` paths.
      *Done. Dropped the old opening sentence — *"vendored, not
      path-referenced, so the suite runs standalone"* — because it argued for
      the arrangement this project replaces; `C-16` records that supersession
      where it belongs, in `pygments-pss`. Added the reason the frozen-input
      rule bites: several suites read these exact bytes and none goes red on an
      edit.*
- [x] **`C-5a`** — Add a **licence column** to that table, `Apache-2.0` for
      every current bucket (§5.4), and a one-paragraph statement of the
      single-licence policy above it: new material is Apache 2.0 or it is not
      vendored. State it as an acceptance criterion, since that is the only
      form of it that survives contact with a tempting file.
      *Done, with one deviation: the column distinguishes **verified** (source
      LICENSE read, or authored here) from **stated** (upstream not checked out
      — `stdlib/`, `language-ref/`) and from **stated, source carries no
      LICENSE** (`example2/`, per `C-5b`). A licence table that cannot be told
      apart from an assumption is worth less than one that admits which rows
      were checked.*
- [ ] **`C-5b`** — Add a LICENSE to `psstools/example` so `example2/`'s
      provenance can cite a source licence rather than an intent. Small, in
      someone else's repo, and the only currently-open licence loose end.
      Not a blocker for `C-4`. *Confirmed on disk: no `LICENSE`, and not a git
      checkout. `peakrdl-pss`'s Apache 2.0 was verified at the same time.*
- [x] **`C-6`** — `manifest.toml` per §5.3, one entry per bucket. Pending
      `CQ-1`; if `CQ-1` resolves against it, this item becomes "document the
      bucket policy in `PROVENANCE.md` prose" instead.
      *Done on `CQ-1`'s recommendation (minimal). Verified it parses, covers
      exactly the seven buckets on disk, and carries no field beyond `parses`
      and `description`. The §5.3 boundary is in its header, with a usable test
      for a proposed field: would it still be true if every consumer were
      deleted?*

**Exit:** `pss-corpus` holds 92 files with recorded provenance, and
`git status` in a fresh clone is clean.

> **Met 2026-08-26**, except that `C-2a` cannot be checked until the mirror
> lands. Nothing downstream waits on it: Phase C2 works against the checkout.

### Phase C2 — Adopt `pssfmt`  (~1 hour)  ✅ 2026-08-26

The cheapest consumer, because the resolver was written for this.

- [x] **`C-7`** — Rename `PSSFMT_CORPUS` → `PSS_CORPUS` in
      `tests/support.py`, and update the docstring's search order to name
      `curated/` explicitly.
      *Done, with a trap the item did not ask for: setting `PSSFMT_CORPUS`
      without `PSS_CORPUS` now raises and says what to do. Silently ignoring an
      environment variable someone deliberately exported would sweep the wrong
      tree and report success — the same failure class as `C-8`'s skipping
      gate, and not worth leaving open to save four lines.*
- [x] **`C-8`** — Turn corpus-absent from *skip* into *fail*, keeping the
      pssparser-absent skip intact (§5.2). This is the change that makes M3
      real.
      *Done. Note the subtlety: deleting the `skipif` is not sufficient, because
      every other test in the file is parametrized over `FILES` and an empty
      corpus makes them all collect zero cases and pass. The failure has to live
      in a test that cannot vanish with its input —
      `test_the_corpus_is_present`. Both conditions verified by hiding the
      relevant thing: corpus hidden → 3 failures; `pssparser` hidden → 293
      passed, 10 skipped, `T-2` intact.*
- [x] **`C-9`** — Point `BROKEN_BUCKETS` at the manifest rather than at a
      hardcoded tuple, if `C-6` lands. Leave `KNOWN_UNPARSEABLE` where it is.
      *Done; `KNOWN_UNPARSEABLE` left in `pssfmt`, per §5.3. The hardcoded tuple
      survives as `FALLBACK_BROKEN_BUCKETS` for a corpus with no manifest (a
      bare `$PSS_CORPUS`, or the pre-`C-15` `pygments-pss` layout), pinned to
      the manifest by a test so it cannot rot in the one configuration nobody
      runs.*
- [x] **`C-10`** — Verify: 462 corpus tests still pass, and pass with
      `packages/pygments-pss` renamed away, proving the sibling fallback is no
      longer what is being used.
      *Done — 465 cases, not 462 (three new tests: corpus-present,
      manifest-agrees-with-fallback, broken-bucket-exists). Green with **both**
      `pygments-pss` copies hidden; renaming only the `packages/` one would have
      left the sibling fallback able to answer.*
- [x] **`C-11`** — Update `pssfmt/PLAN.md`: close `Q-3`, tick `T-4`/`T-5`,
      promote M3 🔶 → ✅.
      *Done except the last clause, which was wrong. `Q-3` closed and `T-4`
      ticked, but **M3 stays 🔶** and `T-5` stays `[~]`: `pssfmt`'s `ci.yml`
      installs no `pssparser`, so the suite skips in CI whether or not a corpus
      is present. `Q-3` was never the only blocker — it was the only visible
      one. `Q-9` is the live one.*

**Exit:** M3's gate runs in CI against a declared dependency.

> **Half met, 2026-08-26.** *Against a declared dependency*: yes, and
> absent-corpus now fails. *Runs in CI*: no, and not for a corpus reason. This
> exit criterion silently assumed the corpus was the last thing missing, which
> is the same assumption `pssfmt`'s M3 note made. Kept unticked rather than
> reworded — an exit criterion that is edited to match what was achieved stops
> being one. **CM2 does not close until `pssfmt` `Q-9` does.**

### Phase C3 — Adopt `pygments-pss`  (~2 hours)  ✅ 2026-08-26

The donor repo, and the only migration that deletes anything.

- [x] **`C-12`** — Add the `pss-corpus` dev dependency to
      `pygments-pss/ivpm.yaml`, using the `C-2` template.
      *Done, naming `git.dvkit.org` — `C-2` settled the convention as per-repo,
      and this repo's other dependency already names the upstream.*
- [x] **`C-13`** — Repoint `tests/conftest.py`: `CORPUS` becomes the discovery
      function from §5.1 rather than `Path(__file__).parent / "corpus"`.
      `corpus_files()`, `corpus_id()` and `PATHOLOGICAL_DIRS` keep their
      signatures, so no test module changes.
      *Held exactly: the four names other modules import are unchanged, so no
      test module needed editing for the move. `PATHOLOGICAL_DIRS` now derives
      from `manifest.toml` with the literal kept as a pinned fallback, matching
      `C-9`.*
- [x] **`C-14`** — Run the suite and diff the collected test IDs against the
      pre-migration list. **Identical, or the migration lost files.** `corpus_id`
      is relative to the corpus root, so the extra `curated/` component will
      shift every ID — decide whether to strip it in `corpus_id` or to accept
      the churn, and *check* rather than assume.
      *Decided by precedent rather than freshly: point `CORPUS` at the **sweep
      root** (`<repo>/curated`), which is what `pssfmt` does, so `curated/`
      never enters an ID and neither option was needed. Baseline captured
      before touching anything — **378 IDs, identical after**, same
      376-passed/2-error result.*
- [x] **`C-15`** — Delete `pygments-pss/tests/corpus/`. Not "later" — the same
      commit. A migration that leaves the old copy has doubled the drift it set
      out to remove.
      *Done, `git rm`, staged. Two preconditions checked first rather than
      assumed: the 93 files are committed at `0e11de7` so the deletion is
      recoverable, and the 92 `.pss` are sha256-identical to `curated/`. A
      guard test now asserts `tests/corpus/` does **not** exist, so the copy
      cannot quietly come back and be preferred.*
- [x] **`C-16`** — Update `pygments-pss`'s `DESIGN.md` §8.1, which currently
      argues *for* vendoring (*"so the suite runs standalone"*). That argument
      was right and is now superseded; record why, rather than deleting it.
      *Done as a superseded-note under the original text. Also fixed three
      other references that had gone stale and would have misdirected a reader:
      the `corpus` marker description in `pyproject.toml`, the `_builtins.py`
      docstring citing `tests/corpus/stdlib/`, and the tree diagram in
      `DESIGN.md` §4.*

**Exit:** one copy of the corpus exists in the project. **Met 2026-08-26** —
`pygments-pss` 378 passed against the shared corpus, `pssfmt` 950 passed, and
corpus-absent is a hard error in both.

### Phase C4 — Adopt `pssparser`  (~half a day)

The point of the exercise. New capability, not a migration.

- [x] **`C-17`** — Add `pss-corpus` to `pssparser/ivpm.yaml` under
      `default-dev` only. No cycle: the corpus depends on nothing.
      **Done** — `type: raw`, `default-dev` only, verified absent from
      `default`. Resolves `CQ-3` as recommended: pssparser depends on the
      corpus the way it depends on gtest, as a developer and never as a
      package. URL names the GitHub mirror, matching every other source
      dependency in that file; the Forgejo CI remaps `psstools/` already.
- [x] **`C-18`** — A corpus sweep in `pssparser/tests/`: every `curated/` file
      outside `pathological/` parses with zero syntax errors; every
      `pathological/` file fails to parse *without crashing*. Expect it to be
      **red on arrival** — the five `U-8` gaps are exactly what it will find.
      **Done** — `tests/python/corpus/test_pss_corpus.py`, 104 cases, ~7s.
      97 passed / 7 xfailed. Two decisions worth recording:
      - **`--syntax-only`.** Linking the corpus fails on 53 of 92 files, all
        of it unresolved-name noise: most of the corpus is single files lifted
        out of multi-file models, and `example2/` is one model in 35 pieces.
        The sweep asks whether the parser can *read* PSS 3.1 surface. Whole-
        model linking is already covered by the neighbouring `test_corpus.py`.
      - **Crash-freedom is asserted in its own unmarked test**, split out from
        the rejection check. Folding them together would have put crash-
        freedom under `U-9`'s xfail — no recorded defect is a reason to accept
        a signal.
- [x] **`C-19`** — Mark the `U-8` failures `xfail(strict=True)` with the same
      cause strings `pssfmt` uses, so one fix flips both repos' markers and
      neither can drift green unnoticed.
      **Done**, and the sweep reproduced `pssfmt`'s `KNOWN_UNPARSEABLE`
      exactly — same six files, same five identifiers, independently derived.
      It also needed a *second* table, `KNOWN_ACCEPTED`, for the inverse
      defect: **`U-9`**, broken input the front end accepts. See the header
      note. `U-9` is minted here rather than folded into `U-8` because the two
      fail opposite promises — `U-8` is a grammar too narrow, `U-9` is a front
      end that is unsound — and a fix for one says nothing about the other.
- [x] **`C-20`** — Cross-reference: `pssfmt`'s `tests/corpus/test_parser_gaps.py`
      and `pssparser`'s new sweep must name the same `U-8a`…`U-8e` identifiers.
      **Done**, three tests in `pssfmt` (which is the only repo that can see
      both). Vocabulary in each direction, plus the stronger check: the two
      file→cause tables must be *equal*, not merely compatible. Read out of
      the source with `ast`, not imported — importing would run pssparser's
      corpus discovery inside pssfmt's process to compare two dicts of
      strings. Mutation-checked: changing one cause string in `pssparser`
      turns the pssfmt test red, naming the file.

**Exit:** a `pssparser` grammar change that breaks PSS 3.1 surface fails a
`pssparser` test, in `pssparser`, before it reaches a consumer. **Met
2026-08-26**, in both CI workflows.

### Phase C5 — Breadth  (unsequenced, unowned)

- [ ] **`C-21`** — Triage `sav/` (185 files) into *parses cleanly* /
      *known-bad*. Answers `formatter.md` §7.8's first bullet.
- [ ] **`C-22`** — Diff `example/2` (40) against curated `example2/` (39) and
      `peakrdl-pss` (36) against curated `peakrdl/` (25); vendor only what is
      genuinely new.
- [ ] **`C-23`** — Land as `breadth/`, with provenance, and wire it into
      consumers as an **opt-in** sweep (`-m breadth`) — it is bulk material and
      should not slow the per-PR gate.

---

## 7. Open questions

- [x] **`CQ-1` — Machine-readable manifest, or prose?** **Resolved 2026-08-26:**
  built, minimal, as recommended — `manifest.toml` with `parses` and
  `description` and nothing else. `C-9` (pointing `pssfmt`'s `BROKEN_BUCKETS`
  at it) is now live rather than conditional. Original text follows.

  > **Machine-readable manifest, or prose?**
  > A `manifest.toml` (§5.3) turns three hardcoded bucket lists into one shared
  > fact. Against: today those lists are one line each
  > (`PATHOLOGICAL_DIRS = {"pathological"}`), so the manifest adds a parser and a
  > schema to save two lines, and every consumer grows a TOML read.
  > **Recommendation: yes, minimal** — bucket name, `parses`, one-line
  > description, nothing else. The value is not the two lines; it is that a new
  > bucket arrives with its policy attached instead of requiring a matching
  > commit in three repos. **Hard boundary: no consumer-specific data in it**
  > (§5.3). Blocks: `C-6`, `C-9`.

- [x] **`CQ-2` — Redistribution licensing.** **Resolved 2026-08-26:** one
  Apache 2.0 licence for the whole repository, with per-file licensing as the
  documented fallback for material that cannot be taken under it. Everything
  vendored so far *is* Apache 2.0, so the fallback is unexercised. See §5.4 for
  the policy and the mechanism. Residual work is `C-5a`/`C-5b`; nothing blocks
  `C-4`. Original text follows.

  > The curated set vendors files from four upstreams. `psstools/peakrdl-pss`
  > is Apache 2.0 ✓. `psstools/example` carries **no LICENSE file**.
  > `zuspec/zuspec-fe-pss` and `psstools/pss-skills` are not checked out here
  > and were not verified. `pss-corpus` itself is Apache 2.0, which does not by
  > itself grant the right to redistribute someone else's files under it.
  > **Needed before the repo is pushed anywhere public**; irrelevant while it
  > is internal. Deliverable is the license column in `C-5`. Blocks:
  > publishing, not `C-4`.

- [x] **`CQ-3` — Does `pssparser` take a dependency on test data at all?**
  **Resolved 2026-08-26:** yes, as recommended — `default-dev` only,
  `type: raw`, verified absent from `default`, so no released wheel carries it.
  The case for it stopped being hypothetical within an hour: the sweep found
  `U-9`, a defect no consumer had found in the time the corpus has existed.
  Original text follows.

  > `C-17` adds a dev dependency to the lowest repo in the stack. The
  > alternative is that `pssfmt` keeps being the only place PSS 3.1 surface is
  > exercised, which is how `U-8` went unnoticed. **Recommendation: yes** —
  > `default-dev` only, `type: raw`, so no released artefact carries it.

- [ ] **`CQ-4` — Who owns re-vendoring?**
  `PROVENANCE.md` records commits, so the corpus can go stale against its
  upstreams silently. Options: (a) nobody, re-vendor on demand — honest, and
  what happens anyway; (b) a script that reports drift against recorded
  commits. **Recommendation: (a) for now**, and revisit if a bucket is ever
  found stale in a way that mattered.

---

## 8. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| CR1 | **Migration silently drops files.** 92 files across three repos, moved by hand | The oracle weakens without any test going red — the exact failure mode `pssfmt` `R8` describes | `C-4` verifies by checksum, `C-14` diffs collected test IDs before and after. Neither is "look at it" |
| CR2 | **The `.gitignore` swallows a bucket.** `cover/`, `lib/`, `build/`, `target/` are all ignored today | A future bucket is invisible to `git add`; nobody notices until a sweep is mysteriously small | `C-3`, with `git check-ignore` as the check rather than inspection |
| CR3 | **Adoption before the contract.** A consumer migrates and encodes its own discovery order and its own bucket policy | Exactly the divergence this project exists to remove, re-created during the removal | §5 is agreed before Phase C2. `pssfmt` goes first *because* it is cheapest, so the contract is exercised before the expensive migrations |
| CR4 | **The old copy survives.** `pygments-pss/tests/corpus/` left in place "until the migration settles" | Two corpora, one of them stale, and the drift is now sanctioned | `C-15` is in the same commit as `C-13`, not a follow-up |
| CR5 | **The corpus gets reformatted.** By a dogfooding run, an editor-on-save, or a well-meaning fix to a `pathological/` file | Frozen input stops being frozen; `pathological/` is the bucket most likely to look "broken" to someone who does not know why it exists | `PROVENANCE.md`'s frozen-input paragraph carried verbatim (`C-5`); `pssfmt`'s `X-5` dogfooding must exclude `packages/` |
| CR6 | **`CQ-1` over-builds.** The manifest grows consumer-specific fields until it is a config file three repos fight over | A shared data repo becomes a coupling point | The §5.3 boundary is written into the manifest's own header comment, not just into this plan |
| CR7 | **Mixed-licence creep.** One valuable file arrives under a different licence, is vendored "just this once", and the repo quietly becomes multi-licence | Three dependent projects inherit a licence question nobody can answer from the repo root; auditing it later means auditing 92+ files | §5.4 states the policy as an *acceptance criterion*: Apache 2.0 or do not vendor. For a corpus the alternative is cheap — author an equivalent, as `pss31/`, `lexical/` and `pathological/` already were. `C-5a` writes the criterion into `PROVENANCE.md`, where a contributor is already looking |
| CR8 | **SPDX headers added to the corpus files themselves**, by a contributor doing the normally-correct thing | Edits frozen vendored input, and silently changes what all three consumers are testing — the round-trip gate reads these exact bytes | §5.4's boxed note, repeated in `PROVENANCE.md` alongside the frozen-input paragraph. If per-file licensing is ever needed it goes in `REUSE.toml`, which exists precisely for files that cannot carry a header |

---

## 9. Milestones

| M | Name | Gate | Items |
|---|---|---|---|
| CM1 | ✅ **Seeded** *(2026-08-26)* | `pss-corpus` holds 92 files with provenance; fresh clone is clean | `C-1`–`C-6` |
| CM2 | 🔶 **M3 real** *(2026-08-26)* | `pssfmt`'s corpus gate runs against the dependency and *fails* when it is absent — both true; still skips in CI for want of `pssparser` (`pssfmt` `Q-9`), which is not a corpus problem | `C-7`–`C-11` |
| CM3 | ✅ **One copy** *(2026-08-26)* | `pygments-pss/tests/corpus/` deleted; suite green on the same file set — 378 IDs, unchanged | `C-12`–`C-16` |
| CM4 | ✅ **Parser guarded** *(2026-08-26)* | `pssparser` sweeps the corpus in both CI workflows — 104 cases, 97 passed / 7 xfailed; `U-8` is red-by-marker in the repo that owns the fix, and the sweep found `U-9` | `C-17`–`C-20` |
| CM5 | Breadth | `breadth/` triaged and opt-in | `C-21`–`C-23` |

**CM2 is the one with a deadline attached**, because `pssfmt`'s M3 is blocked
on it and M3 is the milestone after which style work becomes reversible.

CM4 was written as "no deadline, but where the value is, so do not let it wait
indefinitely." It found a live soundness defect on its first run. Read that as
evidence about the *class* rather than about `U-9`: the gates worth building
are the ones that ask a question nothing else in the stack asks, and their
value shows up immediately or not at all.

---

## 10. Traceability

| `pssfmt/PLAN.md` | Here |
|---|---|
| `Q-3` — corpus placement | this plan; closed by `C-11` |
| `T-4` — corpus wiring | `C-7`–`C-9` |
| `T-5` — corpus gate in CI | `C-8`, `C-10` |
| `R8` — corpus drift | `CR1`, `CR4`, `CR5` |
| `U-8` — pssparser gaps | `C-18`–`C-20`; the reason Phase C4 exists |
| `U-9` — lexical errors miss the exit status | found by `C-18`; recorded in both repos, fixed in neither |
| `M3` — proof of safety | `CM2` |
| `X-5` — dogfooding | `CR5` |
| `formatter.md` §7.8 | §3.2, `C-21`, `CQ-4` |
