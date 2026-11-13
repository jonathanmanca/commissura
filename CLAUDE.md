# commissura — project brief

> Context handoff. Read this first in any new session.
>
> **How to keep this file true.** Everything above the decision log describes
> the present and is **rewritten in place**: when a fact changes, edit the
> sentence that states it and delete what it replaced. Only the decision log is
> append-only, because it is a log. Appending a correction beside the text it
> corrects is how this file rotted once already — three paragraphs each
> claiming a more complete version of the same fact, in increasing order of
> truth, and only the last one accurate.

## What this is

A command-line tool (plus Python library) that turns raw clinical material —
HL7 v2 lab messages, free-text reports, DICOM imaging metadata — into a
**standardised, de-identified, research-ready dataset** with a verifiable
manifest.

One-line pitch: *BIDS exists for neuroimaging; nothing equivalent links lab
results and clinical reports to the same subject. This builds that bridge.*

The name is the commissure — the fibre bundle joining two hemispheres that
would otherwise not communicate. Say this once in the README; it is the kind of
detail that makes a repo memorable.

## Why it exists

EU Regulation 2025/327 (European Health Data Space) makes secondary use of
health data a legal obligation for data holders. The access mechanism is a data
permit issued by a Health Data Access Body plus a patient opt-out — **not**
case-by-case consent. Hospitals, IRCCS and labs will have to produce
structured, de-identified, documented datasets and mostly have no idea how.

