"""The HealthDCAT-AP transcription, checked for internal consistency.

These tests cannot verify the transcription against the source — that needs the
network, and a test suite that fails when a Commission server is down is a test
suite people learn to ignore. What they can do is catch the ways a transcription
goes wrong on its own: a row silently lost, a label duplicated, a cardinality
that contradicts its obligation.

The mandatory sets are pinned literally. They are the part of the profile that
`build` has to satisfy, so a change to them should be a deliberate edit with a
failing test in front of it, not something that slips through.
"""

from __future__ import annotations

import re

import pytest

from commissura.healthdcat import (
    ACCESS_RIGHT_DEFINITIONS,
    ACCESS_RIGHT_VOCABULARY,
    CONDITIONAL_RULES,
    CSVW_COLUMN_PROPERTIES,
    DATA_THEME_BASE,
    DATA_THEME_FOR_HEALTH,
    DATA_THEMES,
    DATASET_TYPE_BASE,
    DATASET_TYPE_FOR_SYNTHETIC,
    DATASET_TYPE_SCHEME,
    DATASET_TYPES,
    DATASET_VALUE_CONSTRAINTS,
    DEFAULT_TIER,
    HEALTH_CATEGORIES,
    HEALTH_CATEGORY_BASE,
    HEALTH_CATEGORY_FOR_EHR,
    HEALTH_CATEGORY_SCHEME,
    HEALTHDCATAP_NAMESPACE_IS_PROVISIONAL,
    IMPORTED_PROFILE,
    NAMESPACES,
    NON_PUBLIC_ONLY_TERMS,
    PERSONAL_DATA_CATEGORY,
    PERSONAL_DATA_CATEGORY_LABEL,
    PERSONAL_DATA_CATEGORY_TYPES,
    PROPERTIES,
    PROPERTY_COUNT,
    RANGE_CONSTRAINTS_PATH,
    RELEASE,
    SHAPES_PATHS,
    SOURCE_URL,
    STRUCTURED_DATA_RULE_MESSAGE,
    SUPERSET_TIER,
    TIER_ACCESS_RIGHT,
    UNTIERED_ACCESS_RIGHTS,
    Cardinality,
    NodeKind,
    Obligation,
    Tier,
    access_right_iri,
    data_theme_iri,
    dataset_type_iri,
    expand,
    find,
    health_category_iri,
    mandatory_terms,
    properties_by_obligation,
    required_terms,
    tier_for_access_right,
    value_constraint,
)

MANDATORY_PUBLIC = (
    "dct:accessRights",
    "dcatap:applicableLegislation",
    "dct:description",
    "dcat:distribution",
    "healthdcatap:healthCategory",
    "healthdcatap:hasStructuredData",
    "dct:identifier",
    "dcat:theme",
    "dct:title",
    "healthdcatap:hdab",
)

MANDATORY_ONLY_IN_NON_PUBLIC = (
    "dcat:contactPoint",
    "dcat:keyword",
    "dct:provenance",
    "dct:type",
)


# --------------------------------------------------------------------------
# Transcription integrity
# --------------------------------------------------------------------------


def test_no_row_was_lost_in_transcription() -> None:
    """The source lists 57 properties per tier."""
    assert len(PROPERTIES) == PROPERTY_COUNT


def test_labels_are_unique() -> None:
    """Labels are the key in the source file, so a duplicate means a row was overwritten."""
    labels = [p.label for p in PROPERTIES]
    assert len(set(labels)) == len(labels)


def test_rdf_terms_are_unique_where_present() -> None:
    terms = [p.term for p in PROPERTIES if p.term is not None]
    assert len(set(terms)) == len(terms)


@pytest.mark.parametrize("prop", PROPERTIES, ids=lambda p: p.label)
def test_every_term_is_a_prefixed_name(prop: object) -> None:
    term = prop.term  # type: ignore[attr-defined]
    if term is None:
        return
    assert re.fullmatch(r"[a-z][a-zA-Z0-9]*:[a-zA-Z][a-zA-Z0-9]*", term), term


def test_exactly_one_property_has_no_term_and_it_is_not_mandatory() -> None:
    """The gap is deliberate: the source gives no term, so none was invented."""
    without = [p for p in PROPERTIES if p.term is None]
    assert [p.label for p in without] == ["in series"]
    for tier in Tier:
        assert without[0].rule_for(tier).obligation is not Obligation.MANDATORY


