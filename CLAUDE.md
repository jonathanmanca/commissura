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

Still unread, now in order of how much they would change things:

1. `ranges/range.ttl` — the class range constraints the shapes file explicitly
   excludes from itself. The largest remaining gap in the constraint set.
2. The imported DCAT-AP 3.0.0 shapes, for `Agent_Shape` and
   `PeriodOfTime_Shape`, both referenced by the health shapes and defined
   upstream.
3. `catalogue/health-theme.rdf` and `publisher-type.rdf` —
   `healthdcatap:healthTheme` is only recommended, and its shape says the
   controlled vocabulary does not exist yet, so this is lower value than it
   looks.
4. The packaged validator in `html/shacl/HealthDCAT-AP_validator/`, which is why
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

## Open question to resolve

FAQ Q49 asks who actually performs pseudonymisation and anonymisation — the
health data holder, the HDAB, or both. The answer determines which side of the
chain commissura sits on, and therefore what `build` is responsible for. Read
it and record the answer here.

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
`keygen`, `key-info`, `build`, `risk`. A test pins that list against the CLI's
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

No counts in that paragraph on purpose — a rule total and a test total change
most weeks and no test pins either, so stating them here only schedules the
next correction. `commissura rules` and `pytest` are the places that know.

**Not met**, and the one hard constraint that is not: *deployable by a
stranger*. The package is not on PyPI and the repository is private, so today
only the author can install it. The README says so rather than implying
otherwise; publishing is an irreversible public act and therefore a decision,
not a step to take in passing.

Next, in order:
1. Derive the manifest's per-modality table from the run rather than from a
   static table, which is the known limitation recorded below.
2. Read `ranges/range.ttl` fully and the imported DCAT-AP 3.0.0 shapes. Both are
   now downloaded under `reference/` and used by the conformance test, but
   neither has been read for what else it requires.

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

**2026-11-07 — Known limitation: the manifest's per-modality table states intent,
not observation.** `.deident/manifest.json` lists what was removed, replaced and
kept per modality from a static table. That describes what the rules do, not
what each file actually contained. Deriving it per file would be stronger and is
the obvious next improvement; what makes the current form defensible is that the
rules are deterministic and the scrubber's own per-document counts are recorded
alongside. Recorded here so the gap is not rediscovered as a surprise.

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

## Reference material

- Commission EHDS FAQ, 26 Mar 2026 (CC BY 4.0, quotable):
  https://health.ec.europa.eu/document/download/4dd47ec2-71dd-49fc-b036-ad7c14f6ed68_en?filename=ehealth_ehds_qa_en.pdf
- TEHDAS2 guidelines (10 published July 2026); final conference 16 Nov 2026.
- HealthData@EU Pilot deliverables (above) — WP6 metadata, WP8 quality.
- BIDS specification — structure to extend, not reinvent.
- Philter (UCSF, npj Digital Medicine 2020) — PHI category schema worth
  adapting; note it targets English and HIPAA Safe Harbor, not Italian / GDPR.