Dates that matter (from the Commission's EHDS FAQ, 26 March 2026):

| Date | What |
| --- | --- |
| 26 Mar 2027 | Key implementing acts adopted, incl. **Art. 77(4) dataset descriptions** and **Art. 78(6) data quality and utility label**. Member States designate digital health authorities; Italy's HDAB due. |
| 26 Mar 2029 | Chapter IV secondary use applies for most Art. 51 categories — **including EHR data, i.e. this project's scope**. Data holders must have submitted dataset descriptions to their HDAB. |
| 26 Mar 2031 | Remaining categories: genomic and other -omics, clinical trial data, research cohorts, determinants of health. |

So the relevant window is 2029, and the specification this project must match
lands in **March 2027** — sixteen months out, via comitology with mandatory
public consultation. Watching that consultation is part of the plan.

Secondary goal, equally important: this is a portfolio project to build real
software-delivery skills (packaging, testing, CI, documentation,
deployability), which is the gap in the author's profile.

## Hard constraints

- **Synthetic data only.** No real patient data ever enters this repo, in any
  form, at any time. All fixtures are generated.
- **Runs locally.** No service to install in a hospital, no network component,
  no accreditation needed.
- **Cross-platform**, Python >= 3.11, CLI + importable library, `--json`
  everywhere so the tool composes inside someone else's pipeline.
- **Deployable by a stranger**: `pip install`, README in English, working demo.
  If someone has to ask the author how to run it, that's a bug.

## Alignment decision: HealthDCAT-AP

The manifest must not be an invented schema. The HealthData@EU Pilot (concluded
Dec 2024) produced **HealthDCAT-AP**, an RDF extension of DCAT-AP for health
datasets, built explicitly against EHDS Art. 77 — source, scope, main
characteristics, nature of the data, access conditions. It is the most likely
basis for the 2027 implementing act.

Read before touching the manifest schema. **Go to the source repository, not the
rendered site** — both the old `healthdcat-ap.github.io` address and the current
`data.health.europa.eu/healthdcat-ap/releases/latest/` are dead ends for a
script: the first is decommissioned, the second is client-side rendered and
returns zero bytes to a plain fetch.

The specification's source is a public GitLab repository, and its REST API
returns plain JSON with no JavaScript:

- Repo: https://code.europa.eu/healthdataeu/healthdcat-ap (CC BY 4.0, branch `main`)
- File tree: `https://code.europa.eu/api/v4/projects/healthdataeu%2Fhealthdcat-ap/repository/tree?ref=main&recursive=true&per_page=100` (paginate with `&page=`)
- One file: `https://code.europa.eu/api/v4/projects/healthdataeu%2Fhealthdcat-ap/repository/files/<url-encoded-path>/raw?ref=main`
- Whole repo as a zip: https://code.europa.eu/healthdataeu/healthdcat-ap/-/archive/main/healthdcat-ap-main.zip

What is in there, per release (`public/releases/release-<n>/`):

| Path | What it is |
| --- | --- |
| `context/healthdcat-cardinality-rules.json` | **The cardinalities, machine-readable.** Start here. |
| `context/dcat-ap.jsonld` | JSON-LD context: short names to IRIs. |
| `html/shacl/public-shapes.ttl` | SHACL for the public tier, plus `_recommended` variant. |
| `html/shacl/non-public-shapes.ttl`, `restricted-shapes.ttl` | The other two tiers, plus `_recommended` variants. |
| `shacl/dcat-ap-SHACL.ttl`, `shacl/ranges.ttl` | Base DCAT-AP shapes and property ranges. |
| `html/examples/healthdcatap*.ttl` | One worked example per health-specific property. |
| `html/index.html` | The rendered specification itself. |

Health-specific properties, read off the example filenames (names confirmed,
cardinalities not yet): `analytics`, `codingSystem`, `hasCodeValues`,
`hasCodingSystem`, `hdab`, `healthCategory`, `healthTheme`, `legalBasis`,
`minTypicalAge`, `maxTypicalAge`, `typicalAge`, `numberOfRecords`,
`numberOfUniqueIndividuals`, `personalData`, `populationCoverage`,
`publisherNote`, `publisherType`, `purpose`, `retentionPeriod`,
`trustedDataHolder`. It also reuses DPV (`dpv:hasLegalBasis`,
`dpv:hasPersonalData`, `dpv:hasPurpose`) and DQV (`dqv:hasQualityAnnotation`).

**Release: 8, decided 2026-11-07.** The repository carries releases 5 through 8;
the rendered site still serves 5 as "latest". 8 ships a packaged SHACL validator
that 5 does not, so conformance can be checked against the profile's own tool.
Pinned in `healthdcat.RELEASE`.

**The obligation table is already transcribed** into
[`commissura/healthdcat.py`](src/commissura/healthdcat.py): 57 properties × 3
tiers, with cardinalities, obligations, the one conditional rule, and
`SOURCE_URL` so it can be re-checked. Read that module rather than re-fetching.

The three-tier split (public / non-public / restricted) is a finding worth
absorbing: the profile distinguishes what may be published openly from what is
restricted, and 14 of the 57 properties genuinely differ between tiers, so
"conformant" is not one claim but three. A dataset description must declare its
tier.

**Read and encoded**, all of it in that module: the cardinality table; all three
tiers' shapes with their value constraints — node kinds, datatypes, the
`sh:hasValue` on `dct:accessRights`, the CSVW structure behind `hasVariables`;
and four authority lists. `healthcategories.rdf` (17 concepts) and
`data-theme.rdf` (14) are transcribed whole. From `access-right.rdf` only the
three values the tiers pin, with their definitions, because no tier refers to
the other four. From `dataset-type.rdf`, 22 concepts of 25; the three omitted
carry a character the source renders ambiguously and none of them describes
clinical data. Nothing blocking remains before `build` can emit a dataset
description.

**The constraint set is now read in full**: HealthDCAT-AP's `ranges/range.ttl`
(14 class ranges on `dcat:Dataset`, 2 on the CSVW structures), the DCAT-AP
3.0.0 shapes including `Agent_Shape` and `PeriodOfTime_Shape`, and DCAT-AP's
own `range.ttl` — 84 class ranges that the profile intends to import and, by a
defect, does not. All four files are loaded by the conformance test.

Still unread, now in order of how much they would change things:

1. `catalogue/health-theme.rdf` and `publisher-type.rdf` —
   `healthdcatap:healthTheme` is only recommended, and its shape says the
   controlled vocabulary does not exist yet, so this is lower value than it
   looks.
2. The packaged validator in `html/shacl/HealthDCAT-AP_validator/`, which is why
   Release 8 was chosen. **No longer blocking**: conformance is proven against
   the same shapes with `pyshacl`, and the decision log records why the ITB
   validator itself was not installed. What is left is the question below about
   which DCAT-AP version its configuration actually loads.

The validator config also ships `catalogue/dcat-ap_2.0.1.rdf`, which is worth a
glance: the shapes import DCAT-AP **3.0.0** while the catalogue carries 2.0.1,
and it is not yet clear which one the packaged validator actually loads.
- D6.1 Extension of DCAT-AP: https://zenodo.org/records/15088611
- D6.2 recommendations (incl. "how to break a warehouse into logical datasets"):
  https://zenodo.org/records/15085025
- D8.2 quality control, assurance & provenance: https://zenodo.org/records/15096761
- D8.1 standards for interoperability and exchange: https://zenodo.org/records/15096755
- Open-source catalogue components: https://code.europa.eu/healthdataeu/healthdataeu-eu-dataset-catalogue
  — check for an existing HealthDCAT-AP validator before writing one.

Target claim: *commissura emits HealthDCAT-AP-conformant dataset descriptions.*
That sentence is worth more than any feature.

The quality/utility label (Art. 78) gives a general assessment plus
per-characteristic detail (documentation, accuracy, ...) and is **mandatory for
datasets whose collection was publicly funded**. The EU project QUANTUM is
developing the criteria. The `risk` command should grow toward this, not toward
an invented metric.

## Where commissura sits in the chain

**Answered 2026-11-10 from the Commission's FAQ. commissura is a health data
holder's tool, and both of its outputs are the holder's deliverables.**

Q49 asks who performs pseudonymisation and anonymisation. The answer is
**both, or either**: recital 72 says it "should be possible for
pseudonymisation and anonymisation to be carried out by health data access
bodies or by health data holders", and as early as possible, which the FAQ ties
to GDPR data minimisation. Two things follow that matter here:

- **Ultimate responsibility rests on the HDAB**, in the FAQ's own words, but
  the actual work "might also be already carried out by the health data holder".
  So `build` is a *first* pseudonymisation step, never the last one, and the
  HDAB may add more. This is the strongest argument yet for
  `.deident/manifest.json`: whoever adds the next step has to know exactly what
  the previous one did, field by field.
- Q49's second worked example describes a multi-hospital permit needing record
  linkage, and names the holder's operation as "hashing the identifiers
  before disclosure to the HDAB". That is what `subject_id` is. The design
  decision of 2026-11-06 turns out to match the mechanism the FAQ describes,
  which was luck rather than judgement and is worth knowing.

And **the dataset description is the holder's to submit**, which Q34 and Q35
settle rather than Q49: a health data holder of personal electronic health data
is *always* a controller (Art. 2(2)(t)), joint controllers must agree among
themselves who will "provide dataset descriptions", and a holder notifies IP or
trade secrets "when submitting the dataset description for inclusion in the
dataset catalogue in accordance with Article 60(3)". So emitting
`healthdcat-ap.jsonld` is squarely in scope for a holder's tool.

Two limits this exposes, recorded rather than fixed:

1. **Cross-holder linkage needs key distribution, which commissura does not
   address.** Q49's example has the *HDAB* linking records across hospitals.
   Deterministic HMAC gives two hospitals the same subject label from the same
   key, so the linkage works — but only if they share the key, and this tool
   deliberately keeps the key out of the dataset and says nothing about how it
   would travel. `key_fingerprint` in the manifest is what tells an HDAB whether
   two datasets are relinkable at all, and that is as far as it goes.
2. **commissura pseudonymises; it does not anonymise, and must never imply it
   does.** The FAQ treats the two as alternatives. Pseudonymised data is still
   personal data under the GDPR; anonymised data is not, which is exactly why
   the word is not ours to use. `risk` measures re-identification risk over
   quasi-identifiers and reports k; it does not certify anonymity, and k=1 on a
   small cohort is the honest reminder of that.

## Scope

In scope:
- Synthetic generator: multimodal subjects (lab messages, free-text reports,
  imaging metadata) with injectable, realistic defects and ground-truth PHI
  annotations.
- Dataset layout: BIDS-compatible, extended with `lab/` and `reports/`.
- Consistent pseudonymisation across modalities.
- `validate`: is this dataset conformant? What is missing?
- Manifest: HealthDCAT-AP-aligned, plus schema version, de-identification rule
  version, per-modality record of fields removed / replaced / kept, key
  fingerprint, tool versions.
- Risk report: k-anonymity over participant attributes, flag k < 5.

Explicitly **not** in scope (resist scope creep):
- Statistical analysis of the data — users bring their own tools.
- Writing a DICOM converter — orchestrate `dcm2bids` / `HeuDiConv`.
- LLM-based de-identification. General-purpose LLM tools have been shown to
  miss over half of clinical PHI. Rules first, measurement always.
- Any federated / platform / TRE ambitions. HealthData@EU covers the
  cross-border layer; Lifebit, Aridhia, TriNetX, Datavant and BC Platforms
  cover the commercial one. This project is the on-ramp, not the motorway.

## Pseudonymisation design (decided)

Single secret key, everything derives from it, key never enters the dataset:

```
subject_id  = HMAC-SHA256(key, "subject|" + national_id)[:12]   -> sub-a3f9c21b4e07
date_offset = HMAC(key, "offset|" + subject_id) % 730 - 365     -> stable +/- 1 year
dicom_uid   = prefix + HMAC(key, "uid|" + original_uid)         -> relinkable
```

Deterministic, domain-separated by prefix, useless without the key. Never plain
`hash(national_id)` — the identifier space is enumerable and trivially
brute-forced.

Dates: no absolute dates in the dataset, only `day_offset` from the subject's
baseline. Intervals stay exact. Age truncated at 89, "90+" above.

Imaging gotchas: identifiers hide in vendor private headers, series
descriptions, burned-in pixel annotations, and the head volume itself
(defacing required).

## Layout

```
dataset/
  dataset_description.json
  participants.tsv
  sub-<id>/ses-<n>/
    anat/ pet/ lab/ reports/
  derivatives/
  .deident/
    manifest.json
    risk_report.json
```

## Current state

Every command runs end to end: `generate`, `defects`, `validate`, `rules`,
`keygen`, `key-info`, `build`, `risk`, `verify`, `measure`, `whois`. A test
pins that list against the CLI's
own registrations, so it cannot quietly go stale again — which it had. Five of
them take a corpus from an empty directory to a dataset `validate` reports as
conformant, and the README's worked example is that run with its real output.

Underneath: `layout.py` as the single schema, an enumerable rule registry
behind `validate` (`commissura rules` lists it), ground-truth PHI annotations
with character offsets, HMAC pseudonymisation consistent across the three
modalities, HealthDCAT-AP Release 8 conformance proven against the profile's
own SHACL, k-anonymity in `risk`. Strict mypy, ruff with docstring rules,
branch coverage floored at 99%, Apache-2.0. Under git, with a GitHub remote
and CI on four Python versions on Ubuntu plus 3.14 on Windows.

`read/identity.py` decides who a record belongs to, and refuses what it cannot
decide: a validated codice fiscale or an institution-scoped record number, never
a placeholder, never an ambiguity resolved by guessing. `build/publish.py` stages
every build and publishes it at the end, so a rebuild replaces the dataset
rather than writing over it. Both exist because of the audit of 2026-11-13; read
[IDENTITY_RESOLUTION.md](IDENTITY_RESOLUTION.md) before changing either.

No counts in that paragraph on purpose — a rule total and a test total change
most weeks and no test pins either, so stating them here only schedules the
next correction. `commissura rules` and `pytest` are the places that know.

**Not met**, and the one hard constraint that is not: *deployable by a
stranger*. The package is not on PyPI and the repository is private, so today
only the author can install it. The README says so rather than implying
otherwise; publishing is an irreversible public act and therefore a decision,
not a step to take in passing.

Next, in order:
1. Decide whether to publish to PyPI, which is the only thing standing between
   this repository and the "deployable by a stranger" constraint. An
   irreversible public act, so the author's call and not a step to take in
   passing.
2. Vendor the four upstream SHACL files under `reference/` so CI can check
   conformance offline, and make that test fail rather than skip when they are
   absent. Audit finding 8: the project's headline claim is verified on one
   machine by a test that skips silently, and the log already records that a
   skip is a silent failure mode. HealthDCAT-AP is CC BY 4.0, so redistribution
   with attribution is permitted — which makes this a `NOTICE` decision as much
   as a code one.
3. Nothing else is queued. Three audit findings are open and all are cosmetic
   or one-sentence: symlink reporting under a dataset, the accession collision
   asymmetry, and the `2.25` arc's UUID semantics. The three remaining reading
   jobs are still low value. Pick new work rather than working down this list.

## Decision log

Append here the same session a decision is taken, with the reason. This file is
the project's memory; a decision that lives only in a chat transcript is a
decision that will be re-litigated or silently reversed.

**2026-11-06 — Stack.** Package and CLI `commissura` (verified free on PyPI),
licence Apache-2.0, Python 3.11 floor, `typer` + `pydantic` v2. Apache over MIT
for the explicit patent grant, which is what hospital and IRCCS legal offices
approve without discussion. 3.11 because it is what Debian 12 and RHEL 9 ship;
3.12 would exclude Debian 12. pydantic defines the schema once and exports JSON
Schema from it, so validation, documentation and a publishable spec cannot
diverge. AGPL rejected: network copyleft gets the project screened out of
clinical settings.

**2026-11-06 — `validate` written before `build`.** Forces the schema to be
precise. The layout lives in `layout.py` and holds no logic; the validator is
derived from it, so `build` has a specification to satisfy instead of defining
one by accident. 39 rules in a registry, enumerable via `commissura rules`.

**2026-11-06 — De-identification invariants are structural, not advisory.** A
dataset carrying a calendar date is *malformed*, not weakly de-identified. That
is why the date patterns live in `layout.py` and why `validate` reports a
surviving date as an error.

**2026-11-06 — Writers refuse reserved delimiters rather than escaping them.**
The HL7 and DICOM-JSON writers reject a value containing a delimiter instead of
escaping it. Escaping would rewrite characters after their PHI offsets had been
recorded, which is the one failure mode that silently corrupts every measurement
built on a corpus. A reader for real-world input will need the full escape
table; that belongs with the reader, where unescaping happens before offsets are
taken.

**2026-11-06 — Synthetic identifiers are impossible by construction, not merely
random.** Codice fiscale place code `X###` (municipalities are `A`–`M`, foreign
states `Z`); telephone subscriber part starting `0`, never assignable after an
Italian area code; `.invalid` email domain per RFC 2606; DICOM UIDs under the
registration-free `2.25` arc. Institution names and addresses are invented and
every name carries `SINTETIC`. "Probably nobody" is not good enough, and "it is
only test data" is the sentence that precedes an incident.

**2026-11-06 — Coverage floor enforced in `pyproject.toml`, not as a flag.**
Branch coverage, fail under 99%. With no CI yet, a threshold that applies only
when somebody remembers to pass `--cov` is not a threshold. It is a regression
floor, not a target: coverage says a line ran, not that it was checked.

**2026-11-06 — The secret key is never a command-line argument.** `commissura
keygen` writes a key file; `build` reads it from `--key-file` or the
`COMMISSURA_KEY_FILE` environment variable. A `--key <value>` option is
deliberately not offered: it would put the key in shell history, in `ps` output
and in CI logs. On POSIX the key file is created mode 0600; on Windows the
file-creation mode is largely ignored, so the tool says so rather than implying
a protection it did not apply.

**2026-11-06 — `date_offset` and `day_offset` are different mechanisms.** The
dataset carries only `day_offset`: integer days from the subject's own baseline,
intervals exact, no calendar anchor. `date_offset` — the per-subject ±365-day
HMAC shift — is for values that must stay a *syntactically valid date* for a
downstream tool that refuses to run without one, notably DICOM `StudyDate` on
the way into `dcm2bids`. It never appears in the finished dataset, which is why
`validate` is right to reject date-shaped strings there. Caveat to remember:
baseline is the subject's earliest event in the corpus, so offsets are stable
per (key, corpus) and re-running with additional *earlier* data shifts them.

**2026-11-06 — The `.deident/manifest.json` schema in `layout.py` was flagged as
an invented schema that HealthDCAT-AP would replace. Superseded 2026-11-07: that
diagnosis was half wrong.** See the entry below.

**2026-11-07 — There are two artefacts, not one, and only one of them is
HealthDCAT-AP's business.** Reading the Release 8 obligation table settles this.
Its 57 properties describe a dataset *for a catalogue*: title, theme, access
rights, legal basis, purpose, retention period, population coverage, which HDAB
governs it. That is EHDS Article 77, and its reader is the HDAB. **Nothing in
the profile records what was done to de-identify the data** — not which fields
were removed from which modality, not which key produced the pseudonyms, not
which rule version was applied. So:

| Artefact | Schema | Reader |
| --- | --- | --- |
| HealthDCAT-AP dataset description | The profile, Release 8, RDF / JSON-LD | The HDAB, and any catalogue |
| `.deident/manifest.json` | Ours. Nobody else specifies it. | Whoever audits the de-identification |
| `dataset_description.json` | BIDS | Tools that read the dataset |

So `MANIFEST_REQUIRED_KEYS` is not wrong for what it is; it was only wrong to
treat it as the thing HealthDCAT-AP would replace. The work is to **add** the
dataset description, not to rewrite the manifest. `DS009`, `DI006` and `DI007`
stand. This brief's own scope line already said it — "HealthDCAT-AP-aligned,
**plus** schema version, de-identification rule version, per-modality record..."
— and the word doing the work is *plus*.

**2026-11-07 — The three controlled vocabularies are read in full, and the last
blocking unknown is closed.** `commissura` now knows the three mandatory
IRI-valued fields it must emit:

| Property | Value | Label, verbatim |
| --- | --- | --- |
| `healthdcatap:healthCategory` | `.../healthcategories/EHRS` | "Electronic health data from EHRs" |
| `dcat:theme` | `.../data-theme/HEAL` | "Health" |
| `dct:accessRights` | `.../access-right/NON_PUBLIC` | "non-public" |

`EHRS` is the only one of the seventeen Article 51 categories whose label
mentions EHRs, so choosing it is a reading rather than a guess. The near miss
worth ruling out is `PGEH`, "Personal electronic health data automatically
generated through medical devices" — a different Article 51 category.

**And the access-right definitions settle the tier question that was inference
yesterday.** Quoted from the authority list: `NON_PUBLIC` is "not publicly
accessible for privacy, security or other reasons", noting the category "may
include resources that contain sensitive or personal information". `RESTRICTED`
is "only available under certain conditions", and its own usage note gives those
conditions as **payment, non-disclosure agreements, or a publisher who has not
yet decided** whether the data can be released. Those are commercial and
editorial conditions, not privacy ones. A pseudonymised clinical dataset is
withheld for the first reason. So `DEFAULT_TIER = NON_PUBLIC`, which is also
`SUPERSET_TIER`, so the default is the strictest and moving off it never
requires gathering more metadata. It stays a default and not a decision taken
for the user, because the tier is a fact about the release arrangement.

One trap now encoded rather than waiting to be discovered: the health category
vocabulary is served over **https** and the data-theme vocabulary over **http**.
Using the wrong base produces an IRI that looks entirely plausible and resolves
to nothing, so both bases are constants and a test pins the difference.

**2026-11-07 — All three tiers read. The tier is the data holder's declaration,
not commissura's choice, and `build` gathers the non-public superset.** The three
shapes pin `dct:accessRights` to `.../access-right/PUBLIC`, `NON_PUBLIC` and
`RESTRICTED` respectively, each mandatory at exactly one value, so **the tiers
are mutually exclusive** — no dataset satisfies two. Which one applies is a fact
about the release arrangement that only the holder knows, so `commissura` must
not pick it; it takes the access right as input and refuses a value outside the
three rather than rounding to the nearest tier.

What it *can* do is gather once. The obligation sets are nested even though the
tiers are not: non-public requires everything the other two require plus
`dcat:contactPoint`, `dcat:keyword`, `dct:type` and `dct:provenance`. So `build`
collects the non-public superset — 14 mandatory properties, 15 counting the
conditional `hasVariables` — and emits whichever access right is declared.
Switching tier then changes one triple instead of sending somebody back for four
more fields. Pinned as `healthdcat.SUPERSET_TIER`.

**Counter-intuitive and worth remembering: `RESTRICTED` requires *less* metadata
than `NON_PUBLIC`**, and exactly as much as `PUBLIC`. The names suggest the
opposite. A reading that fits — inference, not a finding, because the
access-right vocabulary's own definitions have not been read — is that a
non-public dataset is one whose *description* is catalogued while its data is
not available, so it needs a contact point, keywords, a type and a provenance
statement precisely so somebody can find it and ask for access.

**2026-11-07 — Correction: a tier is not chosen, it is selected by
`dct:accessRights`.** Yesterday's entry said "a dataset description must declare
its tier". Reading the shapes shows it the other way round:
`public-shapes.ttl` constrains `dct:accessRights` with **`sh:hasValue`**, fixed
to `.../access-right/PUBLIC`, and that property is mandatory at 1..1 in every
tier. So the access-rights value *is* the tier. A dataset released under an EHDS
data permit is not public, which means **the public shapes are the wrong ones to
validate a clinical dataset against** — and they are the ones anyone would reach
for first, because they are the file named without a qualifier. The non-public
and restricted shapes have not been read yet, so the values they pin are
recorded as unknown in `TIER_ACCESS_RIGHT` rather than guessed. Reading them is
the next step, and it decides which tier `commissura` targets.

**2026-11-07 — The `healthdcatap:` namespace IRI is provisional, by the
profile's own admission.** The shapes file declares
`http://healthdataportal.eu/ns/health#` under the comment "To be changed when
the Heathdcat-AP namespace is created". Every health-specific term this tool
emits will therefore need rewriting. Mitigation, which must not be undone: IRIs
are assembled from `healthdcat.NAMESPACES` in one place and never written into
templates, so the eventual change is a one-line edit.
`HEALTHDCATAP_NAMESPACE_IS_PROVISIONAL` exists to make that explicit to whoever
reads it next.

**2026-11-07 — HealthDCAT-AP imports DCAT-AP 3.0.0, so conformance is to both.**
`owl:imports <https://semiceu.github.io/DCAT-AP/releases/3.0.0/html/shacl/shapes.ttl>`.
The health shapes are not the whole constraint set: `Agent_Shape` and
`PeriodOfTime_Shape` are defined upstream, and the health file states that class
range constraints live separately again in `ranges/range.ttl`. The target claim
in this brief — "commissura emits HealthDCAT-AP-conformant dataset
descriptions" — therefore carries a DCAT-AP 3.0.0 dependency that was not
visible before. Scope accordingly.

**2026-11-07 — `hasVariables` is a CSVW table group, and the lab branch nearly
satisfies it already.** The obligation that looked hardest to meet —
`hasStructuredData` is mandatory, and when true at least one `hasVariables` is
required — resolves to a CSVW structure: tables, columns, and per column
`csvw:name`, `dct:description`, `csvw:title`, `csvw:datatype`,
`csvw:propertyUrl`. A `lab/*.tsv` header plus its JSON sidecar already carries a
column name, a description, a datatype and a LOINC code. So `build` can generate
the mandatory variable description from data it has, rather than asking the user
for it. This is the one place where the profile and the existing dataset layout
line up for free, and it is worth not squandering by inventing a parallel
representation.

**2026-11-07 — The Release 8 obligation table is transcribed into
`healthdcat.py`, not fetched or vendored.** 57 properties × 3 tiers, with
`SOURCE_URL` recorded so it can be re-checked. Transcribing makes an upstream
change a reviewable diff instead of a silent behaviour change, and keeps the
tool from depending on a network fetch. The tests check internal consistency —
no row lost, no label duplicated, no mandatory property permitting zero values —
because they cannot check against the network without becoming flaky.

What `build` must therefore satisfy, in the public tier: `dct:accessRights`
(1..1), `dcatap:applicableLegislation` (1..*), `dct:description`,
`dcat:distribution`, `healthdcatap:healthCategory`, `dct:identifier`,
`dcat:theme`, `dct:title` (all 1..*), `healthdcatap:hasStructuredData` (1..1)
and `healthdcatap:hdab` (1..1). The non-public tier adds `dcat:contactPoint`,
`dcat:keyword`, `dct:provenance` and `dct:type`. And one obligation no
cardinality column can express: when `hasStructuredData` is true — which it is
for any clinical dataset — at least one `healthdcatap:hasVariables` is
mandatory.

Two consequences worth seeing now. `healthdcatap:hdab` is mandatory at 1..1,
so a conformant description **cannot be produced without naming a Health Data
Access Body** — and Italy has not designated one yet, which is due March 2027.
A local tool must therefore let the user supply it and must not invent it.
`dcat:distribution` is mandatory at 1..*, so the profile assumes the data is
*distributable*; a dataset sitting on a hospital disk still needs a distribution
node describing how it would be accessed.

**2026-11-06 — The HealthDCAT-AP URL in this brief was stale, and both rendered
sites are dead ends for a script.** `healthdcat-ap.github.io` is decommissioned.
Its replacement, `data.health.europa.eu/healthdcat-ap/releases/latest/`, is
client-side rendered and returns zero bytes to a plain fetch. The way in is the
specification's **source repository** on the Commission's GitLab, whose REST API
serves plain JSON with no JavaScript — so no rendering browser is needed after
all. Endpoints and file inventory are in the alignment section above.

**2026-11-07 — commissura targets HealthDCAT-AP Release 8.** The repository
carries releases 5 through 8; the rendered site still serves 5 as "latest". 8 is
chosen because releases 6 and up ship a packaged SHACL validator
(`html/shacl/HealthDCAT-AP_validator/`) that Release 5 does not, which means
conformance can be checked against the profile's own tool instead of against our
reading of it. Consequences to honour: the manifest must name the release it was
built against, and `validate` must be able to report that a dataset claims a
release it does not satisfy. Risk accepted: 8 may still be moving, so the
release is pinned in one constant and the reason for the pin is here.

**2026-11-07 — Under version control, with LF normalisation declared.** `git
init` plus a `.gitignore` and a first commit, 59 files. `.gitattributes` forces
LF in the repository and in every working copy, which matters more here than in
most projects: the corpus writer exists to put exact bytes on disk, every
recorded PHI offset is a character position, and HL7 terminates segments with a
bare carriage return. A newline conversion applied to a fixture would shift
those offsets and be nearly invisible in a diff. `.gitignore` also excludes
`*.key` — a key in a repository is a key in every clone and every fork,
permanently — and the generated `raw/` and `dataset/` trees, which are
reproducible from a seed and deliberately contain synthetic identifiers. No
remote: nothing has been pushed anywhere.

**2026-11-07 — The readers are tolerant where the writers are strict, and that
asymmetry is the design.** `commissura.hl7` refuses a value containing a
reserved delimiter, because it controls what it emits. `commissura.read.hl7`
accepts a missing field as an empty string, a missing segment as `None`, a
timestamp it cannot parse as `None`, and `\n` where HL7 wants `\r`. Every one
of those is a defect the generator can inject on purpose, so a reader that
raised on them could not be used to measure how a dataset copes. Unescaping
happens at parse time, before any offset is taken, so everything downstream
works in real characters.

**2026-11-07 — Laboratory messages are authoritative for identity; linkage is
accountable.** A subject exists only if an HL7 message established it, because
PID-19 carries the national identifier and a DICOM header does not — it has a
`PatientID`, which is the hospital's own number. Imaging and reports attach to
subjects already known. Every record that cannot attach produces a
`LinkageIssue` naming the file and the reason, the count goes into the manifest,
and that count is the number somebody should look at before trusting a dataset.
Medical record numbers are compared with leading zeros stripped, which recovers
the `imaging.mrn_format_drift` defect: at a defect rate of 1.0 across 20
subjects, zero imaging studies are lost.

**2026-11-07 — Free text is de-identified by targeted redaction, not by named
entity recognition.** The usual approach looks at prose and tries to work out
which words are names. This one already knows: the laboratory message states
this patient's name, national identifier and record number; MSH-4 states the
sending institution; OBR-16 the ordering clinician; the report's own signature
line states who signed it; the imaging metadata states the institution's street
address. So the problem stops being "find the names" and becomes "remove these
specific strings" — exact, auditable, reportable. **This is the argument for
linking modalities before de-identifying them, and the opposite order is the
intuitive one.** What remains is reported rather than hidden: the scrubber emits
a residual-risk list, and on a ten-subject corpus it reduced to one truncated
token.

**2026-11-07 — A birth date is removed, never expressed as an offset.** Found on
the first real build, where a report read `Nato/a il: [day_offset:-22650]`. An
offset from the subject's own baseline *states the birth date exactly*, in a
dataset that also carries the baseline, so it protects nothing — and a birth
date is the most identifying date a record holds. Birth dates are now redacted
by exact match against the known value, before any date rewriting, and get their
own placeholder. Event dates still become offsets, because the interval is
clinically useful and the calendar anchor is what has to go.

**2026-11-07 — Order within the scrubber is load-bearing.** Pattern-based
removal of emails and telephone numbers runs *before* exact-match substitution.
Found by a test: an email address contains the patient's own surname, so
redacting the name first leaves `m.[NAME]@posta.invalid`, the email pattern no
longer matches, and the domain survives — a leak that looks like a redaction.
Consecutive identical placeholders are also collapsed, since word-by-word
redaction of an institution leaks how many words its name had.

**2026-11-07 — Sessions are encounters; imaging metadata goes to
`derivatives/`.** A session directory per distinct date on which something
happened to the subject, which is what a clinician means by a visit; one session
per source file would produce directories that mean nothing. Imaging metadata is
pseudonymised into `derivatives/imaging-metadata/` rather than `anat/` or
`pet/`, because no conversion happened — this project orchestrates `dcm2bids`
rather than reimplementing it, so there is no image to accompany.

**2026-11-07 — Two description documents, and `dcat:distribution` is emitted
even for a dataset on a disk.** `dataset_description.json` is BIDS, plain JSON,
read by tools that walk the tree. `healthdcat-ap.jsonld` is the Article 77
description, RDF, read by a catalogue and an HDAB. Merging them would invent a
hybrid satisfying neither. The profile makes `dcat:distribution` mandatory at
1..*, so it assumes the data is distributable; a dataset sitting on a hospital
disk still gets a distribution node describing the form it would be accessed in.
The imported DCAT-AP 3.0.0 Distribution requirements are unread, and the emitted
document says so in its own `profileNote`.

**2026-11-07 — Known limitation: the manifest's per-modality table states
intent, not observation. Closed 2026-11-10 — and the table turned out to be
wrong, not merely weak.** See the entry at the end of this log.
`.deident/manifest.json` lists what was removed, replaced and kept per modality
from a static table. That describes what the rules do, not what each file
actually contained. Deriving it per file would be stronger and is the obvious
next improvement; what makes the current form defensible is that the rules are
deterministic and the scrubber's own per-document counts are recorded alongside.
Recorded here so the gap is not rediscovered as a surprise.

**2026-11-07 — `risk` is k-anonymity over `participants.tsv` and nothing more.**
A `Counter` over the recommended participant columns, flagging combinations
shared by fewer than five people. It reads the quasi-identifiers from
`layout.RECOMMENDED_PARTICIPANT_COLUMNS`, so adding a column to the table adds
it to the assessment. `build` now writes the report, which closes the warning
`validate` had emitted on every build.

Deliberately **not** shaped toward the Article 78 quality and utility label: the
criteria are unpublished and QUANTUM is still developing them, so there is
nothing to build against. Also skipped: the GitHub Actions workflow the list
below asks for, because with no remote it cannot run and would be dead code
until somebody pushes.

Honest result on a small cohort: minimum k is 1. Ten participants with exact
ages cannot reach k=5 on age and sex together. That is a property of small
cohorts, not a defect in the dataset, and the report says the number rather than
a verdict.

**2026-11-07 — The HealthDCAT-AP claim is now proven by the profile's own
shapes, and proving it found eleven violations.** `pyshacl` loads Release 8's
SHACL, the DCAT-AP 3.0.0 shapes it imports and `range.ttl`, and judges the
emitted description. Dev extra only — never a runtime dependency, because
`pip install commissura` has to stay light.

The eleven were not visible from the cardinality table. Six came from the
imported DCAT-AP shapes and from `range.ttl`, which the health shapes do not
contain: every `dcat:Distribution` needs a `dcat:accessURL`; both the HDAB and
the publisher need a `cv:contactPoint`; `dct:type` must be an IRI from the
dataset-type authority list, not a string; the record counts must be
`xsd:nonNegativeInteger`, where a bare JSON number becomes `xsd:integer`; and a
`healthCategory` reference must be a typed `skos:Concept` carrying its label.
All fixed, and the labels restated are the authority lists' own.

`--access-url` joins `--hdab`, `--publisher` and `--contact-point` as a field
the holder must supply and the tool will not invent. `--dataset-type` defaults
to `SYNTHETIC_DATA`, which is true for this project's own output and must be
changed when building from real clinical material; the help text says so.

**A finding about the profile, not about us: Release 8's published shapes are not
valid SHACL.** An `sh:or` sits inside the `sh:property` list with no `sh:path`,
which no property shape may lack, so a strict engine refuses the whole file. The
test repairs it on the parsed graph rather than editing the download, and a
second test fails once upstream fixes it — so the workaround cannot outlive the
defect. This is presumably why the profile ships a specific validator.

Deliberately not done: installing Java and the ITB RDF validator the profile
packages. It is a web service, and the authoritative answer comes from the
shapes, not from the program that loads them. A conformant SHACL engine gives
the same verdict on the same constraints.

**2026-11-07 — The `.gitignore` silently excluded the whole build subsystem, and
a review caught it three commits late.** A gitignore pattern with a trailing
slash and no leading slash matches a directory of that name **at any depth**, so
`build/` — written for a top-level build-output directory — matched
`src/commissura/build/`. Five files, the entire de-identification pipeline, were
untracked. `git status` reported a clean tree the whole time, so three commits in
a row announced success while `cli.py` in `HEAD` imported modules that were not
in `HEAD`. A clone could not import the CLI at all.

Every plain directory name in `.gitignore` is now anchored with a leading slash,
and the comment there says why. The lesson that generalises: *`git status` being
clean is not evidence that your work is committed.* `git ls-files <dir>` is.

A second consequence found while fixing it: **ruff respects `.gitignore`**, so
`ruff format .` and `ruff check .` had been skipping those five files too — they
were only ever checked when a path was passed explicitly. mypy was unaffected,
because it reads `files = ["src", "tests"]` from `pyproject.toml` and ignores
git. Anchoring the patterns fixed the linter blind spot along with the tracking.

Found by `/ponytail-review`, not by the test suite — and the test suite could
not have found it, because it runs against the working tree. Worth remembering
when deciding what a green run proves.

**2026-11-07 — The conformance test proved the library, not the command.** Same
review. `--contact-point`, `--access-url` and `--dataset-type` existed on
`BuildSpec` but had no CLI flag, so `commissura build` could never emit a
conformant description while `tests/test_shacl_conformance.py` passed — it
constructed `BuildSpec` directly in Python and bypassed the CLI. The flags now
exist, `--dataset-type` is checked against the authority list, and a second
conformance test drives the command line exactly as the README does. A test that
exercises the library instead of the entry point is a test that can be green
while the product is broken.

Also fixed: `SHAPES_DIR` was relative to the working directory, so the whole
conformance check skipped silently when `pytest` ran from anywhere else. It is
now relative to the test file.

**2026-11-07 — CI on GitHub Actions, now that a remote exists.** Four Python
versions on Ubuntu and one on Windows, each running `ruff check`,
`ruff format --check`, `mypy` and `pytest`. Until now the 3.11 floor was
guaranteed only by ruff's `target-version` and mypy's `python_version`, which
catch syntax and standard library APIs but not behaviour, and the whole project
had only ever run on Windows.

Both platforms are deliberate. **Ubuntu is what makes the cross-platform claim
true**, since nothing had ever executed there. **Windows stops the opposite
regression**, where a fix for Linux breaks the platform the author actually
works on — and this project has real platform-dependent code: the key file's
POSIX mode, the newline handling the corpus writer exists for, and the
`Path.read_text(newline=...)` API that only exists from 3.13.

`fail-fast: false`, because on a first run the useful answer is *which*
versions break, not that one did.

`tests/test_shacl_conformance.py` stays skipped in CI. The shapes live under
`reference/`, which is gitignored, and fetching them from code.europa.eu on
every push would make the pipeline depend on a server nobody here controls, and
fail for reasons that have nothing to do with the commit. Conformance is checked
locally, deliberately, and the README says where the download commands are.

Action versions are pinned to a major tag (`actions/checkout@v4`,
`astral-sh/setup-uv@v6`) rather than a commit: a moving major tag picks up
security fixes, and the trade-off against supply-chain pinning is acceptable for
a repository with no secrets and nothing to deploy.

**2026-11-08 — The matrix is now proven, not assumed.** `.python-version` is
tracked and holds `3.14`, and uv reads it when choosing an interpreter. Had it
won over the version `setup-uv` installs, all four Ubuntu jobs would have run on
3.14 and shown four green ticks proving nothing about 3.11 — and four green
ticks are compatible with both outcomes, so the colour cannot tell them apart.
A step after `uv venv` now asserts `sys.version` starts with the matrix version.
It passes in silence when the matrix is real and fails loudly when it is not.

Deliberately not done instead: `uv venv --python ${{ matrix.python-version }}`,
which would make the problem impossible rather than visible. The point was to
find out whether `UV_PYTHON` wins, and pinning the version would have answered
nothing. If the assert ever fails, that is the fix.

**Answered: it passes.** `UV_PYTHON`, as set by `setup-uv`, takes precedence
over a tracked `.python-version`, so the matrix is real and the green run that
preceded this check was genuine too. Keep the assert anyway — it costs one step
and it is what stops a future edit, or a change in uv's precedence rules, from
quietly collapsing four jobs into one.

**2026-11-08 — The README no longer claims an installation that does not
exist.** It said `pip install commissura`; the package is not on PyPI, and the
repository is private, so **today nobody but the author can install it at all**.
That was the only false statement in the repository, and it sat directly under a
hard constraint reading "Deployable by a stranger: `pip install`". The line is
now an honest clone-and-install from a checkout, marked "not published to PyPI
yet".

So that hard constraint is **not met**, and the README stops implying it is.
Publishing to PyPI would meet it and would also claim the name before somebody
else does, which is a real argument for doing it early — but it is an
irreversible public act and therefore the author's call, not a step to take in
passing. Revisit before going public.

**2026-11-10 — The brief rotted at the top while the log at the bottom stayed
true, and the fix has to be structural because a convention already failed.**
Three passages were false. `## Current state` named five commands when there
were eight, so a new session would conclude that `build` did not exist. The
alignment section said the health category vocabulary was half read when all 17
concepts were read. And "still unread" item 4 still called the packaged
validator "the real conformance check, worth doing before claiming conformance
anywhere" — twenty paragraphs above a log entry recording that conformance *was*
proven with `pyshacl` against those same shapes, and why the ITB validator was
deliberately skipped. Two paragraphs even disagreed with each other on how many
authority lists had been read, three against four; three was the right number
and four was the newer sentence.

The mechanism is worth naming, because it is invisible while it operates and
nobody ever wrote anything false. Each time a fact changed, **a correction was
appended beside the text it corrected** instead of replacing it. So
`## Current state` came to hold three lists — "Done:", "Next, in order:" and
"Done since this list was written:" — and the alignment section three paragraphs
each claiming a more complete version of the same reading, in increasing order
of truth, only the last accurate. A reader has to take all of them and work out
which wins. That is not a brief, it is sediment. And it accumulates fastest in
exactly the sections a new session reads first, because those are the summaries,
and a summary is the thing that has to be rewritten when the thing it summarises
moves.

Two fixes, since the convention on its own is what failed. **The rule**, now at
the top of the file where it is read before anything else: everything above the
decision log is rewritten in place, and only the log is append-only, because
only the log is a log. **And a check** — `tests/test_brief.py` compares the
command list in `## Current state` against the names typer actually registers.
Exact comparison, not a subset, so a command that is removed fails too. It asks
typer for the names rather than re-deriving the naming rule, because a test that
re-implemented that rule could agree with itself while disagreeing with the CLI.

The honest limit: exactly one fact in the file is mechanically checkable and the
rest still rests on discipline. It happens to be the fact whose going stale was
the expensive one. Found by reading the file, not by the tests and not by CI —
the same as the `.gitignore` incident, and the second entry in this log about
something a green run cannot see.

Noticed in passing and recorded so the next person does not debug it: **typer
0.28 no longer depends on click.** `import click` raises `ModuleNotFoundError`
in this environment; the vendored copy is at `typer._click`, and the test
reaches the command table through the public `typer.main.get_command` rather
than importing a private module.

**2026-11-10 — The manifest's field table is derived from the run, and
deriving it found the static table had been wrong, not merely weak.** The known
limitation recorded above said the table stated *intent* rather than
observation: it claimed PID-5 was removed whether or not any message carried a
PID-5, and could not say how many did. Replacing it showed the problem was worse
than that framing.

**Two entries were simply false.** The table said `PID-3` was *replaced* by the
subject label and that the laboratory accession was *pseudonymised*. Neither
happens. The medical record number is read to link an imaging study to a person
and then dropped, and the laboratory accession never reaches the dataset at all.
Both are *removed*. The difference matters to the only person who reads this
document: "replaced" tells an auditor that a medical record number is in the
dataset and recoverable with the key, which would have been a false statement
about a privacy property, in the file whose whole purpose is to be believed.

**And it was incomplete in a way no review of it could have caught.** It named
nine removed DICOM tags. A corpus has twenty-two, including `(0010,0030)`
PatientBirthDate and `(0010,1010)` PatientAge — both PHI, both dropped
correctly, neither mentioned. A reader could not tell from the manifest what had
become of the DICOM birth date. A static table can only account for what
somebody remembered to write down, and nobody remembers twenty-two things.

**What makes derivation possible is the shape of the pipeline, and it is worth
naming because it is not obvious: the build carries a whitelist, not a
blacklist.** The lab branch writes nine columns, the imaging branch seven keys,
and everything else in the input is dropped by never being copied. So removal
does not have to be enumerated at all. Only two things need declaring — which
input fields are carried, and whether each passes through the pseudonymiser —
and the second is the reason the declaration cannot be eliminated entirely:
whether a value is relinkable is a fact about the code, not about the data. Two
values can look equally unlike their originals and only one of them be
recoverable with the key. Everything else is observed:

| | |
| --- | --- |
| observed, not carried | removed |
| carried through the pseudonymiser | replaced |
| carried verbatim | kept |

So `CARRIED_FIELDS` in `commissura.build.observe` has eighteen entries where the
old table had thirty-nine prose entries, and reports strictly more.

**The payoff, on a real run**: the vendor private tags `(0029,0010)` and
`(0029,1010)` appear in the manifest as removed, present in 3 of 13 files —
because the `imaging.phi_in_private_tag` defect put them there. Nothing declares
them. They are in the table because they were in the data, which is the whole
point: an unexpected field in a hospital's export is exactly what an auditor is
looking for, and it is now impossible for one to pass through unmentioned.

Four decisions worth keeping:

- **Counts are per file, not per occurrence.** A message with twelve OBX
  segments contributes `OBX-5` once. "Present in 34 of 43 files" is a fact about
  coverage, which is what tells you a field is conditional; an occurrence count
  would mostly measure how long the messages were.
- **A declared field the corpus never carried is reported at zero, not dropped.**
  This immediately earned itself: `Eta` came back as carried in zero of nineteen
  reports, which was not a wrong declaration but a blind spot in the header
  pattern — it anchored on line starts, and the generated reports write
  `Nato/a il:` and `Eta:` on the same line. A table that hid absent fields would
  have hidden the bug.
- **An unreadable file is named, not skipped.** A file whose fields were never
  seen is a file this table cannot vouch for, and silence would read as a clean
  bill of health.
- **Known DICOM tags are named, unknown ones are not.** A bare tag number would
  have made the new table less readable than the old one, and a full data
  dictionary would defeat the purpose, since the tags worth catching are the ones
  nobody anticipated. So twenty-six keywords are transcribed and anything else is
  reported by number.

One rename, forced by an existing guard and worth recording because it looks
arbitrary: the field identifier is emitted as `field`, not `key`.
`layout.FORBIDDEN_MANIFEST_KEYS` reserves `key`, because a manifest property of
that name is what a leaked secret would look like, and nobody should have to
read the value to find out. The guard failed the build immediately, which is
what it is for.

Also centralised while here: the three corpus globs (`lab/*.hl7`,
`reports/*.txt`, `imaging/*.json`) now live in `read.corpus.RAW_SOURCES`. Two
modules walk the same corpus — one to link it, one to account for its fields —
and a glob that disagreed between them would make the manifest describe files
the dataset was not built from.

**2026-11-10 — The constraint set is read in full, and the conformance claim
was narrower than it read. HealthDCAT-AP's `range.ttl` imports itself.** The
file declares its own subject IRI as DCAT-AP's range IRI and then
`owl:imports` that same IRI. A self-loop imports nothing, so the comment three
lines above it — "By importing DCAT-AP range constraints via `owl:imports`, this
file ensures clear distinction between reused and extended constraints" — is not
true of the file that contains it. The file also identifies itself by two
different IRIs: `code.europa.eu/.../healthdcat-ap/range.ttl` for its `dct:format`
metadata, and the DCAT-AP IRI for the ontology declaration.

**Consequence: 84 class range constraints were never being checked here**, and
they are the ones that matter most for a document assembled from authority-list
IRIs. Loading DCAT-AP's `range.ttl` by hand found six failures, every one the
same mistake: **`sh:class` is satisfied by an `rdf:type` triple in the data
graph, and a validator does not dereference an authority list to find one.** The
IRI being correct buys nothing. So `dct:accessRights` must carry
`dct:RightsStatement`, `dct:format` must carry `dct:MediaTypeOrExtent`,
`dct:type` must carry `skos:Concept`, and `dcatap:applicableLegislation` must
carry `eli:LegalResource` — inline, on each reference. That lesson had already
been learned once, for `healthCategory`, and was not generalised; the fix is now
a single `_typed()` helper so the next property cannot miss it.

**`dcat:contactPoint` is the one that is not a mistake but a genuine divergence,
and it must not be tidied away.** DCAT-AP's range constrains the dataset's
`dcat:contactPoint` to `vcard:Kind`. The HealthDCAT-AP shapes constrain an
agent's `cv:contactPoint` to `cv:ContactPoint`, with `cv:email` a literal. Two
profiles, two contact models, both mandatory, in the same document. Each is now
used where its own shapes ask for it. Using one model throughout is the obvious
move and fails half the shapes, which is why this is written down.

What the two shapes the brief was actually looking for turned out to say, both
smaller than their billing: **`Agent_Shape`** requires `foaf:name` at minCount 1
as a literal and allows at most one `dct:type` — already satisfied.
**`PeriodOfTime_Shape`** caps `dcat:startDate`, `dcat:endDate`,
`time:hasBeginning` and `time:hasEnd` at one each and requires none of them, so
an empty period is valid. It applies to `healthdcatap:retentionPeriod`, which is
recommended and which `build` does not emit, so it constrains nothing here yet.

**Two further defects in the profiles, recorded because they change what
"conformant" means rather than what we emit.**

`healthdcatap:hasCodeValues` has its `sh:class` commented out, with the note
"Change healthdcatap:hasCodeValues from skos:Concept to rdfs:Literal". The
replacement was never written, so the property shape carries only a path and a
severity and constrains nothing at all.

And **five constraints in the DCAT-AP 3.0.0 shapes are inert**: they use
`sh:shape`, which belonged to a SHACL draft and is not in the standard, where the
parameter is `sh:node`. `CatalogRecord_Shape` uses `sh:shape` for `dct:modified`
and `sh:node` for `dct:issued`, two lines apart, pointing at the same inner
shape. Confirmed empirically rather than from memory: a minimal graph violating
the inner shape is reported through `sh:node` and passes silently through
`sh:shape`. So the date-type checks DCAT-AP intends on `dct:modified`,
`dcat:startDate` and `dcat:endDate` are enforced by nothing. No workaround is
recorded for this one, and deliberately no test: a test with no workaround
attached is documentation pretending to be a check.

**Also found, and worse than any of the above for a stranger: the README's own
download commands could not work.** They used `curl -O` against an API endpoint
whose path ends in `/raw`, so every shape file was saved as `raw` and each
overwrote the last, and the DCAT-AP file landed as `shapes.ttl` rather than the
name the test looks for. Nobody following the README could run the conformance
test — and because the test skips when a shape file is absent, they would have
seen a tidy skip rather than a problem. Now four explicit `-o` names, verified
by running the block and diffing all four files against the ones in use. The
general lesson: **a skip is a silent failure mode, and a command in a README is
untested code.**

**2026-11-10 — Answered: commissura is a health data holder's tool, performing a
first pseudonymisation step, and both its description documents are the holder's
to produce.** The brief has carried this as an open question since the start,
because it decides what `build` is responsible for. FAQ Q49 settles the
pseudonymisation half and Q34/Q35 settle the description half, and the two
answers point the same way.

Q49: both the holder and the HDAB may pseudonymise, or just one of them, and
recital 72 asks for it as early as possible in the process, which the FAQ ties to
GDPR data minimisation. **Ultimate responsibility rests on the HDAB**, in the
FAQ's words, while the actual work "might also be already carried out by the
health data holder". So nothing commissura does is final, and that reframes the
manifest from a nice-to-have into the thing that makes the next step possible:
whoever pseudonymises after us has to know what we already did, which is why
deriving the per-field table from the run this morning mattered more than it
looked at the time.

Q34 and Q35: a health data holder of personal electronic health data is *always*
a controller (Art. 2(2)(t)); joint controllers must settle among themselves who
will "provide dataset descriptions"; and a holder flags IP or trade secrets "when
submitting the dataset description for inclusion in the dataset catalogue in
accordance with Article 60(3)". The Article 77 description is therefore a holder
deliverable, not an HDAB one. That was assumed here and is now sourced.

**The detail worth the whole reading**: Q49's second example is a permit covering
procedures carried out in different hospitals, needing linkage across them. It
names the holders' operation as "hashing the identifiers before disclosure to the
HDAB", with the identifiers never reaching the data user — only the fact that two
rows refer to the same person. That is `subject_id` exactly. The stack decision of
2026-11-06 chose HMAC-SHA256 for brute-force resistance and domain separation, not
because the FAQ described it; matching the regulator's own worked example is luck,
and worth knowing it was luck.

Two limits this exposes, both recorded rather than fixed, because fixing either
would change what this project is:

**Cross-holder linkage needs key distribution, and commissura says nothing about
it.** In that same example it is the *HDAB* that links records across hospitals.
Deterministic HMAC means two hospitals with the same key produce the same subject
label, so the linkage works — and only then. This tool keeps the key out of the
dataset on purpose and offers no answer to how a key would travel between
institutions, who would hold it, or how it would be rotated. `key_fingerprint`
lets an HDAB tell whether two datasets are relinkable; that is the whole of what
is on offer. Key custody across holders is a governance problem, not a local CLI
problem, and claiming otherwise would be the first dishonest sentence in this
repository.

**commissura pseudonymises and does not anonymise.** The FAQ treats them as
alternatives and so must we. Pseudonymised data is still personal data under the
GDPR; anonymised data is not, and that difference is the entire legal weight of
the word. `risk` reports k over quasi-identifiers — it measures, it does not
certify, and the honest k=1 it reports on a ten-person cohort is the argument for
never letting "anonymised" into the README. Checked while here: the word appears
nowhere in the repository as a claim about our output.

**2026-11-10 — The reports ledger accounts for the prose body too, and its first
run found that one scrubber rule has never been exercised by a real corpus.**
A report has labelled headers, which are fields, and a body, which is not. The
headers were in the field table; the body's per-category counts sat in a
separate top-level `free_text_redactions` map, so seeing what had happened to a
report meant reading two sections and joining them by hand. The counts now live
inside the reports ledger as a second table, with the same three-way vocabulary
the structured modalities use.

**Nothing in free text is ever `kept`**, because the body is carried whole and
only its identifiers are touched, so the useful distinction is the other one —
and only two of the ten categories fall on the `replaced` side. `date` becomes
`[day_offset:N]`, which still states the interval to every other event in that
subject's record. `age` becomes the ceiling marker, which states that the
original was above the ceiling. Everything else becomes a placeholder carrying
nothing of the original. **`date_of_birth` is in the `removed` group and is the
one that looks like it belongs with the dates**: it is removed rather than
offset for the reason recorded on 2026-11-07, and a test now fails if that ever
flips, because the disposition flipping to `replaced` is exactly what a
regression to offsetting it would look like in the manifest.

Two counts per category, not one, because for prose they answer different
questions. `documents_affected` is coverage and reads like the field table's
`files_present`; `occurrences` is how many identifiers the method actually
found. The field table reports only coverage, on the grounds that an occurrence
count there would mostly measure how long the messages were. In free text the
occurrence count *is* the measurement.

**What the table found on its first run, which is the argument for building
it**: `contact` fired in 0 of 19 documents, and `grep` confirms the generator
never writes an email or telephone number into a report body. So the contact
rule — and the ordering fix of 2026-11-07, where redacting a name first broke
the email pattern and left the domain behind, a leak that looks like a
redaction — is exercised by one unit test and by no corpus this tool produces.
That is a gap in the **generator**, not the scrubber, and it matters because
this project's argument is rules first and measurement always: a defect that
cannot be injected is a rule that cannot be measured end to end. Fixing it needs
ground-truth PHI annotations with character offsets, so it is the next step
rather than a passing edit. `age` is also at zero and is not a finding: eight
subjects produced nobody over the age ceiling.

**And the schema version moved to 2.0.0, which it should have done this
morning.** Reshaping `modalities` from an object of prose lists into an array of
observed ledgers was a breaking change, and it shipped with `schema_version`
still reading 1.0.0. A version exists so a consumer can tell; leaving it alone
while rewriting the document told them the opposite of the truth. 2.0.0 now
covers both that change and this one, and the constant's docstring says what
broke. The lesson is dull and worth having anyway: **the schema version is part
of the schema change, not a chore afterwards.**

One guard worth naming: `CATEGORY_DISPOSITION` is looked up without a default,
so a scrubber category added without a declared disposition raises `KeyError`
and stops the build. A manifest that guessed whether an unknown category was
removed or replaced would be worse than a build that stopped, and a test pins
that behaviour.

**2026-11-10 — A generated discharge letter now carries the patient's contact
details, in prose, which closes the one path through the scrubber that no corpus
exercised.** The body table reported `contact` firing in 0 of 19 documents
yesterday and `grep` confirmed why: the generator never wrote an email or a
telephone number into a report body. So the contact rule, and with it the
ordering fix of 2026-11-07 — where redacting the name first left
`m.[NAME]@posta.invalid`, stopped the email pattern matching and let the domain
survive as a leak that looks like a redaction — rested on a single hand-built
test string.

Three choices in how it was added, each of which could have been made the easy
way and would have measured nothing:

- **In prose, not as a `Recapiti:` header.** A labelled field would be caught by
  the scrubber's exact-match pass, which already knows the email from HL7
  PID-13, so the pattern path would still never run. A test asserts the sentence
  contains no `": "`, because turning it into a labelled line later would
  silently undo the whole point — and would also grow a header row in the
  manifest, which is how it would be noticed.
- **Discharge letters only.** A discharge letter carries a follow-up contact; a
  radiology report has no reason to. Coverage is therefore 6 of 19 rather than
  19 of 19, which is the first row in that table where counting documents
  separately from occurrences earns its keep.
- **Normal content, not an injected defect.** A discharge letter legitimately
  holds a follow-up contact. It is PHI to be removed, not damaged data, so
  counting it as a defect would make `--defect-rate 0` report defects on a
  corpus that claims to be clean — the same reasoning already recorded for a
  radiologist citing a previous study's date.

The regression guard is now end to end: a test builds from a generated corpus
and asserts that no report holds an `@`, a `.invalid` domain, or the
half-redacted `[NAME]@` — **and first asserts that the contact category actually
fired**, because without that the other three assertions would pass happily on a
corpus containing no contacts at all, which is exactly the hole being closed.

Two ripples worth recording, because both were found by looking rather than
assumed:

**The README's captured output went stale, including a line nobody would have
predicted.** PHI spans moved 3642 to 3685 and free-text redactions 924 to 975,
which are the obvious consequences. But the residual-risk list lost an entry:
`OSPE` disappeared, leaving only `GIOV`. The reason is the truncation defect —
`reports.truncated` cuts at a position drawn from the document's own length, and
discharge letters are now longer, so the cut lands elsewhere and the truncated
institution fragment that used to survive no longer does. A change to the
generator's *content* moved the output of a *defect*, through the length of the
text. Worth knowing that the two are coupled at all.

**And the fingerprint in the README is still the old one, deliberately.** Subject
labels derive from the key, so re-capturing with a fresh key would have changed
every `sub-...` label in the worked example for no reason. Checked rather than
assumed: building the same corpus under two different keys produces an identical
residual-risk list, so those numbers are corpus-dependent and key-independent,
and the old fingerprint stays consistent with the labels printed beside it.

**2026-11-11 — The codice fiscale is read from the PID-3 identifier list, with
PID-19 kept as a fallback. And HL7 v2 table 0203 has no code for Italy.** The
reader took the national identifier from PID-19 only. HL7 deprecated that field
in v2.3.1, and an Italian installation carries the codice fiscale in the PID-3
identifier list with a type code, so the common case was the one not handled —
the reader would have raised "PID-19 carries no national identifier" on a
perfectly ordinary message and dropped every subject in the export.

**PID-19 stays supported, and that is a decision rather than caution.**
Deprecated is not withdrawn: the field is still in the standard, interfaces
built against v2.3 are still in production, and a reader is the tolerant half of
this codebase by an explicit decision of 2026-11-07. Refusing a deprecated field
would reject messages a hospital cannot stop sending, for the sake of a
correctness nobody benefits from. PID-3 is preferred when both carry a value,
because the undeprecated field is the authoritative one.

**The type code was checked against the table rather than recalled, and the
recollection was wrong.** `NNITA` is *not* a concept in HL7 v2 table 0203. What
the table has is a pattern: `NNxxx`, "National Person Identifier where the xxx
is the ISO table 3166 3-character (alphabetic) country code". So `NNITA` is that
pattern instantiated for Italy — well-formed, and what Italian profiles send,
but not something you can find by searching the table for it. The table does
list `NI`, "National unique individual identifier", which some systems use for
the same value. The reader accepts both; the generator emits `NNITA`. Writing
`NNITA` into a constant without checking would have produced a plausible-looking
code with no provenance, which is the same failure as a plausible IRI that
resolves to nothing.

**The placement belongs to the site, not to the message.** `Site` gains
`national_id_in_pid_19`, and one of the five sites has it set. An interface does
not change its mind between two messages, so varying it per message would model
something that does not happen; varying it per site means a generated corpus
contains both forms — on a 20-subject run, 42 messages in the PID-3 form and 29
in the legacy one — and the reader's fallback is exercised by `generate` instead
of only by a unit test. The same argument as the contact detail yesterday: a
path no corpus reaches is a path nobody has measured.

**One guard that is less obvious than the rest.** When no repetition carries a
medical-record type code, the reader falls back to PID-3's first identifier —
but *only if no repetition carries a type code at all*. Once a sender labels
anything, an unlabelled identifier is something it chose not to label, and
taking it for the record number is how a codice fiscale gets filed as a hospital
number. The record number is what imaging links on, so that mistake would
attach the wrong studies to the wrong person while every count still looked
right. A test pins the distinction.

Also added, because `component` could not express it: `Segment.repetition_components`.
Splitting a repeating field on the component separator first attributes every
later repetition to the first identifier and reads component five out of the
second identifier's text. The two separators have to be applied in the right
order, and PID-3 is the first field in this project that repeats *and* carries
components that matter.

**2026-11-11 — The manifest now digests the dataset, `commissura verify`
recomputes it, and the manifest's own digest is the interesting half of the
question.** The manifest recorded what was done and nothing tied it to the bytes
it described. Anybody could change a value in a `lab/*.tsv` or paste a name back
into a report and every statement in the manifest would go on reading as though
it were still true. A de-identification record that cannot be tied to the data
is a record of something else.

So `build` writes a SHA-256 per produced file and `verify` recomputes them,
reporting altered, missing and added. Deliberately the mirror image of
`generate.writer.verify_corpus`, which re-reads the *input* corpus and confirms
the recorded PHI offsets still quote the text on disk: a claim about bytes gets
checked against the bytes, at both ends of the pipeline.

**The manifest cannot contain its own digest, and the three ways out are not
equally honest.** Excluding it silently leaves a hole anyone can walk through:
recompute the list after editing a report and `verify` passes. A sidecar file
holding the manifest's digest only moves the hole one file along. Re-serialising
the manifest with a zeroed digest field is self-contained but makes verification
depend on byte-exact round-tripping, which is fragile for no gain.

**What was done instead: an HMAC over the manifest's canonical content, keyed by
the secret that built the dataset**, in a `manifest_hmac` field excluded from
its own input. `verify --key-file` checks it. The argument for it is that it
costs nothing in trust: an attacker holding the key can forge the tag, but an
attacker holding the key can already recompute every pseudonym in the dataset,
so the tag is exactly as strong as the rest of the scheme and no weaker. And the
key lives outside the dataset by design, so in the ordinary case — somebody with
write access to a share — they can edit the files and cannot forge the tag.

The HMAC lives in `deident.pseudonymise` under its own domain prefix,
`"manifest|"`, beside `subject|`, `offset|`, `uid|` and `accession|`. Two
reasons. Every use of the secret stays in one file, so there is one place to
read to know what the key touches. And the tag can never collide with a subject
label, which is the whole point of the prefixes. This is authentication rather
than pseudonymisation and the two share a key only because there is one key;
that is worth knowing rather than hiding.

**The honest split, which maps onto who holds what:** anyone can check the
per-file digests, and that detects accident — a TSV opened in a spreadsheet and
saved back, an incomplete copy, a stray export in the tree. Only the key holder
can check the manifest itself, and that detects a deliberate edit. An HDAB
receiving a dataset without the key therefore cannot prove it was not tampered
with, and the manifest's own `integrity.note` says so in the file rather than
leaving it to be inferred. A test demonstrates the limit instead of asserting it
in a comment: a tamperer who recomputes the whole digest list passes
`verify_dataset` completely, and fails it the moment a key is supplied.

Three smaller decisions that each had a wrong-looking alternative:

- **`verify` reports "not authenticated" when given no key**, not "ok". Three
  states and not two: unchecked, checked-and-good, checked-and-bad. Collapsing
  the first two is how a missing `--key-file` comes to read as a clean bill of
  health.
- **A failed tag is reported apart from the file differences**, because zero
  files differing and a failed tag is a *specific* signature — somebody
  adjusting the manifest to cover their tracks — and it would otherwise print
  as "CHANGED: 0 file(s) differ", which is nonsense. Found by running it.
- **The tag covers content, not formatting.** It is computed over sorted-key,
  minimally-separated JSON with the tag field removed, so pretty-printing the
  manifest does not break it. A tag that failed on a reformatted file would
  teach people to ignore the tag, and an ignored tag is worse than none.

**One ordering consequence.** The manifest is now written *last*, after the
HealthDCAT-AP description and the risk report, because it digests them. Written
where it used to be it would describe a dataset that did not exist yet, and
`verify` would report the two documents that followed it as additions on a
dataset nobody had touched.

**And `tests/test_brief.py` earned itself the same day it was written.** Adding
`verify` to the CLI made the brief's command list stale, and the test failed
with the old list before anybody read the file. That is precisely the drift it
exists to catch, caught inside a day rather than inside three weeks.

**2026-11-11 — Four limits are now stated in the README, above the install
instructions rather than below them.** A tool that touches health data should
say what it cannot do before somebody installs it. All four were true before
today and none of them was written down where a reader would meet it, which for
two of them is close to misleading by omission.

- **It needs a structured source beside the free text.** Targeted redaction has
  nothing to work from without the fields that state the name, the identifier
  and the institution. Said plainly: a folder of PDF reports and nothing else is
  not served by this tool. That is a real population of users turned away, and
  turning them away explicitly is better than letting them find out after a
  build that silently redacted nothing.
- **Exact intervals are a re-identification channel, kept open on purpose.** One
  true date for a subject, from any other source, recovers that subject's whole
  timeline, because every other event is a known number of days from the
  baseline. This is the most likely route from a dataset built here back to a
  person, and the mitigation — blurring the intervals — would destroy what the
  offsets exist to preserve. So it is a documented trade-off and not a bug, and
  the README now says which side it takes and why the reader may need the other.
- **Small cohorts cannot reach a useful k.** `risk` already printed the honest
  number; a README reader never saw it. Twenty-five people with exact ages
  cannot reach k=5 on age and sex, and that is arithmetic.
- **Losing the key orphans the dataset permanently.** Readable, but not
  extensible and not linkable: next year's records for the same people can never
  be given the same labels. `keygen` says this at the moment it writes the file;
  the README did not say it at all.

Deliberately *not* restated here: that this tool pseudonymises rather than
anonymises. It is in the `risk` section already, and the convention added
yesterday says to point at the section that owns a fact instead of repeating it.
The new section links there rather than paraphrasing.

**2026-11-11 — `uv.lock` is committed, CI installs from it, and free resolution
moved to a weekly canary with its own badge.** Nothing pinned the dependency
set: `uv pip install -e ".[dev]"` resolved afresh every time, so two people
installing a month apart could get different versions of `typer` or `pydantic`
and only one of them would see a bug.

**That is not hypothetical and it did not take a month.** The very first
`uv sync --locked` in this repository replaced the already-installed `typer`
0.28.0 with 0.29.0 — the same unchanged project, resolved days apart, landing on
different versions. It happens to matter here: `tests/test_brief.py` reaches
into typer through `typer.main.get_command`, and the log entry of 2026-11-10
records that typer 0.28 dropped its dependency on click. Everything passes on
0.29.0, which is a relief rather than a plan.

**The CI question has two answers because it is two questions**, and running one
job cannot answer both.

*Does this commit work?* That is a gate, and a gate has to fail for the change
in front of it and nothing else. A gate that resolves dependencies freely goes
red on a morning when somebody published a release, the failure has nothing to
do with the commit, and the third time it happens people start merging through
red ticks — which costs more than the drift it was supposed to catch. So the
matrix jobs now run `uv sync --locked --extra dev`. `--locked` also fails when
`pyproject.toml` and the lock disagree, which catches a dependency changed
without refreshing the lock; that failure *is* about the commit.

*Do today's dependencies still work?* That is a canary, and it is a real
question — a lockfile answers "it worked" and never "it still works", so a
project that only installs from its lock finds out about an upstream break from
a user. `.github/workflows/upstream.yml` resolves freely with `--upgrade` every
Monday on 3.11 and 3.14 — the floor and the ceiling, because an upstream package
dropping 3.11 is among the likelier breakages and would show there alone. It
prints `uv pip list` before testing, so a failure can be read without re-running
it.

**A separate workflow rather than another job in `ci.yml`, and that is the part
worth defending.** A canary failure in `ci.yml` would turn the CI badge red, and
the badge would stop meaning "this code is good" and start meaning "something,
somewhere, moved". Two badges that each mean one thing are worth more than one
badge that means either. Caching is off in the canary for the same reason: a
cached resolution is the opposite of the point.

Known and accepted: GitHub disables scheduled workflows after 60 days of
repository inactivity, so a long quiet spell switches the canary off silently.
`workflow_dispatch` is declared so it can always be run by hand, and this
paragraph exists so the next person does not conclude from a stale badge that
upstream has been fine for a year.

**2026-11-11 — Chained re-pseudonymisation is designed and deliberately not
implemented.** The scheme, for whenever somebody asks:

```
released_id = HMAC-SHA256(release_key, "relabel|" + subject_id)[:12]
```

The input is the **subject label already in the dataset**, not the national
identifier. That is the whole point and it is what makes the thing worth
designing: the party applying the second layer never needs, never sees and
never stores an original identifier. They take `sub-a3f9c21b4e07`, apply a key
of their own, and get a different label.

**This is the executable form of the double pseudonymisation the regulation
foresees.** The FAQ reading of 2026-11-10 settled that both the health data
holder and the HDAB may pseudonymise, that the holder should do it as early as
possible, and that ultimate responsibility rests on the HDAB. A second layer
applied on top of ours is exactly that arrangement expressed as a function: the
holder pseudonymises first, the HDAB re-does it over the result, and neither
needs what the other holds.

**The threat it actually addresses is less obvious than it looks, and it is not
the data user.** A single layer already hides identities from the user. What it
does not do is stop *the holder* recognising its own released data: the holder
derived those labels and can re-derive them for anybody it can name. So a
hospital receiving an analysis of a dataset it contributed can map rows back to
patients. The second layer breaks that link, because the holder does not have
the release key — and that is a protection against the party doing the
releasing, which is the one a holder-side tool cannot give itself.

Four properties worth having written down before anybody builds it:

- **A distinct domain prefix per stage.** `"relabel|"` rather than reusing
  `"subject|"`. The keys differ so there is no collision to prevent, but the
  prefix records which layer produced a label, and a scheme whose stages are
  indistinguishable is one nobody can audit later.
- **Determinism survives the chain**, so two datasets carrying the same
  first-stage labels still relabel to the same second-stage labels. That is what
  makes cross-holder linkage work at the HDAB, which is the case the FAQ's own
  worked example describes.
- **Collisions propagate and the input is 48 bits.** The first stage keeps 12
  hex characters, so the second stage draws from a space of 2^48 and inherits
  every collision the first produced. The birthday bound is around 16.7 million
  subjects, which is far outside any realistic cohort, and `Pseudonymiser`
  already checks what it issues. Recorded because a reader of the formula would
  otherwise have to work it out.
- **It relabels subjects and nothing else, which is the limit.** `day_offset`
  values are unchanged, and offsets are stable per (key, corpus), so a holder
  can still align two timelines by their shape even after relabelling. Closing
  that would mean re-shifting dates, which would destroy the interval alignment
  the offsets exist to provide. A second layer therefore buys less than it
  appears to, and saying so is more useful than shipping it quietly.

**Why it is not implemented: nobody asked, and it belongs on the other side of
the chain.** commissura is a holder's tool. The party that would run this is the
HDAB, which does not exist in Italy yet — designation is due March 2027 — and
whose requirements arrive with the Article 77 and 78 implementing acts in the
same month. Building it now means building for a user nobody has met against a
specification nobody has written, and the most likely outcome is a mechanism
that has to be thrown away. The formula costs four lines when it is wanted; the
reasoning above is the part that would have been lost.

**2026-11-11 — HealthDCAT-AP issues #55 and #61 can both change what we emit in
`hasVariables`, and the CSVW construction stays behind one function because of
them.** Read rather than recalled: both are open on the profile's own tracker.

**#55, "Support full W3C CSVW structure for variable descriptions."** Release 8
nests `csvw:TableGroup → csvw:Table → csvw:Column`. The W3C CSVW metadata
specification nests `csvw:TableGroup → csvw:Table → csvw:TableSchema →
csvw:Column`, attaching columns through `csvw:tableSchema` and then
`csvw:column` rather than directly to the table. The issue's own argument is
interoperability: W3C-compliant CSVW metadata cannot be reused in a
HealthDCAT-AP description as it stands. If upstream adopts the W3C shape, every
description we have emitted gains a level in the middle.

**#61, "Clarify allowed CSVW Column datatypes (base types vs derived / XSD
IRIs)."** Release 8's SHACL requires exactly one `csvw:datatype` per column, as
a **literal** carrying a CSVW built-in name — `"string"`, `"integer"`. CSVW and
XML Schema also permit types derived from base types, and implementations
mapping from richer source models naturally emit XSD datatype IRIs such as
`xsd:decimal` or `xsd:dateTime`. The issue asks whether rejecting those is
intentional or an oversight. We currently emit the built-in literals, which is
what the published shapes require, so **we are conformant today and would stop
being so if the answer is "IRIs"** — an unusual shape of risk, where doing the
correct thing now is what the change would break.