def test_the_source_is_recorded_so_the_table_can_be_rechecked() -> None:
    assert RELEASE == "8"
    assert "release-8" in SOURCE_URL
    assert len(SHAPES_PATHS) == len(Tier)
    assert all("release-8" in path for path in SHAPES_PATHS)


# --------------------------------------------------------------------------
# Obligations and cardinalities must not contradict each other
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tier", list(Tier), ids=lambda t: t.value)
def test_a_mandatory_property_requires_at_least_one_value(tier: Tier) -> None:
    """A transcription error would most likely show up exactly here."""
    for prop in properties_by_obligation(tier, Obligation.MANDATORY):
        assert prop.rule_for(tier).cardinality.minimum >= 1, prop.label


@pytest.mark.parametrize("tier", list(Tier), ids=lambda t: t.value)
def test_a_non_mandatory_property_permits_zero_values(tier: Tier) -> None:
    for obligation in (Obligation.RECOMMENDED, Obligation.OPTIONAL):
        for prop in properties_by_obligation(tier, obligation):
            assert prop.rule_for(tier).cardinality.minimum == 0, prop.label


@pytest.mark.parametrize("tier", list(Tier), ids=lambda t: t.value)
def test_every_property_carries_exactly_one_obligation_per_tier(tier: Tier) -> None:
    total = sum(len(properties_by_obligation(tier, o)) for o in Obligation)
    assert total == len(PROPERTIES)


@pytest.mark.parametrize("tier", list(Tier), ids=lambda t: t.value)
def test_cardinality_bounds_are_ordered(tier: Tier) -> None:
    for prop in PROPERTIES:
        card = prop.rule_for(tier).cardinality
        if card.maximum is not None:
            assert card.minimum <= card.maximum, prop.label


def test_is_required_agrees_with_the_obligation() -> None:
    for prop in PROPERTIES:
        for tier in Tier:
            rule = prop.rule_for(tier)
            assert rule.is_required == (rule.obligation is Obligation.MANDATORY)


# --------------------------------------------------------------------------
# What build will actually have to satisfy
# --------------------------------------------------------------------------


def test_the_public_mandatory_set_is_what_was_transcribed() -> None:
    assert mandatory_terms(Tier.PUBLIC) == MANDATORY_PUBLIC


def test_non_public_adds_four_obligations_and_removes_none() -> None:
    """A non-public dataset must also say who to contact, and where it came from."""
    public = set(mandatory_terms(Tier.PUBLIC))
    non_public = set(mandatory_terms(Tier.NON_PUBLIC))
    assert public < non_public
    assert non_public - public == set(MANDATORY_ONLY_IN_NON_PUBLIC)


def test_restricted_requires_the_same_as_public() -> None:
    assert set(mandatory_terms(Tier.RESTRICTED)) == set(mandatory_terms(Tier.PUBLIC))


def test_the_tiers_genuinely_differ() -> None:
    """If they did not, one shape set would do and the tier would not need declaring."""
    varying = [p for p in PROPERTIES if not (p.public == p.non_public == p.restricted)]
    assert len(varying) == 14


def test_health_specific_properties_are_present() -> None:
    """The extension relative to plain DCAT-AP is what makes this profile health data."""
    terms = {p.term for p in PROPERTIES if p.term and p.term.startswith("healthdcatap:")}
    assert terms >= {
        "healthdcatap:healthCategory",
        "healthdcatap:healthTheme",
        "healthdcatap:populationCoverage",
        "healthdcatap:numberOfRecords",
        "healthdcatap:numberOfUniqueIndividuals",
        "healthdcatap:retentionPeriod",
        "healthdcatap:hdab",
        "healthdcatap:hasStructuredData",
        "healthdcatap:hasVariables",
        "healthdcatap:minTypicalAge",
        "healthdcatap:maxTypicalAge",
    }


def test_the_privacy_vocabulary_is_reused_rather_than_reinvented() -> None:
    terms = {p.term for p in PROPERTIES if p.term and p.term.startswith("dpv:")}
    assert terms == {"dpv:hasLegalBasis", "dpv:hasPersonalData", "dpv:hasPurpose"}


# --------------------------------------------------------------------------
# Conditional obligations the table cannot express
# --------------------------------------------------------------------------


