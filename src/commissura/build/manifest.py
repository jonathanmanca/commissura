"""Write the two documents that make a dataset accountable.

Two, not one, because they answer different questions for different readers.

``.deident/manifest.json`` answers *what was done to this data*: which key
produced the pseudonyms, which rule version applied, what was removed, replaced
or kept per modality, how many records failed to link, and what the scrubber
knows it could not reach. No standard specifies this. HealthDCAT-AP certainly
does not — its 57 properties describe a dataset for a catalogue and say nothing
about de-identification provenance. So this schema is ours, and the honest thing
is to say so in the file.

``healthdcat-ap.jsonld`` answers *what this dataset is*: title, description,
theme, health category, access rights, who governs it. That is EHDS Article 77,
its reader is a Health Data Access Body, and it is emitted as JSON-LD against
the profile's own terms.

The manifest records a **residual risk** section rather than a score. A number
invites the reader to treat de-identification as solved at some threshold. A
list of what the method cannot reach tells them where to look, which is what a
reviewer actually needs.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from commissura import healthdcat, layout
from commissura.build.integrity import (
    DIGEST_ALGORITHM,
    HMAC_FIELD,
    digest_tree,
    tag_manifest,
)
from commissura.build.observe import AGE_FIELD, ModalityLedger, observe_corpus
from commissura.build.scrub import CATEGORY_DISPOSITION, ScrubReport
from commissura.build.writer import BuildSpec, BuildSummary, tool_versions, utc_now
from commissura.deident.keys import SecretKey
from commissura.deident.pseudonymise import declare
from commissura.read.corpus import RawCorpus
from commissura.read.identity import REASON_KEEPS_RECORD, KeyKind, RefusalReason
from commissura.validate.context import DatasetContext

MANIFEST_SCHEMA_VERSION = "7.2.0"
"""Version of the manifest format defined here.

Separate from the layout schema version, because the manifest will change on a
different clock from the dataset layout.

**7.2.0, 2026-11-23.** ``opt_out.entries_by_kind`` is new, and additive for the
same reason. It is the one thing about an exclusion list an auditor cannot learn
elsewhere: whether the list the holder acted on could reach subjects that no
codice fiscale names. Until that day no entry could, so the section's note
described a limit; now it carries a count per kind of subject key, to be read
against ``source.subject_keys``.

**7.1.0, 2026-11-19.** ``generalisation`` is new. Additive, so a reader of
7.0.0 still parses this; the minor number moves because there is something new
to read.

It states whether participant ages were generalised into bands and how wide,
separately from the age ceiling, which this tool applies to every dataset. D7.2
section 3.1 (p. 18) asks a holder to publish the default minimisation rules
that apply, and section 3.3.1 (p. 22) names exact age as the example to justify
rather than assume. Stated even when no banding was applied, for the reason
``opt_out`` states the same: a reader cannot otherwise tell a decision from a
silence.

One correction ships with it rather than a schema change. Two entries in the
per-field table said the birth date was carried "as an age band", which was
never true -- the helper that produced the value was *named* ``_age_band`` and
banded nothing. A manifest that overstates a disclosure control is worse than
one that claims none, so those notes now describe what happens and point at
``generalisation.age`` for whether a band was applied.

**7.0.0, 2026-11-19.** ``source.opt_out`` is new and ``source.records_not_in_dataset``
widens to include the records it accounts for.

The new section says whether an exclusion list was applied to this build and,
when one was, how many people it named, how many of them this corpus held, how
many of their records are therefore absent, and how many entries matched no
subject here. Counts only: a list of excluded subjects is a list of people who
exercised a right to object, and this document is written to be read by an
access body. Its purpose is that **a dataset built after an objection stops
being indistinguishable from one built before it**, which is what D6.1 Annex 6
A6.2 (p. 68) requires a holder to be able to show.

The major number moves because of the second half. ``records_not_in_dataset``
has meant "the linkage issues that refused a record, plus the records dropped
for want of a date" since 6.0.0, and a consumer could compute it by summing the
two lists beside it. It now also counts records left out because their subject
opted out, so that sum no longer reaches it. The third part is visible as
``source.opt_out.records_excluded``, so the total still reconciles against
fields in the same section — it reconciles against three of them rather than
two. Every dataset built without an exclusion list carries the same number it
carried under 6.2.0.

**6.2.0, 2026-11-17.** Two additions, from the HL7 Italia CDA R2 reader.
Additive, so a reader of 6.1.0 still parses this.

``modalities`` gains a ``cda`` ledger, which accounts for the elements a CDA R2
laboratory document carried and what became of each. It is present even for a
corpus with no CDA in it, reporting zero files read, because the convention the
field table established is that an absent row reads as "no such thing" and a
zero row reads as "looked, found none".

``source.subject_keys`` gains ``assigned_identifier``, for a subject established
from an ENI, STP, TEAM or ANA code — an identifier issued under a namespace the
document names, which is relinkable within that namespace and is neither a
national identifier nor an institution's own record number. A reader comparing
two holders' datasets needs that distinction to know what can be joined.

**6.1.0, 2026-11-17.** Three additions, from the TEHDAS2 reading in ``docs/``.
Nothing is removed and nothing changes meaning, so a reader of 6.0.0 still
parses this; the minor number moves because there is something new to read.

``pseudonymisation`` states the function, the exact specification of its inputs,
the policy and the reversibility, which D7.2 section 4.4 (p. 40) and section 4.3
(p. 37) ask a controller to save alongside cryptographically generated
pseudonyms. It was reconstructable only from this project's own source before.

``pseudonymisation.permit_reference`` and ``.scope`` record whether the build
was scoped to a data permit. D7.2 section 4.4 (p. 41) says pseudonyms MUST NOT
be reused across permits, and an unscoped build reuses them by construction, so
the field says which of the two this is rather than leaving it to be inferred
from a fingerprint.

``predecessor`` names the manifest this one replaced -- its timestamp, its
authentication tag and its schema version -- because D7.2 section 4.4's
documentation requirements (section 5.5.1, p. 51) ask for "mechanisms… to
maintain traceability across documentation updates". A rebuild used to leave no
trace that a previous dataset existed, which is exactly the withdrawal case of
2026-11-13.

