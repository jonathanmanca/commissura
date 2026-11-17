# Target architecture

Where `commissura` sits, what it is responsible for, and the boundaries it must
not cross. Written 2026-11-17 against `682d839`, informed by the gap analysis in
this directory.

**This document does not declare conformance.** It describes a target
architecture read off three TEHDAS2 guidelines, which are not law, and against
implementing acts that do not exist yet. Nothing here should be quoted as
evidence that `commissura` is EHDS-conformant, GDPR-compliant, a certified
anonymisation tool, or a secure processing environment.

The purpose of this document is as much to fix what `commissura` **is not** as
to describe what it is. The strongest finding of the TEHDAS2 reading is that
seventeen of eighteen EHDS-derived secure-processing-environment requirements
belong to other roles, and that a tool which drifted across that line would be
claiming a position it cannot hold.

---

## 1. Role boundary

```
         ┌──────────────────────────────────────────────────────────────┐
         │ HEALTH DATA HOLDER                                           │
         │  hospital, IRCCS, laboratory, registry                       │
         │                                                              │
         │  source systems ──► [ commissura ] ──► dataset + manifest    │
         │   LIS / RIS / EHR        ▲                   │               │
         │                          │                   │               │
         │                    secret key           handover             │
         │                   (outside the             │                 │
         │                     dataset)               │                 │
         └────────────────────────────────────────────┼─────────────────┘
                                                      │
         ┌────────────────────────────────────────────▼─────────────────┐
         │ HEALTH DATA ACCESS BODY                                      │
         │  permit, catalogue, combination across holders,              │
         │  second pseudonymisation, export review                      │
         └────────────────────────────────────────────┬─────────────────┘
                                                      │
         ┌────────────────────────────────────────────▼─────────────────┐
         │ SECURE PROCESSING ENVIRONMENT                                │
         │  access control, logging, analysis, export control           │
         └──────────────────────────────────────────────────────────────┘
```

`commissura` lives entirely inside the first box and runs on the holder's own
machine. Its output crosses one boundary, once, as files. It makes no network
call, holds no service, and has no identity in any of the other two boxes.

### What this fixes

| Belongs to | Examples, with the requirement that says so |
| --- | --- |
| **`commissura`** | Internal linkage across the holder's own modalities (D6.1 §3.6.2, optional for the holder); first pseudonymisation (§3.6.2, delegable, and "good practice… as close as possible to the data source"); the de-identification record (D7.2 §5.5.1); the Art. 77 dataset description (D6.1 §3.4.2, Art. 60(3)); validation before delivery (A6.2, *Recommended*) |
| **The HDAB** | The permit itself; combination across holders; the second pseudonymisation; the catalogue; export review (D7.4 EHDSR-1, 2, 10, 13) |
| **The SPE operator** | Access control, strong identification, logging, retention, monitoring, security audits (EHDSR-3…9, 14…17, and all 26 pages of SPER-*) |
| **The data user** | Analysis, and not attempting re-identification (EHDSR-12) |
| **National law** | Whether opt-out handling falls to the holder or the HDAB (D6.1 Table 2, "To be defined in national laws") |

### Three lines `commissura` does not cross

1. **It does not become an SPE.** No access control, no user identity, no
   logging of who looked at what, no export review. Those are EHDSR-3 through
   EHDSR-17 and they are the SPE operator's. A local CLI that grew an
   authorisation model would be claiming a role it cannot be audited for.
2. **It does not reverse a pseudonym.** `whois` derives forward from a named
   person; there is no command going the other way and a test asserts none
   exists. The only implementation is to enumerate the identifier space, which
   is the attack HMAC was chosen to resist.
3. **It does not decide the holder's declarations.** The access tier, the HDAB,
   the publisher, the contact point, the access URL, the dataset type and — from
   this round — the permit reference and any age-band width are inputs the tool
   refuses to invent. `missing_for_conformance` reports what is absent instead
   of filling it in.

---

## 2. Internal boundaries

Ten boundaries, each with one responsibility and one reason it is separate.

