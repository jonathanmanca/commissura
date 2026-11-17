# Remediation plan

Ordered by how much the gap costs, not by how easy it is to close. Written
2026-11-17 from the gap analysis and risk register in this directory.

**This document does not declare conformance.** Closing an item here closes a
gap against a guideline, which is not the same as satisfying a legal obligation.
Nothing here should be quoted as evidence that `commissura` is EHDS-conformant,
GDPR-compliant, a certified anonymisation tool, or a secure processing
environment.

Nine items. Five are implemented in this round; four are deferred with a reason
and a design, because the brief for this work asks that high-risk or
irreversible architectural decisions be documented rather than taken in passing,
and because two of the four are a holder's judgement that nobody has yet made.

---

## Now

### 1. Permit-scoped pseudonymisation — closes R-01, the one unmet MUST

**Requirement.** D7.2 §4.4, p. 41: "Pseudonyms MUST NOT be reused across
different data permits." §4.3, p. 38 makes per-project generation the condition
for the holder's output reaching the data user without the HDAB redoing the
work.

**Design.** A subkey, derived from the root key and a permit reference under its
own domain prefix:

```
permit_key  = HMAC-SHA256(key, "permit|" + permit_reference)
subject_id  = HMAC-SHA256(permit_key, "subject|" + national_id)[:12]
```

Everything that derives from the key derives from the subkey instead: subject
labels, date offsets, DICOM UIDs, accessions, the manifest tag. One root key
stays in one file, so key custody does not change.

**Why a subkey rather than widening the existing input.** Adding the permit to
the `"subject|"` input would change every label for every dataset ever built,
which the project's constraints forbid without a migration plan. A subkey is
reached only when a permit is named, so a build without `--permit` is
byte-identical to today's. That is checkable, and a test checks it.

**Scope.** `build --permit <reference>`; `whois --permit <reference>` so an
opt-out can be answered for the right permit; the manifest records the reference
and the derived fingerprint. No validation of the reference's format — a permit
identifier's shape is the HDAB's to define and Italy has no HDAB.

**Risk.** The derived fingerprint differs from the root key's, so two datasets
under one permit are relinkable and two under different permits are not, which
is the intended behaviour and is the opposite of what a reader expects from a
fingerprint. The manifest must say which it is.

### 2. The quasi-identifier channels — closes R-02

**Requirement.** D7.2 §4.5, p. 41: identify quasi-identifiers and hand over
information on them to the data minimisation process, including health-specific
ones "beyond what is in the EDPB guidelines (e.g., dates of visits in the
hospital also become quickly identifying)". §3.2, p. 17 lists "a sequence of
hospital visit dates".

**Design.** `risk_report.json` gains a `quasi_identifier_channels` list. Each
entry names the channel, where it is in the dataset, whether a k was computed
for it, and — where none was — why not and what the holder would do about it.
The interval sequence is the entry that matters: it is the strongest channel in
the dataset, it is kept on purpose, and k-anonymity cannot score it.

**Why the risk report and not the manifest.** The risk report is the hand-over
artefact; §4.5 describes handing information to a *process*, and this is the
file that process reads.

**What it does not do.** It names a risk; it does not mitigate one. Blurring the
intervals would destroy what they exist for, which the README already states as
a documented trade-off.

### 3. The pseudonymisation declaration — closes R-04, partly R-07

**Requirement.** D7.2 §4.4, p. 40: save "function used, exact specification of
inputs, value of salt", with the salt kept separate. §4.3, p. 37: state the
pseudonymisation method, reversible or irreversible. §4.3, p. 38: the HDAB
approves the algorithm.

**Design.** A `pseudonymisation` section in `.deident/manifest.json` carrying
the algorithm, the domain prefixes with what each derives, the output length,
the policy (`deterministic`, in D7.2's own vocabulary), the scope (`key-wide` or
`permit-scoped`), and `reversible: false` with a note saying what follows: an
opt-out can be answered because the holder keeps the source corpus and derives
forward, and a significant finding cannot be routed back by lookup.

**The salt is named and not carried.** `key_fingerprint` already identifies
which secret was used without carrying it. A test asserts the key's bytes and
its hex appear nowhere in the section — the fourth time this project has written
that class of test, and the reason is D7.2 §5.5.1's "the documentation shall not
contain personal or identifying information".

### 4. Documentation traceability — closes R-03

**Requirement.** D7.2 §5.5.1, p. 51: documentation shall carry origin,
authorship and time of creation or update per entry, with "appropriate
mechanisms… to maintain traceability across documentation updates, enabling
verification of how the documentation has evolved over time."

**Design.** When a build replaces an existing dataset, the new manifest records
the predecessor's `generated_at`, `manifest_hmac` and `schema_version`. One link
back, not a history: a chain of manifests is followable if each names the one
before, and the HMAC makes each link checkable by the key holder.

**Why only one link.** A dataset directory is not a version-control system, and
storing every previous manifest inside the new dataset would ship the old
counts to an access body as though they described the current data. A first
build records `null` and says so, because absent and unknown are different
facts.

### 5. Two derivable description properties — partly closes P-12, P-20

**Requirement.** D7.2 §3.1, p. 18 recommends holders "specify any standard data
minimisation rules that are applicable by default to the datasets offered",
giving year-of-birth as the example. §3.3.1, p. 22 treats age as a
quasi-identifier needing attention. A catalogue reader deciding whether they
need exact ages has to know the range first.

**Design.** `healthdcatap:minTypicalAge` and `maxTypicalAge`, derived from the
published `participants.tsv` — both `xsd:nonNegativeInteger` under the profile's
own value constraints, so no IRI is invented.

