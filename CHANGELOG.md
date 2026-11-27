# Changelog

Notable changes to `commissura`, newest first. Versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Four other version numbers travel inside the output and move independently of
this one, because a consumer needs to know which of them changed:
`.deident/manifest.json` and `.deident/risk_report.json` each declare their own
schema version, the dataset layout declares a third, and the de-identification
rules declare a fourth. A release that moves any of them says so below.

## 0.1.6 — 2026-11-27

Documentation only. `src/` is byte for byte what 0.1.5 shipped, so nothing an
installation does is different. This release exists because three sentences in
the README were **wrong**, not merely improvable, and a long description is
frozen into the artefact that carried it: the page on the index keeps whatever
the last upload said until a new one replaces it.

### Fixed

- **"Twenty-one of twenty-five participants are unique on age and sex
  together" misread the block printed directly above it, twice.** That block
  reads `below k=5  21 combination(s)`: twenty-one counts combinations of
  attribute values, and several participants can share one, so it is not a
  count of people. And `below k=5` includes k=2, k=3 and k=4, where "unique"
  means k=1 alone. Measured on a rebuild of the walkthrough's own dataset:
  twenty-one distinct pairs, every one of them below the threshold, and
  eighteen participants alone on theirs.
- **The age-band example named `42`, which no participant in the walkthrough
  has.** The cohort runs 22, 26, 41, 44, 46 and up. An invented number beside a
  measured one is the worse kind, because a reader checks the measured half and
  is reassured. It now names `44`.
- **"because 22 is clinically useful" sat three lines under a worked example
  reading `Eta: 72 anni`.**

### Added

- Two guards, so these cannot drift again. The walkthrough fixture already
  builds the dataset, so both are free: one recomputes the (age, sex) pairs
  from `participants.tsv` and requires the prose to state that count and that
  number of lone participants, the other requires the age the banding sentence
  names to be an age the cohort has and to fall inside the band it claims.
  Both were checked by restoring the original errors, and both caught them.

### Schema versions carried by this release

- Manifest `7.2.0`, risk report `1.2.0`, dataset layout `1.1.0`,
  de-identification rules `1.2.0`. All unchanged, because no code changed.

## 0.1.5 — 2026-11-27

Documentation and assets only. `src/` is byte for byte what 0.1.4 shipped, so
nothing an installation does is different. What this release changes is the
project page, which is this repository's README, and a long description is
frozen into the artefact that carried it — so correcting one means publishing
again.

### Added

- The project's symbol and its full lockup as SVG under `assets/`, traced from
  the original raster rather than redrawn, and verified by parsing each emitted
  file back and comparing it against the mask it came from. The README header
  now carries the lockup above the title, with a dark-theme variant that GitHub
  resolves and PyPI reduces to the light one.

### Changed

- The README header is centred. `readme_renderer`, the library PyPI renders a
  long description with, keeps `<div align="center">` and strips `style`, so
  the centring is written as the attribute and not as CSS: written as CSS it
  would look right on GitHub and sit flush left on the index.

### Schema versions carried by this release

- Manifest `7.2.0`, risk report `1.2.0`, dataset layout `1.1.0`,
  de-identification rules `1.2.0`. All unchanged, because no code changed.

## 0.1.4 — 2026-11-25

Closes the limit 0.1.3 stated. A dataset built with any earlier version may
contain a codice fiscale written with separators, and the remedy is the same
as for 0.1.3: build it again.

### Fixed

- **A codice fiscale written with spaces, dots or hyphens survived
  redaction.** `LMB DVD 63H13 X767I` is how a form prints one and how somebody
  reads one out, and exact substitution reads only `LMBDVD63H13X767I`. Each
  declared national identifier now also matches a separator-tolerant form of
  itself, derived from the declared value rather than from a shape — so it
  still cannot fire on a value no export declared, which is what keeps this
  the same targeted method as the rest.
- Three constraints keep that pattern from wandering: at most one separator
  between two characters, no newline among them, and no match inside a longer
  alphanumeric run.

### Known limits, unchanged

- An accented variant of a declared name is not matched, and is not a defect:
  it is a different string, and the documented limit of targeted redaction.

### Schema versions carried by this release

- Manifest `7.2.0`, risk report `1.2.0`, dataset layout `1.1.0`,
  de-identification rules `1.2.0`. Unchanged: nothing here touches a derived
  label, an offset or a UID.

## 0.1.3 — 2026-11-25

**The first release that changes what is removed from a dataset.** Two
identifiers survived redaction in spellings this tool had every reason to
recognise, found by an adversarial pass rather than by a test. A dataset built
with 0.1.0, 0.1.1 or 0.1.2 may contain either of them, and the only remedy is
to build it again — the values were never in the manifest, so nothing recorded
that they had stayed.

### Fixed

- **A medical record number written without its leading zeros survived.**
  `normalise_record_number` strips them on purpose, so that `0012345` in one
  export and `12345` in another resolve to one patient; the redactor matched
  only the padded form, and so disagreed with the linkage that had already
  decided the two were the same person. A document writing the unpadded number
  kept it.
- **A telephone number punctuated with anything but spaces survived.** The
  pattern read `+39 010 0310547` and not `010-0310547`, and it exists for the
  number a document states that no structured field declared. It now accepts
  hyphens, dots and slashes, with two constraints that keep it from eating
  clinical content: at least nine digits, which is the shortest Italian
  telephone number and excludes every date, and at most one separator between
  two digits, which stops a match spanning a date range. Without the first,
  `22/11/2023` would become a redacted contact rather than a day offset.