def test_the_conditional_rule_points_at_real_properties() -> None:
    """A rule naming a property that does not exist would never fire."""
    terms = {p.term for p in PROPERTIES}
    for rule in CONDITIONAL_RULES:
        assert rule.when_term in terms, rule.when_term
        assert rule.then_term in terms, rule.then_term
        assert rule.quote


def test_structured_data_makes_variables_mandatory_in_practice() -> None:
    """``hasStructuredData`` is mandatory in every tier, and a clinical dataset is structured.

    So for anything commissura produces, ``hasVariables`` is effectively
    mandatory too, even though the cardinality column calls it recommended.
    """
    rule = next(r for r in CONDITIONAL_RULES if r.then_term == "healthdcatap:hasVariables")
    trigger = find("structured data")
    variables = find("variables")

    assert rule.when_term == trigger.term
    for tier in Tier:
        assert trigger.rule_for(tier).is_required
        assert not variables.rule_for(tier).is_required, "only the condition makes it required"


# --------------------------------------------------------------------------
# Lookup and formatting
# --------------------------------------------------------------------------


def test_lookup_by_label() -> None:
    assert find("title").term == "dct:title"
    assert find("health data access body").term == "healthdcatap:hdab"


def test_lookup_of_an_unknown_label_fails_loudly() -> None:
    with pytest.raises(KeyError, match="no HealthDCAT-AP property"):
        find("not a property")


@pytest.mark.parametrize(
    ("cardinality", "rendered"),
    [
        (Cardinality(1, 1), "1..1"),
        (Cardinality(1, None), "1..*"),
        (Cardinality(0, 1), "0..1"),
        (Cardinality(0, None), "0..*"),
    ],
)
def test_cardinality_renders_in_the_profiles_notation(
    cardinality: Cardinality, rendered: str
) -> None:
    assert str(cardinality) == rendered


# --------------------------------------------------------------------------
# What the SHACL shapes add on top of the cardinality table
# --------------------------------------------------------------------------


def test_every_prefix_used_by_a_property_is_declared() -> None:
    """A term whose prefix is undeclared cannot be expanded into an IRI."""
    for prop in PROPERTIES:
        if prop.term is None:
            continue
        prefix = prop.term.split(":", 1)[0]
        assert prefix in NAMESPACES, f"{prop.term} uses an undeclared prefix"


def test_namespaces_are_absolute_iris_ending_in_a_separator() -> None:
    for prefix, iri in NAMESPACES.items():
        assert iri.startswith(("http://", "https://")), prefix
        assert iri.endswith(("#", "/")), f"{prefix} would concatenate into a broken IRI"


def test_the_health_namespace_is_flagged_as_provisional() -> None:
    """The profile says so itself, and everything emitted with it will need rewriting."""
    assert HEALTHDCATAP_NAMESPACE_IS_PROVISIONAL
    assert NAMESPACES["healthdcatap"] == "http://healthdataportal.eu/ns/health#"


def test_terms_expand_to_full_iris() -> None:
    assert expand("dct:title") == "http://purl.org/dc/terms/title"
    assert expand("dcat:theme") == "http://www.w3.org/ns/dcat#theme"
    assert (
        expand("dcatap:applicableLegislation") == "http://data.europa.eu/r5r/applicableLegislation"
    )


@pytest.mark.parametrize("term", ["nocolon", "dct:", ":title", ""])
def test_a_malformed_prefixed_name_is_rejected(term: str) -> None:
    with pytest.raises((ValueError, KeyError)):
        expand(term)


def test_an_undeclared_prefix_is_rejected() -> None:
    with pytest.raises(KeyError, match="unknown prefix"):
        expand("nosuch:thing")


def test_every_property_term_expands() -> None:
    for prop in PROPERTIES:
        if prop.term is not None:
            assert expand(prop.term).startswith("http")


# --- The finding that reframes the tiers ---------------------------------


def test_the_public_tier_pins_access_rights_to_public() -> None:
    """The tier is not a style choice: the access-rights value selects the shapes.

    A dataset released under an EHDS data permit is not public, so validating a
    clinical dataset against the public shapes would be checking it against the
    wrong constraint set.
    """
    constraint = value_constraint("dct:accessRights")
    assert constraint is not None
    assert constraint.has_value == f"{ACCESS_RIGHT_VOCABULARY}PUBLIC"
    assert TIER_ACCESS_RIGHT[Tier.PUBLIC] == constraint.has_value


