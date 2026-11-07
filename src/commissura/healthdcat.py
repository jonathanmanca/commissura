"""The HealthDCAT-AP obligation table, transcribed from the profile's own source.

This module holds no logic and no judgement. It is a transcription of
``context/healthdcat-cardinality-rules.json`` from HealthDCAT-AP Release 8, read
from the profile's source repository on the Commission's GitLab. Fifty-seven
properties, each with a cardinality and an obligation, for each of three tiers.

**Why transcribe rather than parse the file at runtime.** Parsing would make
`commissura` depend on a network fetch or a vendored copy of someone else's
file, and on that file's shape staying put. Transcribing makes the dependency a
reviewable diff: when Release 9 lands, the change shows up here as lines added
and removed, with a test that fails if the counts no longer match. The cost is
that the transcription can drift, which :data:`SOURCE_URL` and the counts in the
tests exist to catch.

**The three tiers are three different claims.** HealthDCAT-AP ships separate
SHACL shapes for ``PUBLIC``, ``NON-PUBLIC`` and ``RESTRICTED`` data, and the
obligations genuinely differ: a non-public dataset must carry a contact point,
keywords, provenance and a type, where a public one need not. So "conformant to
HealthDCAT-AP" is not one statement, and anything claiming conformance has to
say which tier it means.

**What this profile is and is not.** These 57 properties describe a dataset for
a *catalogue*: who published it, what it covers, under what access conditions,
which legal basis, how long it is retained. That is EHDS Article 77. It is not
an audit record of what was done to de-identify the data — nothing here records
which fields were removed from which modality, or which key produced the
pseudonyms. Those are two different artefacts for two different readers, and
`commissura` keeps them apart.

Fidelity notes, so the transcription can be checked against the source:

- Obligations are normalised to three values. The source spells one of them
  ``RecommendEd`` (``conforms to``, RESTRICTED tier); that is a typo in the
  source, read as ``Recommended``.
- Cardinalities are normalised to ``(minimum, maximum)``. The source writes the
  unbounded maximum as ``*`` in all but two places, where it writes ``n``
  (``quality annotation`` and ``related resource``, RESTRICTED tier); read as
  equivalent.
- One property, ``in series``, carries no RDF term in the source's usage note.
  It is recorded here with ``term=None`` rather than filled in from DCAT, so the
  gap stays visible.
- The source labels each property with a ``reuse`` code of ``A``, ``E`` or
  ``P``. The file defines none of them, so they are not transcribed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

RELEASE: Final = "8"
"""The HealthDCAT-AP release this table transcribes.

Pinned deliberately. The repository also carries releases 5, 6 and 7, and the
profile's rendered site still serves 5 as "latest"; 8 is chosen because it ships
a packaged SHACL validator, so conformance can be checked against the profile's
own tool rather than against our reading of it.
"""

SOURCE_URL: Final = (
    "https://code.europa.eu/api/v4/projects/healthdataeu%2Fhealthdcat-ap"
    "/repository/files/public%2Freleases%2Frelease-8%2Fcontext"
    "%2Fhealthdcat-cardinality-rules.json/raw?ref=main"
)
"""Where this table came from, so it can be re-checked without a search."""

SHAPES_PATHS: Final = (
    "public/releases/release-8/html/shacl/HealthDCAT-AP_validator/config"
    "/rdf-validator/ehds/shapes/public-shapes.ttl",
    "public/releases/release-8/html/shacl/HealthDCAT-AP_validator/config"
    "/rdf-validator/ehds/shapes/non-public-shapes.ttl",
    "public/releases/release-8/html/shacl/HealthDCAT-AP_validator/config"
    "/rdf-validator/ehds/shapes/restricted-shapes.ttl",
)
"""Repository paths of the SHACL shapes, one per tier.

Recorded so that the eventual conformance check has somewhere to start. The
shapes are the profile in executable form and outrank this table wherever the
two disagree.
"""


class Tier(StrEnum):
    """Which HealthDCAT-AP shape set applies.

    The profile ships one set of SHACL shapes per tier, and the obligations
    differ between them, so a dataset description has to declare its tier for
    the claim of conformance to mean anything.
    """

    PUBLIC = "public"
    NON_PUBLIC = "non-public"
    RESTRICTED = "restricted"


class Obligation(StrEnum):
    """How strongly the profile requires a property."""

    MANDATORY = "mandatory"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class Cardinality:
    """How many values a property may carry.

    Attributes:
        minimum: Fewest permitted occurrences.
        maximum: Most permitted occurrences, or ``None`` when unbounded.
    """

    minimum: int
    maximum: int | None

    def __str__(self) -> str:
        """Return the profile's own notation, such as ``1..*``."""
        return f"{self.minimum}..{'*' if self.maximum is None else self.maximum}"


@dataclass(frozen=True, slots=True)
class PropertyRule:
    """One property's obligation and cardinality within one tier."""

    obligation: Obligation
    cardinality: Cardinality

    @property
    def is_required(self) -> bool:
        """Return whether omitting the property breaks conformance."""
        return self.obligation is Obligation.MANDATORY


