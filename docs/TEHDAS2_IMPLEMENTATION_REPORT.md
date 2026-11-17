# Implementation report

What was read, what was changed, what was tested, and what was not done.
2026-11-17, from `682d839`.

**This document does not declare conformance.** It reports work done against
three TEHDAS2 guidelines, which are not law. The EHDS implementing acts for
Articles 77 and 78 are due March 2027 and do not exist; Italy has not designated
a health data access body; nobody outside this repository has assessed this
tool. Nothing here should be quoted as evidence that `commissura` is
EHDS-conformant, GDPR-compliant, a certified anonymisation tool, or a secure
processing environment.

---

## 1. What was read

Three documents, 294 pages, in full where they bear on a data holder and
selectively where they do not:

| | Pages | Read in full |
| --- | --- | --- |
| D6.1 — guideline for **health data holders** | 69 | §3 legal framework and mandatory process, §3.6.2 data preparation with Table 2, §4 pathways, §5.1.1 maturity, Annex 6 checklists |
| D7.2 — guideline for HDABs on minimisation, pseudonymisation, anonymisation and synthetic data | 89 | §3 data minimisation with all five dimensions, §4 pseudonymisation in full, §5.5 guidelines in full, §6 recommendations |
| D7.4 — technical specification for HDABs on secure processing environments | 136 | §3 scope, §5.3 Table 5.1, §5.4.1 export control, §5.6.1 the data holder API, Annex 1's requirement modality. The 26 pages of operational requirements were searched rather than read, for the reason below |

Fifty-nine requirements were extracted with section and page references into
`TEHDAS2_GAP_ANALYSIS.md`. They are classified by modality — legal obligation,
*Mandatory* in the document's own checklist marking, MUST under IETF BCP 14,
recommended, advisory — because the three documents use three different
conventions and conflating them would manufacture obligations.

### The reading that shaped everything else

**D7.4 is not commissura's document.** Table 5.1 (p. 32–33) lists 18 EHDS-derived
SPE requirements with a named responsible role for each. Exactly one is the data
holder's: EHDSR-11, upload the permitted data to the environment. Across the 26
pages of operational requirements the phrase "data holder" appears only in the
role definitions and the interface chapter. Scoring those against a local CLI
would have produced a hundred gaps belonging to somebody else — and would have
been the first step toward turning a data-preparation tool into a platform.

**D7.2 is not commissura's document either, but it describes commissura's
method.** D6.1 §3.6.2 (p. 27) makes pseudonymisation the access body's duty,
delegable to the holder, and adds that "it is good practice that personal
electronic health data are pseudonymised or anonymised as close as possible to
the data source". D7.2 §4.3 (p. 38) then names the holder in three of its
data-preparation scenarios. So its §3 and §4 are the specification for what this
tool does, written by the party that approves it.

**D6.1 is commissura's document**, and its Annex 6 A6.2 (p. 67–68) is the
closest thing to a requirements list this project has ever been handed.

---

## 2. What the reading confirmed

Worth recording first, because the honest headline is that the method was
already the one these documents describe.

| Already implemented | Sourced to |
| --- | --- |
| HMAC with a secret key, not a plain hash | D7.2 §4.4 (p. 40) — "Use of unsalted hash functions used on direct identifiers… does not qualify as pseudonymisation." The stack decision of 2026-11-06 rejected `hash(national_id)` in those terms |
| Relative day offsets instead of calendar dates | §3.3.3 (p. 24) — "absolute dates are variables that should be avoided when not essential and replaced by relative timespans" |
| Birth dates removed, never offset | §3.3.1 (p. 22) — "Date of birth and Date of death are strong quasi-identifiers and should be avoided whenever possible" |
| Separation of secret from data | §4.5 (p. 41) — "Separation must be implemented between pseudonymisation secrets and pseudonymised data" |
| Deterministic policy | §4.4 (p. 41) — advisable in the EHDS, so the data user can recognise the same patient |
| Post-quantum consideration | §4.4 (p. 40). HMAC-SHA256 is symmetric |
| A machine-readable de-identification record, in this project's own schema | §5.5.1 (p. 51) — "Standard structure for anonymised or synthetic data documentation is currently not existing and should be developed." The decision of 2026-11-07, "Ours. Nobody else specifies it", is now sourced |
| **The manifest carries nothing derived from the input** | §5.5.1 (p. 51) — "The documentation shall not contain personal or identifying information relating to the data subjects." Four audits found four violations of this clause before anybody read it |
| Detection across subjects, care personnel and care organisations | §5.5.8 (p. 57) names exactly that triple, which is the structure `KnownIdentifiers` already had |
| Reporting rather than scoring free-text residual risk | §3.3.2 (p. 24) — identifier removal in unstructured data "less deterministic compared to… structured data" |
| Rule-based filtering over NER | §5.5.4 (p. 54) lists both and requires neither |
| HealthDCAT-AP for the Art. 77 description | D6.1 §3.4.2 (p. 19) — "its use is expected to support implementation of the metadata obligations adopted via implementing acts under Article 77(4)" |

