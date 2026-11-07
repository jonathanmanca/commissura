"""Data the generator draws from. No behaviour lives here.

Keeping the vocabulary separate from the generators is what makes the project
extensible by somebody who is not a Python programmer: adding an analyte, a
hospital or a radiology phrase means editing a table, not a function. It also
keeps the generators short enough to read.

On the clinical content: the LOINC codes below are the common ones for the
panels modelled, and the reference intervals are typical adult ranges. They are
plausible, not authoritative. Anyone wiring this to real laboratory data must
check both against a current LOINC release and the issuing laboratory's own
intervals, which vary by method and instrument. For generating synthetic test
material the distinction does not matter; for anything else it does.
"""

from __future__ import annotations

from dataclasses import dataclass

from commissura.models import Sex


@dataclass(frozen=True, slots=True)
class Analyte:
    """One measurable quantity, with the reference interval it is read against.

    Reference intervals are sex-specific because several common analytes
    genuinely differ, and a generator that ignores that produces results a
    clinician would spot as fake immediately.
    """

    loinc_code: str
    display: str
    unit: str
    male_range: tuple[float, float]
    female_range: tuple[float, float]
    decimals: int = 1

    def reference_for(self, sex: Sex) -> tuple[float, float]:
        """Return the reference interval that applies to ``sex``."""
        return self.male_range if sex is Sex.MALE else self.female_range


@dataclass(frozen=True, slots=True)
class Panel:
    """An ordered group of analytes, reported together as one HL7 message."""

    code: str
    name: str
    analytes: tuple[Analyte, ...]


@dataclass(frozen=True, slots=True)
class SeriesTemplate:
    """One series inside an imaging protocol."""

    modality: str
    description: str
    protocol_name: str
    instance_range: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ImagingProtocol:
    """A study protocol: what was scanned, how, and with which series."""

    modality: str
    body_part: str
    study_description: str
    series: tuple[SeriesTemplate, ...]


@dataclass(frozen=True, slots=True)
class Site:
    """A hospital or laboratory, with the address that appears in its exports."""

    name: str
    address: str
    city: str
    area_code: str


FAMILY_NAMES: tuple[str, ...] = (
    "ROSSI",
    "RUSSO",
    "FERRARI",
    "ESPOSITO",
    "BIANCHI",
    "ROMANO",
    "COLOMBO",
    "BRUNO",
    "RICCI",
    "MARINO",
    "GRECO",
    "GALLO",
    "CONTI",
    "DE LUCA",
    "COSTA",
    "GIORDANO",
    "MANCINI",
    "RIZZO",
    "LOMBARDI",
    "MORETTI",
    "BARBIERI",
    "FONTANA",
    "SANTORO",
    "MARIANI",
    "RINALDI",
    "CARUSO",
    "FERRARA",
    "GALLI",
    "MARTINI",
    "LEONE",
    "LONGO",
    "GENTILE",
    "MARTINELLI",
    "VITALE",
    "LOMBARDO",
    "SERRA",
    "CODDA",
    "PIRAS",
    "MELIS",
    "SANNA",
)
"""Common Italian family names. The last four are frequent in Sardinia, which
keeps the cohort from looking like it came from one region only."""

GIVEN_NAMES_MALE: tuple[str, ...] = (
    "MARIO",
    "GIUSEPPE",
    "ANTONIO",
    "GIOVANNI",
    "LUIGI",
    "FRANCESCO",
    "ANDREA",
    "ALESSANDRO",
    "MARCO",
    "LUCA",
    "PAOLO",
    "ROBERTO",
    "STEFANO",
    "DAVIDE",
    "SALVATORE",
    "MATTEO",
    "SIMONE",
    "FABIO",
    "CLAUDIO",
    "MASSIMO",
    "JONATHAN",
)

GIVEN_NAMES_FEMALE: tuple[str, ...] = (
    "MARIA",
    "ANNA",
    "GIUSEPPINA",
    "ROSA",
    "ANGELA",
    "GIOVANNA",
    "TERESA",
    "LUCIA",
    "CARMELA",
    "FRANCESCA",
    "ELENA",
    "CHIARA",
    "SARA",
    "LAURA",
    "VALENTINA",
    "SILVIA",
    "PAOLA",
    "MARTINA",
    "GIULIA",
    "FEDERICA",
    "EVA",
)

