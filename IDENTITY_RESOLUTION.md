# Identity resolution

How `commissura` decides which records belong to the same person, what it
refuses to decide, and what changes for datasets built before 2026-11-13.

The policy lives in [`read/identity.py`](src/commissura/read/identity.py) and is
applied in one place, [`read_corpus`](src/commissura/read/corpus.py). Read this
before changing either.

---

## 1. Why this is its own module

The pipeline has a layer for parsing, a layer for de-identifying, a layer for
writing and a layer for validating. Until 2026-11-13 it had no layer for the
step between parsing and de-identifying: deciding who is who. That was two
dictionaries and four lookups inside `read_corpus`, and everything downstream
trusted its answer without being able to check it.

**A grouping error is not contained.** Targeted redaction — this project's whole
method — removes the identifiers the structured exports declared *for that
subject*. So two people merged under one key leave only one identity in the
known set, and the second person's name is never looked for. The audit built a
dataset containing `Paziente: FRANCESCA FONTANA`, in plain text, in the one
field the scrubber exists to redact, from two messages whose national identifier
was the string `UNKNOWN`. No error, no warning, no linkage issue.

Four things depend on step three being right, and none of them can tell when it
is wrong:

| What | How a grouping error reaches it |
| --- | --- |
| Redaction | A discarded identity is a name nothing looks for |
| Time | A split person gets two baselines, so `day_offset` stops describing one timeline |
| Attribution | A collided record number moves an imaging study to the wrong patient |
| `whois` | Returns one label for a person the dataset may hold under two, so an opt-out misses records |

---

## 2. Identity key types

A subject is established by exactly one key. The kind is recorded per dataset in
`.deident/manifest.json` under `source.subject_keys`, because the two are not
equivalent and a reader has no other way to tell them apart.

### `national_id`

A validated, normalised national identifier. **Relinkable across institutions**
under the same secret key: two hospitals holding the same key derive the same
subject label for the same person, which is the mechanism the Commission's EHDS
FAQ describes under Q49 as "hashing the identifiers before disclosure to the
HDAB".

Derivation input is the normalised identifier, unchanged from before this
module existed. That is what keeps every label ever issued from valid input the
same — see §7.

### `scoped_record_number`

An `(assigning authority, record number)` pair, used when the national
identifier is not usable but the record number is. **Not relinkable across
institutions**: a hospital's record number means nothing outside it, so two
holders cannot align these subjects even with the same key. Derived under its
own domain separator, `subject-mrn|`, so a record number can never produce the
label a national identifier would.

### No key

A record with neither a usable national identifier nor a record number cannot be
attributed to anybody. It becomes a `LinkageIssue` with reason
`no_usable_identifier` and does not reach the dataset.

---

## 3. What is never an identity key

| Class | Examples | Verdict |
| --- | --- | --- |
| Missing | `""`, `"   "`, `"\t\n"` | `missing` |
| Placeholder | `UNKNOWN`, `unknown`, `N/A`, `NONE`, `NULL`, `NOCF`, `SCONOSCIUTO`, `IGNOTO`, `ANONIMO`, `TBD`, `TEMP`, `TEST`, `DUMMY`, `UNK`, `XXX` | `placeholder` |
| Any single repeated character | `0000000000000000`, `XXXXXXXXXXXXXXXX`, `----` | `placeholder` |
| Wrong length or character classes | 15 or 17 characters, a digit among the name letters, a month letter outside the format's twelve, a day outside 1–31 or 41–71 | `malformed` |
| Check character fails | `RSSMRA80A01X000A` where the check character should be `Z` | `bad_checksum` |

**The principle: missing identity information is not evidence of shared
identity.** Two records that both failed to say who they belong to have told you
nothing in common. The old code keyed a subject on the raw string, so every
patient in an export whose identifier field was unavailable became the same
patient.

