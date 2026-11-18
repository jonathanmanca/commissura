"""Render clinical reports as free text.

Free text is where de-identification actually fails. A structured field either
holds an identifier or it does not, and a scrubber configured for HL7 PID-5
finds every name in every message. Prose has no fields: the name arrives inside
a sentence, abbreviated, in the genitive, next to a clinical term that looks
just like it. This is the material that separates a de-identifier that works
from one that reports that it worked.

So the reports here are built to be hostile in the specific ways real reports
are:

- The header carries identifiers in labelled positions, which is the easy case
  and establishes a baseline.
- The body carries them inside clinical sentences, with no label in front —
  a comparison date, a referring colleague, the hospital where a previous study
  was done. Field-based scrubbing cannot see any of it.
- The signature block repeats the author, so a scrubber that stops at the first
  match under-reports.

Every one of those placements is recorded in the ground truth, so the difficulty
is measurable rather than anecdotal.

**A distinction this module is careful about.** A defect is damaged data; an
identifier sitting in prose is not damaged data, it is how reports are written.
So a corpus generated at ``--defect-rate 0`` is clean *and still hard*: the
comparison sentence, with its date and the institution that performed the
earlier study, is always present, because a report without it would be less
realistic rather than more. What the defect rate controls is the extra hazard
layered on top — a colleague named mid-sentence, an unsigned report, text cut
off by a fixed-width column. Anyone who generates a clean corpus, scrubs the
header fields and sees a perfect score has learnt the lesson this module exists
to teach.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from random import Random

from commissura.annotate import AnnotatedText, Phi
from commissura.generate.defects import DefectInjector
from commissura.generate.vocabulary import (
    DISCHARGE_INSTRUCTIONS,
    DISCHARGE_REASONS,
    RADIOLOGY_CONCLUSIONS,
    RADIOLOGY_FINDINGS,
    RADIOLOGY_INDICATIONS,
    Site,
)
from commissura.models import (
    ClinicalReport,
    ImagingStudy,
    Person,
    PhiCategory,
    PhiSpan,
    ReportKind,
)

_ITALIAN_DATE = "%d/%m/%Y"
"""Reports are written for humans, so dates appear as humans write them.

