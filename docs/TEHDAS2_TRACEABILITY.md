# Traceability

Requirement to code to test, for the five items implemented on 2026-11-17, and
the sourced reason for every one of them.

**This document does not declare conformance.** A row here says a requirement
was read, a change was made and a test holds it down. It does not say a legal
obligation is satisfied: TEHDAS2 deliverables are guidelines, the EHDS
implementing acts for Articles 77 and 78 are due March 2027, and nobody has
assessed this tool. Nothing here should be quoted as evidence that `commissura`
is EHDS-conformant, GDPR-compliant, a certified anonymisation tool, or a secure
processing environment.

Page numbers are PDF pages of the files in `reference/tehdas2/`, which run one
ahead of the printed numbers.

---

## 1. Permit-scoped pseudonymisation

| | |
| --- | --- |
| **Requirement** | D7.2 §4.4, p. 41 — "Pseudonyms MUST NOT be reused across different data permits, to minimise risks of intentional or unintentional linkage of data by the data user." |
| **Supporting** | D7.2 §4.3, p. 38 — pass-through without the access body re-pseudonymising is possible "only… if the data holder can implement per project pseudonym generation and uses a pseudonymisation algorithm approved by the HDAB." |
| **Modality** | MUST. The only unmet one found in the three documents. |
| **Risk** | R-01, Critical |
| **Code** | `deident/pseudonymise.py::scope_to_permit`, `_DOMAIN_PERMIT`; `cli.py::build --permit`, `cli.py::whois --permit`, `cli.py::_permit_of` for `verify` |
| **Status** | IMPLEMENTED, opt-in |

| Test | What it holds down |
| --- | --- |
| `test_permit_scope.py::test_two_permits_give_disjoint_subject_labels` | The requirement, as the property it asks for |
| `…::test_two_permits_produce_two_sets_of_subject_directories` | The same, end to end on the published tree — what a data user actually receives |
| `…::test_an_unscoped_build_uses_the_root_keys_label_space` | **The regression that matters.** Asserted against `Pseudonymiser(KEY).subject_label`, the untouched function that produced every label this tool has ever issued — not against a second build, which would only prove the two agree with each other |
| `…::test_a_rebuild_without_a_permit_is_byte_identical` | The whole published tree, into the same destination both times because `dct:identifier` legitimately differs between two directory names |
| `…::test_one_permit_stays_deterministic` | Scoping must not cost determinism, or internal linkage breaks |
| `…::test_a_subkeys_fingerprint_differs_from_the_root` | The fingerprint is the only handle an access body has on relinkability |
| `…::test_a_subkey_is_an_ordinary_key` | HMAC-SHA256 gives exactly the key length, so no other derivation needs to know about scoping |
| `…::test_the_permit_reference_is_taken_as_given` | No validation: the permit template is an implementing act due March 2027 |
| `…::test_verify_authenticates_a_scoped_dataset_from_the_root_key` | `verify` reads the permit from the manifest, so there is no flag to get wrong |
| `…::test_verify_still_authenticates_an_unscoped_dataset` | The other half of that branch |
| `…::test_whois_under_the_right_permit_finds_the_published_subject` | The opt-out path, including that the *wrong* scope gives a label for nobody |
| `…::test_the_permit_is_an_option_and_the_key_still_is_not` | Asked of click, not of rendered help — the convention of 2026-11-12 |

**Design note.** A subkey rather than a wider HMAC input, and that is what makes
this safe to add. Folding the permit into the `"subject|"` input would move every
label in every dataset ever built here; a subkey is reached only when `--permit`
is passed. The project's constraint is that pseudonym derivation does not change
without a migration plan, and a change nothing can reach by default needs none.

---

## 2. The quasi-identifier channels

| | |
| --- | --- |
| **Requirement** | D7.2 §4.5, p. 41 — "Identification of quasi-identifiers and handing over information on them to the data minimisation process"; and "Provide health-data specific quasi-identifiers beyond what is in the EDPB guidelines (e.g., dates of visits in the hospital also become quickly identifying)." |
| **Supporting** | D7.2 §3.2, p. 17 lists "a sequence of hospital visit dates" among its own examples. §3.3.3, p. 24 asks that absolute dates be replaced by relative timespans — which this tool already does, and which is what creates the sequence. |
| **Modality** | Required activity for whoever pseudonymises |
| **Risk** | R-02, High |
| **Code** | `build/risk.py::channels`, called from both branches of `assess` |
| **Status** | IMPLEMENTED |