STREETS: tuple[str, ...] = (
    "Via Garibaldi",
    "Via Roma",
    "Corso Vittorio Emanuele",
    "Via Dante",
    "Via Mazzini",
    "Viale della Repubblica",
    "Via Cavour",
    "Piazza Marconi",
    "Via San Francesco",
    "Via Trieste",
    "Via Milano",
    "Largo Europa",
    "Via Aldo Moro",
    "Via Giovanni Verga",
    "Via Carducci",
)

CITIES: tuple[tuple[str, str, str, str], ...] = (
    ("Torino", "TO", "10121", "11"),
    ("Milano", "MI", "20121", "2"),
    ("Roma", "RM", "00184", "6"),
    ("Napoli", "NA", "80133", "81"),
    ("Bologna", "BO", "40121", "51"),
    ("Firenze", "FI", "50122", "55"),
    ("Genova", "GE", "16121", "10"),
    ("Palermo", "PA", "90133", "91"),
    ("Cagliari", "CA", "09124", "70"),
    ("Bari", "BA", "70121", "80"),
    ("Padova", "PD", "35121", "49"),
    ("Verona", "VR", "37121", "45"),
)
"""City, province, postal code, telephone area code without its leading zero."""

SITES: tuple[Site, ...] = (
    Site("OSPEDALE SINTETICO DI COLLEVERDE", "Via dei Tigli 40", "Milano", "2"),
    Site("AZIENDA OSPEDALIERA SINTETICA NORDVALLE", "Corso delle Betulle 88", "Torino", "11"),
    Site("IRCCS SINTETICO MAREBIANCO", "Via dei Glicini 35", "Milano", "2"),
    Site("PRESIDIO OSPEDALIERO SINTETICO VALLEDORO", "Via dei Lecci 92", "Cagliari", "70"),
    Site("POLICLINICO UNIVERSITARIO SINTETICO PIETRALTA", "Viale dei Platani 155", "Roma", "6"),
)
"""Invented institutions, at invented addresses, every name carrying ``SINTETIC``.

Two rules are at work and both are deliberate.

The institution must not be a real one. Appending a marker to the name of an
existing hospital does not make it fictional: it produces fabricated clinical
records attributed to a real organisation, at that organisation's real address.
The dedications and street names here are invented, while the cities are real,
because a real city is realism rather than attribution.

The marker must be present in every name with no exceptions, so the rule is
testable as an invariant instead of a convention. A generated file that escapes
into a shared drive should announce what it is in its own text.
"""

LABORATORIES: tuple[str, ...] = (
    "LAB ANALISI CENTRALE",
    "LABORATORIO PATOLOGIA CLINICA",
    "SERVIZIO DI MEDICINA DI LABORATORIO",
)

CLINICAL_SPECIALTIES: tuple[str, ...] = (
    "Medicina Interna",
    "Cardiologia",
    "Oncologia Medica",
    "Nefrologia",
    "Endocrinologia",
    "Pneumologia",
)

RADIOLOGIST_ROLES: tuple[str, ...] = (
    "Dirigente Medico Radiodiagnostica",
    "Dirigente Medico Medicina Nucleare",
)

_HAEMATOLOGY = (
    Analyte("718-7", "Hemoglobin [Mass/volume] in Blood", "g/dL", (13.0, 17.0), (12.0, 15.5)),
    Analyte("4544-3", "Hematocrit [Volume Fraction] of Blood", "%", (40.0, 52.0), (36.0, 48.0)),
    Analyte("789-8", "Erythrocytes [#/volume] in Blood", "10*6/uL", (4.5, 5.9), (4.0, 5.2), 2),
    Analyte("6690-2", "Leukocytes [#/volume] in Blood", "10*3/uL", (4.0, 11.0), (4.0, 11.0), 2),
    Analyte("777-3", "Platelets [#/volume] in Blood", "10*3/uL", (150.0, 400.0), (150.0, 400.0), 0),
)

