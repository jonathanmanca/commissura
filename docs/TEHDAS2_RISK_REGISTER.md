# Risk register

Risks to the privacy of data subjects, to the legal position of a data holder
using `commissura`, and to the project's own claims. Derived from the gap
analysis of 2026-11-17 against `682d839`.

**This document does not declare conformance.** It is a register of risks, and
a mitigated risk is not a compliance statement. Nothing here should be quoted as
evidence that `commissura` is EHDS-conformant, GDPR-compliant, a certified
anonymisation tool, or a secure processing environment.

Scoring is deliberately coarse. **Probability** is the chance the risk
materialises for a holder using the tool as documented over a year of real
operation. **Impact** is what it costs when it does. **Level** is the pair, not
a product of invented numbers.

A risk is only listed if there is a concrete path to it. "Could be attacked" is
not a risk entry; "this input produces this wrong outcome" is.

---

## R-01 — The same person gets the same label under two different data permits

| | |
| --- | --- |
| **Source** | D7.2 §4.4, p. 41: "Pseudonyms MUST NOT be reused across different data permits, to minimise risks of intentional or unintentional linkage of data by the data user." |
| **Path** | A holder runs `keygen` once, stores the key, and builds a dataset for permit A. Six months later a second permit arrives; they use the same key, because nothing tells them not to and `keygen` warns that replacing a key orphans every existing dataset. The two datasets carry identical `sub-…` labels. A data user holding both — or two users who collude, or one SPE that holds both — can join them, producing a linked dataset nobody assessed and no permit authorised. |
| **Probability** | **High.** It is the default behaviour and the path of least effort. The tool's own `keygen` output actively discourages making a second key. |
| **Impact** | **High.** A violation of an explicit MUST, and the harm is exactly the one the MUST names: linkage the HDAB did not evaluate. |
| **Level** | **Critical** |
| **Mitigation** | Permit-scoped derivation: a subkey derived from the root key and a permit reference, so each permit gets its own label space from the one stored secret. Opt-in, so no existing dataset changes. The manifest records the scope and the derived fingerprint, which is what tells an HDAB whether two datasets are relinkable. |
| **Test** | A build with `--permit A` and one with `--permit B` from the same corpus and the same key produce disjoint subject label sets; a build with no `--permit` is byte-identical to the current output. |
| **Residual** | A holder who ignores the option still reuses labels. The tool cannot know a permit exists unless told. The manifest stating the scope in plain words is as far as a local tool can go. |

---

## R-02 — The quasi-identifier hand-over omits the strongest channel

| | |
| --- | --- |
| **Source** | D7.2 §4.5, p. 41: "Identification of quasi-identifiers and handing over information on them to the data minimisation process"; and "Provide health-data specific quasi-identifiers beyond what is in the EDPB guidelines (e.g., dates of visits in the hospital also become quickly identifying)". §3.2, p. 17 lists "a sequence of hospital visit dates" among its examples. |
| **Path** | An HDAB or a downstream processor reads `risk_report.json` to learn which quasi-identifiers the holder identified. The file names the `participants.tsv` columns and the laboratory analytes. It does not name the session day-offset sequence. The reader concludes the quasi-identifier set is age and sex, applies generalisation to those, and ships a dataset in which every subject's full event timeline is intact and exactly aligned. One true date for one subject, from any other source, then recovers that subject's whole history — which the README already identifies as the most likely route from a dataset built here back to a person. |
| **Probability** | **Medium.** It requires the reader to trust the machine-readable artefact over the README, which is what a machine-readable artefact is for. |
| **Impact** | **High.** The omission makes the strongest re-identification channel in the dataset invisible to the one party whose job is to assess it. |
| **Level** | **High** |
| **Mitigation** | Name every quasi-identifier channel the dataset actually carries in `risk_report.json`, with what it is and why it was kept, including the interval sequence that k-anonymity cannot score. A channel that cannot be given a k is still a channel and must not be omitted for being unscoreable. |
| **Test** | The report names the interval channel whenever the dataset carries session day offsets, and a test reads the dataset to confirm it does. |
| **Residual** | Naming a risk is not mitigating it. Blurring the intervals would destroy what they exist for; this stays a documented trade-off, as the README says. |