All 14 mandatory non-public HealthDCAT-AP properties were already emitted, plus
the conditional `hasVariables`, SHACL-checked against the profile's own shapes.

---

## 3. What was changed

Five items. All additive; none changes existing behaviour by default.

### 3.1 Permit-scoped pseudonymisation

**The one MUST in 294 pages that `commissura` was failing.** D7.2 §4.4 (p. 41):
"Pseudonyms MUST NOT be reused across different data permits, to minimise risks
of intentional or unintentional linkage of data by the data user."

One key gave one label space for ever. Nothing in the tool knew what a permit
was. A holder answering two permits from the same key handed the same subject
labels to two data users, which is the unevaluated linkage that requirement
exists to prevent — and `keygen`'s own output actively discouraged making a
second key, because replacing one orphans every dataset built with it.

```
permit_key = HMAC-SHA256(key, "permit|" + permit_reference)
subject_id = HMAC-SHA256(permit_key, "subject|" + national_id)[:12]
```

`build --permit`, `whois --permit`. `verify` needs no flag: the dataset records
which permit it answers, so verification reads it from the manifest — one fewer
thing an operator can get wrong, and getting it wrong would report a sound
dataset as unauthenticated, which reads as tampering.

**A subkey rather than a wider HMAC input, and that is what makes it safe to
add.** Folding the permit into the `"subject|"` input would move every label in
every dataset ever built here. A subkey is unreachable without the flag, so a
build without one is byte-identical to before — asserted against
`Pseudonymiser(KEY).subject_label`, the untouched function that produced every
label this tool has issued, rather than against a second build, which would only
prove the two agree with one another.

### 3.2 The quasi-identifier channels

D7.2 §4.5 (p. 41) makes two things an explicit activity: identifying
quasi-identifiers and "handing over information on them to the data minimisation
process", and providing health-specific ones "beyond what is in the EDPB
guidelines (e.g., dates of visits in the hospital also become quickly
identifying)".

`risk_report.json` is that hand-over and it was under-reporting. It named the
participant columns and counted laboratory analyte rarity. **It said nothing
about the day-offset sequence** — the strongest channel in the dataset, kept on
purpose, documented in the README since 2026-11-11 and absent from the
machine-readable artefact. A reader trusting the file over the prose, which is
what a machine-readable file is for, would have generalised age and sex and
shipped a dataset in which every subject's timeline was intact and exactly
aligned.

The reason it was missing is worth naming because it generalises: **k-anonymity
cannot score it.** k counts people sharing a combination of attribute values, and
a sequence of offsets is not an attribute with a value domain. So the channel
fell outside the measurement, and then outside the report. Each entry now
carries `scored`, and when that is false, why not and what mitigating it would
cost. Four channels are reported, derived from the dataset rather than declared.

### 3.3 The pseudonymisation declaration

D7.2 §4.4 (p. 40) asks a controller generating cryptographic pseudonyms to save
"function used, exact specification of inputs, value of salt"; §4.3 (p. 37) asks
the catalogue record to state whether the method is reversible; §4.3 (p. 38) has
the access body *approve the algorithm*.

None of that was reconstructable from a manifest carrying a key fingerprint and a
rule version — it lived in a module docstring and in the project brief. A
`pseudonymisation` section now states the algorithm, each domain prefix and what
it derives, the output length, the policy, the scope, and the reversibility.

**Including the part that is unflattering.** By D7.2 §4.2's definition — a scheme
is reversible exactly when the mapping secrets are kept — this one is
irreversible, which the document discourages. So the section says so, and
separates the consequences: an opt-out works, because it starts from a named
person and `whois` derives forward; the return of a significant finding does not,
because it starts from a row. That was a known architectural limit with no
statement anywhere a recipient would read it.

### 3.4 Documentation traceability