@dataclass(frozen=True, slots=True)
class ProfileProperty:
    """One property of the profile, across all three tiers.

    Attributes:
        label: The profile's own plain-language label, used as the key in the
            source file.
        term: The RDF term, such as ``dct:title``. ``None`` where the source
            gives none.
        public: The rule in the public tier.
        non_public: The rule in the non-public tier.
        restricted: The rule in the restricted tier.
    """

    label: str
    term: str | None
    public: PropertyRule
    non_public: PropertyRule
    restricted: PropertyRule

    def rule_for(self, tier: Tier) -> PropertyRule:
        """Return the rule that applies in ``tier``."""
        if tier is Tier.PUBLIC:
            return self.public
        if tier is Tier.NON_PUBLIC:
            return self.non_public
        return self.restricted


_CARDINALITIES: Final = {
    "1..1": Cardinality(1, 1),
    "1..*": Cardinality(1, None),
    "0..1": Cardinality(0, 1),
    "0..*": Cardinality(0, None),
}

_OBLIGATIONS: Final = {
    "M": Obligation.MANDATORY,
    "R": Obligation.RECOMMENDED,
    "O": Obligation.OPTIONAL,
}


def _rule(spec: str) -> PropertyRule:
    """Build a rule from a compact ``"<cardinality> <obligation>"`` spec."""
    cardinality, obligation = spec.split()
    return PropertyRule(
        obligation=_OBLIGATIONS[obligation], cardinality=_CARDINALITIES[cardinality]
    )


def _same(label: str, term: str | None, spec: str) -> ProfileProperty:
    """Build a property whose rule is identical in all three tiers."""
    rule = _rule(spec)
    return ProfileProperty(label=label, term=term, public=rule, non_public=rule, restricted=rule)


def _varies(
    label: str, term: str | None, public: str, non_public: str, restricted: str
) -> ProfileProperty:
    """Build a property whose rule differs between tiers."""
    return ProfileProperty(
        label=label,
        term=term,
        public=_rule(public),
        non_public=_rule(non_public),
        restricted=_rule(restricted),
    )


PROPERTIES: Final[tuple[ProfileProperty, ...]] = (
    _same("access rights", "dct:accessRights", "1..1 M"),
    _same("alternative", "dct:alternative", "0..* O"),
    _same("analytics", "healthdcatap:analytics", "0..* R"),
    _same("applicable legislation", "dcatap:applicableLegislation", "1..* M"),
    _same("code values", "healthdcatap:hasCodeValues", "0..* R"),
    _same("coding system", "healthdcatap:hasCodingSystem", "0..* R"),
    _varies("conforms to", "dct:conformsTo", "0..* O", "0..* O", "0..* R"),
    _varies("contact point", "dcat:contactPoint", "0..* R", "1..* M", "0..* R"),
    _same("creator", "dct:creator", "0..* O"),
    _same("custodian", "geodcatap:custodian", "0..1 R"),
    _same("description", "dct:description", "1..* M"),
    _same("dataset distribution", "dcat:distribution", "1..* M"),
    _varies("documentation", "foaf:page", "0..* O", "0..* R", "0..* O"),
    _varies("frequency", "dct:accrualPeriodicity", "0..1 O", "0..1 R", "0..1 O"),
    _same("geographical coverage", "dct:spatial", "0..* O"),
    _same("has version", "dcat:hasVersion", "0..* O"),
    _same("health category", "healthdcatap:healthCategory", "1..* M"),
    _same("structured data", "healthdcatap:hasStructuredData", "1..1 M"),
    _same("variables", "healthdcatap:hasVariables", "0..* R"),
    _same("health theme", "healthdcatap:healthTheme", "0..* R"),
    _same("identifier", "dct:identifier", "1..* M"),
    # The source gives no RDF term for this one; left blank rather than guessed.
    _same("in series", None, "0..* O"),
    _varies("is referenced by", "dct:isReferencedBy", "0..* O", "0..* R", "0..* O"),
    _varies("keyword", "dcat:keyword", "0..* R", "1..* M", "0..* R"),
    _varies("language", "dct:language", "0..* O", "0..* R", "0..* O"),
    _same("legal basis", "dpv:hasLegalBasis", "0..* R"),
    _same("modification date", "dct:modified", "0..1 O"),
    _same("number of records", "healthdcatap:numberOfRecords", "0..1 R"),
    _same("number of unique individuals", "healthdcatap:numberOfUniqueIndividuals", "0..1 R"),
    _same("other identifier", "adms:identifier", "0..* O"),
    _same("personal data", "dpv:hasPersonalData", "0..* R"),
    _same("population coverage", "healthdcatap:populationCoverage", "0..* R"),
    _varies("provenance", "dct:provenance", "0..* O", "1..* M", "0..* O"),
    _same("publisher", "dct:publisher", "0..1 R"),
    _same("purpose", "dpv:hasPurpose", "0..* R"),
    _same("qualified attribution", "prov:qualifiedAttribution", "0..* O"),
    _same("qualified relation", "dcat:qualifiedRelation", "0..* O"),
    _same("quality annotation", "dqv:hasQualityAnnotation", "0..* R"),
    _same("release date", "dct:issued", "0..1 O"),
    _varies("related resource", "dct:relation", "0..* O", "0..* R", "0..* O"),
    _same("retention period", "healthdcatap:retentionPeriod", "0..1 R"),
    _same("sample", "adms:sample", "0..* R"),
    _varies("source", "dct:source", "0..* O", "0..* R", "0..* O"),
    _varies("temporal coverage", "dct:temporal", "0..* O", "0..* R", "0..* O"),
    _varies("temporal resolution", "dcat:temporalResolution", "0..1 O", "0..1 R", "0..1 O"),
    _same("theme", "dcat:theme", "1..* M"),
    _same("title", "dct:title", "1..* M"),
    _varies("type", "dct:type", "0..* O", "1..* M", "0..* O"),
    _same("version", "dcat:version", "0..1 O"),
    _same("version notes", "adms:versionNotes", "0..* O"),
    _same("was generated by", "prov:wasGeneratedBy", "0..* O"),
    _same("health data access body", "healthdcatap:hdab", "1..1 M"),
    _same("health data access body coordinator", "healthdcatap:hdabCoordinator", "0..1 O"),
    _varies("landing page", "dcat:landingPage", "0..* O", "0..* R", "0..* O"),
    _same("spatial resolution", "dcat:spatialResolutionInMeters", "0..1 O"),
    _same("minimum typical age", "healthdcatap:minTypicalAge", "0..1 R"),
    _same("maximum typical age", "healthdcatap:maxTypicalAge", "0..1 R"),
)

