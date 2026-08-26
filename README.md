# pss-corpus

A shared corpus of PSS source files, used as test input by several projects.

There is nothing to build and nothing to install. This repository is data.

```
curated/        92 files in 7 buckets, each with recorded provenance
├── example2/       39  hand-written idiomatic PSS
├── peakrdl/        25  machine-generated register-model idioms
├── language-ref/    9  feature-targeted, written against the LRM
├── pathological/    7  deliberately broken input
├── stdlib/          5  the PSS core library
├── lexical/         4  Clause 4 lexical torture
└── pss31/           3  PSS 3.1-only surface
```

`PROVENANCE.md` records where each bucket came from and under what licence.
`manifest.toml` records what each bucket promises — chiefly whether it is
expected to parse. `pathological/` is the one that is not.

## Using it

Take a dev dependency (ivpm, `type: raw` — there is nothing to build), then
find the corpus in this order:

1. `$PSS_CORPUS` — an explicit path, for a developer pointing at a working copy
2. `<repo>/packages/pss-corpus` — the declared dependency; the normal answer
3. a sibling checkout — the fallback that keeps a bare working tree usable

**Duplicate that search; do not share it.** It is about twenty lines. A Python
package to hold one path lookup would add a build, a release cadence and a
version-skew failure mode to a repository whose whole value is having none of
those.

**A missing corpus should fail your suite, not skip it.** A gate that skips
when its input is absent is not a gate — it is a gate that reports success in
exactly the circumstance it was built to catch.

## The rule that matters

These files are **frozen test input**: do not reformat them, do not "fix" their
PSS, and re-vendor only deliberately.

Several consumers read these exact bytes, so an edit here changes what their
suites are testing without any of them going red to say so. That includes
adding SPDX or copyright headers, however well-intentioned — see
`PROVENANCE.md`.

## Contributing a bucket

New material is Apache 2.0 or it is not vendored (`PROVENANCE.md`). Add the
files, add a row to `PROVENANCE.md` with source, commit and licence, and add an
entry to `manifest.toml`. Then check that the bucket name is not being silently
ignored:

```sh
git check-ignore -v curated/<name>/x.pss   # must print nothing
```

`PLAN.md` tracks the collection and adoption work.
