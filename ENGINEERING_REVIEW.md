# commissura — engineering review

Companion to [SECURITY_AUDIT.md](SECURITY_AUDIT.md). Audit date 2026-11-13,
commit `27216df`. No source file was modified.

This document covers architecture, code quality, data flow, testing, dependencies
and maintainability. Security findings are numbered there and referenced here by
number rather than restated.

---

## 1. Architecture map

```
                      ┌──────────────────────────────────────────┐
  layout.py           │ the single schema: paths, column names,  │
  (no logic)          │ forbidden patterns, manifest key list    │
                      └──────────────────────────────────────────┘
                            ▲            ▲             ▲
                            │            │             │
  ┌─────────────────────────┴──┐  ┌──────┴──────┐  ┌───┴────────────────┐
  │ generate/                  │  │ validate/   │  │ build/             │
  │  cohort  → models.Subject  │  │  context    │  │  writer   (layout) │
  │  labs    → HL7 text        │  │  rules/ ×39 │  │  scrub    (text)   │
  │  reports → prose           │  │  runner     │  │  observe  (ledger) │
  │  imaging → DICOM JSON      │  │  findings   │  │  manifest (two docs)│
  │  defects (injection)       │  └─────────────┘  │  risk     (k)      │
  │  writer  (bytes + truth)   │                   │  integrity (digest) │
  └────────────────────────────┘                   │  report   (HTML)   │
                │                                  └────────────────────┘
                │ raw/                                       ▲
                ▼                                            │
  ┌────────────────────────────┐              ┌──────────────┴──────────┐
  │ read/                      │─────────────►│ deident/                │
  │  hl7    (tolerant parser)  │   RawCorpus  │  keys       (the secret)│
  │  corpus (link + model)     │              │  pseudonymise (HMAC)    │
  └────────────────────────────┘              └─────────────────────────┘
                                                           ▲
  measure.py  ── ground truth vs. dataset ──────────────────┘
  healthdcat.py ── 57 properties × 3 tiers, transcribed, no network
  cli.py ── 11 commands, every one with --json
```

**The shape is right and it is the project's main asset.** Four properties are
worth naming because they are what make the codebase navigable:

1. **One schema, no logic.** `layout.py` holds the paths, the column lists, the
   forbidden date patterns and the reserved manifest keys, and nothing else.
   `validate` is derived from it and `build` satisfies it, so neither defines the
   layout by accident. Writing `validate` before `build` was the right call and
   it shows.

2. **Strict writers, tolerant readers, stated as a rule.** `hl7.py` refuses a
   value containing a delimiter; `read/hl7.py` accepts a missing field, a missing
   segment and `\n` for `\r`. Each direction is right for its job and the
   asymmetry is documented where a reader will meet it.

3. **Whitelist, not blacklist, on the way out.** The lab branch writes nine
   columns and the imaging branch seven keys. Removal needs no enumeration, which
   is what lets the manifest's field table be *observed* rather than declared.
   This is the single best design decision in the repository.

4. **Facts separated from artefacts.** `models.py` holds what is true about a
   synthetic person; `generate/` renders it into three formats. Cross-modal
   consistency is free and inconsistency has to be chosen.

**The one structural gap.** There is no module that owns *identity*. Resolution
lives inside `read_corpus` as two dictionaries and four lookups, interleaved with
file iteration and issue collection, in a 79-line function. Everything downstream
trusts its answer and nothing downstream can check it. All four high-severity
security findings are there, which is not a coincidence: the pipeline has a
layer for parsing, a layer for de-identifying, a layer for writing and a layer
for validating, and the step between parsing and de-identifying — deciding who
is who — has no layer, no model and no tests of its own beyond the happy path.

That is the recommended architectural change, and it is the only one.

---

## 2. Data flow, and where trust changes hands

```
  (1) bytes on disk          read_exact, newline=""        exact characters
  (2) characters             read/hl7, read_report         fields and segments
  (3) fields                 read_corpus                   ← IDENTITY DECIDED HERE
  (4) RawCorpus              build_dataset                 pseudonyms, offsets
  (5) Subject + known ids    scrub_text                    redacted prose
  (6) dataset tree           observe_corpus                field ledger
  (7) + manifest             digest_tree, tag_manifest     authenticated
  (8) + description          validate                      conformance verdict
```

Step 3 is the pivot. Before it, every value is untrusted input. After it, the
pipeline treats the subject grouping as ground truth: `KnownIdentifiers` is built
from one `Identity` per subject, the baseline is the minimum over the records
that reached that subject, and the scrubber only removes strings it was handed.

