# Remediation report

Work on the findings in [SECURITY_AUDIT.md](SECURITY_AUDIT.md) and
[ENGINEERING_REVIEW.md](ENGINEERING_REVIEW.md), 2026-11-13.

Baseline at `27216df`: **806 passed, 1 skipped, 99.11%** branch coverage.
Final at `HEAD`: **930 passed, 1 skipped, 99.08%** branch coverage.
Static checks: `ruff check`, `ruff format --check` and strict `mypy` all clean
across 77 source files. SHACL conformance: 5 passed locally.

Every finding was reproduced against the working tree before being changed, and
every fix was verified by running the original reproduction again. All test data
is synthetic.

---

## Finding 1 — A shared or placeholder national identifier merged two people, and the merge leaked a name

**Severity: Critical. Status: fixed.**

### Root cause

Two causes, and only together do they produce the leak.

A subject was keyed on the raw string from the message, validated only for
emptiness:

```python
national_id = record.identity.national_id
subject = subjects.get(national_id)
if subject is None:
    subject = Subject(identity=record.identity)
    subjects[national_id] = subject
```

So every patient in an export whose identifier field was unavailable — filled
with `UNKNOWN`, `N/A`, zeros, whatever the source system writes — became the
same patient.

And `Subject` held **one** identity, set from the first record. Every later
record's identity was discarded. Targeted redaction is given
`KnownIdentifiers` built from that one identity, so for a merged subject the
second person's name was not in the set of strings to remove — and a method that
removes only what it was told about does not look for it.

### Reproduction, before

Two laboratory messages from a generated corpus for two different people, both
national identifiers replaced by `UNKNOWN`, plus the second person's own report:

```
subjects linked: 1   linkage issues: 0
dataset written: 1 subject(s)
the second person's surname 'FONTANA' appears in:
    ['sub-cc2d4031ebcf/ses-02/reports/sub-cc2d4031ebcf_ses-02_run-01_report.txt']
sub-cc2d4031ebcf/.../report.txt: Paziente: FRANCESCA FONTANA
```

The first person's name was removed correctly, which is what made it hard to
see: the failure was selective and the parts that worked looked like the whole
thing working.

### Fix

`read/identity.py` owns identity resolution. A value that is missing, a
placeholder or structurally impossible is a *diagnosis*, never a key; the record
falls back to its institution-scoped record number or is refused by name. And
`Subject.identities` keeps every identity observed, so redaction is built from
all of them. Full policy in [IDENTITY_RESOLUTION.md](IDENTITY_RESOLUTION.md).

### Reproduction, after

```
subjects linked: 2   linkage issues: 2
dataset written: 2 subject(s)
the first person's surname  'BIANCHI' appears in: []
the second person's surname 'FONTANA' appears in: []
```

### Files

`src/commissura/read/identity.py` (new), `src/commissura/read/corpus.py`,
`src/commissura/build/scrub.py`, `src/commissura/build/writer.py`,
`src/commissura/deident/pseudonymise.py`.

### Tests

`tests/test_identity.py`:
`test_two_placeholder_identifiers_at_one_site_do_not_become_one_person`,
`test_two_patients_sharing_a_placeholder_stay_two_subjects`,
`test_the_audit_scenario_no_longer_leaks_a_patients_name` (end to end, asserts
no surname appears in any published file),
`test_several_messages_for_one_patient_keep_every_identity`,
`test_a_record_with_no_usable_identifier_of_any_kind_is_refused`,
plus 20 parametrised cases over the classifier.

### Found while fixing

Codice fiscale validation **immediately rejected five identifiers in this
project's own test fixtures**, each with a check character that does not check:
`DLCFRN62S44X217T` (the default in `conftest.py`), `RSSMRA80A01X000A`,
`RSSMRA80A01X501U`, `VRDGPP85B02X000B`. Corrected to their valid forms across 19
occurrences in six files, rather than exempted — the validator is right and the
fixtures were invented. The generator's own identifiers all pass, because the
decision of 2026-11-06 had it compute the checksum correctly so the values would
"exercise a real validator rather than bouncing off it"; this is that validator.