**6.0.0, 2026-11-16.** ``source.records_not_in_dataset`` changes meaning: it
counted every linkage issue plus every dropped record, and three of the reasons
it was counting attach the record and merely flag it. On the first corpus that
produced one it claimed 32 records absent where 3 were. Those now land in
``source.records_flagged_in_dataset``, which is new. A consumer that read the
old field read a number that was too large, so the major number moves even
though the field's name did not.

**5.0.0, 2026-11-13.** ``residual_risk.structural`` was a fixed list of four
prose strings written into every manifest regardless of the dataset. One of them
read "no k-anonymity report has been produced for this dataset" while
``risk_report.json`` sat beside it, digested into this manifest's own integrity
list — so the document contradicted a file it authenticated. The entries are now
derived from the dataset and each carries its own count, which means a consumer
that matched on those sentences will not find them. Hence the major number.

Also in 5.0.0: ``source.subject_keys`` says what established each subject,
because a subject keyed on an institution's record number is not relinkable
across institutions and a reader has no other way to tell.

**2.0.0 is a breaking change and the major number is doing real work.**
``modalities`` was an object keyed by modality name whose values were three
lists of prose; it is now an array of observed ledgers. ``free_text_redactions``
was a top-level map of category to a count; it is now the ``body`` table inside
the reports ledger. Anything that read 1.0.0 will not read this.

Recorded with some embarrassment: the first of those two changes shipped without
this number moving. A schema version exists so a consumer can tell, and leaving
it at 1.0.0 while reshaping the document told them the opposite of the truth.

**2.1.0 added** ``source.records_dropped`` and
``source.records_not_in_dataset``, for records that linked to a subject and
were then left out because they carried no readable date.

**3.0.0 breaks both of those and ``source.linkage_issues`` with them.** They
were lists of ``{path, reason, detail}`` and are now lists of
``{reason, count, detail}``. The paths had to go: an export names its files
after the record they hold, so they were patient identifiers, in the document
written to be sent to an access body. The shape had been wrong since linkage
issues were first recorded and never fired, because every corpus tested had
none of them.