The deny-list is explicit rather than inferred, because a structural test alone
cannot distinguish `UNKNOWN` from a short malformed code and the two deserve
different diagnoses. **Order of the tests is load-bearant**: absence, then
placeholders, then structure, then the check character — so the diagnosis names
the earliest thing that is wrong. A checksum failure reported for `UNKNOWN`
would send an operator looking for a transcription error in a field that was
never filled in.

**An unusable value is kept, and that is not a contradiction.** Three roles, and
only the first is identity:

1. **Identity resolution** — only a validated identifier.
2. **Targeted redaction** — the raw value as the source wrote it, because a
   report may quote `Codice fiscale: UNKNOWN` and that line still has to be
   redacted or reported.
3. **Diagnostics** — the classification, reported as a linkage issue naming the
   status.

---

## 4. Normalisation

### National identifiers — `normalise_national_id`

Three transformations, each safe for a codice fiscale, each added because
leaving it out caused a real failure:

| Transformation | Why |
| --- | --- |
| NFKC | Folds the compatibility forms a copy-and-paste from a PDF or a spreadsheet introduces, full-width Latin letters above all: they look identical and compare unequal |
| All whitespace removed | The reader already stripped the ends. An internal space or a non-breaking space survived that and produced a second subject for one person |
| Uppercased | A codice fiscale is conventionally uppercase and a sender is not obliged to send it that way. One case difference produced two subjects with two different baselines |

**And nothing else.** A cleverer normaliser would start merging identifiers that
are not the same identifier, and in this direction a false match is far worse
than a miss.

### Validation — codice fiscale

Structure, then the check character, reusing
[`cf_check_character`](src/commissura/identifiers.py) rather than a second
implementation — the generator computes it, so the validator and the generator
cannot drift.

**Omocodia is handled, and this is the part a checksum-only implementation gets
wrong.** When two people would be assigned the same code, the Agenzia delle
Entrate substitutes letters for digits from the right, per DM 23 December 1976:

```
0→L  1→M  2→N  3→P  4→Q  5→R  6→S  7→T  8→U  9→V
```

Seven positions may be substituted — year (7–8), day (10–11) and the numeric
part of the place code (13–15), counting from one. The check character is
computed over the *substituted* form, so structure is validated after reversing
the substitution and the checksum is validated on the value as issued. A
validator that does not know this rejects genuine identifiers.

**What is deliberately not validated: whether the place code names a real
municipality.** This project's own synthetic identifiers use the unassigned `X`
range precisely so they are well formed and cannot belong to anybody, and
rejecting them would make the validator unusable against the only corpus
available to test it against. A place-code registry would also need maintaining
and would reject identifiers issued before a municipality was merged or renamed.

**Non-Italian schemes are not validated and are therefore not identity keys.** An
ENI or STP code, or any other country's national identifier, fails the codice
fiscale test and the subject falls back to its scoped record number. That is a
real limitation, stated here rather than discovered: a dataset of foreign
patients will be keyed entirely on record numbers and will not be relinkable
across institutions. Extending this means adding a scheme to
`classify_national_id` with its own validator, and the `IdentifierStatus`
vocabulary already has room for it.

### Record numbers — `normalise_record_number`

Strips whitespace, strips leading zeros, folds case. That recovers the
`imaging.mrn_format_drift` defect — the same patient as `0012345` in one export
and `12345` in another.

**Stripping leading zeros widens the collision surface, which is why it may only
be applied within an authority.** `0012345` at one hospital and `12345` at
another are two keys now, where a flat index made them one.

### Authorities — `normalise_authority`

Case and internal spacing only. An institution's name is prose and arrives with
inconsistent whitespace; it is not an identifier, and two genuinely different
hospitals can have names differing in little more than punctuation.

---

## 5. Assigning authority

A medical record number is a hospital's own number, and two hospitals both
number their patients from 1. An unscoped index is therefore wrong in any corpus
assembled from more than one site, and the audit proved it: two patients at two
institutions sharing the number `1787493`, one imaging study carrying it, the
study silently attached to whichever message's filename sorted last.