| # | Boundary | Module | Responsibility | Why it is its own layer |
| --- | --- | --- | --- | --- |
| 1 | **Schema** | `layout.py` | The dataset's shape, and the de-identification invariants expressed as structure | Holds no logic, so the validator can be derived from it rather than agreeing with it by accident |
| 2 | **Identity resolution** | `read/identity.py` | Who a record belongs to; refusal when it cannot be decided | A grouping error is not contained by redaction: two people merged under one key leave the second person's identifiers outside the set the scrubber was told to remove. This is the layer the audit of 2026-11-13 created, and the reason is in its own docstring |
| 3 | **Reading** | `read/hl7.py`, `read/corpus.py` | Parsing real-world input, tolerantly | Deliberately the tolerant half: every defect the generator injects must be readable, or it cannot be measured |
| 4 | **Secrets** | `deident/keys.py` | Key generation, storage, fingerprinting | One file to read to know what touches the key. No command accepts a key as a value, anywhere, and a test over every registered command pins it |
| 5 | **Derivation** | `deident/pseudonymise.py` | Every use of the secret, domain-separated | One place, so the answer to "what does the key touch" is a file rather than a search. Includes the manifest's own authentication tag, which shares the key only because there is one key |
| 6 | **De-identification** | `build/scrub.py`, `build/writer.py` | Targeted redaction, date rewriting, residual-risk assessment | Takes the declared identifiers from layer 2 as input; this is why linkage must precede redaction, which is the counter-intuitive order |
| 7 | **Observation** | `build/observe.py` | What the input actually carried, per file | Derived from the run, never declared. A static table can only account for what somebody remembered to write down |
| 8 | **Documentation** | `build/manifest.py` | The de-identification record, and the Art. 77 description | Two artefacts with two schemas and two readers; merging them would invent a hybrid satisfying neither |
| 9 | **Measurement** | `build/risk.py`, `measure.py` | k-anonymity, quasi-identifier hand-over, recall against ground truth | Measures the *method*, which is the half of "rules first, measurement always" that is easy to promise and hard to keep |
| 10 | **Publication** | `build/publish.py` | Staging, and replacement rather than overwrite | A withdrawal that does not withdraw is the failure this layer exists to prevent; its invariants are not derivable from the code that implements them, so they are in its docstring |

The dependency direction is one-way: 1 ← 2 ← 3 ← 6 ← 8, with 4 and 5 reachable
from 6 and 8 only, and 7, 9 and 10 reading the result rather than producing it.
Nothing in layers 6 to 10 reaches back into layer 3.

### Where this round's changes land

| Change | Layer | Why there |
| --- | --- | --- |
| Permit-scoped subkey | 5 | Every use of the secret is in one file, and a permit scope is a use of the secret |
| `pseudonymisation` section in the manifest | 8, reading 5 | The record describes the derivation; the derivation declares itself |
| Quasi-identifier channels | 9 | The hand-over artefact is the risk report |
| Predecessor link | 8, reading 10 | Only the publication layer knows a predecessor existed |
| `minTypicalAge` / `maxTypicalAge` | 8 | Derived from the published `participants.tsv`, like every other count in the description |

---

## 3. Shared responsibility

For the three steps where the duty is split, what `commissura` does and what it
explicitly leaves to somebody else.

### Pseudonymisation