So a step-3 error is not contained. It propagates into:

- **what gets redacted** — a merged subject's second person is never looked for
  (security finding 1, with a leaked name as evidence);
- **what time means** — a split subject's fragments get different baselines, so
  `day_offset` values stop describing one timeline (finding 4);
- **what attaches to whom** — a collided record number moves an imaging study to
  the wrong person (finding 2);
- **what `risk` measures** — k over an inflated or deflated participant count;
- **what `whois` answers** — one label for a person the dataset may hold under
  two (finding 4).

None of the four downstream checks can see any of it. `validate` checks structure
and the dataset is structurally perfect. `verify` checks bytes against a manifest
derived from the same wrong grouping. `measure` would catch finding 1 on a
generated corpus, but no defect produces the input that triggers it. The
residual-risk detector caught it by accident, through a capitalisation heuristic
(finding 6).

**The generalisable observation**, and the one this review would most like to
leave behind: *this project's instruments all measure the transformation, and
none measures the grouping.* "Rules first, measurement always" has been applied
rigorously to de-identification and not at all to identity resolution, which is
the step de-identification depends on.

---

## 3. Code quality

### Strong

- **Docstrings carry reasoning, not restatement.** Nearly every non-obvious
  decision names the alternative it rejected and why. This is rare and it is why
  a reader can audit the codebase at all. It is also what makes finding 7 a
  Medium rather than a Low: when docstrings are this reliable, a false one is
  load-bearing.
- **Strict mypy over `src` and `tests`, ruff with docstring rules, 99% branch
  coverage floor in `pyproject.toml` rather than as a flag.** All three pass
  (`Success: no issues found in 71 source files`).
- **Named constants with reasons.** `SUBJECT_ID_HEX_CHARS`,
  `DATE_OFFSET_SPAN`, `_MINIMUM_REDACTABLE`, `MEASURABLE_LENGTH`,
  `LABORATORY_SAMPLE` — each with a docstring saying why that value.
- **Frozen dataclasses throughout**, with the two mutable exceptions
  (`Pseudonymiser`, `Subject`) each explaining why.
- **Single points of edit for things known to be unsettled.**
  `healthdcat.NAMESPACES` for the provisional namespace,
  `_csvw_table_group()` for the two open upstream issues, `_REPORT_LABELS` for
  template adaptation. Each with the issue number or the reason recorded. This
  pattern is worth keeping and extending.

### Weak

- **`cli.py` is 1039 lines and the longest module in the project.** Eleven
  commands, each with argument parsing, orchestration and two output formats
  (human and `--json`). The `build` command alone spans roughly 180 lines and
  mixes option validation, pipeline orchestration, terminal formatting and exit
  codes. The split that suggests itself is not one module per command — that
  would be eleven files of boilerplate — but pulling the **rendering** out:
  a `cli/render.py` holding the human-readable formatting for each result type,
  leaving each command as parse → call → render → exit. The project's own
  2026-11-12 lesson applies with extra force here: formatting is the part most
  likely to be asserted on by mistake.

- **`read_corpus` does four jobs in one function** (§1). Iterating files,
  parsing, resolving identity and collecting issues. Splitting out identity
  resolution is the fix for three security findings and would make the function
  readable as a consequence rather than as the goal.

- **`residual_risk.structural` is a static list in the middle of a derived
  document** (finding 5). The same defect the project diagnosed and fixed for
  the field table on 2026-11-10, in the same file, in a section that was not
  revisited at the time. Worth a deliberate pass asking which *other* parts of
  `manifest.py` state intent rather than observation.

- **Two names for one concept.** `DroppedRecord.reason` and
  `LinkageIssue.reason` are both free-form strings drawn from closed sets that
  exist only as literals at their construction sites
  (`unreadable_lab_message`, `unlinked_report`, `unlinked_imaging`,
  `undated_record`, `subject_has_no_dated_event`). The manifest's consumer has
  to know all five and nothing enumerates them. A `Literal` type or a small
  enum would put them in one place, make them greppable, and let a test pin the
  set — the same argument the rule registry already won for `validate`.

### Lean

The codebase is lean. The audit found no dead code, no speculative abstraction,
no interface with one implementation and no wrapper that only forwards. The one
duplicate (three copies of `read_exact`) was removed in the commit under audit.
Both runtime dependencies are used. Possible reductions are small and listed in
§7.

---

## 4. Testing assessment

**Current state:** 806 passed, 1 skipped, 99.11% branch coverage, 39 validation
rules, five conformance tests passing locally.