This is not a defect on its own: it is simply how clinical prose looks. It is
also why a date detector tuned on HL7 timestamps finds nothing here.
"""


def sample_radiology_report(
    rng: Random,
    *,
    study: ImagingStudy,
    author_name: str,
    author_role: str,
    site: Site,
) -> ClinicalReport:
    """Invent the structured content of a radiology report for a study.

    Indications and findings are drawn from the pools for the body part that was
    actually examined, so a chest CT is not reported with the phrasing of a PET
    scan. Mixing them is the single detail that makes synthetic reports read as
    fake to a clinician, however correct everything around them is.

    Args:
        rng: Seeded random source.
        study: The study being reported; supplies the body part and the timing.
        author_name: Reporting radiologist.
        author_role: Their job title.
        site: Reporting institution.

    Returns:
        The report content, not yet rendered to text.

    Raises:
        KeyError: If the study's body part has no phrase pools. That is a gap in
            the vocabulary rather than bad input, so it should fail loudly
            instead of falling back to generic text.
    """
    indications = RADIOLOGY_INDICATIONS[study.body_part]
    findings = RADIOLOGY_FINDINGS[study.body_part]
    finding_count = rng.randrange(2, min(5, len(findings) + 1))
    return ClinicalReport(
        kind=ReportKind.RADIOLOGY,
        authored_at=study.study_date + timedelta(hours=rng.randrange(2, 72)),
        author_name=author_name,
        author_role=author_role,
        institution=site.name,
        indication=rng.choice(indications),
        technique=study.study_description,
        findings=tuple(rng.sample(findings, finding_count)),
        conclusion=rng.choice(RADIOLOGY_CONCLUSIONS),
        linked_study_uid=study.study_uid,
    )


def sample_discharge_report(
    rng: Random,
    *,
    admitted_at: datetime,
    author_name: str,
    specialty: str,
    site: Site,
) -> ClinicalReport:
    """Invent the structured content of a discharge letter.

    Args:
        rng: Seeded random source.
        admitted_at: When the admission began.
        author_name: Discharging clinician.
        specialty: The ward's specialty.
        site: The institution.

    Returns:
        The report content, not yet rendered to text.
    """
    return ClinicalReport(
        kind=ReportKind.DISCHARGE,
        authored_at=admitted_at + timedelta(days=rng.randrange(2, 14)),
        author_name=author_name,
        author_role=specialty,
        institution=site.name,
        indication=rng.choice(DISCHARGE_REASONS),
        technique="",
        findings=tuple(rng.sample(DISCHARGE_INSTRUCTIONS, rng.randrange(2, 4))),
        conclusion=rng.choice(DISCHARGE_INSTRUCTIONS),
    )


def render_report(
    report: ClinicalReport,
    *,
    person: Person,
    site: Site,
    path: str,
    rng: Random,
    injector: DefectInjector,
    previous_study_date: datetime | None = None,
    previous_site: Site | None = None,
) -> tuple[str, tuple[PhiSpan, ...]]:
    """Render a report to text, recording where every identifier was placed.

    Args:
        report: The content to render.
        person: The patient.
        site: The reporting institution.
        path: Corpus-relative path, recorded on every span.
        rng: Seeded random source, for phrasing choices.
        injector: Decides and records defects.
        previous_study_date: If given, the body may refer to a comparison study
            on this date in running prose.
        previous_site: If given, the body may name where that study was done.

    Returns:
        The report text and its identifier spans.
    """
    text = AnnotatedText(path)
    heading = (
        "REFERTO DI DIAGNOSTICA PER IMMAGINI"
        if report.kind is ReportKind.RADIOLOGY
        else "LETTERA DI DIMISSIONE"
    )

    text.line(Phi(site.name, PhiCategory.INSTITUTION))
    text.line(Phi(site.address, PhiCategory.ADDRESS), " - ", Phi(site.city, PhiCategory.ADDRESS))
    text.line()
    text.line(heading)
    text.line("=" * len(heading))
    text.line()

    # --- Header: identifiers in labelled positions. The easy case. ---
    text.line("Paziente: ", Phi(person.full_name, PhiCategory.PERSON_NAME))
    text.line(
        "Nato/a il: ",
        Phi(person.birth_date.strftime(_ITALIAN_DATE), PhiCategory.DATE, "date of birth"),
        "   Eta: ",
        Phi(
            str(person.age_on(report.authored_at.date())),
            PhiCategory.AGE,
            "age in years, re-identifying above 89",
        ),
        " anni",
    )
    # A patient with no codice fiscale gets no codice fiscale line, rather than
    # an empty one or their foreign code under the wrong label. Both
    # alternatives are worse than silence: an empty field is a header a reader
    # would trust, and `Codice fiscale: STPSINTETIC...` states something untrue
    # about what the value is.
    #
    # The report stays linkable without it. `read_report` treats every header
    # as optional and identity resolution falls back to the record number
    # below, which is the institution-scoped key these patients are keyed on
    # anyway. Writing the foreign code here under a *correct* label would be
    # the obvious alternative and would break linkage outright, because
    # `_REPORT_LABELS` recognises four strings and `Codice STP` is not one of
    # them -- every such report would land in `unlinked_report`.
    if person.codice_fiscale:
        text.line("Codice fiscale: ", Phi(person.codice_fiscale, PhiCategory.NATIONAL_ID))
    text.line("Numero nosografico: ", Phi(person.mrn, PhiCategory.PATIENT_ID))
    # An unfilled template placeholder where the date should be. Written as a
    # plain string and *not* as a Phi span, deliberately: `__/__/____` is not an
    # identifier, and recording it as one would put a value in the ground truth
    # that nothing could ever leak, quietly inflating every recall figure
    # measured against this corpus.
    if injector.apply(
        "reports.unreadable_date",
        path,
        "report date left as an unresolved template placeholder",
    ):
        text.line("Data del referto: __/__/____")
    else:
        text.line(
            "Data del referto: ",
            Phi(report.authored_at.strftime(_ITALIAN_DATE), PhiCategory.DATE, "report date"),
        )
    text.line()

    if report.kind is ReportKind.RADIOLOGY:
        text.line("QUESITO CLINICO")
        text.line(report.indication)
        text.line()
        text.line("TECNICA DI ESAME")
        text.line(report.technique)
        text.line()
        text.line("REPERTI")
    else:
        text.line("MOTIVO DEL RICOVERO")
        text.line(report.indication)
        text.line()
        text.line("DECORSO E INDICAZIONI")

    for finding in report.findings:
        text.line(finding)

    # --- Body: identifiers buried in prose. The case that actually matters. ---
    if previous_study_date is not None:
        comparison = previous_study_date.strftime(_ITALIAN_DATE)
        if previous_site is not None:
            text.line(
                "Si confronta con il precedente esame del ",
                Phi(comparison, PhiCategory.DATE, "comparison date inside running prose"),
                " eseguito presso ",
                Phi(
                    previous_site.name,
                    PhiCategory.INSTITUTION,
                    "institution named in running prose, not in a header field",
                ),
                ".",
            )
        else:
            text.line(
                "Si confronta con il precedente esame del ",
                Phi(comparison, PhiCategory.DATE, "comparison date inside running prose"),
                ".",
            )
        # Deliberately *not* logged as an injected defect. A radiologist citing
        # the date of a previous study is ordinary clinical writing, not damaged
        # data, so counting it would make `--defect-rate 0` report defects on a
        # corpus that claims to be clean. The privacy hazard it creates is
        # already captured where it belongs: in the ground-truth spans above.

    if injector.apply(
        "reports.identifier_in_prose",
        path,
        "referring clinician named mid-sentence with no preceding label",
    ):
        text.line(
            "Come concordato con il collega ",
            Phi(
                report.author_name,
                PhiCategory.PROVIDER_NAME,
                "clinician named mid-sentence, no label in front",
            ),
            ", si rimanda a valutazione specialistica.",
        )

    text.line()
    if report.kind is ReportKind.RADIOLOGY:
        text.line("CONCLUSIONI")
    else:
        text.line("TERAPIA ALLA DIMISSIONE")
    text.line(report.conclusion)
    text.line()

    # --- Contact details, in prose, and only in a discharge letter. ---
    #
    # A discharge letter carries a follow-up contact; a radiology report has no
    # reason to. So this fires on some documents and not others, which is what
    # makes the manifest's per-category coverage count mean something.
    #
    # Deliberately written as a sentence rather than a "Recapiti:" header. A
    # labelled field would be found by the scrubber's exact-match pass, which
    # already knows the patient's email from HL7 PID-13. In prose there is no
    # label, so only the email and telephone *patterns* can find it — and that
    # is the one path through the scrubber that no generated corpus exercised.
    #
    # The email is the interesting half: it is built from the patient's own
    # surname, so it is the case where redacting the name first would leave
    # "m.[NAME]@posta.invalid", stop the email pattern matching, and let the
    # domain survive as a leak that looks like a redaction. That ordering bug
    # was found by a unit test on 2026-11-07; from here a plain `generate` can
    # reproduce it.
    if report.kind is ReportKind.DISCHARGE:
        text.line(
            "Per comunicazioni contattare il paziente a ",
            Phi(person.email, PhiCategory.CONTACT, "patient email in running prose"),
            " oppure al numero ",
            Phi(person.phone, PhiCategory.CONTACT, "patient telephone in running prose"),
            ".",
        )
        text.line()

    # --- Signature: a second occurrence of the author. ---
    if injector.apply("reports.missing_author", path, "signature block omitted: report unsigned"):
        text.line("(referto non firmato)")
    else:
        text.line(
            "Dott. ",
            Phi(report.author_name, PhiCategory.PROVIDER_NAME, "signature block"),
        )
        text.line(report.author_role)
        text.line(Phi(site.name, PhiCategory.INSTITUTION, "signature block"))

    content, spans = text.finish()

    # --- Truncation is applied last, and drops any span it cuts through. ---
    if injector.should_apply("reports.truncated"):
        cut = rng.randrange(len(content) // 2, max(len(content) - 10, len(content) // 2 + 1))
        injector.record(
            "reports.truncated",
            path,
            f"text truncated from {len(content)} to {cut} characters mid-sentence",
        )
        content = content[:cut]
        spans = tuple(span for span in spans if span.end <= cut)

    return content, spans