def test_every_tier_now_pins_a_known_access_right() -> None:
    """This test previously asserted the opposite, and that was its job.

    Until the other two shapes files were read, ``TIER_ACCESS_RIGHT`` held
    ``None`` for them and this test pinned that gap, so closing it had to break
    a test rather than pass silently. The shapes have since been read.
    """
    assert all(value is not None for value in TIER_ACCESS_RIGHT.values())
    assert set(TIER_ACCESS_RIGHT) == set(Tier)


def test_access_rights_is_mandatory_and_single_valued_everywhere() -> None:
    """Which is what makes pinning its value equivalent to selecting the tier."""
    prop = find("access rights")
    for tier in Tier:
        rule = prop.rule_for(tier)
        assert rule.is_required
        assert rule.cardinality.minimum == 1
        assert rule.cardinality.maximum == 1


# --- Value constraints ---------------------------------------------------


def test_value_constraints_name_properties_that_exist() -> None:
    terms = {p.term for p in PROPERTIES}
    for constraint in DATASET_VALUE_CONSTRAINTS:
        assert constraint.term in terms, constraint.term


def test_each_constraint_says_something() -> None:
    """A constraint with no constraint in it would be noise in the table."""
    for constraint in DATASET_VALUE_CONSTRAINTS:
        assert any(
            value is not None
            for value in (
                constraint.node_kind,
                constraint.datatype,
                constraint.shape,
                constraint.has_value,
            )
        ), constraint.term


def test_constraint_terms_are_unique() -> None:
    terms = [c.term for c in DATASET_VALUE_CONSTRAINTS]
    assert len(set(terms)) == len(terms)


def test_counting_properties_are_non_negative_integers() -> None:
    """A negative record count is not a thing, and the profile says so."""
    for term in (
        "healthdcatap:numberOfRecords",
        "healthdcatap:numberOfUniqueIndividuals",
        "healthdcatap:minTypicalAge",
        "healthdcatap:maxTypicalAge",
    ):
        constraint = value_constraint(term)
        assert constraint is not None
        assert constraint.datatype == "xsd:nonNegativeInteger"


def test_structured_data_is_a_boolean() -> None:
    constraint = value_constraint("healthdcatap:hasStructuredData")
    assert constraint is not None
    assert constraint.datatype == "xsd:boolean"


def test_three_properties_carry_no_value_constraint() -> None:
    """Recorded so their absence reads as observed rather than overlooked."""
    for term in ("dpv:hasLegalBasis", "dpv:hasPersonalData", "dqv:hasQualityAnnotation"):
        assert value_constraint(term) is None


def test_the_mandatory_health_category_must_be_an_iri() -> None:
    """So it needs a controlled vocabulary, which has not been read yet."""
    constraint = value_constraint("healthdcatap:healthCategory")
    assert constraint is not None
    assert constraint.node_kind is NodeKind.IRI


# --- Structure and dependencies ------------------------------------------


def test_variables_resolve_to_a_csvw_table_group() -> None:
    """The obligation that looked hardest is close to what the lab branch holds."""
    constraint = value_constraint("healthdcatap:hasVariables")
    assert constraint is not None
    assert constraint.shape == "CSVWTableGroup_Shape"
    assert "csvw:name" in CSVW_COLUMN_PROPERTIES
    assert "csvw:propertyUrl" in CSVW_COLUMN_PROPERTIES


def test_csvw_column_properties_all_expand() -> None:
    for term in CSVW_COLUMN_PROPERTIES:
        assert expand(term).startswith("http")


def test_the_profile_depends_on_dcat_ap_3() -> None:
    """Conforming to HealthDCAT-AP means conforming to DCAT-AP 3.0.0 as well."""
    assert "DCAT-AP/releases/3.0.0" in IMPORTED_PROFILE
    assert IMPORTED_PROFILE.endswith("shapes.ttl")


def test_shapes_referenced_but_defined_elsewhere_are_visible_as_such() -> None:
    """Agent_Shape and PeriodOfTime_Shape come from the imported DCAT-AP shapes."""
    referenced = {c.shape for c in DATASET_VALUE_CONSTRAINTS if c.shape}
    assert "PeriodOfTime_Shape" in referenced
    assert "HealthAgent_Shape" in referenced