### Known limits, stated rather than fixed

- A codice fiscale written with spaces, `LMB DVD 63H13 X767I`, is not matched.
  Closing it needs a separator-tolerant form of each declared value, which is
  a mechanism rather than a correction.
- An accented variant of a declared name is not matched, and is not a defect:
  it is a different string, and the documented limit of targeted redaction.

### Schema versions carried by this release

- Manifest `7.2.0`, risk report `1.2.0`, dataset layout `1.1.0`,
  de-identification rules `1.2.0`. Unchanged: nothing here touches a derived
  label, an offset or a UID, so datasets built across these versions remain
  linkable to each other.

## 0.1.2 — 2026-11-25

Documentation only. `src/` is byte for byte what 0.1.1 shipped, so nothing an
installation does is different; what changes is the project page, which is this
README and could only be corrected by publishing it again.

### Fixed

- Every relative link in the README 404ed on the PyPI page. PyPI does not
  resolve a relative target against the repository that produced the archive,
  and has no reason to — the archive could have come from anywhere. Eight of
  them, including three pointing at source modules the prose tells the reader
  to go and read. All absolute now.
- One in-page link pointed at a heading that has never existed, which is
  quieter than a 404: the page stays where it is, so it reads as the browser
  ignoring the click. Broken on GitHub too, for as long as it had been there.
- Six numbers had gone stale, each one restated away from the block it came
  from: the worked `linkage_issues` fragment added up to 29 under a build
  printing 49, having missed a third reason added on 2026-11-24; the imaging
  ledger still quoted a ten-subject corpus; and the lockfile sentence had
  missed four packages. Recaptured from a real build.
- A seventh number was never a capture at all. The illustrative
  `other labelled lines` row carried a count that collided with the linkage
  total by coincidence, so a reader could check it against another part of the
  page and be reassured. The README now says which fragment is an illustration.

### Added

- A badge row: version, Python versions and CI read from the index and the
  workflow rather than being restated here.
- Guards for all of the above. Four new tests tie the README's numbers to
  their source — including one that compares every manifest fragment the page
  quotes against the manifest a real build writes, which closes the class
  rather than this instance.

### Schema versions carried by this release

- Manifest `7.2.0`, risk report `1.2.0`, dataset layout `1.1.0`,
  de-identification rules `1.2.0`. Unchanged from 0.1.0.

## 0.1.1 — 2026-11-25

Packaging only. Nothing an installation reaches has changed: the
pseudonymisation, the manifest, the risk report and the emitted dataset
description are what 0.1.0 produced, byte for byte.

### Fixed

- The test suite errored when run from an unpacked source distribution, which
  is not a git checkout. `tests/test_line_endings.py` asks git which files are
  tracked, and the source distribution carries the tests on purpose so that
  somebody packaging this can run them without cloning — so a guard added for
  one declared property had broken another. It skips there now, stating why.
- The README overstated what the source distribution allows. It said the
  HealthDCAT-AP conformance claim is checkable "with no clone and no network",
  and installing the development extras plainly needs the network. The claim
  worth making is that the profile's own SHACL shapes are not fetched from a
  server nobody here controls, because the archive carries them, and that is
  now measured against the published archive rather than asserted.

### Schema versions carried by this release

- Manifest `7.2.0`, risk report `1.2.0`, dataset layout `1.1.0`,
  de-identification rules `1.2.0`. Unchanged from 0.1.0.

## 0.1.0 — 2026-11-25

First release.

### The tool

- Eleven commands, each with `--json`: `generate`, `defects`, `validate`,
  `rules`, `keygen`, `key-info`, `build`, `risk`, `verify`, `measure`, `whois`.
- Reads HL7 v2 laboratory messages, free-text reports, DICOM imaging metadata
  as JSON, and HL7 Italia CDA R2 documents — laboratory, radiology, discharge
  letter, pathology, outpatient specialist care and the patient summary.
- Writes a BIDS-compatible dataset extended with `lab/` and `reports/`, a
  HealthDCAT-AP Release 8 dataset description, a de-identification manifest and
  a re-identification risk report.
- Pseudonymisation is HMAC-SHA256 from one secret key, domain-separated per
  purpose and consistent across modalities. The key never enters the dataset
  and is never a command-line argument.
- Disclosure controls the holder chooses: `--permit` scopes pseudonyms to one
  data permit, `--age-band` generalises participant ages, and
  `--exclude-subjects` acts on an objection.
- `measure` compares the generator's ground-truth annotations against the built
  dataset and reports recall, so the de-identification is measured rather than
  asserted.

### What it does not do

- **Pseudonymisation, not anonymisation.** The output is still personal data.
  `risk` reports k over the quasi-identifiers it can score and names the
  channels it cannot; it certifies nothing.
- Free-text identity parsing is written against the labels this project's own
  generator produces. A hospital whose template writes something else needs
  that table edited in source, which means editing and reinstalling rather than
  configuring.
- Day offsets keep intervals exact, which is a documented re-identification
  channel kept open deliberately. The README says which side it takes.

### Schema versions carried by this release

- Manifest `7.2.0`, risk report `1.2.0`, dataset layout `1.1.0`,
  de-identification rules `1.2.0`.