So: one is a structural change to the nesting, the other a change to the leaf
values, and between them they could rewrite every `hasVariables` node.

**Which is why `_csvw_table_group()` is the only place that builds it.** One
function, called once, constructing the whole `TableGroup → Table → Column`
nesting and each column's five properties. Inserting a `TableSchema` level or
swapping the datatype literals for IRIs is an edit inside that function and
touches nothing else. The alternative — assembling the structure inline where
the description is written, or spreading it across the column loop and the
caller — would make each of these a change in several places, with the usual
result that one of them is missed and the document is half-migrated.

This is the same mitigation already recorded for the provisional
`healthdcatap:` namespace, which the profile admits will be renamed: IRIs are
assembled from `healthdcat.NAMESPACES` in one place and never written into
templates. Two known-pending upstream changes, two single points of edit. The
pattern is worth naming as a pattern, because the next one will arrive the same
way: **when a specification tells you a part of it is unsettled, put that part
behind one function and write down which issue will move it.**

**2026-11-12 — `commissura measure` exists, and the first thing it did was find
three leaks.** The generator has always recorded every identifier it plants,
with file and character offsets. Nothing ever compared that record to the
output. "Rules first, **measurement always**" was the project's differentiating
claim and half of it was a promise. The number on the walkthrough corpus is
**100% of 3,471 measurable planted identifiers removed**; the value of the
command is not that number but what producing it turned up.