D7.2 §5.5.1 (p. 51): "Appropriate mechanisms shall be in place to maintain
traceability across documentation updates, enabling verification of how the
documentation has evolved over time."

A rebuild replaced the manifest and left no trace that a previous dataset had
existed. That is the withdrawal of 2026-11-13 seen from the documentation side:
the holder acts on an objection, the new dataset is correct, and nothing says why
the counts moved or that anything moved. The manifest now names its predecessor
by timestamp, authentication tag and schema version — three fields and no counts,
because the predecessor's numbers describe data this dataset may no longer hold.

This is only possible because builds are staged: the predecessor has to be read
while the destination still holds the previous build, and after `publish` it is
gone.

### 3.5 The cohort's age range

`healthdcatap:minTypicalAge` and `maxTypicalAge`, derived from the published
`participants.tsv`. D7.2 §3.1 (p. 18) recommends that holders "specify any
standard data minimisation rules that are applicable by default to the datasets
offered"; §3.3.1 (p. 22) asks that age be exact only when indispensable, and an
applicant cannot judge that without knowing the range.

Both are `xsd:nonNegativeInteger` under the profile's own value constraints, so
no IRI is invented. Ages above the ceiling are carried as `90+`, so a cohort of
nothing but those publishes no range — omitted rather than reported as zero,
because both properties are recommended and `0` would be a false statement where
silence is accurate.

### 3.6 And a guard against this work being misread

Six documents with TEHDAS2 in their names are exactly what a reader would
mistake for an assessment against the Regulation. "Aligned with TEHDAS2" becomes
"EHDS-ready" in a README and then "compliant" in a conversation, and nothing in
the repository would contradict it. `tests/test_claims.py` forbids four claims —
EHDS conformance, GDPR compliance, SPE certification, and that this tool
anonymises — and requires any file discussing one to declare what it is not.

---

## 4. Verification

Everything below was run, not inferred.

| | Before | After |
| --- | --- | --- |
| Tests passed | 987 | **1063** |
| Skipped | 2 | 2 |
| Failed | 0 | **0** |
| Branch coverage | 99.19% | **99.40%** |
| `ruff check` | clean | clean |
| `ruff format --check` | clean | clean |
| `mypy` (strict) | clean | clean |

The two skips are unchanged and both are Windows platform limits:
`tests/test_keys.py:126` (POSIX file modes are not honoured) and
`tests/test_publish.py:568` (symlink creation needs elevation).

76 tests were added across four files: `test_permit_scope.py` (30),
`test_claims.py` (27), `test_quasi_identifiers.py` (10),
`test_documentation_requirements.py` (9).

### Checked by sabotage

This project's rule is that a guard nobody has watched fail is a guard nobody
has tested. Each new guard was broken in turn, the relevant suite was run, and
the file restored. **All ten were caught:**

| Sabotage | Caught by |
| --- | --- |
| `scope_to_permit` returns the key unchanged | `test_permit_scope.py` |
| `build` ignores `--permit` | `test_permit_scope.py` |
| `verify` does not scope the key | `test_permit_scope.py` |
| The declaration claims to be reversible | `test_permit_scope.py` |
| The interval channel is dropped | `test_quasi_identifiers.py` |
| An unscored channel stops saying why | `test_quasi_identifiers.py` |
| The predecessor link is never recorded | `test_documentation_requirements.py` |
| The age range is not emitted | `test_documentation_requirements.py` |
| The README claims GDPR compliance | `test_claims.py` |
| A document discusses compliance with no disclaimer | `test_claims.py` |

### The walkthrough is unchanged

Re-run end to end with the README's own arguments, and every captured number is
identical: 3648 PHI spans, 366 defects, 847 free-text redactions, 29 linkage
issues, 3 dropped records, minimum k = 1 with 21 combinations below 5, and
`conforms` with 0 errors and 7 warnings. No file was added or removed, so the
digest list and the file counts did not move either. Nothing to recapture.

### Two existing guards fired, which is the most reassuring result here

**`test_the_manifest_never_carries_the_key` caught the new section twice.**
`layout.FORBIDDEN_MANIFEST_KEYS` is a plain text search over the whole manifest
for `key`, `secret`, `secret_key`, `hmac_key` and `password`, because a manifest
property with one of those names is what a leaked secret would look like and
nobody should have to read the value to find out.