### Where the authority comes from

| Source | Field | Note |
| --- | --- | --- |
| HL7 v2 | PID-3 component 4 | Authoritative: it describes the *identifier* |
| HL7 v2 | MSH-4 | Fallback: it describes the *message*, which is usually but not always who issued the number |
| DICOM | `(0008,0080) InstitutionName` | The only institutional identifier a DICOM header reliably carries |
| Free-text report | — | None. A report header names no facility |

**Read only from the record-number repetition.** There is deliberately no
fallback to "whichever PID-3 repetition names an authority": the national
identifier's repetition names `MINSAL`, the ministry that issues codice fiscali,
and taking that as the authority for a record number would scope every
hospital's numbering under one national namespace — the flat index this change
exists to remove, reintroduced under a plausible-looking name. A test pins it,
and the first version of the function had exactly that bug.

### When there is none

An authority is **never invented**. A record number whose authority is unknown
goes into one shared namespace, `(unscoped)`, which is right for the single-site
export that is the common case.

Every record number is registered **twice** when its authority is known: once
scoped, once unscoped. A report header and some DICOM headers can only look a
number up unscoped, and in a single-site corpus that must still work. Where two
institutions share a number the unscoped entry becomes ambiguous and resolves to
nothing, while the scoped lookups still succeed for whoever can name their
institution.

---

## 6. Ambiguity

**Never resolved. Refused.** Not the first record, not the last, not the one
whose filename sorted higher.

When two different subjects claim one scoped record number, that index is marked
ambiguous and every record resolving through it becomes a `LinkageIssue` with
reason `ambiguous_record_number` — including the record that claimed it first.
The laboratory records themselves are unaffected, because their own national
identifiers established them: only the lookup that cannot tell two people apart
fails. That is safe partial processing rather than an aborted run.

**Deterministic by construction.** The ambiguity set is monotone — a key never
stops being ambiguous once it is — so the result depends on the *set* of records
seen and never on the order they were read. The old code's did: the last
assignment won, and "last" meant whichever filename sorted highest. A test
asserts that reading the same records in two orders gives the same answer.

### Conflicting identity under one valid identifier

Two records sharing a checksum-valid codice fiscale but naming different people
— a different family name or a different birth date — are **kept as one
subject** and reported with reason `conflicting_identity`.

Not split, because there is nothing to split them on: the identifier is
checksum-valid and encodes the surname, the birth date and the sex, so identity
is established and the disagreement is a data-quality finding. Both identities
are retained so that **both names reach redaction**, which is the property the
old model lacked.

Compared only on the family name and the birth date. A different record number
is normal across institutions, and a different given name is common enough in
real exports — a middle name, an abbreviation — that reporting it would bury the
cases that matter.

### The reasons a reader will see

Enumerated in `RefusalReason`, because they reach the manifest and are therefore
an interface:

| Reason | Means |
| --- | --- |
| `no_usable_identifier` | Neither a usable national identifier nor a record number |
| `invalid_national_identifier` | Identifier unusable; the record was attached by its scoped record number, and the subject is not relinkable across institutions |
| `ambiguous_record_number` | More than one person uses that number at that authority |
| `conflicting_identity` | Two records under one valid identifier name different people |
| `unlinked_report`, `unlinked_imaging` | Nothing in the corpus holds that identifier |
| `unreadable_lab_message`, `unreadable_report`, `unreadable_imaging_metadata` | The file could not be parsed |

`LinkageIssue.detail` is for a terminal only. It names the identifier it could
not match, and that identifier is patient data — the decision of 2026-11-12.

---

## 7. Compatibility and migration

### Pseudonyms are unchanged for valid input

`RULE_VERSION` moved from `1.0.0` to **`1.1.0`**, a minor bump, and the claim is
precise.