**What it found, none of it visible by reading the code.**

1. **The manifest recorded the corpus's absolute path.** On any ordinary
   machine that contains the operator's account name, and it sat in the one
   document written to be sent to a Health Data Access Body. It surfaced
   absurdly: the generator invented a clinician called JONATHAN, the measurement
   reported that name as surviving, and the match was the username in
   `source.root`. Now `root_name`, the directory's name alone — the part a human
   chose, where the rest was an accident of where the command was run.
2. **The residual-risk list quoted the tokens it was warning about.** A
   patient's surname appeared in `.deident/manifest.json` of a dataset from
   which every other trace of it had been scrubbed. The document whose sentence
   is "I could not remove these" was handing them over, to the same reader. It
   now reports a count and a length range; `ScrubReport.path` already names the
   document, so a reviewer loses nothing but the convenience of not opening it.
3. **Institution addresses were learned only from imaging metadata.** A site
   that sent laboratory messages and wrote reports but produced no imaging study
   had its street and city printed in every report header and never redacted.
   Its *name* was removed, which is exactly what made it hard to see: the header
   read `[INSTITUTION]` above an intact `Via dei Lecci 92 - Cagliari`. The fix
   reads the line under an institution the structured exports already named —
   anchored rather than positional, because "the second line" would redact
   whatever sits there in somebody else's template, while anchoring on a value
   MSH-4 declared is the same move the rest of this pipeline makes.

