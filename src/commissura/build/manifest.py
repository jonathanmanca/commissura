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
from collections.abc import Sequence
from pathlib import Path

from commissura import healthdcat, layout
from commissura.build.integrity import (
    DIGEST_ALGORITHM,
    HMAC_FIELD,
    digest_tree,
    tag_manifest,
)
from commissura.build.observe import ModalityLedger, observe_corpus
from commissura.build.scrub import CATEGORY_DISPOSITION, ScrubReport
from commissura.build.writer import BuildSpec, BuildSummary, tool_versions, utc_now
from commissura.deident.keys import SecretKey
from commissura.read.corpus import RawCorpus

MANIFEST_SCHEMA_VERSION = "2.0.0"
"""Version of the manifest format defined here.

Separate from the layout schema version, because the manifest will change on a
different clock from the dataset layout.

**2.0.0 is a breaking change and the major number is doing real work.**
``modalities`` was an object keyed by modality name whose values were three
lists of prose; it is now an array of observed ledgers. ``free_text_redactions``
was a top-level map of category to a count; it is now the ``body`` table inside
the reports ledger. Anything that read 1.0.0 will not read this.

Recorded with some embarrassment: the first of those two changes shipped without
this number moving. A schema version exists so a consumer can tell, and leaving
it at 1.0.0 while reshaping the document told them the opposite of the truth.
"""


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
    ledger: ModalityLedger, *, body: list[dict[str, object]] | None = None
) -> dict[str, object]:
    """Render one modality's observed field ledger for the manifest.

    Args:
        ledger: What was observed in that modality's input.
        body: For the one modality with prose, what the scrubber substituted
            inside it. Omitted for the others, which have no body.

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
        "unreadable": list(ledger.unreadable),
        "fields_observed": {
            disposition: ledger.count(disposition)
            for disposition in ("removed", "replaced", "kept")
        },
        "fields": [
            {
                "field": item.key,
                **({"name": item.name} if item.name else {}),
                "disposition": item.disposition,
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


def write_manifest(
    out: Path,
    *,
    corpus: RawCorpus,
    summary: BuildSummary,
    key: SecretKey,
    spec: BuildSpec,
) -> dict[str, object]:
    """Write ``.deident/manifest.json`` and return what it contains.

    Args:
        out: Dataset root.
        corpus: The corpus that was built from.
        summary: What the build produced.
        key: The secret, used only for its fingerprint.
        spec: What the data holder supplied.

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
        "source": {
            "root": str(corpus.root),
            "subjects_linked": len(corpus.subjects),
            "records_linked": corpus.record_count,
            "linkage_issues": [
                {"path": issue.path, "reason": issue.reason, "detail": issue.detail}
                for issue in corpus.issues
            ],
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
            _ledger_payload(ledger, body=body if ledger.modality == "reports" else None)
            for ledger in observe_corpus(corpus.root)
        ],
        "residual_risk": {
            "note": (
                "What the method cannot reach, listed rather than scored. A score "
                "invites a reader to treat de-identification as solved above some "
                "threshold; a list tells them where to look."
            ),
            "observed": list(summary.residual_risks()),
            "structural": [
                "Pixel data is not inspected. Where BurnedInAnnotation is YES, "
                "identifiers may be rendered into the image itself.",
                "Head imaging is not defaced, so the skull surface remains "
                "re-identifiable by facial reconstruction.",
                "Free-text redaction matches identifiers declared in structured "
                "fields. A person named only in prose is not found.",
                "Quasi-identifier combinations are not assessed; no k-anonymity "
                "report has been produced for this dataset.",
            ],
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


def _typed(iri: str, rdf_type: str, label: str = "") -> dict[str, object]:
    """Reference an authority-list IRI as a node that carries its own class.

    ``sh:class`` is satisfied by an ``rdf:type`` triple **in the data graph**: a
    validator does not dereference the authority list to discover that
    ``.../access-right/NON_PUBLIC`` is a ``dct:RightsStatement``. So a bare
    ``{"@id": ...}`` reference fails every class range, and the IRI being correct
    makes no difference. Six properties here learned that the same way.

    Args:
        iri: The concept or resource IRI.
        rdf_type: The prefixed class the shapes require of it.
        label: The authority list's own label, for a ``skos:Concept``. Restated
            verbatim rather than invented, and omitted for the classes that are
            not concepts and so owe no label.

    Returns:
        The JSON-LD node.
    """
    node: dict[str, object] = {"@id": iri, "@type": rdf_type}
    if label:
        node["skos:prefLabel"] = label
    return node


def write_healthdcat_description(
    out: Path, *, spec: BuildSpec, summary: BuildSummary
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

    Returns:
        The JSON-LD payload.
    """
    node: dict[str, object] = {
        "@type": "dcat:Dataset",
        "dct:title": spec.dataset_name,
        "dct:description": spec.description,
        "dct:accessRights": _typed(healthdcat.TIER_ACCESS_RIGHT[spec.tier], "dct:RightsStatement"),
        "dct:identifier": f"urn:commissura:{summary.root.name}",
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
        "healthdcatap:hasStructuredData": True,
        "healthdcatap:numberOfUniqueIndividuals": _non_negative(summary.subject_count),
        "healthdcatap:numberOfRecords": _non_negative(summary.file_count),
        "dcat:keyword": list(spec.keywords),
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
    numeric = {"day_offset", "reference_low", "reference_high"}
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