---

## R-03 — A rebuild erases the record of what the previous release contained

| | |
| --- | --- |
| **Source** | D7.2 §5.5.1, p. 51: "Documentation shall include clear information on the origin, authorship, and time of creation or update for each documentation entry. Appropriate mechanisms shall be in place to maintain traceability across documentation updates, enabling verification of how the documentation has evolved over time." |
| **Path** | A patient objects. The holder removes their records from the corpus and rebuilds. The new dataset is correct and its manifest describes it correctly. Nothing anywhere says a previous dataset existed, what it contained, or that a withdrawal is the reason the counts changed. An auditor comparing a copy taken last month against the current dataset sees two documents each claiming to be authoritative, with no link between them and no account of the difference. |
| **Probability** | **High.** Rebuilding is the normal operation, and opt-out handling (D6.1 A6.2, *Mandatory*) makes withdrawal-driven rebuilds expected rather than exceptional. |
| **Impact** | **Medium.** No data is exposed. What is lost is the ability to show *when* and *why* the dataset changed, which is the point of a de-identification record. |
| **Level** | **High** |
| **Mitigation** | When a build replaces an existing dataset, carry the predecessor's identity forward: its `generated_at`, its `manifest_hmac` and its schema version. A chain of one link is enough to make the history followable, and the HMAC makes each link checkable by the key holder. |
| **Test** | A second build over the same destination records the first manifest's HMAC and timestamp; a first build records no predecessor and says so. |
| **Residual** | Only one step back. A full version history belongs in whatever the holder uses for releases, not in a dataset directory. |

---

## R-04 — A reader of the manifest cannot reconstruct how the pseudonyms were made

| | |
| --- | --- |
| **Source** | D7.2 §4.4, p. 40: for cryptographic pseudonym generation one must "save function used, exact specification of inputs, value of salt". §4.3, p. 37 asks the catalogue record to state the "pseudonymisation method: reversible vs. irreversible pseudonymisation used at data holder". |
| **Path** | A dataset reaches an HDAB with `.deident/manifest.json`. The manifest states a key fingerprint and a rule version. It does not state the algorithm, the domain separation, the truncation, the policy, or that the scheme is irreversible without the source corpus. The HDAB cannot assess the algorithm it is required to approve (§4.3, p. 38: "uses a pseudonymisation algorithm approved by the HDAB"), and cannot tell whether a significant finding could ever be routed back. |
| **Probability** | **Medium.** It bites on first contact with an HDAB, which does not yet exist in Italy. |
| **Impact** | **Medium.** It does not endanger a data subject. It blocks the approval the output needs, and it leaves the irreversibility — which D7.2 discourages — undeclared. |
| **Level** | **Medium** |
| **Mitigation** | A `pseudonymisation` section in the manifest naming the algorithm, the per-use domain prefixes, the output length, the policy (deterministic), the scope (key, or key and permit), and the reversibility in D7.2's own terms, with what follows for opt-out and for significant findings. |
| **Test** | The section is present, states the algorithm and the truncation, and contains no key material; a test asserts the key's bytes and hex appear nowhere in it. |
| **Residual** | None for the stated purpose. Whether an HDAB approves the algorithm is their decision, not a property of the document. |

---

## R-05 — "Removed" reads as a success when it is a utility loss

| | |
| --- | --- |
| **Source** | D7.2 §3.3.4, p. 25: the GP "should always be pseudonymised"; health facilities "may sometimes require attention and may suggest using some form of obfuscation (i.e., substituting identifying facilities codes with sequential numbers)"; location data "should always be generalised by default". |
| **Path** | A researcher applies for a multi-site cohort to compare care pathways between hospitals. The holder builds with `commissura`. Institution names, addresses and ordering clinicians are all removed, so the dataset carries no site and no provider dimension at all. The manifest reports them as `removed`, which reads as de-identification working. The study cannot be done, and nobody discovers this until the data is in the SPE. |
| **Probability** | **Medium.** Site comparison is an ordinary secondary-use purpose. |
| **Impact** | **Medium.** Wasted permit, wasted three-month provision window, and a holder who looks incapable. No privacy harm. |
| **Level** | **Medium** |
| **Mitigation** | Not a code change today. The gap analysis records it, and the manifest's own per-field table already shows which fields are gone — the fix is for a reader to be told that `removed` on a facility or a provider is a deliberate choice with a cost, not a requirement. Pseudonymising rather than removing them is a real feature and a real decision, and it must not be slipped in: a pseudonymised facility code is a new relinkable identifier in the dataset, and whether that is acceptable depends on the permit. |
| **Test** | None yet; this is a documented open point, not an implemented mitigation. |
| **Residual** | Full. Recorded so it is not rediscovered as a surprise. |

