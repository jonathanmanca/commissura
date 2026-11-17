# TEHDAS2 gap analysis

What three TEHDAS2 deliverables ask for, what `commissura` does, and where the
two differ. Written 2026-11-17 against the repository at `682d839`.

**This document does not declare conformance.** It is a reading of three
guidelines against a codebase. TEHDAS2 deliverables are not law; the EHDS
Regulation is, and the implementing acts that will specify Articles 77 and 78
are due March 2027 and do not exist yet. Nothing here should be quoted as
evidence that `commissura` is EHDS-conformant, GDPR-compliant, a certified
anonymisation tool, or a secure processing environment. It is none of those
things and claims none of them.

---

## 1. The documents

| | D6.1 | D7.2 | D7.4 |
| --- | --- | --- | --- |
| Title | Guideline for health data holders on making personal and non-personal electronic health data available for reuse | Guideline for Health Data Access Bodies on data minimisation, pseudonymisation, anonymisation and synthetic data | Technical specification for Health Data Access Bodies on the implementation of secure processing environments |
| Date | 26 February 2026 | 24 March 2026 | 24 February 2026 (v1.2, accepted in Project Steering Group) |
| Length | 69 pp. | 89 pp. | 136 pp. |
| **Addressed to** | **health data holders** | health data access bodies | health data access bodies and SPE operators |
| Nature | guideline; its own checklists "do not extend in any way the rights and obligations deriving from applicable legislation nor introduce any additional requirements" (Annex 6, p. 66) | guideline | technical specification; "none of the requirements presented below are legally prescribed by this work" (§5.5, p. 34) |
| Requirement modality | prose, with steps marked *Mandatory* or *Recommended* in Annex 6 | prose, with a handful of capitalised MUST / MUST NOT | formal, IETF BCP 14: REQUIRED/MUST/SHALL, RECOMMENDED/SHOULD, OPTIONAL/MAY (Annex 1, Table 1.1, p. 77) |

Page numbers throughout are **PDF page numbers** of the files in
`reference/tehdas2/`, which run one ahead of the printed page numbers.

### The first finding is about the audience

`commissura` is a health data holder's tool. That was settled on 2026-11-10 from
the Commission's own FAQ (Q34, Q35, Q49) and the three documents confirm it from
the other side: **D6.1 is the only one of the three addressed to its user.**

This is not a formality. D7.4 carries 18 EHDS-derived SPE requirements in Table
5.1 (p. 32–33) and names a responsible role for each. **Exactly one of the
eighteen is the data holder's** — EHDSR-11. Across the 26 pages of operational
requirements (§5.5, p. 35–60) the phrase "data holder" appears only in the role
definitions and in the interface chapter. Scoring those requirements against
`commissura` would manufacture a hundred gaps that belong to somebody else, and
would be the first step toward the mistake the brief for this work explicitly
forbids: turning a data-preparation tool into an SPE platform.

D7.2 is addressed to HDABs, but it is *not* out of scope, for a reason D6.1
states: the duty to pseudonymise sits with the HDAB and "might be formally
delegated to the HDH, where it has the capacity and expertise to do so. In fact,
it is good practice that personal electronic health data are pseudonymised or
anonymised as close as possible to the data source" (§3.6.2, p. 27). D7.2 §4.3
(p. 38) then names the holder in three of its data-preparation scenarios. So
D7.2 describes the technique `commissura` implements, in the voice of the party
that approves it.

### What D6.1 Table 2 settles about scope

Table 2 (§3.6.2, p. 25) lists seven data-preparation steps with the responsible
entity for each. Mapped onto `commissura`:

| Step | Responsibility of | `commissura` |
| --- | --- | --- |
| Data minimisation and purpose limitation | HDAB, THDH (final); holder bound by GDPR Art. 5 | **not addressed** — no permit-driven field or row selection |
| Data extraction | **HDH**, THDH | partly — reads a corpus as given, applies no selection |
| Opt-out management | to be defined in national laws | partly — `whois` derives the label; nothing excludes |
| IP and trade secrets | HDAB, THDH | not addressed |
| Pseudonymisation or anonymisation | HDAB (may be delegated to the holder) | **this is what the tool is** |
| Data linkage | HDAB; internal linkage optional for the holder | **implemented** — the three modalities, internally |
| Statistical aggregation | HDAB (may be delegated) | out of scope by decision |