Number three is worth dwelling on. It only appeared on a **five**-subject
corpus; the twenty-five-subject walkthrough gives every site an imaging study,
so every address was known and the run was clean. A measurement taken on one
corpus is a measurement of that corpus, and the bug was waiting behind a cohort
size.

**Three exclusions, each reported rather than folded into the number**, because
every one of them could be used to flatter it:

- **Spans under four characters are counted neither way.** `DE`, a fragment of
  a surname, matches inside "de-identification". Calling it survived invents a
  leak; calling it removed invents a success. The threshold is the scrubber's
  own `_MINIMUM_REDACTABLE`, deliberately: measuring against a stricter rule
  than the method was given would be scoring it on a different exam.
- **Ages are kept by design** and reported apart. Scoring them would measure
  the opposite of the intended behaviour. The exclusion currently changes no
  number — report ages are two characters and fall in the short bucket, DICOM
  `045Y` values are four and are removed with the rest of the tag — so it is
  insurance rather than load-bearing, and saying so is part of the entry.
- **Strings the holder typed are excluded**, read back from the emitted Article
  77 description so the dataset itself declares which values were supplied
  rather than derived. Forced by a real collision: the README's own walkthrough
  passes `--publisher "IRCCS SINTETICO MAREBIANCO"`, which is also one of the
  generator's sites, so 72 institution spans "survive" into a description that
  is *supposed* to name its publisher. Reporting that as a leak would be
  literally true and wrong, and any user following the README would hit it.