def test_the_transcription_declares_itself_incomplete() -> None:
    """The shapes file excludes class range constraints, which are in another file."""
    assert RANGE_CONSTRAINTS_PATH.endswith("range.ttl")


def test_the_conditional_rule_message_matches_the_profiles_wording() -> None:
    assert "hasStructuredData" in STRUCTURED_DATA_RULE_MESSAGE
    assert "hasVariables" in STRUCTURED_DATA_RULE_MESSAGE
    rule = next(r for r in CONDITIONAL_RULES if r.then_term == "healthdcatap:hasVariables")
    assert rule.when_value == "true"


# --------------------------------------------------------------------------
# The three tiers, now that all three shapes have been read
# --------------------------------------------------------------------------


def test_all_three_tiers_pin_a_distinct_access_right() -> None:
    values = set(TIER_ACCESS_RIGHT.values())
    assert len(values) == len(Tier) == 3
    assert all(iri.startswith(ACCESS_RIGHT_VOCABULARY) for iri in values)


@pytest.mark.parametrize(
    ("tier", "notation"),
    [(Tier.PUBLIC, "PUBLIC"), (Tier.NON_PUBLIC, "NON_PUBLIC"), (Tier.RESTRICTED, "RESTRICTED")],
)
def test_each_tier_pins_the_value_its_shapes_declare(tier: Tier, notation: str) -> None:
    assert TIER_ACCESS_RIGHT[tier] == f"{ACCESS_RIGHT_VOCABULARY}{notation}"


def test_an_access_right_resolves_back_to_its_tier() -> None:
    for tier, iri in TIER_ACCESS_RIGHT.items():
        assert tier_for_access_right(iri) is tier


def test_an_access_right_outside_the_three_is_rejected() -> None:
    """The vocabulary has other members, and those fall under no tier at all.

    Rounding one of them to the nearest tier would validate a dataset against
    constraints that do not apply to it.
    """
    with pytest.raises(KeyError, match="no HealthDCAT-AP tier pins"):
        tier_for_access_right(f"{ACCESS_RIGHT_VOCABULARY}SENSITIVE")


def test_the_tiers_are_mutually_exclusive() -> None:
    """One mandatory property, one pinned value each, so no dataset satisfies two.

    This is why the tier is a decision rather than a level of completeness.
    """
    prop = find("access rights")
    for tier in Tier:
        rule = prop.rule_for(tier)
        assert rule.cardinality == Cardinality(1, 1)
        assert rule.is_required

    for tier in Tier:
        others = {t for t in Tier if t is not tier}
        assert all(TIER_ACCESS_RIGHT[tier] != TIER_ACCESS_RIGHT[other] for other in others)


# --- The counter-intuitive part ------------------------------------------


def test_restricted_requires_no_more_metadata_than_public() -> None:
    """The names suggest otherwise, which is exactly why this is pinned."""
    assert set(mandatory_terms(Tier.RESTRICTED)) == set(mandatory_terms(Tier.PUBLIC))


def test_non_public_is_the_strictest_tier() -> None:
    counts = {tier: len(mandatory_terms(tier)) for tier in Tier}
    assert counts[Tier.NON_PUBLIC] > counts[Tier.PUBLIC]
    assert counts[Tier.NON_PUBLIC] > counts[Tier.RESTRICTED]
    assert SUPERSET_TIER is Tier.NON_PUBLIC


def test_the_four_extra_obligations_are_exactly_the_recorded_ones() -> None:
    extra = set(mandatory_terms(Tier.NON_PUBLIC)) - set(mandatory_terms(Tier.PUBLIC))
    assert extra == set(NON_PUBLIC_ONLY_TERMS)


def test_the_obligation_sets_are_nested_even_though_the_tiers_are_not() -> None:
    """Which is what makes gathering the superset worthwhile."""
    superset = set(mandatory_terms(SUPERSET_TIER))
    for tier in Tier:
        assert set(mandatory_terms(tier)) <= superset


# --- What build actually has to produce ----------------------------------


def test_required_terms_adds_the_conditional_obligation() -> None:
    """A clinical dataset declares structured data, so it owes its variables."""
    for tier in Tier:
        terms = required_terms(tier)
        assert "healthdcatap:hasVariables" in terms
        assert "healthdcatap:hasStructuredData" in terms
        assert len(set(terms)) == len(terms)