---

## R-06 — Exact age cannot reach a useful k and the tool offers no remedy

| | |
| --- | --- |
| **Source** | D7.2 §3.3.1, p. 22: "Age should only be used as an exact value when it is indispensable for the research question and cannot be replaced by age categories, i.e., generalised, without loss of analytical validity." §3.2, p. 19 names generalisation as the most used mitigation. |
| **Path** | A holder builds a 25-subject dataset. `risk` reports minimum k = 1 and says plainly that this is arithmetic, not a defect. The holder has no way to act on it inside the tool: there is no `--age-band`. They either ship at k = 1 or edit `participants.tsv` by hand, in which case the manifest's digests no longer match and `verify` reports the dataset as altered. |
| **Probability** | **High** for small cohorts, which is most clinical research. |
| **Impact** | **Medium.** The honest k is reported, so nobody is misled. The holder is simply left without the remedy the guideline names. |
| **Level** | **High** |
| **Mitigation** | `--age-band <years>`, width chosen by the holder and recorded in the manifest on the age row, with `risk` then computing k over the banded values. Designed on 2026-11-13; the design holds and is reproduced in the remediation plan. |
| **Test** | Not implemented in this round. Reasons in the remediation plan: the width is a judgement about a cohort and a permit, it changes `participants.tsv` and every captured number in the README, and the 2026-11-13 decision's sequence — let somebody run `risk`, see k = 1, and say what they want — is still the right one now that the guideline has supplied the *what* but not the *how wide*. |
| **Residual** | Full until implemented. |

---

## R-07 — A significant finding cannot be routed back to a patient

| | |
| --- | --- |
| **Source** | D7.2 §4.2, p. 36: "EHDS should rely on reversible pseudonymisation to support implementation of data subject rights such as return of information on significant findings." D7.4 §5.4.1, p. 33 names "returning of clinically significant results to the original data holders" as one of three export-control areas. |
| **Path** | A data user analysing a dataset built here finds something clinically actionable about `sub-a3f9c21b4e07`. The chain runs back to the holder. The holder has the key and the original corpus, and `commissura` offers no way to ask "which record produced this label" — by design, because the only implementation is to enumerate the identifier space, which is the attack the scheme was chosen to resist. In practice the holder must re-derive labels for their whole population and match, which is feasible but is not a feature and is not documented. |
| **Probability** | **Low** today — it needs a data user, an SPE and a permit, none of which exist. |
| **Impact** | **High** if it happens: a patient is not told something they should be told. |
| **Level** | **Medium** |
| **Mitigation** | None implemented, and a reverse command stays refused: a test asserts no `unwhois`, `reverse`, `resolve`, `lookup` or `identify` command exists. What is in scope is **saying so**: the manifest should state that the scheme is irreversible without the source corpus, so the holder knows before a finding arrives rather than after. That is part of R-04's fix. |
| **Residual** | High, and accepted with its reason. A stored mapping would close it and would be the enumerable table the design exists to avoid. The honest statement is that routing a finding back requires the holder's own population and their key, and that this is a bulk re-derivation rather than a lookup. |

---

## R-08 — Nothing excludes a subject who has opted out