| Test | What it holds down |
| --- | --- |
| `test_quasi_identifiers.py::test_the_interval_sequence_is_named_as_a_quasi_identifier` | The finding: the strongest channel in the dataset was the one the hand-over file did not mention |
| `…::test_the_interval_channel_states_the_re_identification_route` | Naming a channel without saying how it is exploited is half a hand-over |
| `…::test_every_channel_either_is_scored_or_says_why_not` | **The invariant.** A channel with no computable k is still a channel; an unscored entry with no reason is how an unscoreable one becomes an omitted one |
| `…::test_a_dataset_with_no_sessions_claims_no_interval_channel` | Derived, not declared — the mistake the four fixed prose strings in `residual_risk.structural` used to make |
| `…::test_the_scored_channels_say_that_they_were_scored` | So a reader can tell a measured channel from a merely named one |
| `…::test_the_demographic_channel_names_the_mitigation_the_guideline_asks_for` | §3.3.1's generalisation, named as available and stated as not applied |
| `…::test_the_imaging_channel_points_at_the_pixel_warning` | The channel this tool cannot inspect at all: metadata is read, pixels never are |
| `…::test_a_table_without_quasi_identifier_columns_still_reports_channels` | The early-return branch had to grow the field too |
| `…::test_the_written_report_carries_the_channels` | It is the file the next step reads |
| `…::test_channels_takes_the_scored_columns_as_given` | So an entry cannot claim a measurement that was skipped |

---

## 3. The pseudonymisation declaration

| | |
| --- | --- |
| **Requirement** | D7.2 §4.4, p. 40 — for cryptographic pseudonym generation, "need to save function used, exact specification of inputs, value of salt… the salt must be kept separate and secure". |
| **Supporting** | §4.3, p. 37 — state the "pseudonymisation method: reversible vs. irreversible pseudonymisation used at data holder". §4.3, p. 38 — the access body approves the algorithm. §4.4, p. 41 — deterministic pseudonymisation is advisable in the EHDS. §4.7, p. 41 — opt-out and significant findings need reversibility. §5.5.1, p. 50 — "data processing steps, methodology, transformations and parameters used". |
| **Modality** | Required for cryptographic pseudonyms; recommended as documentation content |
| **Risk** | R-04 Medium, and R-07's honest mitigation |
| **Code** | `deident/pseudonymise.py::declare`, `DOMAIN_PURPOSES`; `build/manifest.py` `pseudonymisation` section |
| **Status** | IMPLEMENTED |

| Test | What it holds down |
| --- | --- |
| `test_permit_scope.py::test_the_declaration_states_the_function_and_its_truncation` | What a reader of the manifest alone could not reconstruct before |
| `…::test_the_declaration_carries_no_key_material` | The salt named, never carried. The fourth test of this class in the project |
| `…::test_every_domain_prefix_declares_what_it_derives` | Enumerated from the module, so a new prefix without a purpose is a visible gap rather than a silent one |
| `…::test_the_declaration_admits_the_scheme_is_irreversible` | D7.2 discourages it, so it must not be implied — and the note separates opt-out, which works, from significant findings, which do not |
| `…::test_an_unscoped_declaration_says_so_rather_than_staying_quiet` | Silence reads as "scoping was handled", the opposite of the truth |
| `…::test_a_scoped_declaration_names_the_permit_and_both_fingerprints` | They answer different questions; the open point is in the remediation plan |
| `…::test_the_declaration_never_claims_anonymity` | The one way this section could do harm |
| `test_documentation_requirements.py::test_the_pseudonymisation_section_is_present_and_machine_readable` | §5.5.1's "structured, preferably machine-readable", including the round trip |
| `test_claims.py::test_the_manifest_states_what_it_is_not` | A guard that only forbids passes on a document that says nothing |
| `test_build.py::test_the_manifest_never_carries_the_key` | **Pre-existing, and it fired.** `layout.FORBIDDEN_MANIFEST_KEYS` reserves `secret`, so the field is `salt_custody`; and it reserves `key`, so the scope values are `key-wide` and `permit-scoped` |

