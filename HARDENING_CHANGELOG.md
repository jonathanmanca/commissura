# Hardening changelog

Every code and documentation change made in response to
[SECURITY_AUDIT.md](SECURITY_AUDIT.md), 2026-11-13. Rationale and evidence are in
[REMEDIATION_REPORT.md](REMEDIATION_REPORT.md); the identity policy is in
[IDENTITY_RESOLUTION.md](IDENTITY_RESOLUTION.md).

Five commits from `27216df`:

| Commit | Milestone |
| --- | --- |
| `cf57232` | A — identity resolution |
| `bd3165a` | B — build lifecycle |
| `91dd438` | C — residual detection |
| `63616d8` | D — manifest consistency |
| *this one* | E — `whois`, key handling, documentation |

---

## Milestone A — identity resolution (`cf57232`)

### Added

**`src/commissura/read/identity.py`** — the policy, new. Owns classification,
normalisation, identity keys, the index and the refusal vocabulary.

- `IdentifierStatus` — `valid`, `missing`, `placeholder`, `malformed`,
  `bad_checksum`. Only the first may become a key.
- `KeyKind` — `national_id`, `scoped_record_number`.
- `NationalIdentifier` — the raw value, its normalised form and the verdict.
  The raw form is kept for redaction and diagnostics, never as a key.
- `IdentityKey` — `(kind, authority, value)`, ordered, with `derivation_input`.
- `AuthorityScope` — assigning authority with the sending facility as fallback.
- `RefusalReason`, `Refusal` — the reasons that reach the manifest, enumerated
  rather than written as literals at each construction site.
- `IdentityIndex` — `establish`, `resolve_record_number`,
  `ambiguous_record_numbers`.
- `classify_national_id`, `normalise_national_id`, `normalise_record_number`,
  `normalise_authority`, `identities_conflict`.
- `PLACEHOLDER_IDENTIFIERS` — 15 sentinels, plus any single repeated character.
- `UNSCOPED_AUTHORITY` — the namespace for record numbers with no stated
  authority. Never invented.
- Omocodia reversal, per DM 23 December 1976, so genuine substituted
  identifiers validate.

### Changed

**`src/commissura/read/corpus.py`**

- `read_corpus` routes every decision through `IdentityIndex`.
- `read_lab` no longer raises on an unusable national identifier. It parses; the
  index decides. **Breaking** for a caller relying on the `ValueError`.
- `_assigning_authority` added, reading PID-3 component 4 from the
  record-number repetition only.
- `Subject.identities: list[Identity]` replaces a single `identity`, which
  remains as a property returning the first. `Subject.key` added.
  `Subject.observe` reports a material disagreement.
- `LabRecord.assigning_authority` and `.scope` added.
- `ImagingRecord.institution_name` and `.scope` added; `(0008,0080)` is now read.
- `LinkageIssue` documented as an interface.
- `normalise_identifier` **removed**: every caller now uses the scoped
  `normalise_record_number`, and a second normaliser nobody calls is how two
  functions come to disagree.

**`src/commissura/deident/pseudonymise.py`**

- `subject_label_for(key)` added, choosing the domain separator by key kind.
- `_DOMAIN_SUBJECT_RECORD_NUMBER = "subject-mrn|"` added. New derivation, so no
  existing pseudonym changes.
- `subject_label` unchanged in signature and output; callers pass the normalised
  identifier.
- Collision state holds the untruncated digest, not the identifier, and the
  forward cache is gone. (Audit finding 7.)
- `RULE_VERSION` `1.0.0` → `1.1.0`, with the migration documented in the
  constant.

**`src/commissura/build/scrub.py`**

- `KnownIdentifiers.identity` → `identities: tuple[Identity, ...]`.
  **Breaking**, deliberately not papered over: a caller passing one identity
  where the field takes a tuple is a caller whose redaction would be
  incomplete, and that must not compile.
- `_identity_entries` builds the redaction plan from every identity.
- Birth-date forms come from every identity; `_render_date_forms` narrowed to
  `date`.

**`src/commissura/build/writer.py`**

- Labels derive from `subject.key` via `subject_label_for`.
- `_known_identifiers` passes every identity, and adds imaging
  `InstitutionName` to the known institutions.