def test_required_terms_covers_the_mandatory_set() -> None:
    for tier in Tier:
        assert set(mandatory_terms(tier)) <= set(required_terms(tier))


def test_the_superset_is_fifteen_terms() -> None:
    assert len(required_terms(SUPERSET_TIER)) == 15


# --- The health category vocabulary --------------------------------------


def test_the_concept_scheme_and_the_concept_base_differ_by_a_separator() -> None:
    """Concatenating onto the scheme IRI directly would produce a broken concept IRI."""
    assert not HEALTH_CATEGORY_SCHEME.endswith("/")
    assert f"{HEALTH_CATEGORY_SCHEME}/" == HEALTH_CATEGORY_BASE


def test_verified_categories_build_absolute_iris() -> None:
    for notation in HEALTH_CATEGORIES:
        iri = health_category_iri(notation)
        assert iri.startswith("https://")
        assert iri.endswith(f"/{notation}")


def test_category_notations_are_four_uppercase_letters() -> None:
    for notation in HEALTH_CATEGORIES:
        assert re.fullmatch(r"[A-Z]{4}", notation), notation


def test_every_verified_category_has_a_label() -> None:
    for notation, label in HEALTH_CATEGORIES.items():
        assert len(label) > 20, notation


def test_the_vocabulary_is_no_longer_partial() -> None:
    """This test previously asserted the opposite, and that was its job.

    While only half the file had been read, ``HEALTH_CATEGORY_LIST_IS_PARTIAL``
    recorded the gap and a test pinned it, so closing the gap had to break a
    test rather than pass unnoticed. The file has since been read in full.
    """
    assert len(HEALTH_CATEGORIES) == 17
    assert "EHRS" in HEALTH_CATEGORIES


def test_a_notation_outside_the_scheme_is_rejected() -> None:
    with pytest.raises(KeyError, match="not in the scheme"):
        health_category_iri("ZZZZ")


def test_health_category_is_mandatory_and_must_be_an_iri_in_every_tier() -> None:
    """Which is why the vocabulary gap blocks build rather than merely limiting it."""
    prop = find("health category")
    for tier in Tier:
        assert prop.rule_for(tier).is_required
    constraint = value_constraint("healthdcatap:healthCategory")
    assert constraint is not None
    assert constraint.node_kind is NodeKind.IRI


# --------------------------------------------------------------------------
# The controlled vocabularies, now read in full
# --------------------------------------------------------------------------


def test_the_health_category_scheme_holds_seventeen_concepts() -> None:
    """The scheme's own scope note names seventeen Article 51 categories."""
    assert len(HEALTH_CATEGORIES) == 17


def test_the_ehr_category_is_the_one_read_from_the_file() -> None:
    """The value that goes into a mandatory field, so it is pinned literally.

    An earlier version of this module refused ``EHRS`` because it had only been
    seen in a model-generated summary. The file has since been read in full.
    """
    assert HEALTH_CATEGORY_FOR_EHR == "EHRS"
    assert HEALTH_CATEGORIES["EHRS"] == "Electronic health data from EHRs"
    assert health_category_iri("EHRS").endswith("/healthcategories/EHRS")


def test_the_ehr_category_is_the_only_one_mentioning_ehrs() -> None:
    """Which is what makes choosing it a reading rather than a guess."""
    mentioning = [code for code, label in HEALTH_CATEGORIES.items() if "EHR" in label]
    assert mentioning == ["EHRS"]


def test_device_generated_data_is_a_different_category() -> None:
    """``PGEH`` is the near miss: both labels start "Personal electronic health data".

    An earlier version of this test asserted the chosen notation was not
    ``PGEH``, which mypy correctly rejected as comparing two literals that can
    never be equal — a test that checked nothing. What is worth checking is that
    the two categories are distinguishable by what they say.
    """
    chosen = HEALTH_CATEGORIES[HEALTH_CATEGORY_FOR_EHR]
    device = HEALTH_CATEGORIES["PGEH"]
    assert chosen != device
    assert "medical devices" in device
    assert "medical devices" not in chosen


def test_health_category_is_multi_valued_so_a_dataset_may_carry_several() -> None:
    prop = find("health category")
    for tier in Tier:
        assert prop.rule_for(tier).cardinality.maximum is None