A subject established from a well-formed codice fiscale derives from the
normalised identifier, and a well-formed codice fiscale normalises to itself. So
the derivation input is byte-for-byte what it was. **Verified rather than
assumed**: every subject label in the twenty-five-subject walkthrough corpus is
identical before and after, and so is every label in a second four-subject
corpus. A 1.0.0 dataset built from valid identifiers remains linkable with a
1.1.0 one under the same key.

### What does move, and what to do about it

| Case | Before | After | Action |
| --- | --- | --- | --- |
| All identifiers well formed | *n* subjects | the same *n* labels | None. Nothing moves |
| An identifier written in lower case, or with internal whitespace, or compatibility-encoded | One label per spelling | One label per person | Rebuild. The old labels were wrong: one person held two or more |
| Records sharing a placeholder | One subject holding several people | One subject per person, keyed on scoped record numbers | Rebuild. The old dataset's redaction was incomplete — see §1 |
| A record number shared across institutions | Studies attached to whichever file sorted last | Attached by institution, or reported ambiguous | Rebuild and read the linkage issues |

**A rebuild is the migration.** Milestone B made that safe: a build publishes
exactly what the current corpus produced and nothing survives from a previous
one. There is no in-place upgrade path and there should not be — a dataset whose
subjects were merged wrongly cannot be corrected by relabelling, because the
records inside a merged subject have to be separated first.

**What a holder should do before rebuilding.** Run the build and read
`source.subject_keys` and the linkage issues. A dataset where
`scoped_record_number` is non-zero holds subjects that are not relinkable across
institutions, and an export that produces many of those has an identifier
mapping problem worth fixing upstream before release.

### API compatibility

| Symbol | Change |
| --- | --- |
| `Pseudonymiser.subject_label(national_id)` | Unchanged signature and unchanged output. Callers must now pass the *normalised* identifier; `build` and `whois` both go through `normalise_national_id` |
| `Pseudonymiser.subject_label_for(key)` | New. Takes an `IdentityKey` and picks the domain separator |
| `Subject.identity` | Still there, now a property returning the first identity observed |
| `Subject.identities` | New. Every identity observed for the subject |
| `Subject.key` | New. What established the subject |
| `KnownIdentifiers.identity` | **Removed**, replaced by `identities: tuple[Identity, ...]`. A breaking change, and deliberately not papered over with a compatibility property: a caller passing one identity where the field now takes a tuple is a caller whose redaction would be incomplete, and that must not compile |
| `read_lab` | No longer raises when the national identifier is unusable. It parses; the index decides |
| `LabRecord.assigning_authority`, `.scope` | New |
| `ImagingRecord.institution_name`, `.scope` | New |
| `read.corpus.normalise_identifier` | **Removed.** Every caller now uses the scoped `normalise_record_number`, and leaving a second normaliser nobody calls is how two functions come to disagree |
| `commissura whois` | Now refuses an unusable identifier with exit code 2 rather than deriving a label for nobody |

### CLI compatibility

No option was removed or renamed. `build` gained no flag — in particular no
`--force`, and a test asserts it does not exist. `whois` gained an output line
naming the normalised identifier, and a new exit code 2 for an unusable one.

---

## 8. Known limitations

1. **Only the codice fiscale is validated.** Any other national scheme falls
   back to a scoped record number. §4 says what adding one takes.
2. **An unscoped corpus is still one namespace.** A single-site export whose
   messages name no facility at all gets the old behaviour, with the ambiguity
   check as the backstop. That is the best available: inventing an authority
   would be worse than sharing one.
3. **A report header carries no facility**, so a report's record-number fallback
   is always an unscoped lookup. Supporting CDA R2 or FHIR, which state the
   patient in a structured header, removes the need for the fallback entirely —
   the input roadmap recorded on 2026-11-13.
4. **Identity conflict is reported, not resolved.** Two records naming different
   people under one valid codice fiscale stay one subject. Splitting them would
   need a tiebreaker the data does not contain.
5. **`conflicting_identity` compares two fields.** A disagreement in sex, or in
   address, is not reported.