### Remaining limitations

Only the codice fiscale is validated; any other national scheme falls back to a
scoped record number and is not relinkable across institutions.
`conflicting_identity` compares the family name and the birth date only.

---

## Finding 2 — The record-number index was global, with silent last-write-wins

**Severity: High. Status: fixed.**

### Root cause

```python
by_mrn[normalise_identifier(record.identity.mrn)] = national_id
```

One namespace for every record number in the corpus, and an unconditional
assignment. A record number is a hospital's own number and two hospitals both
number from 1, so collisions are the expected case in any multi-institution
corpus — not an edge case. On a collision the later assignment won, "later"
meaning whichever filename sorted last, and **no linkage issue was recorded**
because from the linker's point of view the lookup succeeded.

The information needed to prevent it was already parsed and discarded: PID-3
component 4 carries the assigning authority, MSH-4 the sending facility, and
`LabRecord.sending_facility` already held the latter.

### Reproduction, before

```
  facility 'PRESIDIO OSPEDALIERO SINTETICO VALLEDORO'  MRN '1787493'  name 'GALLI'
  facility 'POLICLINICO UNIVERSITARIO SINTETICO PIETRALTA'  MRN '1787493'  name 'BIANCHI'
subjects linked : 2   linkage issues : 0
  BIANCHI ALESSANDRO  -> imaging studies attached: 1
  GALLI MARTINA       -> imaging studies attached: 0
```

One patient's imaging study released under another patient's subject label.

### Fix

The key is `(normalised authority, normalised record number)`. `InstitutionName`
`(0008,0080)` is now read on the imaging side, so a study resolves to the patient
at the institution that issued the number. Where two subjects claim one scoped
number, the index is marked ambiguous and every record resolving through it is
reported rather than guessed at — including the first.

### Reproduction, after

```
subjects linked : 2   linkage issues : 0
  BIANCHI ALESSANDRO  -> imaging studies attached: 0
  GALLI MARTINA       -> imaging studies attached: 1
```

The study goes to the patient at VALLEDORO, which issued `1787493`. Correct
attribution, not merely a refusal.

### Files

`src/commissura/read/identity.py`, `src/commissura/read/corpus.py`.

### Tests

`test_the_same_record_number_at_two_authorities_is_two_people`,
`test_an_imaging_study_goes_to_the_patient_at_the_issuing_institution`,
`test_one_record_number_claimed_by_two_people_becomes_ambiguous`,
`test_ambiguity_does_not_depend_on_the_order_records_were_read`,
`test_a_record_number_reused_at_one_site_refuses_the_imaging_linkage`,
`test_an_imaging_study_naming_no_institution_is_refused_when_the_number_is_shared`,
`test_an_unscoped_number_still_resolves_in_a_single_site_corpus`,
`test_a_number_two_authorities_share_is_ambiguous_when_looked_up_unscoped`,
`test_a_message_with_no_typed_authority_still_scopes_on_the_sending_facility`.

### Found while fixing

The first version of `_assigning_authority` fell back to "whichever PID-3
repetition names an authority" and picked up `MINSAL` — the ministry that issues
codice fiscali — from the national identifier's repetition. That would have
scoped every hospital's numbering under one national namespace: the flat index
this change exists to remove, reintroduced under a plausible-looking name. Caught
by `test_a_message_with_no_typed_authority_still_scopes_on_the_sending_facility`,
and the fallback is gone with a test pinning its absence.

---

## Finding 3 — A rebuild kept withdrawn records, reported `conforms`, and was then certified authentic

**Severity: High. Status: fixed.**

### Root cause

`build_dataset` resolved its destination and wrote files into it. No staging, no
check on an existing destination, no record of what a previous build left, no
removal of anything. Files the current build did not overwrite simply stayed —
and `digest_tree` then digested *everything under the root*, so they were
recorded in `integrity.files` and covered by `manifest_hmac`.

### Reproduction, before