def test_an_unknown_health_category_is_rejected() -> None:
    with pytest.raises(KeyError, match="not in the scheme"):
        health_category_iri("NOPE")


def test_the_verbatim_footnote_marker_is_preserved() -> None:
    """Tidying it would make this table disagree with the file it transcribes."""
    assert "Council34" in HEALTH_CATEGORIES["EHCT"]


@pytest.mark.parametrize("notation", list(HEALTH_CATEGORIES))
def test_every_health_category_notation_is_four_uppercase_characters(notation: str) -> None:
    assert re.fullmatch(r"[A-Z]{4}", notation), notation


# --- Access rights -------------------------------------------------------


def test_the_three_tiered_access_rights_carry_definitions() -> None:
    assert set(ACCESS_RIGHT_DEFINITIONS) == {"PUBLIC", "NON_PUBLIC", "RESTRICTED"}
    for code, definition in ACCESS_RIGHT_DEFINITIONS.items():
        assert len(definition) > 50, code


def test_the_default_tier_follows_the_vocabularys_own_definition() -> None:
    """NON_PUBLIC is about privacy; RESTRICTED is about payment, NDAs and indecision.

    A pseudonymised clinical dataset is withheld for the first reason, not the
    second, which is what makes this a reading of the authority list rather than
    a preference.
    """
    assert DEFAULT_TIER is Tier.NON_PUBLIC
    assert "privacy" in ACCESS_RIGHT_DEFINITIONS["NON_PUBLIC"]
    assert "personal" in ACCESS_RIGHT_DEFINITIONS["NON_PUBLIC"]
    assert "payment" in ACCESS_RIGHT_DEFINITIONS["RESTRICTED"]
    assert "non-disclosure" in ACCESS_RIGHT_DEFINITIONS["RESTRICTED"]
    assert "privacy" not in ACCESS_RIGHT_DEFINITIONS["RESTRICTED"]


def test_the_default_tier_is_also_the_strictest() -> None:
    """So switching away from the default never requires gathering more metadata."""
    assert DEFAULT_TIER is SUPERSET_TIER


def test_the_untiered_access_rights_belong_to_no_tier() -> None:
    for notation in UNTIERED_ACCESS_RIGHTS:
        with pytest.raises(KeyError, match="no HealthDCAT-AP tier pins"):
            tier_for_access_right(access_right_iri(notation))


def test_untiered_and_tiered_access_rights_do_not_overlap() -> None:
    assert not set(UNTIERED_ACCESS_RIGHTS) & set(ACCESS_RIGHT_DEFINITIONS)


def test_access_right_iris_round_trip_through_the_tier_lookup() -> None:
    for tier in Tier:
        assert tier_for_access_right(access_right_iri(tier.name)) is tier


def test_an_access_right_outside_the_authority_list_is_rejected() -> None:
    with pytest.raises(KeyError, match="not in the authority list"):
        access_right_iri("INVENTED")


# --- Data themes ---------------------------------------------------------


def test_the_data_theme_scheme_holds_fourteen_concepts() -> None:
    assert len(DATA_THEMES) == 14


def test_the_health_theme_is_the_one_read_from_the_file() -> None:
    assert DATA_THEME_FOR_HEALTH == "HEAL"
    assert DATA_THEMES["HEAL"] == "Health"
    assert data_theme_iri("HEAL") == f"{DATA_THEME_BASE}HEAL"


def test_an_unknown_data_theme_is_rejected() -> None:
    with pytest.raises(KeyError, match="not in the scheme"):
        data_theme_iri("NOPE")


def test_theme_is_mandatory_and_must_be_an_iri() -> None:
    """Which is why this vocabulary gated build as much as the health categories."""
    prop = find("theme")
    for tier in Tier:
        assert prop.rule_for(tier).is_required
    constraint = value_constraint("dcat:theme")
    assert constraint is not None
    assert constraint.node_kind is NodeKind.IRI


# --- The trap worth a test ----------------------------------------------


def test_the_two_vocabularies_use_different_url_schemes() -> None:
    """One https, one http. Using the wrong base yields a plausible dead IRI.

    This is exactly the kind of mistake that validates locally and fails only
    when somebody tries to resolve the IRI, so it is pinned here.
    """
    assert HEALTH_CATEGORY_BASE.startswith("https://")
    assert DATA_THEME_BASE.startswith("http://")
    assert not DATA_THEME_BASE.startswith("https://")