PROPERTY_COUNT: Final = 57
"""How many properties the source file lists per tier.

Asserted in the tests. A transcription that silently loses a row is the failure
mode this constant exists to catch.
"""


@dataclass(frozen=True, slots=True)
class ConditionalRule:
    """An obligation the table cannot express, stated in the source's usage notes.

    Attributes:
        when_term: The property whose value triggers the condition.
        when_value: The triggering value, as the source writes it.
        then_term: The property that becomes mandatory.
        quote: The source's own wording, so the rule can be checked.
    """

    when_term: str
    when_value: str
    then_term: str
    quote: str


CONDITIONAL_RULES: Final[tuple[ConditionalRule, ...]] = (
    ConditionalRule(
        when_term="healthdcatap:hasStructuredData",
        when_value="true",
        then_term="healthdcatap:hasVariables",
        quote=("When the value is true, at least one healthdcatap:hasVariables MUST be provided."),
    ),
)
"""Obligations that depend on another property's value.

Kept separate because a cardinality column cannot express them, and dropping
them would make a dataset that satisfies the table look conformant when it is
not. ``hasStructuredData`` is mandatory in every tier, so for any dataset that
declares structured data — which a clinical dataset does — ``hasVariables``
becomes mandatory too.
"""


def properties_by_obligation(tier: Tier, obligation: Obligation) -> tuple[ProfileProperty, ...]:
    """Return the properties carrying one obligation in one tier.

    Args:
        tier: Which shape set applies.
        obligation: The obligation to select.

    Returns:
        The matching properties, in profile order.
    """
    return tuple(p for p in PROPERTIES if p.rule_for(tier).obligation is obligation)


def mandatory_terms(tier: Tier) -> tuple[str, ...]:
    """Return the RDF terms a dataset description must carry in one tier.

    Args:
        tier: Which shape set applies.

    Returns:
        The terms, in profile order. Properties whose term the source does not
        give are omitted, and none of those is mandatory.
    """
    return tuple(
        p.term for p in properties_by_obligation(tier, Obligation.MANDATORY) if p.term is not None
    )


def find(label: str) -> ProfileProperty:
    """Return one property by its profile label.

    Args:
        label: The label exactly as the source file spells it.

    Returns:
        The property.

    Raises:
        KeyError: If no property carries that label.
    """
    for candidate in PROPERTIES:
        if candidate.label == label:
            return candidate
    raise KeyError(f"no HealthDCAT-AP property labelled {label!r}")


# --------------------------------------------------------------------------
# Namespaces, read from the shapes file's own prefix declarations
# --------------------------------------------------------------------------