**The suite is unusually good at some things.** Three practices stand out and
should be kept:

1. **Guards are verified by sabotage.** The `--key` guard, the CI reproducibility
   comparison, the manifest leak test and both tests added in `27216df` were each
   checked by breaking the thing and watching the test fail. The project's own
   phrasing — "a guard nobody has watched fail is a guard nobody has tested" — is
   the right standard and it is applied.
2. **Tests assert on interfaces, not on rendered output.** After the 2026-11-12
   incident the suite asks click for the parameter list rather than grepping
   `--help`. The convention is written down.
3. **The brief itself is tested.** `tests/test_brief.py` pins the documented
   command list against typer's registrations.

**The gap is coherent and it is the same one as everywhere else in this review:
nothing tests identity resolution against adversarial input.** Every test of
`read_corpus` supplies a corpus in which identity is unambiguous — either
generated, or hand-built with distinct identifiers. The tests exercise the
*mechanics* of linkage thoroughly (the PID-3 type-code fallback, the untyped
guard, leading-zero normalisation, `mrn_format_drift` recovery) and the
*semantics* not at all.

### Tests this review specifies

Phase 5 of the brief asked for these. They are specified rather than written,
since this pass is audit-only. Each one fails against `27216df`; the four marked
**(L)** are the ones whose absence let a security finding through.

**Identity resolution — the gap**

| Test | Asserts |
| --- | --- |
| `test_a_placeholder_national_identifier_is_not_a_subject` **(L)** | Two messages carrying `UNKNOWN` produce 0 subjects and 2 linkage issues, not 1 subject |
| `test_two_identities_under_one_national_identifier_are_reported` **(L)** | A second record with a different surname or birth date under an existing key yields a `LinkageIssue`, not a silent merge |
| `test_a_merged_subject_cannot_leak_the_second_persons_name` **(L)** | Build from the finding-1 corpus; no report in the dataset contains either surname. The end-to-end form of the above |
| `test_the_same_identifier_in_two_cases_is_one_subject` **(L)** | `BNCLSN82R26X136L` and `bnclsn82r26x136l` give one subject with two records |
| `test_a_malformed_national_identifier_is_an_issue_not_a_subject` | `"0"`, `""` after strip, `"N/A"`, 3 characters — each a reported issue |
| `test_the_national_identifier_normalisation_is_recorded` | The manifest states which transformation was applied, so `whois` and `build` can be shown to agree |

**Record-number linkage**

| Test | Asserts |
| --- | --- |
| `test_one_record_number_at_two_institutions_is_two_namespaces` | Finding 2's corpus: the imaging study attaches to the patient at the same institution |
| `test_an_ambiguous_record_number_is_reported_not_guessed` | One normalised MRN mapping to two national identifiers, institution unknown: every record resolving through it becomes an issue |
| `test_leading_zero_normalisation_stays_within_an_institution` | `0012345` at site A does not match `12345` at site B |
| `test_a_duplicate_record_number_at_one_institution_is_reported` | Two national identifiers, same site, same MRN |

**Build lifecycle**

| Test | Asserts |
| --- | --- |
| `test_a_rebuild_does_not_keep_a_withdrawn_record` **(L)** | Finding 3B: rebuild after removing one imaging study; the dataset matches a clean build byte for byte |
| `test_a_rebuild_does_not_keep_another_cohorts_subjects` | Finding 3A: 4 subject directories, not 8 |
| `test_a_non_empty_destination_is_refused_or_cleaned` | Whichever policy is chosen, pinned |
| `test_a_destination_that_is_not_our_output_is_never_removed` | A directory with no `.deident/manifest.json` is refused even with `--force` |
| `test_an_interrupted_build_leaves_nothing_published` | Raise partway through; the destination is unchanged or absent, never half-written |
| `test_the_manifest_never_digests_a_file_this_build_did_not_write` | The general form of 3A and 3B |

**Integrity**

| Test | Asserts |
| --- | --- |
| `test_a_symlinked_file_is_not_digested_as_dataset_content` | Finding 10. `pytest.mark.skipif` on Windows without privileges — and the skip reason must name the platform, not read as a pass |
| `test_a_symlink_under_the_dataset_is_reported` | A dataset meant to be archived should not contain one |
| `test_a_manifest_path_outside_the_root_is_rejected` | `integrity.files` containing `../x` does not resolve outside |
| `test_a_manifest_whose_digest_values_are_not_strings_fails_closed` | `{"a": 123}` is a failure, not a comparison |