Two columns of that table are the honest shape of this project: it does one step
thoroughly, one step partly, and deliberately does not do four.

---

## 2. Requirement inventory

Identifiers are local to this document except for D7.4's, which are the
document's own.

### D6.1 — the holder's obligations

| ID | § (p.) | Requirement | Modality |
| --- | --- | --- | --- |
| H-01 | 3.2.1 (15–16) | Communicate to the HDAB a metadata record describing each Art. 51 dataset held, per Art. 77; check at least annually | legal (Art. 60(3), 77) |
| H-02 | 3.2.1 (16) | Make data available on HDAB request within three months, in the SPE named in the permit | legal (Art. 60(2)) |
| H-03 | 3.2.1 (16) | Where national law provides, implement and manage the opt-out mechanism | legal (Art. 71), national |
| H-04 | 3.4.2 (19–20) | Metadata must cover source, scope, main characteristics and conditions for access; HealthDCAT-AP is expected to support the Art. 77(4) obligations | legal + expectation |
| H-05 | 3.4.2 (20) | Categorise the dataset as personal / non-personal restricted / non-personal open | guideline |
| H-06 | 3.4.2 (20) | Metadata should be complete, accurate and aligned with the holder's actual capabilities | guideline |
| H-07 | A6.1 (67) | Notify the HDAB via metadata of the presence of trade secrets | *Mandatory* |
| H-08 | 3.6.2 (26) | Select the relevant data per the permit or request | legal (Art. 60) |
| H-09 | 3.6.2 (26) | The holder must respect data minimisation and purpose limitation (GDPR Art. 5) even though Art. 66 places final responsibility on the HDAB | legal (GDPR Art. 5) |
| H-10 | 3.6.2 (27) | Pseudonymise or anonymise per the permit; good practice to do it as close as possible to the source | guideline + good practice |
| H-11 | 3.6.2 (27) | Linkage of the holder's own internal datasets, where needed | optional |
| H-12 | A6.2 (67) | Include only electronic health records explicitly reported in the permit/request | *Mandatory* |
| H-13 | A6.2 (68) | Include only variables explicitly reported in the permit/request | *Mandatory* |
| H-14 | A6.2 (68) | Identify and remove data of natural persons who opted out | *Mandatory* |
| H-15 | A6.2 (68) | Validate dataset content and structure before delivery | *Recommended* |
| H-16 | A6.3 (68) | Attach metadata and a dataset identifier to the dataset | *Mandatory in some cases* |
| H-17 | A6.3 (68) | Encrypt data before transfer; share the key through a separate channel | *Recommended* |
| H-18 | A6.3 (69) | Add relevant metadata and versioning when needed | *Recommended* |
| H-19 | 3.2.3 (17) | Provide cost estimates on request; pseudonymisation expenses are eligible | legal (Art. 62(2)) |
| H-20 | 5.1.1 (41) | Assess maturity in data governance, quality, metadata management and technical capability | *Recommended* |

### D7.2 — the technique