```
build  (2 imaging studies)         -> derivatives: 2 files
remove one study from the corpus
rebuild into the same directory    -> Validation: conforms, 0 errors, exit 0
                                   -> derivatives: 2 files
diff against a clean build: only in the rebuilt dataset:
  sub-c7ae7c18a196_ae96145dbc2137db_imaging.json
commissura verify --key-file:      manifest authentic, INTACT
```

A data holder acting on a patient's objection by removing records and rebuilding
had not removed them, and the integrity machinery certified the result for as
long as the dataset existed.

### Fix

`build/publish.py`. The whole build — dataset, description, risk report,
manifest, validation — happens in a staging directory beside the destination and
is moved into place at the end. A successful build publishes exactly what the
current corpus produced; a failed one leaves the destination as it was.

**Not called atomic, because it is not.** Publication is two renames and the
destination does not exist between them; `os.replace` cannot do better for a
directory, since POSIX refuses to rename over a non-empty one and Windows over a
directory at all. A failure in that window puts the previous dataset back, and
the module documents the guarantee rather than overclaiming it.

A destination that exists, is not empty and holds no `.deident/manifest.json` or
`dataset_description.json` is **refused outright**. There is no `--force`: the
flag would exist only so somebody could aim it at a directory this check
protects.

### Reproduction, after

```
derivatives before: 2
withdrawing one imaging study
  Validation: conforms - 0 error(s), 0 warning(s)   exit 0
derivatives after:  1
no staging or previous directories left behind
```

### Files

`src/commissura/build/publish.py` (new), `src/commissura/cli.py`,
`src/commissura/build/report.py`, `src/commissura/build/manifest.py`.

### Tests

`tests/test_publish.py`, 20 tests:
`test_a_withdrawn_imaging_study_does_not_survive_a_rebuild`,
`test_a_rebuild_matches_a_clean_build_of_the_same_corpus`,
`test_a_withdrawn_participant_leaves_no_directory_behind`,
`test_the_manifest_does_not_reference_a_withdrawn_record`,
`test_a_destination_that_is_not_our_output_is_refused`,
`test_there_is_no_flag_that_overrides_the_refusal`,
`test_a_failed_publication_puts_the_previous_dataset_back`,
`test_an_interrupted_build_publishes_nothing`, and others.

### Found while fixing

Staging broke two things, both caught by tests rather than review.

**`write_report`'s guard compared against `summary.root`**, which during a staged
build is the staging tree — so `--report ./dataset/x.html` stopped being "inside
the dataset" the moment staging was introduced. It now refuses both trees, and
writing into the staging tree is equally fatal because that tree becomes the
dataset.

**`dct:identifier` is `urn:commissura:<directory name>`**, which became the
staging directory's name, process id included. Every build was suddenly
non-reproducible in exactly one file — the trap the cross-platform
reproducibility job was built to catch, and the one the decision log of
2026-11-13 recorded. The description now takes the published name.

### Remaining limitations

Publication is not atomic; §3 of `publish.py` states the window and the recovery.
A destination on a different filesystem from its parent would make the final
rename a cross-device copy, which is not handled and would fail with a message
naming the staged tree.

---

## Finding 4 — Case variation split one person into several subjects

**Severity: High. Status: fixed.**

### Root cause

The reader stripped surrounding whitespace from the national identifier and did
nothing else. `normalise_identifier`, in the same module, folded case — and was
applied to **record numbers only**. The asymmetry was backwards: the
hospital-local collision-prone identifier got aggressive normalisation that
caused merges, and the globally unique identifier every pseudonym derives from
got none, which caused splits.

### Reproduction, before

```
one person, BNCLSN82R26X136L in one message and bnclsn82r26x136l in the other:
   subjects linked : 2   linkage issues : 0
```

Two participant rows, each with part of the record, **each with its own
baseline** — so the `day_offset` values in the two fragments were anchored
differently and no longer described one timeline. And `commissura whois` returns
one label, so an opt-out would have missed half that person's records.

### Fix

`normalise_national_id`: NFKC, all whitespace removed, uppercased. Applied at
the point of parsing, and by `whois` through the same function.

### Reproduction, after

```
   subjects linked : 1   linkage issues : 0
   subject carrying 2 laboratory record(s)
```