_CHEMISTRY = (
    Analyte(
        "2345-7",
        "Glucose [Mass/volume] in Serum or Plasma",
        "mg/dL",
        (70.0, 100.0),
        (70.0, 100.0),
        0,
    ),
    Analyte(
        "2160-0", "Creatinine [Mass/volume] in Serum or Plasma", "mg/dL", (0.7, 1.3), (0.6, 1.1), 2
    ),
    Analyte(
        "3094-0",
        "Urea nitrogen [Mass/volume] in Serum or Plasma",
        "mg/dL",
        (7.0, 20.0),
        (7.0, 20.0),
        0,
    ),
    Analyte(
        "2951-2",
        "Sodium [Moles/volume] in Serum or Plasma",
        "mmol/L",
        (136.0, 145.0),
        (136.0, 145.0),
        0,
    ),
    Analyte(
        "2823-3", "Potassium [Moles/volume] in Serum or Plasma", "mmol/L", (3.5, 5.1), (3.5, 5.1), 1
    ),
)

_LIVER = (
    Analyte(
        "1920-8",
        "Aspartate aminotransferase [Enzymatic activity/volume]",
        "U/L",
        (10.0, 40.0),
        (10.0, 35.0),
        0,
    ),
    Analyte(
        "1742-6",
        "Alanine aminotransferase [Enzymatic activity/volume]",
        "U/L",
        (7.0, 56.0),
        (7.0, 45.0),
        0,
    ),
    Analyte(
        "1975-2",
        "Bilirubin total [Mass/volume] in Serum or Plasma",
        "mg/dL",
        (0.3, 1.2),
        (0.3, 1.2),
        2,
    ),
)

_INFLAMMATION = (
    Analyte(
        "1988-5",
        "C reactive protein [Mass/volume] in Serum or Plasma",
        "mg/L",
        (0.0, 5.0),
        (0.0, 5.0),
        1,
    ),
)

_THYROID = (
    Analyte(
        "3016-3",
        "Thyrotropin [Units/volume] in Serum or Plasma",
        "mIU/L",
        (0.4, 4.0),
        (0.4, 4.0),
        2,
    ),
)

PANELS: tuple[Panel, ...] = (
    Panel("CBC", "Emocromo completo", _HAEMATOLOGY),
    Panel("CHEM7", "Profilo metabolico di base", _CHEMISTRY),
    Panel("LFT", "Funzionalita epatica", _LIVER),
    Panel("INFL", "Indici di flogosi", _INFLAMMATION),
    Panel("THY", "Funzionalita tiroidea", _THYROID),
)

PROTOCOLS: tuple[ImagingProtocol, ...] = (
    ImagingProtocol(
        "CT",
        "CHEST",
        "TC torace con mezzo di contrasto",
        (
            SeriesTemplate("CT", "Scout", "Topogramma", (2, 3)),
            SeriesTemplate("CT", "Torace basale 1.5mm", "Chest_Plain", (180, 320)),
            SeriesTemplate("CT", "Torace post contrasto 1.5mm", "Chest_CE", (180, 320)),
        ),
    ),
    ImagingProtocol(
        "MR",
        "BRAIN",
        "RM encefalo senza e con mezzo di contrasto",
        (
            SeriesTemplate("MR", "Localizer", "3pl_loc", (3, 3)),
            SeriesTemplate("MR", "T1 MPRAGE sag", "t1_mprage_sag_p2_iso", (176, 208)),
            SeriesTemplate("MR", "T2 FLAIR ax", "t2_tirm_tra_dark-fluid", (24, 40)),
            SeriesTemplate("MR", "DWI ax", "ep2d_diff_tra", (60, 90)),
        ),
    ),
    ImagingProtocol(
        "PT",
        "WHOLEBODY",
        "PET-TC total body con FDG",
        (
            SeriesTemplate("CT", "CT attenuation correction", "CT_AC", (240, 400)),
            SeriesTemplate("PT", "PET corpo intero", "WB_3D_MAC", (240, 400)),
        ),
    ),
)