| ID | § (p.) | Requirement | Modality |
| --- | --- | --- | --- |
| P-01 | 4.4 (40) | Unsalted hash functions on direct identifiers, or any method where knowing the method and some identifiers yields deterministic pseudonyms, **does not qualify as pseudonymisation** | disqualifying |
| P-02 | 4.4 (40) | Save the function used, the exact specification of inputs, and the salt value; the salt must be kept separate and secure | required for cryptographic pseudonyms |
| P-03 | 4.4 (40) | Recommended to also save complete identifier↔pseudonym mappings where feasible, to handle corrections at source | recommended |
| P-04 | 4.4 (40) | Scheme and configuration should consider post-quantum security | should |
| P-05 | 4.4 (41) | **Pseudonyms MUST NOT be reused across different data permits** | **MUST** |
| P-06 | 4.4 (41) | Deterministic pseudonymisation is advisable in the EHDS context | advisable |
| P-07 | 4.4 (41) | Irreversible pseudonymisation is discouraged; for legacy situations only | discouraged |
| P-08 | 4.5 (41) | Separation **must** be implemented between pseudonymisation secrets and pseudonymised data | must |
| P-09 | 4.5 (41) | Identify quasi-identifiers and hand over information on them to the data minimisation process | required activity |
| P-10 | 4.5 (41) | Provide health-data-specific quasi-identifiers beyond the EDPB guidelines — the example given is hospital visit dates | required activity |
| P-11 | 4.2 (36) | EHDS should rely on reversible pseudonymisation to support data subject rights, including return of significant findings; reversible pseudonymisation is needed at the holder to implement opt-out for future applications | should |
| P-12 | 4.3 (36–37) | Indicate in the catalogue record whether the dataset has personal data, a sample distribution, and linkage suitability; and additionally the pseudonymisation method (reversible vs irreversible) and linkage information | recommended |
| P-13 | 4.3 (38) | Pass-through without HDAB re-pseudonymisation is possible **only** if the holder implements **per-project pseudonym generation** with an HDAB-approved algorithm | conditional |
| P-14 | 3.2 (18–19) | Quasi-identifiers should be removed unless crucial; when retained, mitigate by generalisation, suppression or randomisation | should |
| P-15 | 3.3.1 (22) | Date of birth and date of death are strong quasi-identifiers and should be avoided; substitute year of birth or age group | should |
| P-16 | 3.3.1 (22) | Age should be exact only when indispensable; categorise the extreme values where numbers thin out | should |
| P-17 | 3.3.2 (24) | Unstructured data needs particular attention: identifier removal there is less deterministic than for structured data | advisory |
| P-18 | 3.3.3 (24) | Absolute dates should be avoided when not essential and replaced by relative timespans | should |
| P-19 | 3.3.4 (25) | Location should be generalised by default; the GP should always be pseudonymised; health facilities may need obfuscation such as sequential codes | should |
| P-20 | 5.5.1 (50–51) | Documentation content: creator identifier, **data permit identifier**, source-dataset metadata and descriptive statistics, processing steps and parameters, tools and versions, quality metrics, privacy risk assessment methods and results, disclosure documentation | recommended, enumerated |
| P-21 | 5.5.1 (51) | The documentation **shall not** contain personal or identifying information relating to the data subjects | shall |
| P-22 | 5.5.1 (51) | Documentation shall be structured and preferably machine-readable; a standard structure "is currently not existing and should be developed" | shall + state-of-the-art gap |
| P-23 | 5.5.1 (51) | Documentation shall carry origin, authorship and time of creation or update per entry, with mechanisms maintaining traceability across updates | shall |
| P-24 | 5.5.4 (53) | For anonymisation, all direct identifiers **and pseudonyms** must be removed | must, for anonymisation |
| P-25 | 5.5.4 (54) | k-anonymity, l-diversity and t-closeness are the privacy properties targeted in tabular anonymisation | informative |
| P-26 | 5.5.4 (54) | Free text: NER and rule-based filtering; generalisation and masking; perturbation and synthesis | informative, a menu |
| P-27 | 5.5.8 (57) | Tooling should detect direct identifiers of data subjects, **care personnel and care organisations** | should |
| P-28 | 5.5.8 (57) | Tooling should detect quasi-identifiers and outliers, and classify variables by sensitivity level | should |
| P-29 | 5.5.8 (57) | Tooling should generate structured reports or visual summaries, and parse the metadata to retrieve parameters and metrics computed earlier | should |
| P-30 | 5.5.8 (57) | Where applicable the tools should create the information needed for the §5.5.1 documentation | should |
| P-31 | 5.5.5 (54) | Synthetic data may still be personal data if it can be linked back to individuals with reasonable effort | advisory |

### D7.4 — the environment, and the one line that is the holder's