**Case-insensitive, and that decision earned itself immediately.** Matching
case-sensitively reported a clean sweep. The same corpus matched
case-insensitively showed surviving clinician names. A name in different case
is still the name.

**The threshold is two thresholds, because the honest answers differ.** A clean
corpus is pinned at 100%: a floor with slack absorbs the first regression
silently, and the first is the one worth catching. A corpus at
`--defect-rate 0.6` scores **98.45%** and is pinned above 95% — *and* every
survivor is asserted to be a person's name in a report. The leak there is
`reports.missing_author` meeting `reports.identifier_in_prose`: the signature
block is the only structured field naming that clinician, and removing it
leaves them named mid-sentence with nothing to match against. That is the
documented limit of targeted redaction with a number attached rather than a
caveat in prose, and closing it would mean named entity recognition, which this
project rejects. Pinning the *class* of survivor matters more than the bound: a
number alone stays green while the failure changes character into something
that is a defect rather than a limit.

**And the limit no exclusion fixes, stated in the command's own output.** This
asks whether the exact planted string survived. A fragment of one is not a miss
here and never will be. The scrubber's residual-risk list answers the opposite
question — it inspects the output for anything shaped like an identifier,
knowing nothing about what was planted. Two measurements that fail differently,
and a reader needs both. A test pins that a truncated institution name is *not*
reported, so nobody later "improves" the recall figure by making it
substring-match and quietly turns it into a different, worse metric.

**2026-11-12 — The README now says how to bring your own data, because the
capability existed and the instructions did not.** `read_corpus` never required
the generator: it globs `lab/*.hl7`, `reports/*.txt` and `imaging/*.json` and
reads what it finds. So a hospital could always have pointed `build` at a real
export. Nothing anywhere said so, which made a working feature invisible.

Documentation only, no code. The part worth the entry is **what fails quietly**,
because both failure modes read to a new user as "the tool is broken":

- **Unrecognised header labels mean every report is unlinked.** A template
  writing `CF` instead of `Codice fiscale` attaches no report to anybody. The
  build then *succeeds*, with no reports in the dataset and an
  `unlinked_report` issue per file — which is the tool stating the problem
  exactly, in `.deident/manifest.json`, where nobody has looked yet.
- **A linked record with an unparseable date is dropped and is not an issue.**
  Sessions are dated encounters, so a report whose `Data del referto` cannot be
  read has nowhere to go. Linkage succeeded, so nothing is reported; the record
  is simply absent. The only signal is the file count in the build summary
  being lower than the number of files handed over, and the README now says to
  compare them.

The second one is the worse of the two and was the harder to find: a failure
that produces no issue, no warning and no error, visible only as a number that
is smaller than you expected and only if you were counting.

Not fixed here, deliberately — this task was documentation, and turning a
silent drop into a reported one changes `build`'s behaviour and the manifest's
schema. Recorded as the obvious next improvement: records dropped for an
unreadable date belong in `linkage_issues` with a reason of their own, since
"the dataset does not contain what you gave it" is exactly the class of fact
that file exists to carry.

**2026-11-12 — `commissura whois` derives a subject label from a real
identifier, and the inverse does not exist and will not.** Without it a data
holder cannot act on an EHDS opt-out. Somebody exercises their right to object;
the holder knows exactly who they are and has to find them in datasets already
released, where the name appears nowhere. The subject label is the only handle,
and until now nothing produced one outside a build.

**Why there is no command going the other way**, recorded here so that it is a
decision and not an omission somebody later "fixes":

- **There is nothing to implement.** The label is
  `HMAC-SHA256(key, "subject|" + national_id)` truncated to twelve hex
  characters. An HMAC has no inverse, and the truncation means the mapping is
  not injective even in principle, so "the identifier for this label" is not a
  well-defined question.
- **The only way to fake one is to enumerate the identifier space and build a
  table — which is the attack this design was chosen to resist.** The stack
  decision of 2026-11-06 rejected a plain `hash(national_id)` in exactly those
  words. A reverse command would be that attack, shipped, with the key holder's
  convenience as the excuse. A codice fiscale is derivable from a name, a date
  of birth, a birthplace and a sex, so the space is enumerable for any
  individual somebody is actually interested in.
- **The forward direction is all the use case needs.** An opt-out starts from a
  named person. You do not need to ask who a label belongs to; you need to ask
  which label a person was given.

A test asserts that no command named `unwhois`, `reverse`, `resolve`, `lookup`
or `identify` exists. That is cheap and it is how the decision survives a
future contributor who has a good afternoon and a bad idea.

**Three constraints on the command itself.**

It takes **no key as a value**, only `--key-file` or the environment variable,
and a test pins that the help text offers no `--key`. Same reasoning as `build`:
a key on the command line is a key in shell history, in `ps` output and in CI
logs.

It also **reads the identifier from stdin** when the argument is omitted, and
the help says why. The argument against putting the key on a command line
applies, less severely, to a codice fiscale: it is patient data, and
`whois RSSMRA80A01X000A` sits in `.bash_history` afterwards. Offering the pipe
costs one line and the test confirms both routes agree.

And it **reads no dataset**. Pure derivation, which has a consequence worth
stating rather than discovering: it gives the same answer for somebody who is
in no dataset at all. That is deliberate. A command that looked the label up
would answer "is this person in this dataset?", which is a different and much
more dangerous question, and one that a tool handing out answers over a key
should not be in the business of. The text output says so, and tells the
operator to check the key fingerprint against the manifest's before trusting a
label against a particular dataset.

**2026-11-12 — A record that links and is then dropped is now reported, with
its own reason.** Yesterday's entry on bringing your own data named this as the
worse of two silent failures and left it: a report whose `Data del referto`
cannot be parsed, or an imaging study with no StudyDate, has nowhere to go
because sessions are dated encounters. Linkage *succeeded*, so it produced no
linkage issue, no warning and no error. The only evidence was a file count
lower than the number of files handed over, visible to somebody who was
counting. "The dataset does not contain what you gave it" is exactly the class
of fact the manifest exists to carry, and it was not carrying it.

**Two lists, not one, and the reason is precision rather than tidiness.** A
`LinkageIssue` is a record that could not be attached to anybody; a
`DroppedRecord` was attached and then had nowhere to go. Folding the second
into `source.linkage_issues` would have been one fewer field and a lie about
half its contents — and the two need different fixes, a labelling problem in
the export versus a date format the reader does not recognise. What a reader
actually wanted was the *sum*, so `source.records_not_in_dataset` is that one
number and the two lists keep their own names.

**Two reasons, because one would have hidden the worse case.**
`undated_record` names the field that should have held a date, in the source
format's own terms, so a reader knows what to open. `subject_has_no_dated_event`
is reported separately: with no baseline, *every* one of that subject's records
drops rather than one, and a row still appears in `participants.tsv` — so the
dataset claims a participant it holds nothing for. A single reason would have
made that look like several ordinary parse failures that happened to share a
subject.

Schema to **2.1.0**. Additive, so a reader of 2.0.0 still parses it; the minor
number moves because there is something new to read. Noted because yesterday's
entry had to record a reshape that shipped without the version moving at all.

**And the honest gap: no generated corpus reaches this code.** At
`--defect-rate 0.8` the drop count is zero. The generator has no defect that
produces an unparseable date — the format-drift defect emits `DD/MM/YYYY`,
which `parse_timestamp` accepts — so the path is exercised by hand-built
fixtures and by nothing else. That is the third time this project has found a
rule no corpus reaches, after the contact patterns and the PID-19 fallback, and
both of those were closed by giving the generator a way to produce the case. An
`*.unreadable_date` defect would close this one and is the obvious next step.
It is not done here because it was not what was asked, and because it changes
the ground-truth annotations and every captured number in the README again —
which is a reason to do it deliberately rather than in passing.

**2026-11-12 — `reports.unreadable_date` makes the dropped-record path
reachable from a generated corpus, and adding it found a leak I had introduced
that morning.** The drop reporting shipped hours earlier with an honest gap
recorded against it: at `--defect-rate 0.8` the drop count was zero, because
the only date defect emits `DD/MM/YYYY` and the reader accepts that. The new
defect leaves the report date as an unfilled template placeholder,
`Data del referto: __/__/____` — a document that reads perfectly to a human and
carries no date a parser can use.

**The placeholder is written as a plain string and not as a `Phi` span**, which
matters more than it looks. Recording it as ground truth would put a value in
the annotations that nothing could ever leak, and it would count as removed for
free: a way of scoring better by planting easier targets. A test asserts no
span in a generated corpus looks like it.

**And then `measure` reported fifty-five surviving patient identifiers.** The
manifest's `records_dropped` entries carried the file paths, and an export
names its files after the record they hold — `reports/8750056_dim_1.txt` is a
medical record number with an extension. So the list of absent records was a
list of patient identifiers, inside the document written to be sent to an
access body. One commit old, mine, and the instrument built that morning caught
it the same afternoon.