**Keys**

| Test | Asserts |
| --- | --- |
| `test_a_binary_key_file_error_names_no_byte_of_the_key` | Finding 9: no `0x..` in the message |
| `test_the_pseudonymiser_retains_no_national_identifier` | Finding 7: after N calls, no attribute of the object contains any input string |
| `test_two_keys_cannot_be_compared_with_equality` | Finding 11: `eq=False`, so `==` is identity |
| `test_key_rotation_produces_a_different_fingerprint_and_different_labels` | The property a holder needs to reason about, currently untested |

**Residual risk and manifest truth**

| Test | Asserts |
| --- | --- |
| `test_a_title_case_name_is_reported_as_residual_risk` | Finding 6 |
| `test_the_manifest_does_not_deny_a_risk_report_it_digests` | Finding 5: the k-anonymity sentence appears only when no report was written |
| `test_burned_in_annotation_is_counted_not_merely_warned_about` | Finding 5: the count matches the dataset |
| `test_a_dataset_with_burned_in_annotation_does_not_validate_clean` | A warning-severity rule |

**What should not be built.** No fuzzing harness and no property-based testing
framework. The gaps above are specific and a hand-written case pins each one;
adding `hypothesis` would be a dependency and a maintenance surface for failures
nobody has seen. Revisit if the identity-resolution rewrite turns out to have a
large input space, which it should not.

### One note on coverage

99.11% branch coverage coexists with every finding in the security audit. That is
not a criticism of the floor — it is a regression floor, and the project says so
— but it is worth recording as the sharpest available illustration: **coverage
measured that `read_corpus` ran, on inputs where it was right.** The two lines
that were uncovered before `27216df`'s test additions (`recall` returning `None`)
were found by reading the coverage report, not by it failing. The findings here
were found by constructing inputs, which no coverage number can prompt.

---

## 5. Dependency assessment

| Dependency | Scope | Verdict |
| --- | --- | --- |
| `typer>=0.12,<1.0` | runtime | Justified. Upper bound present. Pins the vendored-click surface `tests/test_brief.py` reaches through |
| `pydantic>=2.7,<3.0` | runtime | Justified: `models.py` and `validate/findings.py` both use `BaseModel`. Upper bound present |
| `pytest`, `pytest-cov`, `ruff`, `mypy` | dev | Standard |
| `pyshacl>=0.26` | dev | Correct: conformance only, never shipped |
| `hatchling>=1.27` | build | Standard |

Two runtime dependencies for a tool of this size is lean and both earn their
place. `uv.lock` is committed, CI installs with `--locked`, and free resolution
runs weekly in a separate workflow with its own badge — the reasoning for which
is recorded in the decision log and is correct.

**One observation, not a finding.** `typer<1.0` is a wide range for something the
test suite reaches into (`typer.main.get_command`). The weekly canary is what
catches a break there, which is the right mechanism; it is worth knowing that a
canary failure on `typer` is more likely to be a *test* break than a product
break, and the canary's own output should be read with that in mind.

---

## 6. Maintainability and technical debt

### The ledger

| Item | Where | Cost if left |
| --- | --- | --- |
| Identity resolution has no module, model or adversarial tests | `read/corpus.py:484` | Four security findings; nothing downstream can detect a step-3 error |
| `cli.py` mixes orchestration with rendering | `cli.py` | Grows with every command; invites assertions on formatted text |
| `reason` strings are free-form literals at construction sites | `read/corpus.py`, `build/writer.py` | A consumer must know five undocumented values; a sixth can appear unnoticed |
| `residual_risk.structural` states intent, not observation | `build/manifest.py:329` | A false statement in the authenticated document |
| Conformance verified on one machine, skipping silently | `ci.yml:68` | The headline claim can quietly stop being true |
| `_REPORT_LABELS` and `_assess_residual_risk` are both calibrated to this generator | `read/corpus.py:365`, `build/scrub.py:412` | Named for the first, undocumented for the second |
| No key rotation story | `deident/` | A holder who must rotate has no path and no documentation |

### What is explicitly *not* debt

No `shortcut:` comments exist in the tree. The deliberate omissions — the ITB
validator, chained re-pseudonymisation, age banding, a GUI, CDA/FHIR input — are
each recorded in the decision log with their reasoning, which is the correct
treatment: they are decisions, not debt, and the log makes them revisitable
rather than forgotten.

### The practice that is keeping this project healthy