It rejected a field I had called `secret` — now `salt_custody`. Then it rejected
a *value* of `"key"` on the new `scope` field, which is where the interesting
decision was: the guard is crude because a text search is the only thing it can
be, and loosening it to parse property names would have weakened a guard
protecting the one secret this project has. The values became `key-wide` and
`permit-scoped`, which read better anyway. This is the second time that guard has
renamed a field here, after `key` became `field` in the per-input table on
2026-11-10.

**And the SHACL conformance suite passed the two new properties unchanged**,
against HealthDCAT-AP Release 8's shapes, its `range.ttl`, and the DCAT-AP 3.0.0
shapes and class ranges it imports.

### The new guard found something on its first full run

`test_claims.py` failed on `CLAUDE.md` — the project brief, which discusses all
four forbidden claims at length in its decision log and carried no statement of
what it is not. That is the guard doing exactly its job on the file where it
matters most: the brief is what a new session reads first, so it is where an
overclaim would propagate from. It now carries the disclaimer, and says in it
that a test put it there.

---

## 5. What was not done, and why

Four items are deferred with designs in `TEHDAS2_REMEDIATION_PLAN.md`, and the
reasons are not evasions:

| | Why not |
| --- | --- |
| **Age banding** (D7.2 §3.3.1) | The guideline supplies the *what*, not the *how wide*, and the width is a judgement about a cohort and a permit. **This is the item whose status changed most**: the 2026-11-13 decision deferred it for want of a user who had asked, and the ask now exists with a date and a page number. It moves from speculative to queued |
| **Opt-out exclusion** (D6.1 A6.2, *Mandatory*) | Two interface decisions unmade: subject labels or national identifiers, and whether an exclusion matching nothing is an error. A holder who mistypes a label and sees a successful build has not acted on the objection. The highest-value of the four |
| **Permit-driven field and row selection** (D6.1 A6.2, *Mandatory* ×2) | Needs a permit model, and the permit and data-access-application templates are implementing acts expected March 2027. Inventing a schema now means inventing the thing the Commission is about to specify |
| **Trade-secret metadata flag** (D6.1 A6.1, *Mandatory*) | The profile property to carry it is not sourced. A reading job, not a coding job |

And one that was considered and rejected within this round:
`dpv:hasPersonalData`, which D7.2 §4.3 explicitly names. The Release 8 shapes
place **no value constraint** on it — only a path and a severity — so the DPV
concept to use is unsourced. Writing a plausible IRI is the trap this project
recorded on 2026-11-07, when it found one authority list served over https and
another over http: an IRI that looks entirely right and resolves to nothing.
It is an open question in the remediation plan rather than a guess in the code.

External de-identification engines were **not** integrated. The composition
point already exists — `read_corpus` globs three patterns and reads whatever is
there, so a holder can run Microsoft's FHIR or DICOM anonymiser, or Mainzelliste,
or ARX, as a step before `build` with no code here at all. What was verified is
that this works and that it would require one manifest change: D7.2 §5.5.1 asks
for "tools, software and platforms used (with versions)", and `tool_versions`
records only this tool's. A record that silently omits half the processing is
worse than one that says it covers half. Both findings are in
`ARCHITECTURE_TARGET.md` §4 so the next person does not re-derive them.

---

## 6. Honest assessment

`commissura` implements one step of the EHDS secondary-use chain — a health data
holder's first pseudonymisation — and the TEHDAS2 reading confirms that the
method, the invariants and the documentation form are the ones these guidelines
describe. Several decisions this project took for its own reasons turn out to
match requirements published afterwards: keyed rather than plain hashing,
relative intervals rather than calendar dates, removing birth dates rather than
shifting them, and a de-identification record that carries nothing derived from
the input. The last of those was found four times the hard way before anybody
read the clause requiring it.

One published MUST was unmet and is now met when the holder invokes it. Two
documentation requirements were partly met and are now met. Two mandatory
checklist items from D6.1 — permit-driven record and variable selection — are not
met and cannot honestly be met before the March 2027 templates exist. One more,
opt-out exclusion, is not met and is next.

Where the tool diverges from a guideline it diverges toward caution, and that
has a cost worth stating plainly: institution names, addresses and ordering
clinicians are **removed** where D7.2 asks for them to be pseudonymised or
obfuscated, so a multi-site or by-clinician study cannot be done on this output
at all, and the manifest reports it as `removed`, which reads as success.

What stands between this and being usable by a data holder is not in this
report. It is that report-prose identity parsing is written against four header
strings this project's own generator invented, that the package is not
published, and that nobody has run it on real data. The gap between a sound
data-preparation component and "EHDS-ready" is governance, not code.