The shape had been wrong since linkage issues were first recorded, months of
commits ago. It never fired because every corpus tested had zero linkage
issues, so an empty list hid an unsafe shape until `records_dropped` gave it a
non-empty case. That is the third latent problem this project has found behind
"the list happened to be empty", after the conformance test that skipped
silently and the contact rule no corpus exercised.

**Two audiences, and only one of them needs the paths.** An auditor needs to
know how many records are absent and why; the operator needs to know *which
files* to go and fix. So the manifest carries `{reason, count, detail}` and
`build` prints the paths to the terminal, which does not travel. Breaking
change, schema **3.0.0**, and `linkage_issues` changes shape with
`records_dropped` because it had the same defect.

**One consequence I predicted and one I did not.**

Predicted: a dropped record removes its identifiers by not existing, so the
defect would flatter the recall figure. In the degenerate case a build that
dropped everything would score 100% for producing nothing. `measure` now reads
`records_not_in_dataset` from the manifest and prints it beside the recall —
*beside* and not subtracted from, because attributing it span by span would
need the file paths that had just been removed for good reason. The first
attempt did exactly that and had to be undone within the hour.

Not predicted: the defect **silenced an existing test**.
`test_a_defective_corpus_leaks_only_names_nothing_declared` asserted that seed
23 at rate 0.6 leaks clinician names, and it stopped leaking — because the new
defect drops the very reports that used to leak. The assertion's own message
said "if it no longer does, find out why before celebrating", which is exactly
what happened. The test now fixes a seed that still exercises the limit and
says in its docstring why the seed is load-bearing.

That seed also widened the documented limit: it leaks an **institution** as
well as clinician names — the site of a previous study, cited in prose after
"presso", declared in no structured field. Same class, and the scrubber's
residual-risk list already warns about exactly that sentence shape. The test
now pins the class as "named in prose, declared nowhere" rather than "a
person's name", which is what it always meant.

Cost, recorded because it is visible to anyone reading the README: at the
walkthrough's `--defect-rate 0.2`, thirteen of forty-eight reports are now
dropped. The example dataset is smaller and the example is better, because the
number is on screen and the paths are under it.

**2026-11-12 — CI went red on a test that asserted against rendered help text,
and the fix exposed a second guard that had been green without guarding.** The
failure was `test_whois_takes_no_key_as_a_value`, which did
`assert "--key-file" in result.stdout` after invoking `whois --help`. It passed
on this machine and failed on every CI job.

**The cause is that typer renders help through rich, and rich emits style codes
when colour is on.** GitHub Actions sets an environment where colour is
enabled; the terminal these commands run in locally does not, so rich printed
plain text here and ANSI there. And the codes land *inside* the token:
`--key-file` is simply not a substring of the coloured output. Reproduced
exactly before changing anything — with `FORCE_COLOR=1` the substring test
returns False, and after stripping the escapes it returns True.

**The fix is not to strip ANSI in the test.** That would keep asserting against
a picture of the interface, which is also width-dependent and renderer-
dependent, and would break again the next time typer changes how it draws a
panel. The intent was always about the *declared* interface: `whois` offers
`--key-file` and offers no option taking a key as a value. So the tests now ask
click for the parameter list — `get_command(app).commands[name].params` — which
is the interface itself.

**The second finding is the better one.** The pre-existing
`test_there_is_no_option_to_pass_a_key_as_an_argument` asserted only
*negatives* against the same help text: `"--key " not in help_text`. A negative
substring assertion against coloured output passes no matter what, because the
styled token never matches the plain one. That test had therefore been green in
CI while checking nothing at all, since the day CI was set up — and it guards
one of this project's load-bearing security decisions.

It is now `test_no_command_anywhere_takes_a_key_as_a_value`, over **every**
registered command rather than the two that existed when it was written,
because the rule is about the project and a new command is exactly where it
would be broken. And a second test asserts the positive it was missing: the
commands that read a key do offer `--key-file`. A guard that only forbids
something passes on a command that offers no way to do the thing at all.

Both were checked by sabotage rather than by reading: adding `--key` as an
alias to `whois` makes both fail, and removing it makes them pass. A guard
nobody has watched fail is a guard nobody has tested.

**The generalisable lesson, and it is the second time today.** The brief's
sentinel broke this morning because a sentence wrapped across two lines; this
broke because a token acquired colour. Both asserted on *rendered text* when
they meant something structural. Assert on the thing, not on its picture — and
where the picture is all you have, be suspicious of a negative assertion, which
is the shape that fails silently.

**2026-11-13 — `build --report` writes a single-file HTML page, and it is the
only output of this tool that must never be released.** Everything it shows is
already on disk in JSON. What was missing is a way to *look* at it: comparing a
report before and after de-identification is the one check nobody can automate,
because the question is whether the clinical content survived, and it meant
opening two files in two windows and reading across. A terminal is bad at this
and always will be.

**The whole design follows from one fact: the "before" half is unredacted
patient data.** That makes this artefact a different class from the manifest,
which is written to travel, and the difference had to be impossible to miss
rather than mentioned in documentation:

- **It is refused, not warned about, if the path is inside the dataset.** A file
  there is digested into the manifest's integrity list and shipped with the
  release — and `--report ./dataset/report.html` is precisely what somebody
  would type. A warning on a build that otherwise succeeded is a warning nobody
  reads. Tests cover the dataset root and a path nested deeper in it, because
  "inside" is the property and not "equal to".
- **The operator names the file.** There is no safe default location for
  something that must not be filed with the dataset, so there is no default.
- **It is opt-in and the page says what it is in its first screenful**, with a
  test asserting the warning appears before the first section heading. A test
  also asserts the dataset contains no HTML afterwards and that the manifest's
  digest list names none.

Also worth the entry because it looks like laziness and is not: **the page is
plain string assembly with escaping, and must not become a template system.** A
report that needs a build step is a report nobody regenerates. The checks that
earn that choice are a balanced-HTML parser over the whole document and a test
that feeds a report containing `<script>` and a stray `</pre>` through the
renderer — which is not hypothetical for a tool whose entire input is other
people's documents, where a report containing `<b>` would silently restyle the
page and one with a stray closing tag would break the comparison it sits in.

**One structural addition.** `BuildSummary` now records `ReportPair`, the
corpus path and dataset path of each report. Nothing else could reconstruct it:
the output path depends on which session a date fell into and how many reports
that session already held, so re-deriving it afterwards would mean running the
same logic twice and hoping the two agreed.

And one behaviour: a comparison whose source file has since moved is skipped
rather than raised. A picture of a build must not be able to fail the build.

**2026-11-13 — `risk` now measures the rarity of laboratory values, and the
honest answer is that almost everything is unique.** The demographic assessment
asks who is alone on age and sex. This asks who is alone on a *measurement*,
which is the same question about a column nobody thinks of as identifying: a
haemoglobin of 13.2 that nobody else in the cohort shares is a handle on
whoever has it, for anyone who knows that one value — and a clinician, a
relative or a previous employer may well know it.

**The number, on a sixty-subject corpus: 469 of 478 analyte-and-value
combinations are shared by fewer than five subjects. 98.1%.** On eight subjects
it was 100%. Tripling the cohort moved it two points. That is not a defect in
the dataset and not something a bigger cohort fixes: a measured value is a
near-unique quantity rather than a category, so **full k-anonymity over
continuous multivariate clinical data is not reachable at all**.

Which is worth stating because it explains the shape of the regulation this
project is built against. The EHDS does not protect secondary use by demanding
anonymisation; it protects it with **data permits and secure processing
environments**, because for data like this anonymisation is not available. The
report is a measurement handed to whoever makes that judgement. A test asserts
the note says so — that it contains "not a certificate of anonymity" and "not
reachable" — because the one way this section could do harm is by being read as
a clearance.

**Counted per subject and not per row**, which took a moment to see and matters.
The same person measured three times at the same value is one person. A row
count would report a patient with frequent bloods as *less* identifiable than
one with a single test, which is exactly backwards, and a test pins it.

**It reports and does not correct, and that is the substantive decision.** Every
available remedy destroys what the data is for:

- **Suppressing rare rows** removes the unusual value, which is simultaneously
  the re-identification risk and the reason somebody asked for the dataset.
- **Top and bottom coding** removes the extremes, where the clinically
  interesting cases live by definition.
- **Rounding into bands** does the same thing more quietly: a creatinine banded
  to the nearest whole number is a different measurement, and nothing
  downstream can tell.
- **Adding noise** is worse in a clinical setting than in most. An analyst who
  does not know how far wrong their numbers are cannot reason about them at
  all; the usual defence — that the distribution is preserved — is no comfort
  to somebody asking a question about one patient.

And the choice between them depends on the permit, the recipient and the release
arrangement, which only the data holder knows. A tool that silently banded the
values would be making that call on their behalf and hiding it in a build log.

One sizing decision: the listing is capped at fifty combinations while the count
stays exact. A complete list would be the dataset again with its rarest values
highlighted — a worse artefact than the dataset itself, written into the file
that travels.

**2026-11-13 — CI now proves that the same inputs produce the same bytes on
Ubuntu and on Windows.** Recording a SHA-256 per file made this checkable, and
for a tool whose whole point is to produce artefacts somebody will verify later,
"probably reproducible" is not a claim worth making. Each platform builds the
same dataset from the same seed and the same key, uploads its manifest, and a
third job compares the `integrity.files` maps.

**Only `integrity.files` is compared**, because the rest of the manifest
legitimately differs: `generated_at` is a timestamp and `tool_versions` names
the interpreter. The manifest excludes itself from its own digest list, which is
what makes this comparison possible at all — a document containing a timestamp
cannot be digested into a reproducible list that includes itself.

**Three things had to be pinned, and the third was a surprise.** The seed and
the key are obvious. The third is the *name* of the output directory:
`dct:identifier` is `urn:commissura:<directory name>`, so a build into `ds_a`
and one into `ds_b` differ in exactly one file and for a completely legitimate
reason. My first local comparison reported `healthdcat-ap.jsonld` as
non-deterministic and it was the test that was wrong. Running the comparison
locally before writing the CI job is the only reason that is a footnote rather
than a morning spent reading CI logs.

**The key is a published test vector**, the bytes `0x00` to `0x1f` in order,
which is what the test suite already uses. It is written by the workflow rather
than committed, because `.gitignore` excludes `*.key` for a reason and this file
has no business existing outside a CI run. It pseudonymises synthetic data in a
throwaway runner; a comment in the workflow says so, so nobody later mistakes it
for something that could be reused.

**Checked by sabotage before being trusted**, the same discipline as the
`--key` guard: the comparison script was extracted from the YAML, run against
two real manifests — which it declared identical — and then run again with one
digest altered, which it rejected while naming the file. A comparison nobody has
watched fail is a comparison nobody has tested. The embedded Python is also
compiled out of the YAML by hand, because a syntax error there is a round trip
through CI to discover.

What it also establishes, quietly: the corpus and dataset writers really do put
identical bytes on every platform. Checked while here — every file in a built
dataset is LF-terminated on Windows, which is the `newline=""` discipline the
brief has argued for since the beginning actually holding.

**2026-11-13 — Age generalisation into bands is designed and not implemented,
and when it arrives the manifest must record the width that was applied.** The
`risk` report says plainly that twenty-five people with exact ages cannot reach
k=5 on age and sex, and that banding is the fix. So the obvious next feature is
`--age-band 5`, replacing `42` with `40-44` in `participants.tsv`.

The design, for whoever builds it:

- **The width is the holder's choice, not a default.** Five years is the
  convention; ten is what a small cohort actually needs; one is no banding at
  all. Picking one for the user is the same mistake as picking their access
  tier, which this project already refuses to do.
- **The manifest must record the width**, and that is the part worth writing
  down now, because it is the part that gets forgotten. A dataset whose ages
  read `40-44` is not self-describing: a reader cannot tell a five-year band
  from a decade that happens to start on a multiple of five, and cannot tell a
  banded dataset from one whose source only ever had bands. The per-field table
  already distinguishes *removed*, *replaced* and *kept*; a banded age is
  `replaced`, and the note on that row is where the width belongs.
- **`risk` must then report k over the banded values**, not the originals, or
  the report describes a dataset nobody has.
- **The age ceiling stays separate.** Truncating at 89 is a de-identification
  invariant this project treats as structural; banding is a disclosure-control
  choice the holder makes. Collapsing the two into one option would make the
  invariant look optional.

Not implemented because nobody has asked and because the honest sequence is to
let somebody run `risk`, see k=1, and then say what they want — the width is a
judgement about their cohort and their permit, and a feature built before that
conversation is a guess with a flag on it.

**2026-11-13 — The real obstacle to using this on real data is that report
identity parsing is written against labels this project's own generator
produces.** `_REPORT_LABELS` maps four exact strings — `Paziente`,
`Codice fiscale`, `Numero nosografico`, `Data del referto` — and
`_signature_pattern` looks for a line beginning `Dott.`. Every one of those is a
convention invented here. A real hospital's template writes `CF`, or
`Pz.`, or nothing at all, and the consequence is already documented: every
report lands in `unlinked_report` and the build succeeds with no reports in it.

This is worth naming as *the* obstacle rather than one of several, because
everything else in the pipeline reads a standard. HL7 v2 field positions are
HL7's. DICOM tags are DICOM's. The dataset layout is BIDS. The description is
HealthDCAT-AP. Only the free-text header is ours, and it is the one part that
cannot be adapted by reading a specification — a new deployment means somebody
reading a sample document and editing a table.

The mitigation already in place is that it *is* a table, in one place, with a
docstring saying adaptation is an edit there and not a rewrite of the reader.
That is the most a layout-matching approach can offer, and it is not much. The
next entry is about the direction that escapes the problem rather than managing
it.

**2026-11-13 — There is no national standard for Italian report *prose*, but
there is one for the structured documents hospitals already have to produce —
and that, not better layout matching, is the direction for input.** Which
changes what "supporting real data" means.

What was found, and the provenance matters: **this is read from secondary
sources, not from the official implementation guides**, so it needs checking
against HL7 Italia and AgID before anybody builds against it.

- HL7 Italia, the Italian affiliate of HL7 International, develops CDA
  Release 2 profiles **with the Ministero della Salute, AgID and the Tavolo
  Tecnico sul Fascicolo Sanitario Elettronico**. The base standard is
  ANSI/HL7 CDAR2-2005.
- The profiles cover the documents this project already models: *Referto di
  Laboratorio*, *Referto di Radiologia*, *Lettera di Dimissione Ospedaliera*,
  *Verbale di Pronto Soccorso*, *Profilo Sanitario Sintetico*, and a
  specialist report.
- AgID made LOINC **mandatory** for identifying examinations in CDA2 laboratory
  reports in 2014 — which is the same vocabulary `lab/*.tsv` already carries in
  `loinc_code`.
- The radiology profile is the CDA form of the textual report, with optional
  linkage to the related DICOM studies.