`CLAUDE.md`'s decision log, the "rewrite in place" rule above it, and
`tests/test_brief.py` pinning one fact mechanically. Four of the findings in the
security audit were found *because* the log said what the author believed and the
code could be checked against it. A codebase whose documentation is reliable
enough to audit against is worth more than one with better tests and vaguer
prose.

The honest limit, which the log already states: exactly one fact in that file is
mechanically checked. Two candidates for the second and third, both cheap:
the set of `reason` values the manifest can contain, and the manifest schema
version against the shape `build` actually writes.

---

## 7. Recommended architectural improvements

In priority order. The first is the only one this review would call necessary.

### 7.1 Give identity its own module (necessary)

Extract a `read/identity.py` owning one job: turn a stream of parsed records into
a set of subjects, or into reported reasons why it cannot.

```python
@dataclass(frozen=True, slots=True)
class SubjectKey:
    """What makes two records the same person, and from which authority."""

    national_id: str  # validated and normalised, or empty
    authority: str  # normalised assigning authority or sending facility


class IdentityIndex:
    """Resolves records to subjects, or refuses and says why."""

    def establish(self, record: LabRecord) -> SubjectKey | Conflict: ...
    def resolve_record_number(self, mrn: str, authority: str) -> SubjectKey | Ambiguity: ...
```

What this buys, beyond fixing findings 1, 2 and 4:

- **It can be tested in isolation**, which is why the gaps in §4 exist: testing
  identity resolution today means building a corpus on disk and running the whole
  reader.
- **`Conflict` and `Ambiguity` become types**, so the five `reason` strings get
  one home and a test can pin the set.
- **`read_corpus` shrinks to iterate–parse–resolve–collect**, and becomes
  readable as a consequence.
- **The invariant becomes statable**: a subject has exactly one identity, and a
  record attaches to exactly one subject or is reported. Today that invariant is
  true only when the input is well-formed, and nothing says so.

Keep it a plain class with explicit methods. No registry, no strategy objects, no
plugin interface — the project's own standard, and there is one caller.

### 7.2 Make the build transactional (necessary for finding 3)

Stage, validate, publish, with the old root moved aside rather than deleted.
This closes findings 3 and 12 together and gives `build` the property its outputs
already claim: that a dataset is either the one described by its manifest or
absent.

Platform note: `Path.replace` is atomic for files on both platforms but not for a
non-empty directory on Windows, so publish is a three-step move, and the window
between steps must leave the old dataset recoverable. Worth a test on both
platforms, which the CI matrix already supports.

### 7.3 Separate rendering from orchestration in the CLI (worthwhile)

One `cli/render.py`. Not one module per command.

### 7.4 Close the measurement gap on grouping (worthwhile)

`measure` answers "did the planted identifiers survive". The missing companion
answers "did the records end up on the right person". The generator knows the
answer — it planted every record for a known subject — so this is the same shape
of work as `measure` itself and the same argument applies: the claim is currently
a promise.

The cheap version is a defect: `lab.placeholder_national_id` and
`lab.record_number_reused_across_sites`. Then the existing `measure` catches
finding 1's leak automatically, and the project's recurring lesson — "a path no
corpus reaches is a path nobody has measured" — stops applying to the fifth case.

### 7.5 Not recommended

- **Do not add a GUI.** The reasoning in the decision log of 2026-11-13 stands,
  and this audit adds one argument to it: the findings above are all about input
  the operator did not control. A GUI addresses none of them and adds a key
  surface.
- **Do not add a schema-validation library for the manifest.** `pydantic` is
  already present and `layout.py` already owns the key list; a third mechanism
  would be the invented schema the project rejected.
- **Do not redesign the de-identification.** It is sound. The findings are
  upstream of it.

---

## 8. Summary

| Dimension | Assessment |
| --- | --- |
| Architecture | Strong, with one missing layer: identity |
| Code quality | High. Documentation is reliable enough to audit against, which is rare |
| Data flow | Clear and traceable; one unguarded pivot at step 3 |
| Testing | Thorough on transformation, absent on grouping. 99.11% coverage coexists with 1 critical finding |
| Dependencies | Lean and justified; two runtime, both used, both bounded |
| Supply chain | Lockfile committed, CI installs locked, canary separate. Correct |
| Packaging | Clean. Wheel builds and installs into an empty environment; 11 commands run |
| Maintainability | Good, and actively maintained by the decision log |
| Compliance claims | Careful and defensible. No GDPR claim, no anonymisation claim |

**The one-sentence version:** commissura does the hard part well and has not yet
hardened the easy part, because the easy part only looks easy when the input comes
from its own generator.