### Tests

- **`tests/test_identity.py`** — new, 66 tests.
- **Five invented codice fiscali corrected** across 19 occurrences in
  `conftest.py`, `test_build.py`, `test_cli.py`, `test_observe.py`,
  `test_patient_identifiers.py`, `test_pseudonymise.py`. Each had a check
  character that does not check; the validator found them on its first run.
- `test_a_message_with_no_national_identifier_anywhere_is_refused` retargeted to
  `..._still_parses`.
- `test_a_message_with_no_national_identifier_is_refused` retargeted to
  `test_a_message_with_no_identifier_of_any_kind_is_refused`.

### Compatibility

Pseudonyms unchanged for valid input — verified, every label in two corpora
byte-identical. Migration in
[IDENTITY_RESOLUTION.md §7](IDENTITY_RESOLUTION.md).

---

## Milestone B — build lifecycle (`bd3165a`)

### Added

**`src/commissura/build/publish.py`** — new.

- `begin(destination)` — refuses an unsafe destination before anything is
  written, returns a staging area.
- `publish(staged)` — moves the old root aside, moves the new one in, removes
  the old. Restores on failure.
- `abandon(staged)` — removes the staging tree, never the destination.
- `looks_like_our_dataset(root)` — the guard between a mistyped `--out` and
  somebody's files.
- `PublicationError`, `Staged`, `STAGING_SUFFIX`, `PREVIOUS_SUFFIX`.

### Changed

**`src/commissura/cli.py`** — `build` stages, validates while staged, then
publishes. A failure at any point abandons the staging tree and leaves the
destination untouched. Exit 2 for a refused destination, 1 for a failed
publication.

**`src/commissura/build/report.py`** — `write_report` takes `destination` and
refuses a path inside **either** tree. Writing into the staging tree is equally
fatal, because that tree becomes the dataset.

**`src/commissura/build/manifest.py`** — `write_healthdcat_description` takes
`dataset_name`, so `dct:identifier` uses the published directory's name rather
than the staging path's.

**`src/commissura/cli.py`** — `verify` now prints what a clean verification does
*not* prove. Integrity, authenticity, completeness and correctness are four
claims.

### Tests

- **`tests/test_publish.py`** — new, 20 tests.
- `test_build_fails_when_its_output_does_not_conform` retargeted to
  `test_build_refuses_a_destination_that_is_not_its_own_output`: staging makes
  the old premise moot and turns the case into the one that matters.

### Compatibility

No option added or removed. No `--force`, and a test asserts it does not exist.

---

## Milestone C — residual detection (`91dd438`)

### Changed

**`src/commissura/build/scrub.py`**

- `_assess_residual_risk(text)` → `assess_residual_risk(text, *, known)`, now
  public, now three layers.
- Layer 1: declared values, NFKD-decomposed and case-folded. New — nothing
  checked the scrubber's output against its own input list before.
- Layer 2: `_NAME_LABELS` and `_TITLED_NAME`, detection by position.
- Layer 3: `_WORD = [^\W\d_]{4,}` under `re.UNICODE`, replacing `[A-Z]{4,}`.
- `_fold`, `_declared_values`, `_span`, `_looks_unredacted` added.

**`src/commissura/measure.py`** — `_dataset_text` prepends each file's relative
path to its contents, so ground-truth measurement covers filenames.

### Tests

**`tests/test_residual_risk.py`** — new, 19 tests. The clean fixture is copied
from a real build's output, after an invented one produced a false positive of
its own.

### Compatibility

`_assess_residual_risk` renamed and given a required keyword. Private before, so
no public API changed; the output strings are new, so anything matching on them
will not match.

---

## Milestone D — manifest consistency (`63616d8`)

### Changed

**`src/commissura/build/manifest.py`**

- `MANIFEST_SCHEMA_VERSION` `4.0.0` → **`5.0.0`**.
- `write_manifest` takes `risk`, so the manifest describes the report instead of
  asserting about the method. `None` means no report, said in those words.
- `_structural_risks` derives every claim from the dataset, each with its count.
  A limit that does not apply is not claimed.
- `_imaging_payloads` reads the metadata back from the dataset, because the
  claim is about the dataset.