**What is deliberately not emitted.** `dpv:hasPersonalData`, which D7.2 §4.3
explicitly names. The Release 8 shapes place **no value constraint** on it —
only a path and a severity — so the DPV concept to use is unsourced, and writing
a plausible one is the trap this project recorded when it found that the health
category vocabulary is served over https and the data theme over http. It goes
in the deferred list with the open question stated.

---

## Deferred, with designs

### 6. Age banding — R-06

`--age-band <years>`, width chosen by the holder, recorded in the manifest on
the age row, with `risk` computing k over the banded values. The full design is
in the decision log of 2026-11-13 and holds unchanged:

- the width is the holder's choice, never a default;
- the manifest must record it, because `40-44` is not self-describing — a reader
  cannot distinguish a five-year band from a decade starting on a multiple of
  five, nor a banded dataset from one whose source only had bands;
- `risk` must then report k over the banded values or it describes a dataset
  nobody has;
- the age ceiling at 89 stays separate, because truncation is a
  de-identification invariant and banding is a disclosure-control choice.

**Why not now.** D7.2 §3.3.1 supplies the *what* and not the *how wide*, and the
width is a judgement about a cohort and a permit. The 2026-11-13 sequence — let
somebody run `risk`, see k = 1, and say what they want — is still right; what
has changed is that the recommendation now has a page number, which moves this
from speculative to queued. It also moves every captured number in the README,
which is a reason to do it deliberately.

### 7. Opt-out exclusion — R-08

`build --exclude-subjects <file>` taking subject labels, dropping every record
that resolves to one, recording the **count** in the manifest and never the
labels — a list of excluded labels in a document that travels is a list of
people who objected.

**Why not now.** Two decisions are unmade and both change the interface. Does
the file hold subject labels, which the holder gets from `whois` and which are
permit-scoped, or national identifiers, which the tool would hash itself and
which would then be patient identifiers in a file on disk? And is an exclusion
that matched nothing an error — a holder who mistypes a label and sees a
successful build has not acted on the objection, which is the failure mode of
the 2026-11-13 withdrawal that did not withdraw. This is the next item after
this round, and it is the one with the highest value of the four deferred.

### 8. Permit-driven field and row selection — H-12, H-13

Both are marked *Mandatory* in D6.1's own checklist: include only the records
and only the variables the permit reports. `read_corpus` globs three patterns
and builds everything.

**Why not now.** It needs a permit model — a machine-readable statement of
variables, inclusion and exclusion criteria — and the templates for the data
access application and the permit are implementing acts expected in **March
2027** (D6.1 §3.6.1, p. 23). Inventing a permit schema now means inventing the
thing the Commission is about to specify, and the most likely outcome is a
model that has to be thrown away. The permit *reference* lands in this round,
which is the part that will still be true in 2027.

### 9. The trade-secret flag — H-07

*Mandatory* in D6.1 A6.1, p. 67: notify the HDAB via metadata of the presence of
trade secrets. A holder declaration, one boolean and a note, and the Art. 60(3)
notification route D6.1 describes.

**Why not now.** The profile property to carry it has not been established.
HealthDCAT-AP Release 8's transcribed obligation table has no trade-secret term;
the route is probably `dct:rights` or an ODRL policy, neither of which is
transcribed here, and the project's rule is not to write an IRI it has not
sourced. Resolving it is a reading job on the profile, not a coding job, and it
belongs with the three reading jobs already queued.

---

## Not planned

| | Why |
| --- | --- |
| Encryption of the handover (R-09) | A transfer concern with an unknown counterpart. A sentence in the README's handover section is the right size |
| Reverse pseudonym lookup (R-07) | Refused by design and pinned by a test. The honest mitigation is to declare the irreversibility, which item 3 does |
| Pseudonymising facilities and clinicians instead of removing them (R-05) | A real feature with a real cost — a pseudonymised facility code is a new relinkable identifier in the dataset — and whether that is acceptable depends on the permit. Documented, not slipped in |
| An external de-identification engine adapter | No holder has asked, no engine has been chosen, and `read_corpus` already accepts whatever is in the three globs, so a pre-processing engine needs no code here. The composition point and the one manifest change it would require are recorded in `ARCHITECTURE_TARGET.md` §4 |
| Anything from D7.4's operational requirements | Seventeen of eighteen EHDS-derived requirements and all 26 pages of SPER-* belong to other roles |

---

## Open architectural points

Recorded rather than decided, as the brief asks.

1. **Whether a permit-scoped fingerprint should replace the root fingerprint in
   the manifest or sit beside it.** This round emits both, because an HDAB
   combining two of a holder's datasets needs to know they came from one key
   *and* that they are not relinkable. If that turns out to be two facts nobody
   wants together, the root fingerprint is the one to drop — it is the one that
   tells a reader the datasets could have been linked.
2. **Which DPV concept `dpv:hasPersonalData` should carry.** The shapes do not
   constrain it. Candidates exist in the DPV vocabulary but are not transcribed
   here, and the property is recommended rather than mandatory, so guessing buys
   nothing and risks an IRI that resolves to nothing.
3. **Whether permit scoping should become the default once a permit model
   exists.** It cannot be today: there is no permit to name. When the March 2027
   implementing acts land, a build with no permit will arguably be a build
   nobody should be doing, and the flag should probably become required for any
   dataset bound for an HDAB. That is a breaking change and belongs with the
   permit model, not with this round.
4. **Whether `commissura` should refuse to build when the key's fingerprint has
   already been used for a different permit.** It cannot know: the tool holds no
   state between runs, and the only record is in datasets it may not be able to
   see. Stating the scope in the manifest is what a local tool can do; enforcing
   it needs a registry, which is a governance component and not a CLI.