NAMESPACES: Final[dict[str, str]] = {
    "adms": "http://www.w3.org/ns/adms#",
    "csvw": "http://www.w3.org/ns/csvw#",
    "cv": "http://data.europa.eu/m8g/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcatap": "http://data.europa.eu/r5r/",
    "dct": "http://purl.org/dc/terms/",
    "dpv": "https://w3id.org/dpv#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "geodcatap": "http://data.europa.eu/930/",
    "healthdcatap": "http://healthdataportal.eu/ns/health#",
    "prov": "http://www.w3.org/ns/prov#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "sh": "http://www.w3.org/ns/shacl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "vcard": "http://www.w3.org/2006/vcard/ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
"""Prefix to IRI, transcribed from the shapes file's own prefix block."""

HEALTHDCATAP_NAMESPACE_IS_PROVISIONAL: Final = True
"""The health namespace IRI is a placeholder, by the profile's own admission.

The shapes file carries this comment immediately above the declaration:
"To be changed when the Heathdcat-AP namespace is created". So every
health-specific term this tool emits will need rewriting when the real namespace
is minted. That is survivable only because the IRI is assembled from
:data:`NAMESPACES` in one place rather than written into templates, which is the
reason this constant exists and the reason to keep it that way.
"""

IMPORTED_PROFILE: Final = "https://semiceu.github.io/DCAT-AP/releases/3.0.0/html/shacl/shapes.ttl"
"""HealthDCAT-AP imports the DCAT-AP 3.0.0 shapes with ``owl:imports``.

The consequence, plainly: conforming to HealthDCAT-AP means conforming to
DCAT-AP 3.0.0 as well, and the health shapes alone are not the whole constraint
set. Two shapes the health file references, ``Agent_Shape`` and
``PeriodOfTime_Shape``, are defined there rather than here.
"""

RANGE_CONSTRAINTS_PATH: Final = "ranges/range.ttl"
"""Where the class range constraints live.

The shapes file says so itself: it includes all constraints to be satisfied
*except* class range constraints, which are defined separately. That file has
not been read yet, so the transcription here is incomplete by the profile's own
account.
"""


# --------------------------------------------------------------------------
# Access rights, which is what actually selects the tier
# --------------------------------------------------------------------------

ACCESS_RIGHT_VOCABULARY: Final = "http://publications.europa.eu/resource/authority/access-right/"
"""The EU Publications Office authority list used for ``dct:accessRights``."""

TIER_ACCESS_RIGHT: Final[dict[Tier, str]] = {
    Tier.PUBLIC: f"{ACCESS_RIGHT_VOCABULARY}PUBLIC",
    Tier.NON_PUBLIC: f"{ACCESS_RIGHT_VOCABULARY}NON_PUBLIC",
    Tier.RESTRICTED: f"{ACCESS_RIGHT_VOCABULARY}RESTRICTED",
}
"""The ``dct:accessRights`` value each tier's shapes pin with ``sh:hasValue``.

All three read from the shapes files. This is the finding that reframes the
tiers: a tier is not a reporting style somebody picks, **the access-rights value
selects which shapes apply**, and the property is mandatory at exactly one value
per tier.

The consequence that matters for `build`: the three are **mutually exclusive**.
A dataset cannot satisfy two tiers at once, because each pins a different single
value for the same mandatory property. So the tier is a decision, not a
spectrum, and only the data holder knows which release arrangement applies.
"""


def tier_for_access_right(iri: str) -> Tier:
    """Return the tier whose shapes apply to a dataset with this access right.

    Args:
        iri: A full ``dct:accessRights`` IRI.

    Returns:
        The tier.

    Raises:
        KeyError: If the IRI is not one of the three the profile pins. The
            vocabulary has other members, and a dataset carrying one of those
            falls under no HealthDCAT-AP tier at all — which is a thing to
            report, not to round off to the nearest tier.
    """
    for tier, pinned in TIER_ACCESS_RIGHT.items():
        if pinned == iri:
            return tier
    raise KeyError(
        f"no HealthDCAT-AP tier pins dct:accessRights {iri!r}; expected one of "
        + ", ".join(sorted(TIER_ACCESS_RIGHT.values()))
    )


SUPERSET_TIER: Final = Tier.NON_PUBLIC
"""The tier with the most mandatory properties, and the one to gather metadata for.

The three tiers are mutually exclusive on ``dct:accessRights``, but their
*other* obligations are nested: non-public requires everything public and
restricted require, plus ``dcat:contactPoint``, ``dcat:keyword``, ``dct:type``
and ``dct:provenance``. The profile's own comment on those four says they are
mandatory "in addition to those required for PUBLIC datasets".

So the useful strategy is to collect the non-public superset and emit whichever
access right the holder declares. Switching tiers then changes one triple
instead of sending somebody back to gather four more fields.

Worth noticing because it is counter-intuitive: **restricted requires less
metadata than non-public**, not more. The names suggest the opposite. A reading
that fits, though the profile does not say so and this is inference rather than
a finding: a non-public dataset is one whose *description* is catalogued while
its data is not available, so it needs a contact point, keywords, a type and a
provenance statement precisely so somebody can find it and ask. The permitted
values of the access-right vocabulary have not been read, so the definitions
behind the three names are not yet confirmed.
"""

NON_PUBLIC_ONLY_TERMS: Final = (
    "dcat:contactPoint",
    "dcat:keyword",
    "dct:type",
    "dct:provenance",
)
"""The four properties mandatory only in the non-public tier."""


# --------------------------------------------------------------------------
# Value constraints the cardinality table does not carry
# --------------------------------------------------------------------------


class NodeKind(StrEnum):
    """What kind of RDF node a value may be."""

    IRI = "IRI"
    LITERAL = "Literal"
    BLANK_NODE_OR_IRI = "BlankNodeOrIRI"


@dataclass(frozen=True, slots=True)
class ValueConstraint:
    """What a property's value must look like, beyond how many there may be.

    Attributes:
        term: The RDF term the constraint applies to.
        node_kind: ``sh:nodeKind``, if given.
        datatype: ``sh:datatype``, if given, as a prefixed name.
        shape: ``sh:node``, naming another shape the value must satisfy.
        has_value: ``sh:hasValue``, the single permitted value.
    """

    term: str
    node_kind: NodeKind | None = None
    datatype: str | None = None
    shape: str | None = None
    has_value: str | None = None


DATASET_VALUE_CONSTRAINTS: Final[tuple[ValueConstraint, ...]] = (
    ValueConstraint("dct:source", node_kind=NodeKind.BLANK_NODE_OR_IRI),
    ValueConstraint("dct:accessRights", has_value=f"{ACCESS_RIGHT_VOCABULARY}PUBLIC"),
    ValueConstraint("dcatap:applicableLegislation", node_kind=NodeKind.IRI),
    ValueConstraint("dcat:distribution", shape="Distribution_Shape"),
    ValueConstraint("dct:identifier", node_kind=NodeKind.LITERAL),
    ValueConstraint(
        "dct:publisher",
        node_kind=NodeKind.BLANK_NODE_OR_IRI,
        shape="HealthPublisherAgent_Shape",
    ),
    ValueConstraint("adms:sample", shape="Distribution_Shape"),
    ValueConstraint("dcat:theme", node_kind=NodeKind.IRI),
    ValueConstraint("dpv:hasPurpose", node_kind=NodeKind.BLANK_NODE_OR_IRI),
    ValueConstraint(
        "healthdcatap:hdab", node_kind=NodeKind.BLANK_NODE_OR_IRI, shape="HealthAgent_Shape"
    ),
    ValueConstraint(
        "healthdcatap:hdabCoordinator",
        node_kind=NodeKind.BLANK_NODE_OR_IRI,
        shape="HealthAgent_Shape",
    ),
    ValueConstraint(
        "geodcatap:custodian", node_kind=NodeKind.BLANK_NODE_OR_IRI, shape="HealthAgent_Shape"
    ),
    ValueConstraint("healthdcatap:healthCategory", node_kind=NodeKind.IRI),
    ValueConstraint("healthdcatap:healthTheme", node_kind=NodeKind.BLANK_NODE_OR_IRI),
    ValueConstraint("healthdcatap:hasStructuredData", datatype="xsd:boolean"),
    ValueConstraint("healthdcatap:hasVariables", shape="CSVWTableGroup_Shape"),
    ValueConstraint("healthdcatap:analytics", shape="Distribution_Shape"),
    ValueConstraint("healthdcatap:hasCodeValues", node_kind=NodeKind.LITERAL),
    ValueConstraint("healthdcatap:hasCodingSystem", node_kind=NodeKind.BLANK_NODE_OR_IRI),
    ValueConstraint("healthdcatap:minTypicalAge", datatype="xsd:nonNegativeInteger"),
    ValueConstraint("healthdcatap:maxTypicalAge", datatype="xsd:nonNegativeInteger"),
    ValueConstraint("healthdcatap:numberOfRecords", datatype="xsd:nonNegativeInteger"),
    ValueConstraint("healthdcatap:numberOfUniqueIndividuals", datatype="xsd:nonNegativeInteger"),
    ValueConstraint("healthdcatap:populationCoverage", node_kind=NodeKind.LITERAL),
    ValueConstraint("dct:alternative", node_kind=NodeKind.LITERAL),
    ValueConstraint("healthdcatap:retentionPeriod", shape="PeriodOfTime_Shape"),
)
"""Value constraints on ``dcat:Dataset``, from the public tier shapes.

Three properties carry a path and a severity and nothing else, so they are
absent here: ``dpv:hasLegalBasis``, ``dpv:hasPersonalData`` and
``dqv:hasQualityAnnotation``. The shapes file notes that the controlled
vocabularies for ``healthTheme`` and ``hasCodingSystem`` do not exist yet, which
is why those are blank nodes rather than IRIs for now — and a reason to expect
this table to change.
"""


# --------------------------------------------------------------------------
# hasVariables is a CSVW table group, which this tool already has the data for
# --------------------------------------------------------------------------

CSVW_COLUMN_PROPERTIES: Final = (
    "csvw:name",
    "dct:description",
    "csvw:title",
    "csvw:datatype",
    "csvw:propertyUrl",
)
"""What the profile wants said about each variable in a structured dataset.

``healthdcatap:hasVariables`` resolves to a CSVW table group: tables, each with
columns, each column described by these properties. That is a close match to
what a ``lab/*.tsv`` and its JSON sidecar already carry — a column name, a
description, a datatype, and through ``csvw:propertyUrl`` the LOINC code the
column measures. So the obligation that looked hardest to satisfy is the one the
existing lab branch nearly satisfies already.
"""

STRUCTURED_DATA_RULE_MESSAGE: Final = (
    "If healthdcatap:hasStructuredData is true, the dataset must include at "
    "least one healthdcatap:hasVariables."
)
"""The profile's own message for the conditional rule, verbatim.

Expressed in the shapes as an ``sh:or`` with three branches: structured data
true plus at least one variable; structured data false; or structured data
absent. The third branch is unreachable, since ``hasStructuredData`` is
mandatory at 1..1 in every tier — a harmless inconsistency in the profile,
recorded so that reading the shapes again does not raise it as a question twice.
"""


def expand(term: str) -> str:
    """Expand a prefixed name into a full IRI.

    Args:
        term: A prefixed name such as ``dct:title``.

    Returns:
        The full IRI.

    Raises:
        ValueError: If the term is not a prefixed name.
        KeyError: If the prefix is not one the profile declares.
    """
    prefix, separator, local = term.partition(":")
    if not separator or not local:
        raise ValueError(f"not a prefixed name: {term!r}")
    if prefix not in NAMESPACES:
        raise KeyError(f"unknown prefix {prefix!r} in {term!r}")
    return NAMESPACES[prefix] + local


def value_constraint(term: str) -> ValueConstraint | None:
    """Return the value constraint on one dataset property, if the profile sets one.

    Args:
        term: The RDF term, as a prefixed name.

    Returns:
        The constraint, or ``None`` when the profile constrains only cardinality.
    """
    for constraint in DATASET_VALUE_CONSTRAINTS:
        if constraint.term == term:
            return constraint
    return None


# --------------------------------------------------------------------------
# The health category vocabulary, which the mandatory property draws from
# --------------------------------------------------------------------------

HEALTH_CATEGORY_SCHEME: Final = (
    "https://hdeu-dcat.data.health.europa.eu/resource/authority/healthcategories"
)
"""The SKOS concept scheme ``healthdcatap:healthCategory`` draws from."""

HEALTH_CATEGORY_BASE: Final = f"{HEALTH_CATEGORY_SCHEME}/"
"""Base IRI of the concepts.

Note the scheme IRI has no trailing separator while the concepts hang off it
with a slash, so the two are not interchangeable — concatenating onto the scheme
IRI directly would produce a broken concept IRI.
"""

HEALTH_CATEGORIES: Final[dict[str, str]] = {
    "EMRD": "Other health data from medical devices",
    "DIOH": (
        "Data on factors impacting on health, including socio-economic, environmental "
        "and behavioural determinants of health"
    ),
    "IDHP": (
        "Data on professional status, and on the specialisation and institution of health "
        "professionals involved in the treatment of a natural person"
    ),
    "EINS": "Health data from biobanks and associated databases",
    "RMMD": "Data from registries for medicinal products and medical devices",
    "MRMR": "Data from medical registries and mortality registries",
    "RPDG": "Data on pathogens that impact human health",
    "HPML": (
        "Other human molecular data such as proteomic, transcriptomic, metabolomic, "
        "lipidomic and other omic data"
    ),
    "HGPD": "Human genetic, epigenomic and genomic data",
    "HRAD": (
        "Healthcare-related administrative data, including on dispensations, "
        "reimbursement claims and reimbursements"
    ),
    "NRPE": (
        "Aggregated data on healthcare needs, resources allocated to healthcare, the "
        "provision of and access to healthcare, healthcare expenditure and financing"
    ),
    "PGEH": "Personal electronic health data automatically generated through medical devices",
    "RQSH": (
        "Data from research cohorts, questionnaires and surveys related to health, "
        "after the first publication of the related results"
    ),
    "EHRS": "Electronic health data from EHRs",
    "EHCT": (
        "Data from clinical trials, clinical studies, clinical investigations and "
        "performance studies subject to Regulation (EU) No 536/2014, Regulation (EU) "
        "2024/1938 of the European Parliament and of the Council34, Regulation (EU) "
        "2017/745 and Regulation (EU) 2017/746"
    ),
    "PHDR": ("Data from population-based health data registries such as public health registries"),
    "WELA": "Data from wellness applications",
}
"""All seventeen health category concepts, in the scheme's own top-concept order.

The scheme's scope note says these correspond to the seventeen health data
categories defined by **Article 51 of the EHDS Regulation**. That is why the
property is mandatory: it is the field saying which Article 51 category a
dataset falls under, and therefore which part of the 2029 / 2031 timetable
applies to it.

Two transcription notes. The concepts carry no ``skos:notation``; the code lives
in ``dct:identifier``, which is what the keys here are. And the ``EHCT`` label
contains a stray ``34`` after "Council" — a footnote marker that leaked into the
source data. It is kept, because the label is quoted verbatim and silently
tidying it would make this table disagree with the file it transcribes.
"""

HEALTH_CATEGORY_FOR_EHR: Final = "EHRS"
"""The category this project's own output falls under.

Read verbatim: ``EHRS``, "Electronic health data from EHRs". It is the only
concept in the scheme whose label mentions EHRs, and this project's scope is EHR
data, so it is the value `build` should emit by default.

Not to be confused with ``PGEH``, "Personal electronic health data automatically
generated through medical devices", which is a different Article 51 category. A
dataset combining both would carry both: ``healthCategory`` is 1..*, not 1..1.
"""


def health_category_iri(notation: str) -> str:
    """Return the full concept IRI for a health category notation.

    Args:
        notation: A notation such as ``HRAD``.

    Returns:
        The concept IRI.

    Raises:
        KeyError: If the notation is not one that has been verified. The
            scheme holds exactly these seventeen, so a rejection here means
            the notation is not in the vocabulary at all.
    """
    if notation not in HEALTH_CATEGORIES:
        raise KeyError(
            f"health category {notation!r} is not in the scheme; expected one of "
            + ", ".join(sorted(HEALTH_CATEGORIES))
        )
    return f"{HEALTH_CATEGORY_BASE}{notation}"


def required_terms(tier: Tier) -> tuple[str, ...]:
    """Return every term a dataset description must carry in one tier.

    Combines the mandatory properties with the access right that tier pins, and
    with the property the conditional rule makes mandatory in practice: a
    clinical dataset declares structured data, so it owes at least one
    ``healthdcatap:hasVariables``.

    Args:
        tier: Which shape set applies.

    Returns:
        The terms, in profile order, without duplicates.
    """
    terms = list(mandatory_terms(tier))
    for rule in CONDITIONAL_RULES:
        if rule.then_term not in terms:
            terms.append(rule.then_term)
    return tuple(terms)


# --------------------------------------------------------------------------
# What the three access rights actually mean
# --------------------------------------------------------------------------

ACCESS_RIGHT_DEFINITIONS: Final[dict[str, str]] = {
    "PUBLIC": (
        "Publicly accessible by everyone. Usage note: Permissible obstacles include "
        "registration and request for API keys, as long as anyone can request such "
        "registration and/or API keys."
    ),
    "NON_PUBLIC": (
        "Not publicly accessible for privacy, security or other reasons. Usage note: "
        "This category may include resources that contain sensitive or personal "
        "information."
    ),
    "RESTRICTED": (
        "Only available under certain conditions. Usage note: This category may include "
        "resources that require payment, resources shared under non-disclosure "
        "agreements, resources for which the publisher or owner has not yet decided if "
        "they can be publicly released."
    ),
}
"""The EU authority list's own definitions of the three values the profile pins.

Quoted verbatim from ``catalogue/access-right.rdf``, authority table version
20240612-0. They settle a question that was inference until now.
"""

DEFAULT_TIER: Final = Tier.NON_PUBLIC
"""The tier a de-identified clinical dataset falls under, on the vocabulary's own words.

``NON_PUBLIC`` is defined as "not publicly accessible for privacy, security or
other reasons", with a usage note saying the category "may include resources
that contain sensitive or personal information". That describes a pseudonymised
clinical dataset released under an EHDS data permit exactly.

``RESTRICTED`` is the near miss, and worth ruling out explicitly because its
name is the tempting one: it means "only available under certain conditions",
and its usage note gives those conditions as payment, non-disclosure agreements,
or a publisher who has not yet decided whether the data can be released. Those
are commercial and editorial conditions, not privacy ones.

It is a default, not a decision taken for the user: the tier is a fact about the
release arrangement, and `build` takes it as input. But a default that matches
the vocabulary's definition beats making every user read an authority list
first. Pleasingly, it is also :data:`SUPERSET_TIER`, so the default is the
strictest and switching away from it never requires more metadata.

The authority list holds four further values — ``SENSITIVE``, ``CONFIDENTIAL``,
``OP_DATPRO`` and the deprecated ``NORMAL``. None is pinned by any HealthDCAT-AP
tier, so a dataset carrying one of those falls under no tier of the profile.
"""

UNTIERED_ACCESS_RIGHTS: Final = ("SENSITIVE", "CONFIDENTIAL", "OP_DATPRO", "NORMAL")
"""Access rights in the vocabulary that no HealthDCAT-AP tier pins.

``NORMAL`` is marked deprecated in the source, superseded by ``PUBLIC``.
"""


# --------------------------------------------------------------------------
# dcat:theme, the other mandatory IRI-valued property
# --------------------------------------------------------------------------

DATA_THEME_SCHEME: Final = "http://publications.europa.eu/resource/authority/data-theme"
"""The authority list ``dcat:theme`` draws from, version 20241211-0.

Note the ``http`` scheme. The health category vocabulary uses ``https``. Two EU
authority lists, two different schemes, and concatenating the wrong one produces
an IRI that resolves to nothing while looking entirely plausible — which is why
both bases are constants here rather than string literals at the call sites.
"""

DATA_THEME_BASE: Final = f"{DATA_THEME_SCHEME}/"

DATA_THEMES: Final[dict[str, str]] = {
    "ECON": "Economy and finance",
    "AGRI": "Agriculture, fisheries, forestry and food",
    "GOVE": "Government and public sector",
    "ENER": "Energy",
    "ENVI": "Environment",
    "EDUC": "Education, culture and sport",
    "JUST": "Justice, legal system and public safety",
    "REGI": "Regions and cities",
    "INTR": "International issues",
    "HEAL": "Health",
    "SOCI": "Population and society",
    "OP_DATPRO": "Provisional data",
    "TECH": "Science and technology",
    "TRAN": "Transport",
}
"""All fourteen data themes, in the scheme's own top-concept order.

As with the health categories, the code lives in ``dc:identifier`` rather than
``skos:notation``.
"""

DATA_THEME_FOR_HEALTH: Final = "HEAL"
"""The theme a clinical dataset carries. ``dcat:theme`` is mandatory at 1..*."""


def data_theme_iri(notation: str) -> str:
    """Return the full concept IRI for a data theme notation.

    Args:
        notation: A notation such as ``HEAL``.

    Returns:
        The concept IRI.

    Raises:
        KeyError: If the notation is not in the authority list.
    """
    if notation not in DATA_THEMES:
        raise KeyError(
            f"data theme {notation!r} is not in the scheme; expected one of "
            + ", ".join(sorted(DATA_THEMES))
        )
    return f"{DATA_THEME_BASE}{notation}"


def access_right_iri(notation: str) -> str:
    """Return the full concept IRI for an access-right notation.

    Args:
        notation: A notation such as ``NON_PUBLIC``.

    Returns:
        The concept IRI.

    Raises:
        KeyError: If the notation is in neither the tiered nor the untiered set.
    """
    known = set(ACCESS_RIGHT_DEFINITIONS) | set(UNTIERED_ACCESS_RIGHTS)
    if notation not in known:
        raise KeyError(
            f"access right {notation!r} is not in the authority list; expected one of "
            + ", ".join(sorted(known))
        )
    return f"{ACCESS_RIGHT_VOCABULARY}{notation}"


# --------------------------------------------------------------------------
# dct:type, which the shapes require to be an IRI and not a literal
# --------------------------------------------------------------------------

DATASET_TYPE_SCHEME: Final = "http://publications.europa.eu/resource/authority/dataset-type"
"""The authority list ``dct:type`` draws from. Mandatory in the non-public tier."""

DATASET_TYPE_BASE: Final = f"{DATASET_TYPE_SCHEME}/"

DATASET_TYPES: Final[dict[str, str]] = {
    "APROF": "Application profile",
    "CODE_LIST": "Code list",
    "CORE_COMP": "Core component",
    "DIRECTORY": "Directory",
    "DOMAIN_MODEL": "Domain model",
    "DSCRP_SERV": "Service description",
    "GEOSPATIAL": "Geospatial data",
    "GLOSSARY": "Glossary",
    "HVD": "High-value dataset",
    "IEPD": "Information exchange package description",
    "MAPPING": "Mapping",
    "NAL": "Name authority list",
    "ONTOLOGY": "Ontology",
    "OP_DATPRO": "Provisional data",
    "RELEASE": "Release",
    "SCHEMA": "Schema",
    "STATISTICAL": "Statistical data",
    "STYLES": "Style sheets",
    "SYNTHETIC_DATA": "Synthetic data",
    "TAXONOMY": "Taxonomy",
    "TEST_DATA": "Test data",
    "THESAURUS": "Thesaurus",
}
"""Dataset types, transcribed from ``catalogue/dataset-types.rdf``.

Three concepts of the twenty-five are omitted because their labels contain a
character the source renders ambiguously (the ATTO table entries and the syntax
encoding scheme); none of them describes clinical data. Transcribed rather than
left open so that a notation can be checked: ``sh:nodeKind sh:IRI`` passes for
any IRI, so a typo would otherwise produce a plausible dead reference.
"""

DATASET_TYPE_FOR_SYNTHETIC: Final = "SYNTHETIC_DATA"
"""The type a dataset built from this project's own generator carries.

A default rather than a detection: the tool cannot tell whether its input was
synthetic, and the data holder can. It is the right default *here* because this
project's hard constraint is synthetic data only, and the worked example in the
README is generate-then-build. Anyone building from real clinical material has
to pass ``--dataset-type``, and the help text says so.
"""


def dataset_type_iri(notation: str) -> str:
    """Return the full concept IRI for a dataset type notation.

    Args:
        notation: A notation such as ``SYNTHETIC_DATA``.

    Returns:
        The concept IRI.

    Raises:
        KeyError: If the notation is not in the transcribed list.
    """
    if notation not in DATASET_TYPES:
        raise KeyError(
            f"dataset type {notation!r} is not in the authority list; expected one of "
            + ", ".join(sorted(DATASET_TYPES))
        )
    return f"{DATASET_TYPE_BASE}{notation}"