**The structural point is the one that matters.** In a CDA document the
patient's identity is in the structured `recordTarget` header, not in the
narrative block. So the problem the previous entry describes — guessing which
line holds the codice fiscale — does not exist: the document *states* it, in a
defined element, the way HL7 v2 and DICOM already do for the other two
modalities. Targeted redaction, which is this project's whole method, would
work on CDA input without any template matching at all.

And hospitals must already produce these documents for the FSE, so supporting
them asks for nothing a site does not already have.

**One correction to the framing, and it is material.** The direction is not
simply "support CDA". HL7 Italia has moved much of its work to **FHIR** for
FSE 2.0, with implementation guides covering the Profilo Sanitario Sintetico,
laboratory reports, emergency-room reports, discharge letters, specialist
reports and vaccination records; the laboratory one is published as trial use
against FHIR R4. So a reader of this entry in a year should check which of the
two a hospital is actually sending before writing a parser: CDA R2 for the
documents already in regional FSEs, FHIR for FSE 2.0. One secondary source
claims a March 2026 deadline for structured delivery to FSE 2.0, which could
not be confirmed and is recorded here as unverified rather than as a date.

Either way the conclusion is the same and it is the useful one: **the input
roadmap is structured documents, not better layout matching.** Chasing
templates is work that never finishes and that no standard will ever reward.

**2026-11-13 — No graphical interface, and the reason is not aesthetics.**
Three arguments, in order of weight.

**The user works in a terminal and the point is composability.** Every command
takes `--json` precisely so the tool can sit inside somebody else's pipeline —
a nightly job, a Makefile, another institution's extract-and-ship script. A GUI
serves the one-off interactive case, which is the case this tool is least
needed for, and nothing in a GUI composes.

**It would build a security surface around the key file where there is none
today.** The key never appears on a command line, never in shell history,
never in `ps` output — decisions recorded on 2026-11-06 and still enforced by a
test over every command. A GUI needs somewhere to put the key: a file picker
that remembers its last directory, a field that might be logged, a session that
holds it in memory for as long as the window is open, a "remember this key"
checkbox that somebody will ask for. Each of those is a new way for the one
secret that matters to end up somewhere it should not be, and none of them buys
any de-identification that the CLI does not already do.

**And it does not address the real problem.** The honest state of this project
is that nobody has used it: the package is not on PyPI, the repository is
private, and the only person who has ever run it wrote it. A GUI would be
building for an imagined user while the actual gap is that there is no user at
all. The `--report` page added today is as far toward "visual" as this should
go: a static artefact, generated by the same command, with no interface to
maintain and nothing to secure.

Revisit only if somebody who has used the CLI says the interface is what stopped
them. Nobody has said that, because nobody has used the CLI.

**2026-11-13 — An audit asked the manifest question a fourth time and the answer
was yes, twice. Breaking change, schema 4.0.0.** The pattern had been found
three times — an absolute path, quoted residual-risk tokens, an institution
address — so the instruction was to look for a fourth: *for every field of
`.deident/manifest.json`, can it carry something derived from the input?*

Two could. `source.linkage_issues` and `source.records_dropped` each carried a
`detail` sentence assembled from the file that failed, so an unlinked report
named a codice fiscale and an unreadable file named a path with an exception
message, in the one document written to be sent to an access body. Both are now
`{reason, count}` only, and the modality ledgers' `unreadable` is a count rather
than a list of `path: error` strings. `build` prints the detail to the terminal,
which does not travel — the same split already decided for `records_dropped`
paths the day before.

**The shape had been wrong since linkage issues were first recorded, and never
fired.** Every corpus tested had zero of them, so an empty list hid an unsafe
shape until `records_dropped` gave it a non-empty case. That is the fourth time
this project has found a latent problem behind "the list happened to be empty",
after the conformance test that skipped silently, the contact rule no corpus
exercised, and the drop reporting itself. The generalisable form: **an empty
collection is not evidence that what fills it is safe.** The test that now
guards it is class-level — no planted identifier from the ground truth appears
anywhere in the manifest, whatever field it would travel in — because a test
naming the two fields would have passed on the next field somebody added.

Three other findings from the same audit, none of them a leak:

**The one place input reaches a format a browser interprets was escaping all but
two interpolations.** `build --report` assembles HTML by hand, deliberately, and
every value goes through `_esc` — except the two `class="tag {...}"` attributes,
where a disposition reading `removed" onmouseover="alert(1)` closed the
attribute and attached an event handler. Proven by passing that value through
the real renderer, not by reading. The existing balanced-HTML test **passed with
the injection in place**, which is the lesson worth keeping: a balance check
cannot see an attribute breakout, because the result is still balanced. The new
test parses the document and asserts on the set of attribute *names*, and the
dispositions are written by this tool — the manifest is read back from disk, so
"this value cannot contain a quote" is a statement about the code and not about
the file.

**`measure` was quadratic in the dataset.** It searched every file for every
span. Now one joined text answers "is this string anywhere", and only a span
that survived that is attributed to a file. 60 subjects went from 60.4s to
14.7s; 8 from 2.0s to 0.6s. Same output, checked by comparing the reports.

**`read_exact` existed three times** — in the corpus reader, the corpus writer
and the validator's context — identical, 20 lines of docstring apiece. One copy
now, in `read.corpus`, which has the fewest dependencies, and it keeps the
docstring that says *why*: `Path.read_text` grew `newline` only in 3.13 and this
project supports 3.11, and without it a bare carriage return would be
translated on Windows and every offset after the first would be wrong. Three
copies of a byte-exactness primitive is three places for one to drift.

And one test gap the coverage report had been showing all along: `recall`
returns `None` rather than 1.0 for a category with nothing measurable, and no
test exercised it. The decision is deliberate — printing 100% for a rule that
never fired is how a corpus that tests nothing comes to look like a corpus that
passes — so it now has a test. Both new tests were checked by sabotage before
being trusted, which is this project's rule: a guard nobody has watched fail is
a guard nobody has tested.

**2026-11-13 — An audit of the whole repository found one critical and three
high-severity defects, all four upstream of the de-identification, and all four
in the step that had no layer: deciding who is who.** The findings and the
remediation have their own documents — [SECURITY_AUDIT.md](SECURITY_AUDIT.md),
[ENGINEERING_REVIEW.md](ENGINEERING_REVIEW.md),
[REMEDIATION_REPORT.md](REMEDIATION_REPORT.md),
[IDENTITY_RESOLUTION.md](IDENTITY_RESOLUTION.md),
[HARDENING_CHANGELOG.md](HARDENING_CHANGELOG.md) — so this entry records only
what a future session needs to know and would not otherwise find.

**The lesson that generalises, and it is uncomfortable.** Every instrument this
project has built measures the *transformation*: `validate` checks the shape of
the output, `verify` checks its bytes, `measure` checks whether planted
identifiers survived, the residual-risk list checks what the output still looks
like. Not one of them measures the *grouping*. "Rules first, measurement always"
had been applied with real rigour to de-identification and not at all to the
step de-identification depends on — and 99.11% branch coverage coexisted with a
dataset containing `Paziente: FRANCESCA FONTANA` in plain text.

The reason a grouping error is not contained is worth stating once, properly:
**targeted redaction removes the identifiers the structured exports declared for
that subject.** So two people merged under one key leave one identity in the
known set, and the second person's name is not a name the method fails to find —
it is a name the method was never told to look for. The audit's corpus was two
messages whose national identifier was the string `UNKNOWN`, which is what a
real interface writes when the field is unavailable. One subject, zero linkage
issues, and selective redaction that looked like success because the first
person's name *was* removed.

**Four decisions in the fix, each of which had a wrong-looking alternative.**

*A placeholder is not a key, and the records are not discarded either.* The
tempting answers were to merge them (what it did) or to refuse them outright.
Neither is right: the record number still identifies the patient within the
institution that issued it, so the subject exists, is keyed on
`(authority, number)`, and is reported as not relinkable across institutions. An
unusable identifier is a diagnosis, not a dead end.

*A subject keeps every identity, not the first.* This is the actual fix for the
leak and it is one line of model change. `KnownIdentifiers.identity` became
`identities`, deliberately without a compatibility property: a caller passing
one identity where the field takes a tuple is a caller whose redaction would be
incomplete, and that must not compile.

*An ambiguity is refused, and refused deterministically.* The old code's
last-write-wins made the result depend on filename sort order. The ambiguity set
is now monotone, so the answer is a property of the set of records and not of
their order, and a test reads the same corpus in two orders.

*The authority is read only from the record-number repetition.* The first
version fell back to "whichever repetition names an authority" — exactly as the
audit's own recommended mitigation suggested — and picked up `MINSAL`, the
ministry that issues codice fiscali, from the national identifier's repetition.
That scopes every hospital under one national namespace: the flat index this
change exists to remove, reintroduced under a plausible name. **The audit was
wrong about its own fix, and a test caught it.**

**Pseudonyms are unchanged for valid input, and that was verified rather than
assumed.** A well-formed codice fiscale normalises to itself, so the derivation
input is byte-for-byte what it was. Every subject label in the 25-subject
walkthrough and in a second corpus is identical. `RULE_VERSION` is 1.1.0, a
minor bump, and the constant documents which inputs do move: lowercase, internal
whitespace, compatibility encodings, and anything that was merged under a
placeholder. A rebuild is the only migration and there should not be another —
a dataset whose subjects were merged wrongly cannot be fixed by relabelling,
because the records inside a merged subject have to be separated first.

**Adding codice fiscale validation immediately rejected five identifiers in this
project's own fixtures**, including the default in `conftest.py`. Each had a
check character that does not check. Corrected across 19 occurrences rather
than exempted, because the validator is right and the fixtures were invented.
The generator's own identifiers all pass — the decision of 2026-11-06 had it
compute the checksum properly "so the values exercise a real validator rather
than bouncing off it", and this is that validator finally existing. Also worth
knowing: **omocodia is handled**, because a checksum-only validator rejects
genuine substituted identifiers, and `whois` now refuses an unusable value
instead of handing out a label for nobody.

**2026-11-13 — A build is staged and published, and the reason is a withdrawal
that did not withdraw.** `build` wrote straight into its destination, so a
second build left the first one's files wherever it did not happen to overwrite
them. An imaging study was removed from the corpus, the dataset was rebuilt into
the same directory, and the build reported `conforms` with exit code 0 while the
withdrawn study was still in `derivatives/` — digested into the new manifest and
certified `INTACT` by `commissura verify` for as long as the dataset existed. A
data holder acting on a patient's objection had not acted on it.

`build/publish.py` stages the whole build beside the destination and moves it
into place at the end. **Not called atomic, and the restraint is the point.**
Publication is two renames and the destination does not exist between them;
`os.replace` cannot do better, because POSIX refuses to rename over a non-empty
directory and Windows over a directory at all. A single swap would need
`renameat2(RENAME_EXCHANGE)`, which is Linux-only, so the choice was between a
portable two-step and a platform-specific one-step and a project whose
cross-platform claim is tested on both took the portable one. A failure in that
window puts the previous dataset back, and a test drives that path rather than
trusting it.

**There is no `--force`, and a test asserts the flag does not exist.** A
destination that exists, is not empty and holds no manifest is refused. The flag
would exist only so that somebody could aim it at the directory this check
protects, which is the same reasoning that keeps `--key` off every command.

**Staging broke two things, and tests caught both.** `write_report`'s guard
compared the report path against `summary.root`, which during a staged build is
the staging tree — so `--report ./dataset/x.html` stopped being "inside the
dataset" the moment staging arrived. It now refuses both trees, because writing
into the staging tree is equally fatal: that tree *becomes* the dataset. And
`dct:identifier` is `urn:commissura:<directory name>`, which became the staging
directory's name with its process id, making every build non-reproducible in
exactly one file — the trap recorded in this log that same morning, walked into
by the afternoon. The lesson, such as it is: **when a build's working directory
stops being its output directory, every path-derived value is suspect.**

**2026-11-13 — The residual detector and the manifest's structural risks were
both calibrated to nothing, and both are derived now.** Two findings with one
shape.

The detector matched `[A-Z]{4,}`. It reported `FRANCESCA FONTANA` and said
nothing about `Francesca Fontana`, so a real hospital's title-case template
would have left a leaked name completely silent. Three layers now: declared
values (NFKD-folded, case-insensitive, **no false positives possible** — and
nothing had ever checked the scrubber's output against its own input list),
position inside a declared name field, and the old heuristic made Unicode-aware.
Measured: on the walkthrough corpus the three layers together report the same
two fragments the single layer did. Strictly more sensitive at no cost in noise.

`residual_risk.structural` was four fixed sentences, one of which read "no
k-anonymity report has been produced for this dataset" while `risk_report.json`
sat beside it, digested into that manifest's own integrity list and covered by
its HMAC. **The document contradicted a file it authenticated.** Derived now,
each claim carrying its own count, and a limit that does not apply is not
claimed. New rule DI009 warns per study whose pixels are said to carry text,
where `validate` previously reported `conforms` with zero warnings over a
dataset in which every study was flagged.

This is the third time the same defect has been found in a different section of
`manifest.py`: a static list that can only account for what somebody remembered
to write down, in a section nobody revisits. The field table went this way on
2026-11-10 and the structural risks were in the same file and not looked at.
**A derived section does not make its neighbours derived.**

**2026-11-13 — `verify` says what it does not prove.** Integrity, authenticity,
completeness and correctness are four claims, and the first was doing duty for
the third. A dataset still holding a withdrawn record verifies perfectly and
correctly, because its bytes have not changed since the manifest was written.
The command now prints that, and a test keeps an old dataset with its old
manifest and shows that verification is entirely happy with it.

## Conventions

- English for code, comments, docs, commit messages.
- Every feature ships with tests and a line in the README.
- Ship something runnable each week rather than a perfect subsystem each month.
- Do not mark a command "available" in the README before it runs end to end.
- **Record every new decision in the decision log above, in the session it is
  taken, with the reason and not just the conclusion.**
- **One fact, one place.** A fact stated in two sections will disagree with
  itself inside a week. Point at the section that owns it instead of restating
  it, and rewrite rather than append.
- **Assert on the thing, not on its picture.** Rendered output wraps, gets
  coloured and gets redrawn by whatever library draws it. A test that reads
  `--help` or a formatted document is testing the renderer. Ask the code for
  its interface instead — and distrust a negative assertion against rendered
  text, because that is the shape that passes while checking nothing.

## Reference material

- Commission EHDS FAQ, 26 Mar 2026 (CC BY 4.0, quotable):
  https://health.ec.europa.eu/document/download/4dd47ec2-71dd-49fc-b036-ad7c14f6ed68_en?filename=ehealth_ehds_qa_en.pdf
- TEHDAS2 guidelines (10 published July 2026); final conference 16 Nov 2026.
- HealthData@EU Pilot deliverables (above) — WP6 metadata, WP8 quality.
- BIDS specification — structure to extend, not reinvent.
- Philter (UCSF, npj Digital Medicine 2020) — PHI category schema worth
  adapting; note it targets English and HIPAA Safe Harbor, not Italian / GDPR.