| ID | § (p.) | Requirement | Role | Modality |
| --- | --- | --- | --- | --- |
| EHDSR-11 | 5.3 (32) | The health data holder **MUST** upload the permitted EHD to be available in an SPE for the data user (Art. 73(2)) | **Data Holder** | Mandatory |
| EHDSR-1…10, 12…18 | 5.3 (32–33) | Access control, logging, auditing, monitoring, export review, security audits, risk assessment | HDAB / SPE Operator / Data User | Mandatory, **not the holder's** |
| SPER-* | 5.5 (35–60) | 26 pages of operational requirements | SPE Operator / HDAB | not the holder's; and not legally prescribed by D7.4 |
| TIR-1 | 5.6.1 (62) | API services MUST be accessed via data user and data holder applications, which may be dedicated client applications | both | Mandatory |
| TIR-4 | 5.6.1 (63) | The API MUST support at least JSON for requests and responses | SPE operator | Mandatory |
| TIR-5 | 5.6.1 (63) | Upload and download of standard file types, e.g. CSV and parquet, with configurable restrictions | SPE operator | Mandatory |
| TIR-8 | 5.6.1 (63) | Encryption in transit; the API MUST support content encryption (e.g. AES-256) prior to transmission, enforced by the HDAB | SPE operator | Mandatory |
| TIR-17 | 5.6.1 (64) | Payloads SHOULD comply with the specified formats and content standards, with semantic validation | SPE operator | Recommended |
| — | 5.4.1 (33) | Export control covers three areas, the second being "returning of clinically significant results to the original data holders" | HDAB / SPE | functional area |

The TIR requirements are the SPE operator's to build. They matter here because
`commissura`'s output is what crosses that interface, and TIR-1 says the holder
side of it is a **client application** — which is the shape `commissura`
already has.

---

## 3. Gap matrix

Status vocabulary, applied strictly:

- **IMPLEMENTED** — there is code in the application flow and a test that fails
  if it breaks. Not "there is a class for it".
- **PARTIAL** — some of the requirement is met and the rest is named here.
- **NOT IMPLEMENTED** — nothing does it.
- **OUT OF SCOPE** — somebody else's role, or an explicit project non-goal; the
  rationale is given, and this is not a euphemism for "not done".
- **N/A** — the requirement's precondition does not hold here.

### 3.1 Pseudonymisation — the core claim