---

## 4. Documentation traceability

| | |
| --- | --- |
| **Requirement** | D7.2 §5.5.1, p. 51 — "Documentation shall include clear information on the origin, authorship, and time of creation or update for each documentation entry. Appropriate mechanisms shall be in place to maintain traceability across documentation updates, enabling verification of how the documentation has evolved over time." |
| **Modality** | shall |
| **Risk** | R-03, High |
| **Code** | `build/manifest.py::predecessor_of`; `cli.py::build` reads it from `staged.destination` before publication |
| **Status** | IMPLEMENTED |

| Test | What it holds down |
| --- | --- |
| `test_documentation_requirements.py::test_a_rebuild_names_the_manifest_it_replaced` | The requirement, and that exactly three fields are carried — no counts, which would describe data this dataset may no longer hold |
| `…::test_the_predecessor_link_survives_a_real_rebuild` | Through the command line, where staging is what makes it possible: after `publish` the predecessor is gone |
| `…::test_a_first_build_records_no_predecessor` | `null`, written and not omitted: absent and unknown are different facts |
| `…::test_an_unreadable_destination_manifest_is_treated_as_absent` | A malformed manifest in the destination must not fail a sound build |
| `…::test_a_destination_manifest_that_is_not_an_object_is_absent` | Valid JSON is not a manifest |
| `test_manifest_consistency.py::test_the_manifest_is_consistent_after_a_withdrawal` | Pre-existing; now also pins schema 6.1.0 |

---

## 5. The cohort's age range

| | |
| --- | --- |
| **Requirement** | D7.2 §3.1, p. 18 — "it is recommended that data holders specify any standard data minimisation rules that are applicable by default to the datasets offered", the worked example being a birth date available only as a year. |
| **Supporting** | §3.3.1, p. 22 — age is a quasi-identifier that "should only be used as an exact value when it is indispensable"; an applicant has to know the range before they can judge that. D6.1 §3.4.2, p. 19 — the Art. 77 metadata covers "scope, main characteristics". |
| **Modality** | recommended |
| **Code** | `build/manifest.py::_typical_age_range`, merged into the `dcat:Dataset` node |
| **Status** | IMPLEMENTED |

| Test | What it holds down |
| --- | --- |
| `test_documentation_requirements.py::test_the_description_publishes_the_cohorts_age_range` | Derived from the published table, so it cannot disagree with the data; and `xsd:nonNegativeInteger`, not a bare JSON number, which JSON-LD would read as `xsd:integer` |
| `…::test_a_cohort_with_no_numeric_age_claims_no_range` | Ages above the ceiling are `90+`; both properties are recommended, so absence is silence and `0` would be a lie |
| `test_shacl_conformance.py` (pre-existing) | Both new properties pass the profile's own SHACL and the DCAT-AP 3.0.0 shapes it imports |

**Not emitted, deliberately.** `dpv:hasPersonalData`, which D7.2 §4.3 (p. 37)
explicitly names. The Release 8 shapes place **no value constraint** on it —
only a path and a severity — so the DPV concept to use is unsourced. Writing a
plausible IRI is the trap recorded when this project found one authority list
served over https and another over http: an IRI that looks entirely right and
resolves to nothing. It is open point 2 in the remediation plan.

---

## 6. No overclaiming

| | |
| --- | --- |
| **Requirement** | The project's own hard constraint, and the pattern recorded on 2026-11-16: a reason that sounds like a security reason gets less scrutiny than one that does not. A compliance claim has the same shape. |
| **Risk** | R-10, High |
| **Code** | None — this is a guard over the repository |
| **Status** | IMPLEMENTED as a test |

| Test | What it holds down |
| --- | --- |
| `test_claims.py::test_the_readme_makes_no_conformance_claim` | The document read by somebody deciding whether to use this on health data |
| `…::test_the_command_line_interface_makes_no_conformance_claim` | Asked of click, not of rendered help |
| `…::test_the_documents_the_build_writes_make_no_conformance_claim` | The manifest and the risk report, built rather than read off source, because the notes are assembled at run time |
| `…::test_a_file_discussing_a_claim_carries_the_disclaimer` | The structural answer to what a regex cannot do |
| `…::test_every_tehdas2_document_declares_what_it_is_not` | R-10's mitigation, asserted rather than trusted |
| `…::test_the_patterns_catch_the_sentences_they_are_for` | Sabotage, as this project's rule requires |
| `…::test_the_patterns_allow_what_this_project_actually_says` | The half that stops the guard being deleted as a nuisance |
| `…::test_the_disclaimer_pattern_is_not_satisfied_by_silence` | Otherwise the disclaimer check would pass on an empty document |
| `…::test_there_is_something_to_search` | An empty file list makes every assertion pass over nothing — the fifth time this project has guarded against that shape |