**4.0.0 drops ``detail`` from both of those lists**, leaving ``reason`` and
``count``. A reason is a word this project chose; a detail is a sentence built
from the input, and an unlinked report's named the codice fiscale and the
record number of the person who could not be matched. Removing the paths in
3.0.0 and leaving the detail beside them fixed the smaller half.
"""


def _absent_record_count(corpus: RawCorpus, summary: BuildSummary) -> int:
    """Return how many handed-over records are not in the dataset.

    Three parts, each visible on its own elsewhere in ``source`` so the total
    reconciles: a record that could not be attached to anybody, one that was
    attached and had nowhere to go, and one whose subject opted out. The third
    is the only one that is absent *on purpose*, and it is counted here anyway
    because the question this field answers is "what did I hand over that is not
    here" and the reason does not change the answer.

    Args:
        corpus: The linked corpus.
        summary: What the build produced.

    Returns:
        The count.
    """
    refused = sum(
        1 for issue in corpus.issues if not REASON_KEEPS_RECORD[RefusalReason(issue.reason)]
    )
    excluded = summary.opt_out.records_excluded if summary.opt_out else 0
    return refused + len(summary.dropped) + excluded


def _generalisation_section(summary: BuildSummary) -> dict[str, object]:
    """Describe which values were coarsened before release, and by how much.

    D7.2 section 3.1 (p. 18) asks a holder to "specify any standard data
    minimisation rules that are applicable by default to the datasets offered",
    and section 3.3.1 (p. 22) names age as the worked example: it "should only
    be used as an exact value when it is indispensable for the research question
    and cannot be replaced by age categories". A dataset whose ages read
    ``40-44`` cannot answer either on its own -- a reader cannot tell a
    five-year band from a decade that starts on a multiple of five, nor a banded
    dataset from one whose source only ever carried bands.

    **The ceiling and the band are reported as the two different things they
    are.** Truncating above :data:`commissura.layout.AGE_CEILING` is a
    de-identification invariant this project applies to every dataset; banding
    is a disclosure-control choice the holder makes per release. Reporting them
    in one field would make the first look optional.

    Args:
        summary: What the build produced.

    Returns:
        The section, which states that no banding was applied as plainly as it
        states a width -- the reason being the one the opt-out section gives.
    """
    ceiling = {
        "ceiling_years": layout.AGE_CEILING,
        "above_ceiling": layout.AGE_ABOVE_CEILING,
        "ceiling_note": (
            "Applied to every dataset this tool writes, independently of any "
            "band width. In a small cohort an age of 97 is close to a unique "
            "identifier, and the information lost is negligible for most "
            "research questions."
        ),
    }
    if summary.age_band is None:
        return {
            "age": {
                "banded": False,
                **ceiling,
                "note": (
                    "Ages are exact. D7.2 section 3.3.1 asks that an exact age "
                    "be used only where it is indispensable and cannot be "
                    "replaced by a category, so this is a statement the "
                    "recipient should weigh rather than a default nobody chose. "
                    "`commissura build --age-band <years>` generalises them; "
                    "the width is the holder's judgement about their own cohort "
                    "and their own release, which is why there is none here."
                ),
            }
        }
    return {
        "age": {
            "banded": True,
            "band_years": summary.age_band,
            "band_format": f"low{layout.AGE_BAND_SEPARATOR}high, both bounds inclusive",
            "band_anchor": "bands start at zero, so a width of ten gives decades",
            **ceiling,
            "note": (
                "The upper bound of a band is clamped to the ceiling, so the two "
                "mechanisms cannot interfere: a width of seven would otherwise "
                "place an 85-year-old in a band reaching 90 and state that they "
                "might be 90. `risk` measures k over these values and not over "
                "the ages they came from, because the banded values are what the "
                "dataset holds."
            ),
        }
    }


def _opt_out_section(summary: BuildSummary) -> dict[str, object]:
    """Describe what an exclusion list did to this build.

    **Whether one was applied is itself the first fact**, and it is stated even
    when none was. A reader who finds no counts cannot otherwise tell a build
    that excluded nobody from a build that was never asked to, and this project
    has recorded twice that an absent collection is not evidence about what
    would have filled it.

    Args:
        summary: What the build produced.

    Returns:
        The section. Counts only — never the identifiers on the list, never the
        subject labels they resolved to.
    """
    record = summary.opt_out
    if record is None:
        return {
            "applied": False,
            "note": (
                "No exclusion list was given to this build, so no subject was "
                "left out on account of an objection. This is not a statement "
                "that nobody objected: it is a statement that this build was "
                "not told. Supply one with `commissura build "
                "--exclude-subjects`."
            ),
        }
    return {
        "applied": True,
        "entries": record.entries,
        "subjects_excluded": record.subjects_excluded,
        "records_excluded": record.records_excluded,
        "entries_by_kind": dict(record.entries_by_kind),
        "entries_matching_no_subject": len(record.unmatched),
        "note": (
            "Counts only. Neither the identifiers on the list nor the subject "
            "labels they resolved to are recorded: a list of excluded subjects "
            "is a list of people who exercised a right to object, which is "
            "itself a disclosure, and this document is written to be read by an "
            "access body. `entries_by_kind` is the one thing that cannot be "
            "learnt any other way: it says whether the list this build acted on "
            "could reach subjects that no codice fiscale names -- one "
            "established from an institution's own record number, or from an "
            "ENI, STP or ANA code -- which a list of codici fiscali alone "
            "cannot reach. "
            "Compare it against `subject_keys` above, which says what "
            "established the subjects this corpus actually held. An "
            "entry matching no subject is reported to the operator and is not "
            "an error, because the person may simply have no records in this "
            "export and no tool can tell that from a mistyped identifier."
        ),
    }


def _flagged_record_count(corpus: RawCorpus, summary: BuildSummary) -> int:
    """Return how many records are in the dataset and carry a linkage issue.

    A different fact from the one above, and one an auditor needs separately: a
    record here is published, and something about how it was attributed is
    worth a second look.

    **A record whose subject opted out is not published**, however its
    attribution was flagged, so it belongs to neither count once it belongs to
    the one above. Said explicitly because this is the shape of the defect found
    on 2026-11-16: that field overstated by exactly the number of flagged
    records, because three reasons had been added that attach a record instead
    of refusing it and nothing revisited the arithmetic. Exclusion is a fourth
    way for a record to be absent, and it reaches this field too.

    Args:
        corpus: The linked corpus.
        summary: What the build produced, for the paths it left out.

    Returns:
        The count.
    """
    absent = summary.opt_out.excluded_paths if summary.opt_out else frozenset()
    return sum(
        1
        for issue in corpus.issues
        if REASON_KEEPS_RECORD[RefusalReason(issue.reason)] and issue.path not in absent
    )


def _by_reason(reasons: Iterable[str]) -> list[dict[str, object]]:
    """Count records that are absent from the dataset, by why they are absent.

    **The reason token only, never the detail that goes with it.** A reason is a
    fixed word this project chose; a detail is a sentence built from the input,
    and the input is patient data. `unlinked_report` details named the codice
    fiscale and the record number of the person who could not be matched, and
    `unreadable_lab_message` details were `str(exc)`, which for an OSError is
    the absolute path of the file — the operator's account name and a record
    number together. Both were published in the document written to be sent to
    an access body.

    That is the fourth time the same pattern has been found in this file: a
    field that looks like metadata and carries something derived from the
    input. The paths were removed from these lists on 2026-11-12 and the detail
    beside them was left, which was the worse half.

    Args:
        reasons: One reason token per absent record.

    Returns:
        One row per reason with a count, sorted by reason.
    """
    counts: Counter[str] = Counter(reasons)
    return [{"reason": reason, "count": counts[reason]} for reason in sorted(counts)]


def _body_payload(reports: Sequence[ScrubReport]) -> list[dict[str, object]]:
    """Account for what the scrubber substituted inside the report bodies.

    The counterpart to the field table, for the one modality that has prose. A
    report's labelled headers are fields and are observed by
    :mod:`commissura.build.observe`; its body is not, and until now its counts
    sat in a separate section of the manifest, so seeing what had happened to a
    report meant reading two places and joining them by hand.

    Two counts, because for free text they answer different questions.
    ``documents_affected`` is coverage and reads like the field table's
    ``files_present``; ``occurrences`` is how many identifiers were actually
    substituted. The field table reports only the first, on the grounds that an
    occurrence count there would mostly measure how long the messages were.
    Here the occurrence count is the measurement: it is the number of
    identifiers the method found.

    Args:
        reports: One scrub report per document written.

    Returns:
        One row per category, including the categories that never fired, sorted
        by name.

    Raises:
        KeyError: If the scrubber emitted a category with no declared
            disposition. Deliberate: a manifest that guessed would be worse
            than a build that stopped.
    """
    documents: Counter[str] = Counter()
    occurrences: Counter[str] = Counter()
    markers: dict[str, str] = {}
    for report in reports:
        for category, count in report.categories().items():
            documents[category] += 1
            occurrences[category] += count
        for item in report.replacements:
            markers[item.category] = item.replacement

    return [
        {
            "category": category,
            "disposition": CATEGORY_DISPOSITION[category],
            "documents_affected": documents.get(category, 0),
            "occurrences": occurrences.get(category, 0),
            **({"marker": markers[category]} if category in markers else {}),
        }
        for category in sorted(set(CATEGORY_DISPOSITION) | set(occurrences))
    ]


def _ledger_payload(
    ledger: ModalityLedger,
    *,
    body: list[dict[str, object]] | None = None,
    age_band: int | None = None,
) -> dict[str, object]:
    """Render one modality's observed field ledger for the manifest.

    Args:
        ledger: What was observed in that modality's input.
        body: For the one modality with prose, what the scrubber substituted
            inside it. Omitted for the others, which have no body.
        age_band: The width ages were generalised into, which rewrites exactly
            one row. `observe_corpus` describes the *input* and cannot know
            what the build did to it, so the adjustment belongs here, where
            both facts are in hand. The alternative -- a static note claiming
            one disposition for a value whose disposition depends on a flag --
            is the defect this whole pass was looking for.

    Returns:
        The manifest section, with the counts first so that a reader sees the
        shape of the modality before the field-by-field table.

    The field identifier is emitted as ``field`` and not ``key``:
    :data:`commissura.layout.FORBIDDEN_MANIFEST_KEYS` reserves ``key``, because
    a manifest property of that name is how the secret would look if it ever
    leaked into one, and nobody should have to read the value to find out.
    """
    return {
        "modality": ledger.modality,
        "key_kind": ledger.key_kind,
        "files_read": ledger.files_read,
        # Counted, not named. Found by the test written for the two leaks
        # above, which is the fifth place in this document where a field that
        # looks like metadata carried something derived from the input: the
        # entry was "<relative path>: <exception>", so it held a record number
        # and, for an OSError, the operator's absolute path as well. The
        # operator still gets the path, because an unreadable input file also
        # produces a linkage issue and `build` prints those.
        "unreadable": len(ledger.unreadable),
        "fields_observed": {
            disposition: ledger.count(disposition)
            for disposition in ("removed", "replaced", "kept")
        },
        "fields": [
            {
                "field": item.key,
                **({"name": item.name} if item.name else {}),
                "disposition": "replaced"
                if (item.key == AGE_FIELD and age_band is not None)
                else item.disposition,
                "files_present": item.files_present,
                **({"note": item.note} if item.note else {}),
            }
            for item in ledger.fields
        ],
        **(
            {
                "body_note": (
                    "A report's prose body is not a field, so it is accounted for "
                    "here rather than above: one row per category of thing the "
                    "scrubber substitutes, with the marker left in the text. "
                    "documents_affected reads like files_present above; "
                    "occurrences is how many identifiers were found. A category "
                    "at zero did not fire in this corpus and its rule still "
                    "applies."
                ),
                "body": body,
            }
            if body is not None
            else {}
        ),
    }


def _subject_key_counts(corpus: RawCorpus) -> dict[str, int]:
    """Return how many subjects each kind of identity key established.

    Both kinds are reported even at zero, the convention the field table
    established on 2026-11-10: a row that is missing reads as "no such thing",
    and "no subject rested on a record number" is a fact worth stating rather
    than an absence to be inferred.
    """
    counts = {kind.value: 0 for kind in KeyKind}
    for subject in corpus.subjects:
        counts[subject.key.kind.value] += 1
    return counts


def _structural_risks(
    out: Path, summary: BuildSummary, risk: dict[str, object] | None
) -> list[str]:
    """Return the structural limits that apply *to this dataset*, with evidence.

    This used to be four prose strings written unconditionally. Three of them
    were true of the method in general; one was false of every dataset this
    tool produced, because it read "no k-anonymity report has been produced for
    this dataset" while ``risk_report.json`` sat beside it in the same
    directory, digested into this manifest's own integrity list. The manifest
    contradicted a file it authenticated.

    That is the same failure the per-modality field table had and shed on
    2026-11-10: a static list can only account for what somebody remembered to
    write down, and nobody revisits a list that has stopped being read. So this
    is derived, and a limit that does not apply to this dataset is not claimed
    to.

    Args:
        out: The dataset root, which is read for the evidence.
        summary: What the build produced.
        risk: The risk report payload this build computed, or ``None`` if no
            report was produced. The distinction is reported rather than
            smoothed over: "not assessed" and "assessed and k is 1" are
            different facts and only one of them is reassuring.

    Returns:
        One sentence per limit that applies, each carrying its own number.
    """
    risks: list[str] = []

    studies = _imaging_payloads(out)
    if studies:
        burned_in = sum(1 for payload in studies if payload.get("burned_in_annotation"))
        risks.append(
            f"Pixel data is not inspected. {burned_in} of {len(studies)} studies "
            "in this dataset carry BurnedInAnnotation=YES, where identifiers may "
            "be rendered into the image itself."
        )
        risks.append(
            f"No image is defaced. {len(studies)} studies are described here; "
            "where any is of the head, the skull surface remains re-identifiable "
            "by facial reconstruction."
        )

    if summary.scrub_reports:
        risks.append(
            f"Free-text redaction matches identifiers declared in structured "
            f"fields. {len(summary.scrub_reports)} documents were scrubbed this "
            "way; a person named only in prose is not found."
        )

    if risk is None:
        risks.append(
            "Quasi-identifier combinations were not assessed: no k-anonymity "
            "report was produced for this dataset."
        )
    else:
        minimum = risk.get("minimum_k")
        below = risk.get("combinations_below_threshold")
        count = len(below) if isinstance(below, list) else 0
        risks.append(
            f"Quasi-identifier combinations were assessed over "
            f"{risk.get('quasi_identifiers')}: minimum k is {minimum}, with "
            f"{count} combination(s) below the threshold of "
            f"{risk.get('threshold')}. See {layout.RISK_REPORT_JSON}. This is a "
            "measurement and not a certificate of anonymity."
        )

    return risks


def _imaging_payloads(out: Path) -> list[dict[str, object]]:
    """Read the imaging metadata this build wrote, for the evidence above.

    Read back from the dataset rather than threaded through the build, because
    the claim being made is about the dataset: a count derived from anything
    else could be right about the run and wrong about the files.
    """
    found: list[dict[str, object]] = []
    directory = out / "derivatives" / "imaging-metadata"
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # pragma: no cover - we wrote these
            continue
        if isinstance(payload, dict):
            found.append(payload)
    return found


def predecessor_of(destination: Path) -> dict[str, object] | None:
    """Return the identity of the manifest a build is about to replace.

    D7.2 section 5.5.1 (p. 51) asks that "appropriate mechanisms shall be in
    place to maintain traceability across documentation updates, enabling
    verification of how the documentation has evolved over time". A rebuild left
    no trace that there had been a previous dataset. That is the withdrawal case
    of 2026-11-13 from the documentation side: the holder acts on an objection,
    the new dataset is correct, and nothing says why the counts moved or that
    anything moved at all.

    Three fields and no more. The timestamp says when, the authentication tag
    identifies *which* document (and lets the key holder check a retained copy
    against it), and the schema version says how to read that copy. Carrying the
    predecessor's counts would ship numbers describing data this dataset no
    longer contains, in the file written to be believed.

    Read before publication, while the destination still holds the previous
    build. A destination with no manifest -- a first build, or a directory this
    tool did not produce -- gives ``None``, which the manifest states in those
    words, because "there was none" and "we did not look" are different facts.

    Args:
        destination: Where the build will be published, which during a staged
            build still holds the dataset being replaced.

    Returns:
        The predecessor's identity, or ``None`` when there is no readable one.
    """
    path = destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Unreadable is treated as absent on purpose. A malformed or
        # inaccessible manifest in the destination must not fail a build whose
        # own output is fine, and the alternative -- recording "there was
        # something here but we could not read it" -- is a field nobody can act
        # on.
        return None
    if not isinstance(previous, dict):
        return None
    return {
        "generated_at": previous.get("generated_at"),
        HMAC_FIELD: previous.get(HMAC_FIELD),
        "schema_version": previous.get("schema_version"),
    }


def write_manifest(
    out: Path,
    *,
    corpus: RawCorpus,
    summary: BuildSummary,
    key: SecretKey,
    spec: BuildSpec,
    risk: dict[str, object] | None = None,
    permit_reference: str | None = None,
    root_fingerprint: str | None = None,
    predecessor: dict[str, object] | None = None,
) -> dict[str, object]:
    """Write ``.deident/manifest.json`` and return what it contains.

    Args:
        out: Dataset root.
        corpus: The corpus that was built from.
        summary: What the build produced.
        key: The secret, used only for its fingerprint. When the build is
            permit-scoped this is the subkey, so the fingerprint recorded is the
            one that identifies this permit's label space.
        spec: What the data holder supplied.
        risk: The risk report this build computed, so the manifest can describe
            it instead of asserting about it. ``None`` means no report was
            produced, which the manifest says in those words.
        permit_reference: The data permit this build answers, or ``None`` for an
            unscoped build -- which the manifest states, because D7.2 forbids
            reusing pseudonyms across permits and an unscoped build does.
        root_fingerprint: The root key's fingerprint when ``key`` is a subkey.
        predecessor: The identity of the manifest this one replaces, from
            :func:`predecessor_of`.

    Returns:
        The manifest payload.
    """
    body = _body_payload(summary.scrub_reports)
    payload: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "schema_note": (
            "This manifest records de-identification provenance. No published "
            "standard covers it: HealthDCAT-AP describes a dataset for a catalogue "
            "and carries no properties for what was done to de-identify it. The "
            "schema is therefore this project's own, and is versioned separately."
        ),
        "deidentification_rule_version": tool_versions()["deidentification_rules"],
        "key_fingerprint": key.fingerprint,
        "key_note": (
            "A digest identifying which secret key produced the pseudonyms in this "
            "dataset, without carrying the key. Two datasets sharing a fingerprint "
            "are relinkable; a dataset whose key is lost is permanently orphaned."
        ),
        "tool_versions": tool_versions(),
        "generated_at": utc_now().isoformat(),
        # The function, its inputs and its policy, which a reader of this file
        # alone could not reconstruct before: they were in a module docstring.
        # D7.2 section 4.4 (p. 40) asks a controller generating cryptographic
        # pseudonyms to save exactly this, and section 4.3 (p. 38) has the
        # access body approve the algorithm -- which it cannot do from a
        # fingerprint and a rule version.
        "pseudonymisation": declare(
            key, permit_reference=permit_reference, root_fingerprint=root_fingerprint
        ),
        # Beside pseudonymisation because it is the other half of the same
        # question: pseudonymisation replaces an identifier with something
        # unlinkable, generalisation keeps a value and makes it coarser. D7.2
        # treats both as data minimisation and asks a holder to publish which
        # rules were applied by default.
        "generalisation": _generalisation_section(summary),
        # What this manifest replaced, so a chain of rebuilds is followable.
        # `None` is written rather than omitted: a reader must be able to tell a
        # first build from one whose predecessor went unrecorded.
        "predecessor": predecessor,
        "predecessor_note": (
            "The manifest this one replaced, identified by its timestamp and its "
            "authentication tag. Its counts are deliberately not carried: they "
            "describe data this dataset may no longer contain. `null` means this "
            "build published into an empty destination."
        ),
        "source": {
            # The directory's name, not its path. An absolute path carries the
            # operator's account name and local layout -- "C:\\Users\\<someone>\\..."
            # -- into a document written to be sent to a Health Data Access
            # Body. That is information about a person which nobody decided to
            # publish, in the one file whose purpose is to be read by outsiders.
            # The name is what a human chose and is the part with provenance
            # value; the rest was an accident of where the command was run.
            # Found by `commissura measure`, which flagged a generated clinician
            # called JONATHAN as surviving into the dataset and turned out to be
            # pointing at the username in this field.
            "root_name": corpus.root.name,
            "subjects_linked": len(corpus.subjects),
            # Which kind of identifier established each subject. A subject keyed
            # on a national identifier is relinkable to another institution's
            # export under the same key; one keyed on an institution's own
            # record number is not, and nothing else in this document would tell
            # a reader which subjects those are.
            "subject_keys": _subject_key_counts(corpus),
            "records_linked": corpus.record_count,
            # Counted by reason, and **without the file paths**. An export names
            # its files after the thing they are about, so `lab/6895111_LAB...`
            # carries a medical record number in its name, and a list of paths
            # is a list of patient identifiers inside the document written to be
            # sent to an access body.
            #
            # This list has had that shape since linkage issues were first
            # recorded. It never fired, because every corpus tested had zero of
            # them, so the leak sat latent until `records_dropped` gave it a
            # non-empty case and `commissura measure` reported the identifiers
            # the next morning.
            #
            # Two audiences, and only one of them needs the paths. An auditor
            # needs to know how many records are absent and why, which is here.
            # The operator needs to know *which* files to go and fix, and gets
            # them from `build`'s own output, which stays on their terminal.
            "linkage_issues": _by_reason(issue.reason for issue in corpus.issues),
            # The other half of "what did I hand over that is not here". A
            # linkage issue is a record that could not be attached to anybody;
            # a dropped record was attached and then had nowhere to go, because
            # sessions are dated encounters and it carried no readable date.
            # Separate from the list above, because the two need different fixes
            # and a shared name would misdescribe one of them.
            "records_dropped": _by_reason(record.reason for record in summary.dropped),
            # Only the reasons that mean the record is *absent*. A reason that
            # attaches the record and flags it belongs in the field below, and
            # conflating the two made this number overstate by exactly the
            # number of flagged records -- 32 claimed where 3 were absent, on
            # the first corpus that produced a conflict at all.
            "records_not_in_dataset": _absent_record_count(corpus, summary),
            "records_flagged_in_dataset": _flagged_record_count(corpus, summary),
            "records_not_in_dataset_note": (
                "Reasons and counts only. Neither the file paths nor the detail "
                "sentences are recorded: an export names its files after the "
                "record they hold, and a detail is built from the input, so an "
                "unlinked report's detail named a codice fiscale and a record "
                "number. This document is written to be read by an access body. "
                "`commissura build` prints both for the operator instead. "
                "`records_not_in_dataset` counts records that are not here, in "
                "three parts: the linkage issues whose reason refused the "
                "record, `records_dropped`, and `opt_out.records_excluded`. "
                "`records_flagged_in_dataset` counts records that are here and "
                "carry a linkage issue anyway, which is a different fact and was "
                "being added to the first one. A flagged record whose subject "
                "opted out is not here, so it is counted above and not there; "
                "`linkage_issues` is a log of what reading the corpus found and "
                "counts it either way."
            ),
            # Whether anybody was deliberately left out, and stated even when
            # nobody was. Without it a dataset built after an objection is
            # indistinguishable from one built before it, which is the whole of
            # what D6.1 A6.2 asks a holder to be able to show.
            "opt_out": _opt_out_section(summary),
        },
        "output": {
            "subjects": summary.subject_count,
            "sessions": summary.session_count,
            "lab_files": summary.lab_files,
            "report_files": summary.report_files,
            "imaging_metadata_files": summary.imaging_files,
        },
        "modalities_note": (
            "Derived from this run, not declared. Every field the input actually "
            "carried is listed with the number of files that held it, so a field "
            "nobody anticipated is reported as removed rather than going "
            "unmentioned. The build carries a whitelist: a field absent from the "
            "output is absent because nothing copies it, which is why removal does "
            "not have to be enumerated in advance. A report's prose body is not a "
            "field, so the reports modality carries a second table, 'body', "
            "counting what the scrubber substituted inside it."
        ),
        "modalities": [
            _ledger_payload(
                ledger,
                body=body if ledger.modality == "reports" else None,
                age_band=summary.age_band,
            )
            for ledger in observe_corpus(corpus.root)
        ],
        "residual_risk": {
            "note": (
                "What the method cannot reach, listed rather than scored. A score "
                "invites a reader to treat de-identification as solved above some "
                "threshold; a list tells them where to look."
            ),
            "observed": list(summary.residual_risks()),
            "structural": _structural_risks(out, summary, risk),
        },
        "profile": {
            "name": "HealthDCAT-AP",
            "release": healthdcat.RELEASE,
            "tier": spec.tier.value,
            "access_rights": healthdcat.TIER_ACCESS_RIGHT[spec.tier],
            "mandatory_properties_unsatisfied": list(summary.missing_for_conformance),
        },
    }

    path = out / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    path.parent.mkdir(parents=True, exist_ok=True)

    # Last, and after every other file is on disk, because this covers them all.
    # The manifest is excluded from its own list: a digest cannot cover the bytes
    # that hold it. `manifest_hmac` closes that gap for whoever has the key.
    payload["integrity"] = {
        "algorithm": DIGEST_ALGORITHM,
        "note": (
            "A digest per file produced by this build, so a dataset can be shown "
            "to be the one this manifest describes. The manifest itself is not in "
            "the list, because a digest cannot cover the bytes holding it; "
            f"{HMAC_FIELD} authenticates the manifest's own content and checking "
            "it requires the key. Without the key, these digests detect an "
            "altered, missing or added file, which is what happens by accident. "
            "They do not detect an edit made deliberately, because whoever can "
            "change a report can change this list beside it."
        ),
        "files": digest_tree(out, exclude=frozenset({path.relative_to(out).as_posix()})),
    }
    payload[HMAC_FIELD] = tag_manifest(payload, key)

    _write(path, payload)
    return payload


def _non_negative(value: int) -> dict[str, str]:
    """Render a count as an ``xsd:nonNegativeInteger`` literal.

    A bare JSON number becomes ``xsd:integer`` in JSON-LD, and the shapes ask
    for ``xsd:nonNegativeInteger`` specifically. The two are different datatypes
    and a SHACL engine does not treat one as the other.
    """
    return {"@value": str(value), "@type": "xsd:nonNegativeInteger"}


def _typical_age_range(out: Path) -> dict[str, object]:
    """Return ``minTypicalAge`` and ``maxTypicalAge``, read off the dataset.

    Two recommended profile properties, derived rather than asked for, and the
    reason they are worth emitting is in D7.2 section 3.1 (p. 18): a holder
    should "specify any standard data minimisation rules that are applicable by
    default to the datasets offered", the worked example being that a birth date
    is normally available only as a year. Section 3.3.1 (p. 22) then treats age
    as a quasi-identifier that should be exact only when indispensable. An
    applicant deciding whether they need exact ages has to know the range first,
    and this is the one place a catalogue reader can learn it without row access.

    Both carry ``xsd:nonNegativeInteger``, which the profile's own value
    constraints require and which needs no IRI -- unlike ``dpv:hasPersonalData``,
    which D7.2 also asks for and whose vocabulary the Release 8 shapes do not
    constrain at all. Writing a plausible concept IRI there is the trap this
    project recorded when it found one authority list served over https and
    another over http, so that property is left to the reading job in
    ``docs/TEHDAS2_REMEDIATION_PLAN.md`` rather than guessed at.

    Ages above the ceiling are carried as ``90+`` and are not integers, so a
    cohort of nothing but those yields no range and the properties are omitted.
    Omitted rather than reported as zero: both are recommended, and a
    ``maxTypicalAge`` of 0 would be a false statement where absence is merely
    silence. That is the opposite of the convention the per-field table follows,
    and the difference is that the table's readers need to know a declared field
    was absent, while a catalogue reader needs no claim at all.

    Args:
        out: Dataset root, which already holds ``participants.tsv`` by the time
            the description is written.

    Returns:
        Zero or two properties, ready to merge into the dataset node.
    """
    bounds = [
        pair
        for value in DatasetContext(out).participants.column("age")
        # `90+` above the ceiling, or `n/a`. Neither states a number and
        # neither is an error. A band states two, and reading only the first
        # would understate the maximum by almost a whole band.
        if (pair := layout.age_bounds(value)) is not None
    ]
    if not bounds:
        return {}
    return {
        "healthdcatap:minTypicalAge": _non_negative(min(low for low, _ in bounds)),
        "healthdcatap:maxTypicalAge": _non_negative(max(high for _, high in bounds)),
    }


def _typed(iri: str, rdf_type: str | tuple[str, ...], label: str = "") -> dict[str, object]:
    """Reference an authority-list IRI as a node that carries its own class.

    ``sh:class`` is satisfied by an ``rdf:type`` triple **in the data graph**: a
    validator does not dereference the authority list to discover that
    ``.../access-right/NON_PUBLIC`` is a ``dct:RightsStatement``. So a bare
    ``{"@id": ...}`` reference fails every class range, and the IRI being correct
    makes no difference. Six properties here learned that the same way.

    Args:
        iri: The concept or resource IRI.
        rdf_type: The prefixed class the shapes require of it, or several where
            the vocabulary itself declares the concept an instance of more than
            one. Several is not hedging: ``dpv:hasPersonalData`` needs
            ``dpv:PersonalData`` for the range and carries
            ``dpv:SpecialCategoryPersonalData`` because DPV's own file says so
            and because that is the half an access body reads.
        label: The authority list's own label, for a ``skos:Concept``. Restated
            verbatim rather than invented, and omitted for the classes that are
            not concepts and so owe no label.

    Returns:
        The JSON-LD node.
    """
    node: dict[str, object] = {
        "@id": iri,
        "@type": rdf_type if isinstance(rdf_type, str) else list(rdf_type),
    }
    if label:
        node["skos:prefLabel"] = label
    return node


def write_healthdcat_description(
    out: Path,
    *,
    spec: BuildSpec,
    summary: BuildSummary,
    dataset_name: str | None = None,
) -> dict[str, object]:
    """Write ``healthdcat-ap.jsonld`` and return what it contains.

    Emitted as JSON-LD with an inline context built from the profile's own
    prefix declarations, so the terms expand to the IRIs the SHACL shapes expect.
    The health namespace is provisional by the profile's own admission, which is
    why the context is assembled from :data:`commissura.healthdcat.NAMESPACES`
    rather than written out here.

    Args:
        out: Dataset root.
        spec: What the data holder supplied.
        summary: Used for the record and participant counts.
        dataset_name: The name of the directory the dataset will be published
            to, which ``dct:identifier`` is derived from. Needed because builds
            are staged, so the directory being written to is not the one the
            dataset ends up in. Defaults to ``summary.root.name``.

    Returns:
        The JSON-LD payload.
    """
    node: dict[str, object] = {
        "@type": "dcat:Dataset",
        "dct:title": spec.dataset_name,
        "dct:description": spec.description,
        "dct:accessRights": _typed(healthdcat.TIER_ACCESS_RIGHT[spec.tier], "dct:RightsStatement"),
        # The *published* directory's name, which is not the directory being
        # written to: builds are staged, so `summary.root` here is
        # `<name>.commissura-staging-<pid>`. Deriving the identifier from it
        # would put a process id into the dataset's own name and make two runs
        # of the same corpus differ in exactly one file -- which is the trap the
        # cross-platform reproducibility job was built to catch, and did.
        "dct:identifier": spec.identifier or f"urn:commissura:{dataset_name or summary.root.name}",
        # Mandatory at 1..*, and a dataset on a hospital disk still needs one:
        # the profile assumes the data is distributable, so a description has to
        # say in what form it would be. The Distribution shape requires its own
        # applicable legislation, which is why that is repeated here.
        "dcat:distribution": [
            {
                "@type": "dcat:Distribution",
                "dct:title": "Tabular laboratory results and clinical report text",
                "dct:description": (
                    "BIDS-shaped directory tree. Laboratory results as tab-separated "
                    "values with JSON sidecars; reports as UTF-8 text with JSON "
                    "sidecars; imaging metadata under derivatives/."
                ),
                "dct:format": _typed(
                    "http://publications.europa.eu/resource/authority/file-type/TSV",
                    "dct:MediaTypeOrExtent",
                ),
                "dct:accessRights": _typed(
                    healthdcat.TIER_ACCESS_RIGHT[spec.tier], "dct:RightsStatement"
                ),
                "dcatap:applicableLegislation": [
                    _typed(iri, "eli:LegalResource") for iri in spec.applicable_legislation
                ],
                **({"dcat:accessURL": {"@id": spec.access_url}} if spec.access_url else {}),
            }
        ],
        "dcat:theme": [
            _typed(
                healthdcat.data_theme_iri(healthdcat.DATA_THEME_FOR_HEALTH),
                "skos:Concept",
                healthdcat.DATA_THEMES[healthdcat.DATA_THEME_FOR_HEALTH],
            )
        ],
        "dcatap:applicableLegislation": [
            _typed(iri, "eli:LegalResource") for iri in spec.applicable_legislation
        ],
        "healthdcatap:healthCategory": [
            _typed(
                healthdcat.health_category_iri(code),
                "skos:Concept",
                healthdcat.HEALTH_CATEGORIES[code],
            )
            for code in spec.health_categories
        ],
        # Recommended rather than mandatory, and emitted because the range is
        # sourced and the value is derivable: everything this tool builds is
        # personal data about health, which is what `healthdcat.
        # PERSONAL_DATA_CATEGORY` names and why it is a constant rather than a
        # flag -- the same reasoning as `healthCategory` being EHRS.
        "dpv:hasPersonalData": _typed(
            healthdcat.PERSONAL_DATA_CATEGORY,
            healthdcat.PERSONAL_DATA_CATEGORY_TYPES,
            healthdcat.PERSONAL_DATA_CATEGORY_LABEL,
        ),
        "healthdcatap:hasStructuredData": True,
        "healthdcatap:numberOfUniqueIndividuals": _non_negative(summary.subject_count),
        "healthdcatap:numberOfRecords": _non_negative(summary.file_count),
        **_typical_age_range(out),
        "dcat:keyword": _keywords(spec, summary),
        "dct:type": _typed(
            healthdcat.dataset_type_iri(spec.dataset_type),
            "skos:Concept",
            healthdcat.DATASET_TYPES[spec.dataset_type],
        ),
        # Provenance is a statement the tool can make for itself, and the
        # non-public tier requires one. It says how the dataset came to exist,
        # which is exactly what a reader of an Article 77 description wants.
        "dct:provenance": {
            "@type": "dct:ProvenanceStatement",
            "rdfs:label": (
                "De-identified from a raw clinical corpus by commissura, "
                f"de-identification rules {tool_versions()['deidentification_rules']}. "
                "Dates are expressed only as day_offset from each subject's own "
                "earliest recorded event; no absolute date is carried."
            ),
        },
        "healthdcatap:hasVariables": [_csvw_table_group()],
    }

    if spec.contact_point:
        # vcard:Kind here, cv:ContactPoint on the agents below, and the
        # difference is not ours to tidy away. DCAT-AP's range.ttl constrains
        # dcat:contactPoint to vcard:Kind; the HealthDCAT-AP shapes constrain an
        # agent's cv:contactPoint to cv:ContactPoint. Two profiles, two contact
        # models, each used where its own shapes ask for it. Picking one and
        # using it everywhere is the tempting move and fails half the shapes.
        node["dcat:contactPoint"] = {
            "@type": "vcard:Kind",
            "vcard:hasEmail": {"@id": f"mailto:{spec.contact_point}"},
        }
    # Both agent shapes require exactly one cv:contactPoint, which the
    # cardinality table does not mention and only the shapes reveal.
    contact = (
        {"@type": "cv:ContactPoint", "cv:email": spec.contact_point} if spec.contact_point else None
    )
    if spec.hdab:
        node["healthdcatap:hdab"] = {
            "@type": "foaf:Agent",
            "foaf:name": spec.hdab,
            **({"cv:contactPoint": contact} if contact else {}),
        }
    if spec.publisher:
        node["dct:publisher"] = {
            "@type": "foaf:Agent",
            "foaf:name": spec.publisher,
            **({"cv:contactPoint": contact} if contact else {}),
        }

    payload: dict[str, object] = {
        "@context": dict(healthdcat.NAMESPACES),
        "@graph": [node],
        "commissura:profileNote": (
            "The imported DCAT-AP 3.0.0 shapes have not been read, so the "
            "Distribution node carries only what the HealthDCAT-AP shapes "
            "constrain. Validate against the profile's own validator before "
            "claiming conformance. "
            f"Emitted against HealthDCAT-AP Release {healthdcat.RELEASE}, "
            f"{spec.tier.value} tier. Mandatory properties still unsatisfied: "
            + (", ".join(summary.missing_for_conformance) or "none")
        ),
    }

    _write(out / layout.HEALTHDCAT_DESCRIPTION, payload)
    return payload


def _keywords(spec: BuildSpec, summary: BuildSummary) -> list[str]:
    """Return the catalogue keywords, derived unless the holder supplied them.

    `dcat:keyword` is mandatory at 1..* in the non-public tier, so there is
    always at least one: `clinical`, which is true of anything this tool
    builds.

    **Everything else is a claim about this dataset and is derived from it.**
    The fixed list this replaces said `laboratory`, `imaging` and `synthetic`
    whatever the build produced, which made two false statements reachable at
    once: a corpus with no imaging study was catalogued as imaging, and a
    holder who correctly declared `--dataset-type TEST_DATA` still had
    `synthetic` in the keywords of the same record. A catalogue record that
    contradicts itself is worse than one that says less.

    `synthetic` is tied to the declared dataset type rather than asserted,
    because those two properties state the same fact and a reader should not
    have to decide which to believe.

    Args:
        spec: What the holder supplied.
        summary: What the build produced.

    Returns:
        The holder's keywords if they gave any, otherwise the derived ones.
    """
    if spec.keywords:
        return list(spec.keywords)

    derived = ["clinical"]
    if summary.lab_files:
        derived.append("laboratory")
    if summary.report_files:
        derived.append("reports")
    if summary.imaging_files:
        derived.append("imaging")
    if spec.dataset_type == healthdcat.DATASET_TYPE_FOR_SYNTHETIC:
        derived.append("synthetic")
    return derived


def _csvw_table_group() -> dict[str, object]:
    """Describe the lab table's columns as a CSVW table group.

    ``healthdcatap:hasVariables`` resolves to a CSVW table group, and a dataset
    declaring structured data must carry at least one. The columns are the lab
    table's own, which is the one place where this profile and the dataset
    layout line up without extra work.
    """
    descriptions = {
        "day_offset": "Whole days from the subject's own earliest recorded event.",
        "loinc_code": "LOINC code identifying the analyte.",
        "value": "Measured value as the laboratory reported it.",
        "unit": "Unit of measure.",
        "display": "Human-readable analyte name.",
        "reference_low": "Lower bound of the reference interval.",
        "reference_high": "Upper bound of the reference interval.",
        "abnormal_flag": "HL7 table 0078 interpretation code.",
        "panel_code": "Code of the panel the result belongs to.",
    }
    # `day_offset` alone, and the two that left are the finding. The reference
    # bounds were declared `integer` while the column holds `0.30`, `1.10` and
    # `17.0` -- a datatype a catalogue consumer would parse by and fail on the
    # first row, in a document the SHACL check calls conformant because
    # `integer` is a valid CSVW built-in name. `decimal` would be wrong too:
    # `_split_reference_range` writes `n/a` for a one-sided or unparseable
    # interval, so the column's domain includes a non-numeric sentinel and no
    # numeric type describes it. `value` was already `string` for the same
    # reason. `day_offset` is genuinely always an integer, because a record with
    # no readable date is dropped rather than written with a blank offset.
    numeric = {"day_offset"}
    columns = [
        {
            "@type": "csvw:Column",
            "csvw:name": name,
            "csvw:title": name.replace("_", " "),
            "dct:description": descriptions[name],
            "csvw:datatype": "integer" if name in numeric else "string",
        }
        for name in (*layout.LAB_REQUIRED_COLUMNS, *layout.LAB_RECOMMENDED_COLUMNS)
    ]
    return {
        "@type": "csvw:TableGroup",
        "dct:title": "Laboratory results",
        "csvw:table": [
            {
                "@type": "csvw:Table",
                "dct:title": "Laboratory results",
                "csvw:column": columns,
            }
        ],
    }


def _write(path: Path, payload: object) -> None:
    """Write JSON with no newline translation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="",
    )