### Tests

`test_one_person_written_in_two_cases_is_one_subject`,
`test_equivalent_spellings_normalise_to_one_identifier` (5 cases),
`test_full_width_digits_normalise`,
`test_whois_gives_the_label_the_dataset_carries` (asserts every spelling an
operator might type yields a label the dataset holds).

### Found while fixing

**`whois` was only half fixed by the above**, and this is the part that mattered
most. It passed the raw stripped value straight to `subject_label`, so
`whois` on a lowercase identifier returned a label for nobody — and
`whois UNKNOWN` returned one too. An operator acting on an objection could
search a dataset for a subject that was never in it and conclude the person was
not there: the opt-out the command exists for, failing silently. `whois` now
classifies through the same function `build` uses, reports the normalised form,
and exits 2 on an unusable value with the diagnosis.

---

## Finding 5 — `residual_risk.structural` contradicted the dataset it was written into

**Severity: Medium. Status: fixed.**

### Root cause

Four fixed prose strings written into every manifest regardless of the dataset.
One read "no k-anonymity report has been produced for this dataset" while
`risk_report.json` sat beside it reporting `minimum_k = 1`, digested into the
same manifest's integrity list and covered by its HMAC. The document contradicted
a file it authenticated.

The other three were true of the *method*. `BurnedInAnnotation` was warned about
in identical words whether a dataset held four flagged studies or none — and
`validate` reported `conforms` with zero warnings over one in which all four
were flagged.

This is the same failure the per-modality field table had and shed on
2026-11-10: a static list can only account for what somebody remembered to write
down, in a section nobody revisits.

### Fix

Derived from the dataset, each claim carrying its own count:

```
 * Pixel data is not inspected. 4 of 4 studies in this dataset carry
   BurnedInAnnotation=YES, where identifiers may be rendered into the image.
 * Quasi-identifier combinations were assessed over ['age', 'sex']: minimum k
   is 1, with 6 combination(s) below the threshold of 5. See risk_report.json.
   This is a measurement and not a certificate of anonymity.
```

A limit that does not apply is not claimed: no imaging means no claim about
pixels or defacing. Where no risk report was produced the manifest says so in
those words, because "not assessed" and "assessed, and k is 1" are different
facts and only one is reassuring.

New rule **DI009** warns per study whose metadata says the pixels carry text — a
warning and not an error, because the flag is carried on purpose so a downstream
converter knows to beware, and refusing to build would leave the holder worse
off than telling them.

`source.subject_keys` says what established each subject, both kinds reported
even at zero. Manifest schema **5.0.0**: a consumer matching the old sentences
will not find them.

### Files

`src/commissura/build/manifest.py`, `src/commissura/validate/rules/deident.py`,
`src/commissura/validate/context.py`, `src/commissura/cli.py`.

### Tests

`tests/test_manifest_consistency.py`, 16 tests, including
`test_the_manifest_does_not_deny_a_risk_report_it_digests`,
`test_a_higher_k_is_reported_as_the_number_it_is`,
`test_a_missing_risk_report_is_stated_in_those_words`,
`test_burned_in_studies_are_counted_not_merely_warned_about`,
`test_a_dataset_with_no_imaging_makes_no_imaging_claim`,
`test_a_burned_in_dataset_does_not_validate_clean`,
`test_the_manifest_is_consistent_after_a_withdrawal`.
Plus the DI009 case in `tests/test_validate_rules.py`, which the project's
"every registered rule has a case" guard required.

---

## Finding 6 — The residual detector was blind to anything but capitals

**Severity: Medium. Status: fixed.**

### Root cause

```python
capitalised = set(re.findall(r"\b[A-Z]{4,}\b", text))
```

Measured: `FRANCESCA FONTANA` → 1 risk. `Francesca Fontana` → **0 risks**. The
detector was calibrated to a convention this project's own generator invented,
and a real hospital's title-case template would have left a leaked name
completely silent. The decision log names `_REPORT_LABELS` as *the* obstacle to
using this tool on real data for exactly this reason; the detector had the same
dependency, unrecorded, and failed quietly rather than loudly.