def test_every_vocabulary_base_ends_in_a_separator() -> None:
    for base in (HEALTH_CATEGORY_BASE, DATA_THEME_BASE, ACCESS_RIGHT_VOCABULARY):
        assert base.endswith("/"), base


def test_the_three_mandatory_iri_values_commissura_emits_are_all_resolvable_shapes() -> None:
    """A smoke test over the whole chain: the values build will actually write."""
    assert health_category_iri(HEALTH_CATEGORY_FOR_EHR).startswith("https://")
    assert data_theme_iri(DATA_THEME_FOR_HEALTH).startswith("http://")
    assert access_right_iri(DEFAULT_TIER.name) == TIER_ACCESS_RIGHT[DEFAULT_TIER]


# --------------------------------------------------------------------------
# The dataset-type authority list
# --------------------------------------------------------------------------


def test_the_dataset_type_scheme_holds_the_transcribed_concepts() -> None:
    """Twenty-two of the source's twenty-five; three omitted, none clinical."""
    assert len(DATASET_TYPES) == 22


def test_the_synthetic_type_is_the_one_read_from_the_file() -> None:
    assert DATASET_TYPE_FOR_SYNTHETIC == "SYNTHETIC_DATA"
    assert DATASET_TYPES["SYNTHETIC_DATA"] == "Synthetic data"
    assert dataset_type_iri("SYNTHETIC_DATA").endswith("/dataset-type/SYNTHETIC_DATA")


def test_an_unknown_dataset_type_is_rejected() -> None:
    """A typo would otherwise build a plausible IRI that resolves to nothing."""
    with pytest.raises(KeyError, match="not in the authority list"):
        dataset_type_iri("SYNTETIC_DATA")


def test_dataset_type_notations_are_uppercase_tokens() -> None:
    for notation in DATASET_TYPES:
        assert re.fullmatch(r"[A-Z][A-Z_]*", notation), notation


def test_every_dataset_type_has_a_label_and_builds_an_absolute_iri() -> None:
    for notation, label in DATASET_TYPES.items():
        assert label, notation
        assert dataset_type_iri(notation).startswith("http://")


def test_the_dataset_type_base_is_served_over_plain_http() -> None:
    """Like data-theme and unlike health categories, which use https."""
    assert f"{DATASET_TYPE_SCHEME}/" == DATASET_TYPE_BASE
    assert DATASET_TYPE_BASE.startswith("http://")


# --------------------------------------------------------------------------
# The DPV personal-data category, and the namespace the profile gets wrong
# --------------------------------------------------------------------------


def test_the_personal_data_concept_uses_dpvs_current_namespace() -> None:
    """Not the one the profile's own worked example declares.

    `html/examples/dpvhasPersonalData.ttl` writes
    ``@prefix dpvpd: <https://w3id.org/dpv/dpv-pd#>``. DPV's Personal Data
    extension states that the namespace for its terms is
    ``https://w3id.org/dpv/pd#``, and ``dpv-pd`` appears nowhere in its
    vocabulary file as an alias. Copying the example would emit an IRI no
    current DPV release defines — and `w3id.org` redirects both document URLs
    to the same page, so following the link confirms nothing. Pinned because
    the next person to read that example will reach for it.
    """
    assert NAMESPACES["pd"] == "https://w3id.org/dpv/pd#"
    assert "dpv-pd" not in PERSONAL_DATA_CATEGORY
    assert PERSONAL_DATA_CATEGORY == "https://w3id.org/dpv/pd#HealthRecord"


def test_the_personal_data_concept_carries_both_classes_dpv_declares() -> None:
    """``dpv:PersonalData`` for the range, special category for the reader.

    ``healthdcat-ap/range.ttl`` constrains this path with
    ``sh:class dpv:PersonalData``, which is satisfied by an ``rdf:type`` triple
    in the data graph and by nothing else. The second class is DPV's own
    statement about this concept and is the half an access body reads, since
    DPV sources it to GDPR Art. 9(1).
    """
    assert PERSONAL_DATA_CATEGORY_TYPES == (
        "dpv:PersonalData",
        "dpv:SpecialCategoryPersonalData",
    )
    assert PERSONAL_DATA_CATEGORY_LABEL == "Health Record"
