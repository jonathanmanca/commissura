# Changelog

Notable changes to `commissura`, newest first. Versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Three other version numbers travel inside the output and move independently of
this one, because a consumer needs to know which of them changed:
`.deident/manifest.json` and `.deident/risk_report.json` each declare their own
schema version, the dataset layout declares a third, and the de-identification
rules declare a fourth. A release that moves any of them says so below.

## 0.1.0 — unreleased

First release. `commissura` is not on an index yet, so this entry describes what
a first release would carry rather than what anybody has installed.

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