### Fix

Three layers, strongest first:

1. **Did a value we were told about survive?** Exact, NFKD-decomposed,
   case-folded. No false positives are possible: these are strings the scrubber
   was handed and asked to remove. **Nothing checked this before** — the
   scrubber counted its own replacements and never looked at its own output.
   Accent insensitivity falls out of the decomposition rather than a table:
   `Fontanà` decomposes to `Fontana` plus a combining accent, so the folded
   needle is still a substring.
2. **Is something still where a name is declared to be?** A line beginning
   `Paziente:` holds a name by definition, so a residue there is a residue in
   any case. Position does the work, which bounds the false-positive rate
   without a name model — this project rejects named entity recognition and that
   is not reopened.
3. **An unrecognised word that looks like an identifier?** The original
   heuristic, now Unicode-aware: `[^\W\d_]` sees every letter in every script
   where `[A-Z]` saw none of them accented.

`measure` now searches each file's path along with its contents, which closes the
filename question against ground truth rather than a heuristic.

### Measured result

Every required case is detected — `FRANCESCA FONTANA`, `Francesca Fontana`,
`francesca fontana`, `FONTANA FRANCESCA`, `Francesca Fontanà`, a name in an
ordinary sentence, `Dott. Bianchi` in title case, an identifier in lower case.

**And no new false positives.** On the twenty-five-subject walkthrough the three
layers together report the same two truncation fragments the single layer did,
and nothing else. Strictly more sensitive at no cost in noise.

### Tests

`tests/test_residual_risk.py`, 19 tests, including the seven parametrised
spellings, four "stays quiet" cases built from a real build's output,
`test_the_detector_never_quotes_what_it_found` and
`test_the_note_never_reads_as_a_clearance`.

### Remaining limitations

Layer 2 depends on a label table, which is the dependency the decision log
already names for `_REPORT_LABELS`. A template using labels this tool does not
know gets layers 1 and 3 only. The limit is now documented in the detector
itself rather than implied.

---

## Finding 7 — `Pseudonymiser` retained every national identifier against its own docstring

**Severity: Medium. Status: fixed.**

### Root cause

Two dictionaries: a forward cache keyed on the national identifier, and a reverse
collision witness holding it as a value. Both lived for the length of the build,
while the docstring of `subject_label` said "It is used and discarded; nothing
here retains it."

### Fix

The collision witness is the **untruncated digest**, which distinguishes two
inputs exactly as well as the inputs do and is not patient data. The forward
cache is gone entirely: a cache would have to be keyed on the derivation input,
putting the identifier straight back into the object it was just removed from,
and an HMAC over a short string costs microseconds against a build that reads
files from disk.

```
before: {'_subject_ids': {'RSSMRA80A01X000A': '4e424f09e6f9'},
         '_issued_subjects': {'4e424f09e6f9': 'RSSMRA80A01X000A'}}
after:  {'_witnesses': {'508a56555aba': '508a56555ababc7b...5e08'}}
```

### Tests

`tests/test_pseudonymise.py::test_a_truncation_collision_raises_instead_of_merging_two_people`
retargeted onto the digest witness.

---

## Findings 9 and 11 — key material in an exception, and non-constant-time equality

**Severity: Low and Informational. Status: fixed.** Outside the four priorities,
done because each is one line and each makes the key-handling story honest.

**Finding 9.** `UnicodeDecodeError` names the offending byte and its position, so
interpolating it disclosed one byte of the secret — by value and index — into
whatever caught the message. A key file holding raw bytes instead of hex is a
plausible operator mistake:

```
before: 'ascii' codec can't decode byte 0x8f in position 1: ordinal not in range(128)
after:  key file ...\raw.key is not ASCII text; it should hold 64 hex characters
```

**Finding 11.** `SecretKey` is now `eq=False`, so `==` is identity and `matches`
— which uses `compare_digest` — is the only way to compare two keys. Two ways to
ask one question, one constant-time and one not, with nothing steering a caller
to the safe one.

Tests: `test_a_binary_key_file_error_names_no_byte_of_the_key`,
`test_two_keys_cannot_be_compared_with_equality`.