- `_subject_key_counts` → `source.subject_keys`, both kinds reported at zero.

**`src/commissura/validate/rules/deident.py`** — **DI009**, warning severity,
one finding per study whose metadata says the pixels carry text. 39 → 40 rules.

**`src/commissura/validate/context.py`** — `imaging_metadata()` added, so two
rules asking the same question cannot reach different conclusions.

**`src/commissura/cli.py`** — passes `risk` to `write_manifest`.

### Tests

- **`tests/test_manifest_consistency.py`** — new, 16 tests.
- `tests/test_validate_rules.py` — `_burned_in_imaging` and the DI009 case,
  required by the project's "every registered rule has a case" guard.

### Compatibility

**Breaking for a manifest consumer.** `residual_risk.structural` no longer
carries the four fixed sentences. `source.subject_keys` is additive.

---

## Milestone E — `whois`, key handling, documentation (this commit)

### Changed

**`src/commissura/cli.py`** — `whois` classifies and normalises through
`classify_national_id`, the same function `build` uses. Exits 2 on an unusable
value with the diagnosis, rather than deriving a label for nobody. Reports the
normalised identifier in both output formats.

**`src/commissura/deident/keys.py`**

- `read_key_file` no longer interpolates a `UnicodeDecodeError`, which named the
  first non-ASCII byte by value and position. (Audit finding 9.)
- `SecretKey` is `eq=False`, so `==` is identity and `matches` is the only way
  to compare two keys. (Audit finding 11.)

### Documentation

- **`IDENTITY_RESOLUTION.md`** — new. Key types, normalisation, validation,
  authority semantics, ambiguity, migration, limitations.
- **`REMEDIATION_REPORT.md`** — new. Finding, root cause, fix, files, tests,
  results, remaining limitations.
- **`HARDENING_CHANGELOG.md`** — this file.
- **`SECURITY_AUDIT.md`** — finding status and remediation evidence added. No
  historical finding deleted.
- **`README.md`** — the `whois` example's identifier corrected (it had an
  invalid check character and the command now refuses it), identity resolution
  documented, the rebuild contract stated, `verify`'s limits stated, and the
  residual-risk section rewritten for the three layers.
- **`CLAUDE.md`** — decision log entries for each milestone.

### Tests

`test_whois_gives_the_label_the_dataset_carries`,
`test_whois_refuses_a_value_no_subject_can_be_keyed_on`,
`test_whois_refuses_a_checksum_failure_by_name`,
`test_a_binary_key_file_error_names_no_byte_of_the_key`,
`test_two_keys_cannot_be_compared_with_equality`.
`test_a_key_file_that_is_not_ascii_is_reported_not_raised` retargeted.

### Compatibility

`whois` gains exit code 2 and an output line. A script calling it with an
invalid identifier now fails where it previously returned a meaningless label —
which is the point.

---

## Summary of breaking changes

| Change | Who it affects | What to do |
| --- | --- | --- |
| `KnownIdentifiers.identity` → `identities` | Library callers | Pass a tuple. mypy will say so |
| `read_lab` no longer raises on a bad identifier | Library callers | Use `IdentityIndex`, or check `classify_national_id` |
| `read.corpus.normalise_identifier` removed | Library callers | Use `normalise_record_number`, scoped |
| Manifest schema 5.0.0 | Manifest consumers | `residual_risk.structural` sentences changed |
| `RULE_VERSION` 1.1.0 | Dataset holders | Nothing, for valid input. [§7](IDENTITY_RESOLUTION.md) covers the rest |
| `whois` exit 2 on an unusable identifier | Script callers | Handle the exit code; the value never had a label |
| `build` refuses a foreign non-empty destination | Operators | Use an empty directory or one this tool wrote |

## Remaining work

1. **Audit finding 8** — vendor the four upstream SHACL files so CI can check
   conformance offline, and make the test fail rather than skip when they are
   absent. A licensing and repository-layout decision.
2. **Audit finding 10** — report symlinks under a dataset as their own finding.
   Mitigated by staging, not closed.
3. **Audit findings 13 and 14** — two docstring sentences.
4. **The five open questions** in §6 of the audit, untouched.