**Why the first version of this guard was wrong, kept because it is the
instructive part.** It searched every text file for the claim phrases and failed
on this project's own disclaimers: the sentence "Nothing here should be quoted as
evidence that `commissura` is EHDS-conformant, GDPR-compliant, a certified
anonymisation tool, or a secure processing environment" contains all four phrases
and asserts none of them. Teaching a regular expression to tell a claim from a
denial across a wrapped Markdown paragraph is asserting on the picture of the
prose rather than on the thing, which is a convention this project already
wrote down. The guard became structural instead: the phrases are forbidden
outright in the three surfaces where a claim reaches somebody relying on it, and
anywhere else the file must declare what it is not.

---

## Requirements read and deliberately not implemented

Traceable in the other direction, so that "not done" is a decision with a
citation rather than a gap nobody noticed.

| Requirement | § (p.) | Why not, and where it is recorded |
| --- | --- | --- |
| Age banding | D7.2 §3.3.1 (22) | The guideline supplies the *what*, not the *how wide*, and the width is a judgement about a cohort and a permit. Design in the decision log of 2026-11-13; queued as remediation item 6 |
| Opt-out exclusion | D6.1 A6.2 (68), *Mandatory* | Two interface decisions unmade: labels or identifiers, and whether a no-match exclusion is an error. Remediation item 7, and the highest-value of the four deferred |
| Permit-driven field and row selection | D6.1 A6.2 (67–68), *Mandatory* ×2 | Needs a permit model, and the permit and application templates are implementing acts expected March 2027. Remediation item 8 |
| Trade-secret metadata flag | D6.1 A6.1 (67), *Mandatory* | The profile property to carry it is not sourced. A reading job, not a coding job. Remediation item 9 |
| Identifier↔pseudonym mapping | D7.2 §4.4 (40), recommended | A stored mapping is the enumerable table this scheme was chosen to avoid. Gap analysis P-03; the limit it leaves is now stated in the manifest |
| Reverse pseudonym lookup | D7.2 §4.2 (36), §4.7 (41) | Refused by design; pinned by a pre-existing test asserting no `unwhois`, `reverse`, `resolve`, `lookup` or `identify` command exists. The mitigation is the declaration in item 3 |
| Pseudonymising facilities and clinicians instead of removing them | D7.2 §3.3.4 (25) | A pseudonymised facility code is a new relinkable identifier in the dataset, and whether that is acceptable depends on the permit. Risk R-05 |
| Encryption of the handover | D6.1 A6.3 (68), D7.4 TIR-8 (63) | A transfer concern with an unknown counterpart. Risk R-09 |
| Upload to a secure processing environment | D7.4 EHDSR-11 (32), Mandatory, **Data Holder** | The only one of eighteen that is the holder's. No SPE exists to upload to; the API is specified as a recommendation in a document stating it prescribes nothing legally, and TIR-14 says it will version |
| Statistical aggregation | D6.1 Table 2 (25) | The access body's by default, and an explicit project non-goal |
| IP and trade-secret protection measures | D6.1 §3.6.2 (27) | "Assumed that the appropriate protection measures… have been established and applied by the HDAB" |
| l-diversity, t-closeness | D7.2 §5.5.4 (54) | Informative, not required. k is computed; the other two would add numbers without adding a decision anybody has asked to make |
| Differential privacy, distance metrics, shadow-model attacks | D7.2 §5.5.3, §5.5.7 (51–57) | The framework assumes a generator trained on real patient data. This generator is trained on nothing, so there is no real individual to link back to. Gap analysis P-31 |
| D7.4 operational requirements (26 pp.) | §5.5 (35–60) | Not one names the data holder; and D7.4 itself states they are not legally prescribed |