---

## Not fixed, and why

| Finding | Severity | Status |
| --- | --- | --- |
| 8 — conformance unverified in CI, and skips silently | Medium | **Open.** Needs the four upstream SHACL files vendored under `reference/` with a `NOTICE` entry, un-gitignored. CC BY 4.0 permits it. Not done here: it is a licensing and repository-layout decision, not a code fix, and it belongs with the author |
| 10 — `digest_tree` follows file symlinks | Low | **Mitigated, not closed.** Milestone B removed the dangerous half: `digest_tree` now runs over a staging tree containing only what the build wrote, so a symlink cannot enter `integrity.files`. One placed afterwards is reported as `added` by `verify`. What remains is that `is_file()` reads through the link at verify time. Closing it properly means reporting symlinks as their own finding, which is more than a one-line change |
| 12 — no staging or rollback | Low | **Closed by finding 3** |
| 13 — `accession()` has no collision check | Informational | **Open.** 64 bits; the asymmetry with `subject_label` is undocumented and deserves one sentence |
| 14 — `2.25.<112-bit>` is not a UUID rendering | Informational | **Open.** Changing it would move every imaging UID, which needs a rule-version bump for no safety gain. Documenting the intent is the cheaper honest answer |

The five "potential findings requiring further investigation" in §6 of the audit
are untouched and still stand as questions.

---

## Test results

| Stage | Tests | Coverage |
| --- | --- | --- |
| Baseline (`27216df`) | 806 passed, 1 skipped | 99.11% |
| Milestone A — identity | 869 passed, 1 skipped | 99.23% |
| Milestone B — build lifecycle | 889 passed, 1 skipped | 99.16% |
| Milestone C — residual detection | 908 passed, 1 skipped | 99.17% |
| Milestone D — manifest consistency | 925 passed, 1 skipped | 99.14% |
| Milestone E — `whois`, keys | **930 passed, 1 skipped** | **99.08%** |

**The one skip, reported separately as required:**
`tests/test_keys.py:126` — "POSIX file modes are not honoured". Platform-gated,
skipped on Windows only, and it runs in CI on Ubuntu.

`tests/test_shacl_conformance.py` passes locally (5 tests) and skips in CI by
design — which is finding 8, still open.

Other checks, all clean:

- `ruff check .` and `ruff format --check .`
- `mypy` (strict), 77 source files
- A wheel built with `uv build`, installed into an empty virtual environment:
  all 11 commands run, `py.typed` shipped, no test file, no `reference/`
  material and no `.key` in the 52 entries
- Two builds of the same corpus into same-named directories in different
  parents: `integrity.files` identical across 27 files
- `git diff` reviewed for unintended changes; no secret-shaped additions

---

## Acceptance criteria

| # | Criterion | Evidence |
| --- | --- | --- |
| 1 | Two `UNKNOWN` records cannot silently become one patient | Reproduced: 2 subjects, 2 reported issues |
| 2 | Valid equivalent identifiers resolve consistently | 1 subject from two cases; `whois` agrees with `build` on 4 spellings |
| 3 | Record numbers are scoped to their authority | Study attached to the patient at the issuing institution |
| 4 | Ambiguous linkage cannot silently overwrite | Refused by name; order-independent |
| 5 | All known identifiers remain available to redaction | `Subject.identities`; `KnownIdentifiers.identities` |
| 6 | No patient name from the audit scenario survives | Both surnames absent from every published file |
| 7 | Rebuilding after withdrawal removes the record | 2 → 1 derivatives, matches a clean build |
| 8 | Verification does not substitute for completeness | `verify` prints what it does not prove; a test keeps the old manifest and shows it verifies |
| 9 | Residual detection handles case and Unicode | 7 spellings, all detected |
| 10 | Manifest risk claims reflect actual reports | Counts derived from the dataset |
| 11 | Cryptographic behaviour compatible | Every label in two corpora byte-identical; `RULE_VERSION` 1.1.0 documents what moves |
| 12 | All tests pass, skips reported | 930 passed, 1 skipped, named above |