| | |
| --- | --- |
| **Source** | D6.1 Annex 6 A6.2, p. 68, marked *Mandatory*: "Identify and remove data of natural persons who opted-out." §3.2.1, p. 16: where national law provides, holders "must implement and manage the opt-out mechanism". |
| **Path** | A holder receives an opt-out, runs `whois` to learn the subject label, and then has nowhere to put it. `build` takes a corpus directory and builds all of it. The holder deletes files from the corpus by hand; if they miss one, nothing notices, and the manifest records no exclusion at all — so a dataset built after an opt-out is indistinguishable from one built before it. |
| **Probability** | **Medium.** It depends on Italian national law assigning opt-out handling to holders, which is undecided. |
| **Impact** | **High.** A *Mandatory* checklist item, and the failure mode is a dataset released against an exercised right. |
| **Level** | **High** |
| **Mitigation** | `build --exclude-subjects <file>` taking subject labels, dropping every record that resolves to one, and recording the count in the manifest — count only, never the labels, because a list of excluded labels in a document that travels is a list of people who objected, which is itself a disclosure. |
| **Test** | Not implemented in this round. It needs a decision on the input format (labels, or identifiers that the tool hashes) and on whether an exclusion that matched nothing is an error. Recorded in the remediation plan as the next item after the ones built here. |
| **Residual** | Full. The present answer is that the holder filters the corpus and the tool does not help or check. |

---

## R-09 — The handover is unencrypted and the tool says nothing about it

| | |
| --- | --- |
| **Source** | D6.1 Annex 6 A6.3, p. 68, *Recommended*: "Encrypt data before transfer" and "Share encryption key through a separate channel". D7.4 TIR-8, p. 63: the SPE API "MUST support content encryption (e.g., AES-256) prior to transmission, enforced by the HDAB". |
| **Path** | A holder finishes a build and copies `dataset/` to wherever the HDAB said. Nothing in the tool's output mentions encryption, so a holder following `commissura`'s instructions and nothing else transfers pseudonymised personal data in the clear. |
| **Probability** | **Low** in practice — any real transfer runs over a channel somebody else secured, and the SPE API will enforce TIR-8 at its end. |
| **Impact** | **Medium.** Pseudonymised data is personal data. |
| **Level** | **Low** |
| **Mitigation** | Deliberately none in code. Encryption is a transfer concern, the counterpart's requirements are unknown, and adding a bespoke encryption step would mean inventing a key-management story next to the one key this project guards carefully. A sentence in the README's handover section is the right size of fix. |
| **Residual** | Accepted. Recorded so that "the tool does not encrypt" is a decision with a reason rather than an oversight. |

---

## R-10 — The project's own documents overstate what the analysis establishes

| | |
| --- | --- |
| **Source** | The brief for this work, and the pattern recorded on 2026-11-16: a reason that *sounds* like a security reason gets less scrutiny than one that does not. |
| **Path** | A reader finds six documents under `docs/` with TEHDAS2 in their names and concludes the project has been assessed against the EHDS. "Aligned with TEHDAS2" becomes "EHDS-ready" in a README, then "compliant" in a conversation. Nothing in the repository would contradict it. |
| **Probability** | **Medium.** This is how the `.gitignore` rationale rotted, two days after it was written. |
| **Impact** | **High.** A false compliance claim about health data is the worst sentence this repository could contain, and the hard constraint "synthetic data only, no claims we cannot support" is what the whole project rests on. |
| **Level** | **High** |
| **Mitigation** | Every document in this set opens by stating what it is not. The gap analysis's conclusion is a technical assessment and says so. No document uses "compliant", "conformant" or "certified" about `commissura` except where it means the HealthDCAT-AP SHACL result, which is a mechanically checked claim about one file. A test asserts the forbidden claims appear nowhere in the repository. |
| **Test** | `tests/test_claims.py` — the repository contains no sentence claiming EHDS compliance, GDPR compliance, SPE certification, or that `commissura` anonymises. |
| **Residual** | Low once the test exists, because the test fails on the sentence rather than relying on a reader's restraint. |

---

## Ranking

| Level | Risks |
| --- | --- |
| Critical | R-01 |
| High | R-02, R-03, R-06, R-08, R-10 |
| Medium | R-04, R-05, R-07 |
| Low | R-09 |

Mitigated in this round: R-01, R-02, R-03, R-04, R-10.
Documented and deliberately left open: R-05, R-06, R-07, R-08, R-09.
