# Changelog

Notable changes to `commissura`, newest first. Versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Four other version numbers travel inside the output and move independently of
this one, because a consumer needs to know which of them changed:
`.deident/manifest.json` and `.deident/risk_report.json` each declare their own
schema version, the dataset layout declares a third, and the de-identification
rules declare a fourth. A release that moves any of them says so below.

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