| Req | Status | Evidence in code and tests | Gap | Priority |
| --- | --- | --- | --- | --- |
| P-01 | **IMPLEMENTED** | `deident/pseudonymise.py` uses HMAC-SHA256 with a secret key and a domain prefix per use; the stack decision of 2026-11-06 rejected plain `hash(national_id)` in these words. `tests/test_pseudonymise.py` | — | — |
| P-02 | **PARTIAL** | The salt is kept separate: the key never enters the dataset, `keygen` writes it mode 0600 on POSIX, `.gitignore` excludes `*.key`, no command accepts `--key` (pinned by `tests/test_cli.py::test_no_command_anywhere_takes_a_key_as_a_value`). `manifest.json` records `key_fingerprint` and `deidentification_rule_version`. | **The function used and the exact specification of inputs are not in the manifest.** "HMAC-SHA256, domain prefix `subject\|`, truncated to 12 hex characters" lives in a module docstring and in the project brief. A reader of the manifest alone cannot reconstruct the derivation. | **P1** |
| P-03 | **NOT IMPLEMENTED, by decision** | No mapping table exists anywhere; `whois` re-derives forward instead. Pinned by `tests/test_cli.py`, which asserts no `unwhois`/`reverse`/`resolve`/`lookup`/`identify` command exists. | A mapping is recommended, and the stated reason is to survive a correction at source — the exact case `lab.conflicting_identity` now injects. Without one, correcting a codice fiscale changes that subject's label and nothing reconciles the old dataset. **Recorded as a limit, not closed:** a stored mapping is the enumerable table this scheme was chosen to avoid. | P3 (document) |
| P-04 | **IMPLEMENTED** | HMAC-SHA256 is a symmetric construction and not threatened by Shor's algorithm. | The 12-hex truncation (48 bits) is a collision bound, not a quantum one; `Pseudonymiser` carries a collision witness. Already recorded 2026-11-11. | — |
| **P-05** | **NOT IMPLEMENTED** | Nothing in the tool knows what a permit is. `grep -rn permit src/` returns prose only. One key produces one label space for ever, so two builds under the same key for two permits produce identical labels. | **The one MUST in these three documents that `commissura` violates when used across two permits.** | **P0** |
| P-06 | **IMPLEMENTED** | Deterministic by construction; the same identifier and key always give the same label. | Not stated in the manifest as a *policy* choice, which is what P-12 asks a catalogue reader for. | P1 (with P-02) |
| P-07 | **DIVERGENT, deliberately** | There is no stored secret mapping to reverse, so by D7.2's definition (§4.2, p. 36: reversible iff the secrets are kept) this is **irreversible** pseudonymisation, which the document discourages. | Real divergence. Mitigated for the opt-out case — the holder keeps the source corpus identifiable and `whois` derives forward from a named person, which is what an opt-out needs. **Not** mitigated for the significant-findings case, which starts from a row. See P-11. | **P1** (document honestly) |
| P-08 | **IMPLEMENTED** | Key outside the dataset by design; `tests/test_keys.py`, `tests/test_build.py` assert no key material in the output. | — | — |
| P-09, P-10 | **PARTIAL** | `build/risk.py` writes `quasi_identifiers`, naming the `participants.tsv` columns, plus a laboratory analyte/value rarity assessment. | **The interval channel is not named as a quasi-identifier**, although D7.2's own example of a health-specific quasi-identifier is "a sequence of hospital visit dates" and the README already documents the channel in prose. The risk report is the hand-over artefact and it under-reports. | **P0** |
| P-11 | **PARTIAL / divergent** | Opt-out: `whois` derives the label from a validated codice fiscale, forward only, reading no dataset. Significant findings: nothing. | A finding about a row cannot be traced to a person without the holder re-deriving every candidate. Architecturally this is the price of refusing a mapping table, and it should be stated rather than discovered. | P2 (document) |
| P-13 | **NOT IMPLEMENTED** | Follows P-05. | Without per-project generation the HDAB must re-pseudonymise, which is permitted but makes `commissura`'s output an intermediate rather than a deliverable. | **P0** (same fix as P-05) |

### 3.2 Data minimisation

| Req | Status | Evidence | Gap | Priority |
| --- | --- | --- | --- | --- |
| P-14 | **PARTIAL** | Direct identifiers are removed; quasi-identifiers are *measured* (`risk`) and not mitigated. The decision of 2026-11-13 argues each available mitigation destroys what the data is for, and that the choice depends on the permit, so the tool reports instead of correcting. | The argument holds for lab values. It is weaker for age, where P-16 names a specific, utility-preserving mitigation. | P2 |
| P-15 | **IMPLEMENTED** | Birth dates are removed by exact match before any date rewriting and get their own placeholder; the decision of 2026-11-07 records why an offset would have stated the birth date exactly. A test fails if the disposition flips from `removed` to `replaced`. | — | — |
| P-16 | **NOT IMPLEMENTED** | Age is carried exact and truncated at 89. The ceiling is the "categorise the extreme values" half; the banding half is designed (2026-11-13) and not built. | `--age-band` with the width recorded in the manifest. **The 2026-11-13 decision deferred this for want of a user who had asked. D7.2 §3.3.1 is that ask, in writing, dated 24 March 2026.** It stays the holder's choice of width. | **P1** |
| P-17 | **IMPLEMENTED** | Targeted redaction plus a three-layer residual-risk detector; `measure` scores recall against ground truth, and the 2026-11-12 entry records the documented limit with a number on it (98.45% at `--defect-rate 0.6`, every survivor named in prose and declared nowhere). | — | — |
| P-18 | **IMPLEMENTED** | `day_offset` only; `validate` reports a surviving calendar date as an **error**, not a warning (`layout.py`, rule family `DI`). | — | — |
| P-19 | **DIVERGENT, more protective** | Addresses and institution names are **removed**; the ordering clinician is **removed**. | D7.2 asks for the GP to be *pseudonymised* and facilities to be *obfuscated with sequential codes*. Removal is stronger on privacy and destroys the analysis dimension — no site comparison, no clinician clustering, no geography at all. This is a **utility** gap, not a privacy one, and it is invisible in the current manifest because "removed" reads as success. | P2 |
| H-09, H-12, H-13 | **NOT IMPLEMENTED** | `read_corpus` globs three patterns and builds everything it finds. There is no permit, no variable list, no inclusion/exclusion criteria. | Two of these are marked *Mandatory* in D6.1's own checklist. Closing them properly means a permit model, which is the same P0 work as P-05. | P1 |
| H-14, H-03 | **PARTIAL** | `whois` gives the holder the handle an opt-out needs. Nothing excludes. | `build` cannot be told "these subjects opted out". The holder must filter the corpus by hand before running it, and nothing records that they did. | **P1** |