| | `commissura` (holder) | HDAB |
| --- | --- | --- |
| First layer | derives `sub-<12 hex>` from a validated national identifier, or from an institution-scoped record number | — |
| Second layer | — | may re-pseudonymise over the holder's output (D7.2 §4.3); the chained scheme is designed and not implemented, for the reason in the decision log of 2026-11-11 |
| Per-permit scoping | derives a subkey from a permit reference when told one | approves the algorithm (§4.3, p. 38) |
| Key custody | holds the root key, outside the dataset, and says nothing about how a key would travel between institutions | holds its own, for its own layer |
| Reversal | refuses; forward derivation only | may hold a mapping if it chooses to; that is its design decision, not ours |
| Cross-holder linkage | publishes a fingerprint so an HDAB can tell whether two datasets are relinkable; offers nothing more | performs the linkage (Q49's worked example) |

### Data minimisation

| | `commissura` | HDAB |
| --- | --- | --- |
| Direct identifiers | removes them | — |
| Quasi-identifiers | identifies and reports them, with k where k is computable and a named channel where it is not | decides what is proportionate for the permit |
| Mitigation | applies none by default, because every available one destroys what the data is for and the choice depends on the permit (decision of 2026-11-13) | requires it, in the permit |
| Permit-driven field and row selection | **does not implement it** (D6.1 A6.2, two *Mandatory* items) | has final responsibility (Art. 66) |

### Documentation

| | `commissura` | HDAB |
| --- | --- | --- |
| De-identification record | produces it, machine-readable, derived from the run | reads it; adds its own for its own layer |
| Art. 77 dataset description | emits it, HealthDCAT-AP Release 8, SHACL-checked | maintains the national catalogue (Art. 77(1)) |
| Art. 78 quality and utility label | does not emit one; the criteria are unpublished and QUANTUM is still developing them | verifies the label's accuracy (D6.1 §3.2.1) |
| Disclosure decision | none of its business | makes it |

---

## 4. External tools and portability

### No cloud provider, now or later

`commissura` is a local CLI and an importable library with four runtime
dependencies. It makes no network call in any code path. There is no account to
create, no region to pick, no service to keep running, and nothing to bill. This
is a hard constraint, not a default: a tool a hospital can run on a laptop
inside its own network is a tool that needs no procurement, no data-processing
agreement with a third party, and no accreditation. The moment it required a
hosted service it would stop being installable by the people who need it.

Concretely, and testable: no code path opens a socket; the conformance check
reads SHACL from `reference/` on disk; the only network operation documented
anywhere is the one-off download of those shapes, which the README gives as four
`curl` commands the operator runs themselves.

### Integrating external de-identification engines

Microsoft publishes de-identification tooling for FHIR and for DICOM — an
anonymiser configured by rule files, usable as a library, as a container, or as
a managed Azure service. The same shape applies to other engines: Mainzelliste
and the MOSAIC suite (E-PIX, gPAS, gICS) for pseudonymisation and record
linkage, named by D7.2 §4.6 (p. 41–42) as reference open-source tools; ARX,
sdcMicro and Amnesia for disclosure control, named by §5.5.8 (p. 60).

The integration shape that keeps `commissura` independent:

1. **An engine is a step in the holder's pipeline, not a dependency of the
   package.** `commissura` already composes this way: `--json` on every command
   exists so the tool can sit inside somebody else's script. A holder who wants
   Microsoft's DICOM anonymiser runs it over `imaging/` first and points
   `commissura build` at the result. Nothing in the package has to know.
2. **Never the managed service.** The library and the container are portable;
   the hosted service is a cloud dependency wearing the same name. If an
   integration is ever written, it must target the local form, and the
   distinction must be stated where somebody choosing between them will read it.
3. **Optional extras, never runtime requirements.** The precedent is `pyshacl`:
   the project's headline conformance claim is proven with it, and it is a dev
   extra, because `pip install commissura` has to stay light. Any engine
   adapter follows that rule or it does not ship.
4. **The manifest must record which engine ran.** D7.2 §5.5.1 asks for "tools,
   software and platforms used (with versions)". `tool_versions` records
   `commissura`'s own; a step performed outside it is invisible, and a record
   that silently omits half the processing is worse than one that says it only
   covers its own half. **This is the one change an external integration would
   require of the manifest**, and it is the reason not to add an adapter
   casually.
5. **Nothing is implemented in this round**, deliberately. The brief's own
   constraint — do not implement connectors before verifying the need and the
   existing architecture — is the right one: no holder has asked, no engine has
   been chosen, and `read_corpus` already accepts whatever is in the three
   globs, so a pre-processing engine needs no code here at all. What was
   verified is that the composition point exists and that the manifest would
   need extending; both are recorded above so the next person does not have to
   re-derive them.

### The input roadmap, unchanged by this reading

The obstacle to real data is report **prose**: `_REPORT_LABELS` matches four
header strings this project's own generator invented, and a real template writes
something else. The direction recorded on 2026-11-13 stands and these three
documents do not touch it: the way out is structured documents — HL7 Italia's
CDA R2 profiles for the documents already in regional FSEs, FHIR for FSE 2.0 —
where the patient's identity is in the header rather than guessed from a line of
prose. Chasing templates is work that never finishes and no standard rewards.

---

## 5. What stays out, with the page that says so

| Not doing | Why, sourced |
| --- | --- |
| An SPE, or any part of one | D7.4 Table 5.1, p. 32–33: 17 of 18 requirements are the HDAB's, the SPE operator's or the data user's |
| Uploading to an SPE | EHDSR-11 is the holder's, but the API is specified as a recommendation in a document stating it prescribes nothing legally (§5.5, p. 34), and TIR-14 says the API will version. No SPE exists to upload to |
| Statistical aggregation for data requests | D6.1 Table 2, p. 25: the HDAB's, delegable; and an explicit project non-goal — users bring their own tools |
| IP and trade-secret protection measures | D6.1 §3.6.2, p. 27: "assumed that the appropriate protection measures… have been established and applied by the HDAB". The holder's part is the *metadata flag* (A6.1, *Mandatory*), which is a gap and is in the remediation plan |
| Anonymisation | D7.2 §5.5.4, p. 53: anonymisation requires removing direct identifiers **and pseudonyms**. `commissura` keeps pseudonyms on purpose, which is exactly why it never uses the word about its own output |
| LLM-based de-identification | Project non-goal, with the measured reason: general-purpose LLM tooling has been shown to miss over half of clinical PHI. D7.2 §5.5.4 lists NER and rule-based filtering as alternatives and requires neither |
| A graphical interface | Decision of 2026-11-13: the user works in a terminal, the point is composability, and a GUI would build a key-handling surface where there is none |
| Encryption of the handover | Risk R-09: a transfer concern, with an unknown counterpart, and adding one would mean inventing a second key-management story beside the one this project guards |