RADIOLOGY_INDICATIONS: dict[str, tuple[str, ...]] = {
    "CHEST": (
        "Stadiazione di neoplasia polmonare nota.",
        "Dolore toracico persistente, sospetta embolia polmonare.",
        "Controllo a distanza in paziente oncologico.",
        "Screening in paziente con familiarita oncologica.",
    ),
    "BRAIN": (
        "Cefalea di recente insorgenza, non responsiva alla terapia.",
        "Deficit neurologico focale transitorio in accertamento.",
        "Episodio sincopale, esclusione di lesioni strutturali.",
        "Controllo a distanza di lesione nota.",
    ),
    "WHOLEBODY": (
        "Stadiazione di neoplasia nota.",
        "Rivalutazione post-terapia.",
        "Sospetta ripresa di malattia per incremento dei marcatori.",
        "Ricerca di neoplasia primitiva occulta.",
    ),
}
"""Clinical questions, keyed by the body part examined.

Keyed rather than pooled because the alternative is a chest CT asked for to
investigate a headache. A pooled vocabulary is the kind of shortcut that makes
synthetic data obviously synthetic to the one audience whose opinion matters.
"""

RADIOLOGY_FINDINGS: dict[str, tuple[str, ...]] = {
    "CHEST": (
        "Non si apprezzano lesioni focali a carico del parenchima polmonare.",
        "Nodulo solido di 8 mm al lobo superiore destro, invariato rispetto al controllo "
        "precedente.",
        "Linfonodi mediastinici di dimensioni nei limiti.",
        "Non versamento pleurico ne pericardico.",
        "Modesta accentuazione della trama interstiziale ai campi polmonari inferiori.",
        "Trachea e bronchi principali pervi, in asse.",
    ),
    "BRAIN": (
        "Non alterazioni densitometriche a carico del parenchima encefalico.",
        "Sistema ventricolare in asse, di ampiezza regolare.",
        "Non segni di sanguinamento intra o extra-assiale.",
        "Modeste alterazioni di segnale della sostanza bianca periventricolare, di probabile "
        "natura vascolare cronica.",
        "Strutture della linea mediana in sede.",
        "Non alterazioni patologiche dopo somministrazione di mezzo di contrasto.",
    ),
    "WHOLEBODY": (
        "Captazione fisiologica del radiofarmaco a livello cerebrale e miocardico.",
        "Non si osservano aree di ipercaptazione patologica.",
        "Modesta captazione linfonodale laterocervicale destra, di dubbio significato.",
        "Fisiologica escrezione urinaria del tracciante.",
        "Captazione midollare diffusa, compatibile con stimolazione da fattori di crescita.",
        "Non lesioni ipermetaboliche a carico dello scheletro.",
    ),
}
"""Reported findings, keyed by the body part examined.

Each pool holds at least as many entries as a single report can draw, so the
sampling never has to repeat itself inside one document.
"""

RADIOLOGY_CONCLUSIONS: tuple[str, ...] = (
    "Quadro sostanzialmente stabile rispetto al precedente controllo.",
    "Non evidenza di malattia in progressione.",
    "Si consiglia controllo a sei mesi.",
    "Reperti nei limiti di norma per eta.",
    "Si suggerisce approfondimento con esame istologico.",
)

DISCHARGE_REASONS: tuple[str, ...] = (
    "Ricovero per riacutizzazione di broncopneumopatia cronica ostruttiva.",
    "Ricovero programmato per ciclo di chemioterapia.",
    "Ricovero per scompenso glicometabolico.",
    "Accesso in urgenza per dolore toracico.",
    "Ricovero per approfondimento diagnostico di anemia.",
)

DISCHARGE_INSTRUCTIONS: tuple[str, ...] = (
    "Prosecuzione della terapia domiciliare come da schema allegato.",
    "Controllo ematochimico fra trenta giorni.",
    "Visita di controllo ambulatoriale fra tre mesi.",
    "Si raccomanda astensione dal fumo e attivita fisica regolare.",
)