### 3.3 Documentation — the manifest

| Req | Status | Evidence | Gap | Priority |
| --- | --- | --- | --- | --- |
| **P-21** | **IMPLEMENTED, and this is the strongest result in the analysis** | `.deident/manifest.json` must carry nothing derived from the input. Four separate audits found four violations and closed each: the corpus's absolute path (2026-11-12), quoted residual-risk tokens (2026-11-12), `linkage_issues`/`records_dropped` detail sentences and the modality ledgers' `unreadable` list (2026-11-13), and the dropped-record file paths (2026-11-12). The guard is class-level: `tests/test_manifest_consistency.py` and the ground-truth test assert that **no planted identifier appears anywhere in the manifest, whatever field it would travel in**. | — | — |
| P-22 | **IMPLEMENTED** | JSON, versioned (`MANIFEST_SCHEMA_VERSION`, now 6.0.0), with `schema_note` stating that no published standard covers it. **D7.2 says the same thing**: "Standard structure for anonymised or synthetic data documentation is currently not existing and should be developed." The 2026-11-07 decision — "Ours. Nobody else specifies it." — is now sourced. | — | — |
| P-23 | **PARTIAL** | `generated_at`, `tool_versions`, `manifest_hmac` and per-file digests; `verify` recomputes them. Authorship of the *tool* is recorded; authorship of the *holder* is not. | **No traceability across updates.** A rebuild replaces the manifest and nothing records that a predecessor existed or what it said. The withdrawal case of 2026-11-13 is exactly this: the previous dataset is gone and no document admits there was one. | **P1** |
| P-20 | **PARTIAL** | Present: processing steps and parameters (the derived per-field ledgers, the scrubber's per-category counts, `deidentification_rule_version`), tools with versions (`tool_versions`), privacy risk assessment methods and results (`risk_report.json` with `threshold`, `quasi_identifiers`, `minimum_k`), source provenance (`root_name`, record and subject counts, linkage issues and drops by reason). | Absent: **data creator identifier** (the holder is named in the JSON-LD, not in the manifest), **data permit identifier** (nothing), descriptive statistics of the source, the Art. 78 quality and utility label, and disclosure documentation. The last is the HDAB's; the first two are the holder's. | P1 |
| P-29, P-30 | **IMPLEMENTED** | `--json` on every command; `build --report` writes a single-file HTML page that reads the manifest back and renders the before/after comparison — which is literally "parse the metadata to retrieve and visualise parameters used and metrics computed in the earlier processing steps". | — | — |
| P-27 | **IMPLEMENTED** | `KnownIdentifiers` carries exactly the triple D7.2 names: data subjects (`identities`, `declared`), care personnel (`providers`), care organisations (`institutions`, `addresses`). The residual detector's three layers are NFKD-folded and case-insensitive since 2026-11-13. `tests/test_residual_risk.py` | — | — |
| P-28 | **PARTIAL** | Outlier detection: the laboratory rarity assessment finds values shared by fewer than k subjects. | No sensitivity classification of variables. The per-field ledger classifies by *disposition* (removed/replaced/kept), which is a different axis. | P3 |

### 3.4 Catalogue metadata

| Req | Status | Evidence | Gap | Priority |
| --- | --- | --- | --- | --- |
| H-01, H-04, H-16 | **IMPLEMENTED** | `healthdcat-ap.jsonld`, HealthDCAT-AP Release 8, non-public tier, with `dct:identifier` as `urn:commissura:<dataset name>`. All **14 mandatory non-public properties** are emitted plus the conditional `hasVariables`; conformance is proven against the profile's own SHACL and the DCAT-AP 3.0.0 shapes it imports (`tests/test_shacl_conformance.py`, `tests/test_cli_conformance.py`). | Annual review (H-01) is a process, not a tool feature. | — |
| H-05 | **IMPLEMENTED** | `dct:accessRights` fixed per tier by `sh:hasValue`; the default is `NON_PUBLIC`, which is the "personal health data [sensitive data]" category of D6.1 §3.4.2. | — | — |
| P-12 | **NOT IMPLEMENTED** | Of 22 recommended profile properties, 4 are emitted (`dct:publisher`, `hasVariables`, `numberOfRecords`, `numberOfUniqueIndividuals`). | D7.2 §4.3 names three things to indicate that are absent: `dpv:hasPersonalData`, a sample distribution (`adms:sample`), and linkage information. It also asks for the **pseudonymisation method (reversible vs irreversible)**, for which the profile has no property at all. Note the shapes place **no value constraint** on `dpv:hasPersonalData` — only a path and a severity — so the DPV concept to use is unsourced and must not be guessed. | P1 (partial), P3 (the rest) |
| H-06 | **IMPLEMENTED** | `missing_for_conformance` is reported rather than invented; `--hdab`, `--publisher`, `--contact-point`, `--access-url` are refused-to-invent fields; `--dataset-type` is checked against the authority list. | — | — |
| H-07 | **NOT IMPLEMENTED** | No trade-secret flag. | *Mandatory* in D6.1 A6.1. The profile's `dct:rights`/`odrl` route is not transcribed here. Small, and genuinely the holder's declaration. | P2 |
| H-18 | **PARTIAL** | The manifest and the profile document are versioned; the *dataset* has no version. | `dcat:version`, `adms:versionNotes` and `dct:modified` are all unemitted (optional/recommended). Pairs with P-23. | P2 |

### 3.5 Secure processing environments

| Req | Status | Rationale |
| --- | --- | --- |
| EHDSR-11 | **NOT IMPLEMENTED, and correctly so for now** | The holder must upload to the SPE. `commissura` produces a dataset on a disk and stops. No SPE exists to upload to: Italy has not designated an HDAB, the SPE API is specified only as a recommendation in a document that says it prescribes nothing legally, and TIR-14 tells us the API will version. Building a client against an unbuilt API is the mistake D7.4's own scope section warns about. |
| EHDSR-1…10, 12…18 | **OUT OF SCOPE by role** | HDAB, SPE operator and data user. Seventeen of eighteen. |
| SPER-* (26 pp.) | **OUT OF SCOPE by role** | Same. Not one names the data holder. |
| TIR-1 | **ALIGNED** | A CLI is a dedicated client application. `--json` everywhere means it composes into whatever uploads. |
| TIR-4 | **ALIGNED** | Every command speaks JSON. |
| TIR-5 | **PARTIAL** | The API must handle "standard file types (e.g. CSV and parquet)". `commissura` writes TSV, JSON and plain text. TSV is BIDS, which is the right answer for the dataset layout; whether an SPE upload wants CSV or parquet is unknown until one exists. |
| TIR-8, H-17 | **NOT IMPLEMENTED** | Two documents independently ask for content encryption before transfer with the key on a separate channel. `commissura` has none. It is a real gap in the handover and it is *not* a de-identification gap. |
| §5.4.1 area 2 | **NOT IMPLEMENTED** | Returning clinically significant results to the holder needs the reverse direction. See P-07 and P-11. |

### 3.6 Synthetic data

| Req | Status | Rationale |
| --- | --- | --- |
| P-31 | **N/A, and worth stating** | D7.2 §5.5.5 frames synthetic-data privacy risk around a generator *trained on real patient data*, which may leak through memorisation; hence the distance metrics, shadow-model attacks and DP of §5.5.7. `commissura`'s generator is trained on nothing. It composes invented people from vocabularies, and its identifiers are impossible by construction (codice fiscale place code `X###`, telephone subscriber part starting `0`, `.invalid` e-mail domains, DICOM UIDs under the registration-free `2.25` arc, every name carrying `SINTETIC`). There is no real individual to link back to, so the §5.5.7 risk framework has no subject. |
| P-25 | **IMPLEMENTED (k only)** | `risk` computes k-anonymity over participant quasi-identifiers and over analyte/value pairs. l-diversity and t-closeness are not computed. |
| P-24 | **N/A by position** | This is the baseline for *anonymisation*: remove direct identifiers **and pseudonyms**. `commissura` keeps pseudonyms on purpose, which is precisely why it says it pseudonymises and never that it anonymises. |
| P-26 | **ALIGNED** | Rule-based filtering is one of the two options D7.2 lists for free text; NER is the other. The project rejects NER with a cited reason and the guideline does not require it. |

---

## 4. Summary

Fifty-nine requirements were read across the three documents. Scored only
against the ones that are the holder's:

| | Count |
| --- | --- |
| IMPLEMENTED | 17 |
| PARTIAL | 12 |
| NOT IMPLEMENTED | 11 |
| OUT OF SCOPE by role | 15 |
| N/A | 4 |

The counts are a rough shape, not a score, and they should not be turned into a
percentage. A single MUST outweighs a dozen recommendations.

**What the reading confirms.** The method is the one these documents describe.
HMAC with a secret key is the construction D7.2 recommends and the one it uses
to disqualify naive hashing. Relative day offsets instead of calendar dates are
what §3.3.3 asks for. Removing birth dates rather than shifting them is what
§3.3.1 asks for. A machine-readable de-identification record is what §5.5.1 asks
for, and §5.5.1 says the standard for it does not exist — which is the citation
this project's own manifest schema needed. The invariant that the manifest must
carry nothing derived from the input, found the hard way four times, is §5.5.1's
"shall not contain personal or identifying information relating to the data
subjects". The triple of identifiers to detect — subjects, care personnel, care
organisations — is the structure `KnownIdentifiers` already has.

**What it changes.** Three things, in order:

1. **P-05 is a MUST and it is unmet.** Pseudonyms must not be reused across data
   permits. `commissura` has one key and therefore one label space, and knows
   nothing about permits. §4.3 (p. 38) makes this the condition for the holder's
   output passing through to the data user without the HDAB re-doing the work.
2. **The risk report under-reports the quasi-identifiers it is supposed to hand
   over.** §4.5 makes identification and hand-over an explicit activity and §3.2
   names hospital visit-date sequences as the health-specific example. The
   README discusses the channel; the machine-readable artefact does not name it.
3. **Age banding is no longer speculative.** §3.3.1 asks for it in writing. The
   design was written on 2026-11-13 and deferred for want of a user who had
   asked; the ask now exists with a date and a page number.

**What it does not change.** `commissura` is not an SPE and should not grow
toward one: seventeen of eighteen EHDS-derived SPE requirements and all 26 pages
of operational requirements belong to other roles. The three omitted
data-preparation steps — minimisation against a permit, IP and trade secrets,
statistical aggregation — are either the HDAB's by default or outside this
project's stated scope, and saying so with a page reference is more useful than
building them speculatively.

**The honest assessment.** `commissura` implements one step of the EHDS
secondary-use chain — the holder's first pseudonymisation — to a standard that
matches what TEHDAS2 describes, and documents it in a form TEHDAS2 asks for and
says does not yet exist. It does not implement permit-scoped operation, which is
the one place a published MUST is unmet, and it does not address the steps that
belong to the HDAB. It is a data-preparation and control component, and the gap
between that and "EHDS-ready" is governance, not code.
