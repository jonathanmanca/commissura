"""Pseudonyms must not be reused across data permits, and now need not be.

TEHDAS2 D7.2 section 4.4 (p. 41) states it in capitals: "Pseudonyms MUST NOT be
reused across different data permits, to minimise risks of intentional or
unintentional linkage of data by the data user." One key gives one label space
for ever, so before this a holder answering two permits from the same key handed
the same subject labels to two data users -- the unevaluated linkage that
requirement exists to prevent.

Section 4.3 (p. 38) is the other half of the argument: the holder's output
reaches the data user without the access body re-pseudonymising it *only* if the
holder "can implement per project pseudonym generation".

The option is opt-in, and the test that matters most here is the one proving an
unscoped build is byte-identical to what this tool produced before the option
existed. A change to pseudonym derivation that moved existing datasets would need
a migration plan; one that cannot be reached without a flag needs only this.

Every identifier here is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from commissura import layout
from commissura.cli import _permit_of, app
from commissura.deident.keys import SecretKey
from commissura.deident.pseudonymise import (
    DOMAIN_PURPOSES,
    RULE_VERSION,
    SUBJECT_ID_HEX_CHARS,
    Pseudonymiser,
    declare,
    scope_to_permit,
)
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus
from commissura.read.identity import KeyKind

KEY = SecretKey(bytes(range(32)))
PERMIT_A = "IT-HDAB-2029-00417"
PERMIT_B = "IT-HDAB-2029-00892"

runner = CliRunner()


# --------------------------------------------------------------------------
# The derivation
# --------------------------------------------------------------------------


def test_a_subkey_is_an_ordinary_key() -> None:
    """HMAC-SHA256 gives exactly the key length, so nothing downstream changes.

    If it did not, every derivation would need to know about scoping instead of
    only this one function.
    """
    scoped = scope_to_permit(KEY, PERMIT_A)

    assert isinstance(scoped, SecretKey)
    assert len(scoped.material) == len(KEY.material)


def test_two_permits_give_disjoint_subject_labels() -> None:
    """The requirement itself, stated as the property it asks for."""
    identifiers = ["RSSMRA80A01X000Z", "VRDGPP85B02X000V", "DLCFRN62S44X217P"]
    a = {Pseudonymiser(scope_to_permit(KEY, PERMIT_A)).subject_label(i) for i in identifiers}
    b = {Pseudonymiser(scope_to_permit(KEY, PERMIT_B)).subject_label(i) for i in identifiers}

    assert len(a) == len(identifiers)
    assert not a & b


def test_one_permit_stays_deterministic() -> None:
    """Scoping must not cost determinism, which is the whole point of the scheme.

    D7.2 section 4.4 (p. 41) advises deterministic pseudonymisation in the EHDS
    so a data user can recognise the same patient; and two of a holder's
    datasets answering one permit have to agree, or internal linkage breaks.
    """
    first = Pseudonymiser(scope_to_permit(KEY, PERMIT_A)).subject_label("RSSMRA80A01X000Z")
    second = Pseudonymiser(scope_to_permit(KEY, PERMIT_A)).subject_label("RSSMRA80A01X000Z")

    assert first == second


def test_a_subkeys_fingerprint_differs_from_the_root() -> None:
    """Which is what tells an access body whether two datasets are relinkable.

    A fingerprint is the only handle an access body has on that question, so a
    permit-scoped dataset must not advertise the root key's.
    """
    scoped = scope_to_permit(KEY, PERMIT_A)

    assert scoped.fingerprint != KEY.fingerprint
    assert scope_to_permit(KEY, PERMIT_B).fingerprint != scoped.fingerprint


def test_the_permit_reference_is_taken_as_given() -> None:
    """No validation, deliberately: a permit identifier's shape is not ours.

    Italy has no designated access body and the permit template is an
    implementing act expected in March 2027. A tool that rejected a
    well-formed-but-unexpected reference would be inventing that specification.
    """
    assert scope_to_permit(KEY, "a").fingerprint != scope_to_permit(KEY, "b").fingerprint
    assert scope_to_permit(KEY, " a").fingerprint != scope_to_permit(KEY, "a").fingerprint


def test_every_domain_prefix_declares_what_it_derives() -> None:
    """Looked up by hand rather than defaulted, so a new prefix is a visible gap.

    D7.2 section 4.4 (p. 40) asks for the "exact specification of inputs"; a
    prefix with no stated purpose is half of one.
    """
    import commissura.deident.pseudonymise as module

    prefixes = {
        value
        for name, value in vars(module).items()
        if name.startswith("_DOMAIN_") and isinstance(value, str)
    }

    assert prefixes == set(DOMAIN_PURPOSES)
    assert all(purpose for purpose in DOMAIN_PURPOSES.values())


# --------------------------------------------------------------------------
# The declaration
# --------------------------------------------------------------------------


def test_the_declaration_states_the_function_and_its_truncation() -> None:
    """What a reader of the manifest alone could not reconstruct before."""
    payload = declare(KEY)

    assert payload["algorithm"] == "HMAC-SHA256"
    assert payload["subject_label_hex_chars"] == SUBJECT_ID_HEX_CHARS
    assert payload["rule_version"] == RULE_VERSION
    assert payload["policy"] == "deterministic"


def test_the_declaration_carries_no_key_material() -> None:
    """The fourth test of this class in the project, and the reason is the same.

    D7.2 section 5.5.1 (p. 51): the documentation shall not contain personal or
    identifying information. A key is not a data subject's, but the salt must be
    "kept separate and secure" (section 4.4, p. 40), and a manifest travels.
    """
    text = json.dumps(declare(KEY, permit_reference=PERMIT_A, root_fingerprint=KEY.fingerprint))

    assert KEY.material.hex() not in text
    assert KEY.material.hex().upper() not in text
    for byte in (KEY.material[:4], KEY.material[-4:]):
        assert byte.hex() not in text


def test_an_unscoped_declaration_says_so_rather_than_staying_quiet() -> None:
    """A build that reuses labels across permits must say that it does.

    Silence here reads as "scoping was handled", which is the opposite of the
    truth, and the reader is the one party required to care.
    """
    payload = declare(KEY)

    assert payload["scope"] == "key-wide"
    assert payload["permit_reference"] is None
    assert "MUST NOT" in str(payload["scope_note"])


def test_a_scoped_declaration_names_the_permit_and_both_fingerprints() -> None:
    """Both, because they answer different questions.

    The subkey's fingerprint says which permit's label space this is; the root's
    says the datasets came from one holder's key. The open question of whether
    anybody wants them together is recorded in the remediation plan.
    """
    payload = declare(KEY, permit_reference=PERMIT_A, root_fingerprint=KEY.fingerprint)

    assert payload["scope"] == "permit-scoped"
    assert payload["permit_reference"] == PERMIT_A
    assert payload["root_key_fingerprint"] == KEY.fingerprint


def test_the_declaration_admits_the_scheme_is_irreversible() -> None:
    """D7.2 discourages irreversible pseudonymisation, so it must not be implied.

    Section 4.2 (p. 36) makes a scheme reversible exactly when the mapping
    secrets are kept, and none is. Section 4.7 (p. 41) ties reversibility to
    opt-out and to the return of significant findings, which is why the note
    separates the two: one works here and one does not.
    """
    payload = declare(KEY)

    assert payload["reversible"] is False
    note = str(payload["reversibility_note"])
    assert "opt-out" in note
    assert "significant finding" in note


def test_the_declaration_never_claims_anonymity() -> None:
    """The one way this section could do harm is by being read as a clearance."""
    text = json.dumps(declare(KEY, permit_reference=PERMIT_A)).lower()

    assert "anonymis" not in text
    assert "compliant" not in text


# --------------------------------------------------------------------------
# Through the command line
# --------------------------------------------------------------------------


def _corpus(tmp_path: Path, *, subjects: int = 6, seed: int = 42) -> Path:
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=subjects, seed=seed, defect_rate=0.0), raw)
    return raw


def _key_file(tmp_path: Path) -> Path:
    path = tmp_path / "k.key"
    path.write_text(KEY.material.hex(), encoding="utf-8")
    return path


def _build(tmp_path: Path, raw: Path, out: Path, *extra: str) -> None:
    argv = [
        "build",
        str(raw),
        "--out",
        str(out),
        "--key-file",
        str(_key_file(tmp_path)),
        "--hdab",
        "Agenzia Sintetica",
        "--publisher",
        "IRCCS SINTETICO MAREBIANCO",
        *extra,
    ]
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output


def _manifest(out: Path) -> dict[str, object]:
    payload = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    return payload


def _subject_dirs(out: Path) -> set[str]:
    return {path.name for path in out.glob(f"{layout.SUBJECT_PREFIX}*")}


def test_an_unscoped_build_uses_the_root_keys_label_space(tmp_path: Path) -> None:
    """The regression that matters: default-off changes nothing.

    Asserted against `Pseudonymiser(KEY).subject_label`, which is the function
    that produced every label this tool has ever issued and which this round did
    not touch. Comparing two builds against each other would only prove they
    agree with one another, which they would even if both had moved.

    **The expected set comes from the keys, not from the planted codice
    fiscali, and it has to.** This read the ground-truth ``national_id`` spans,
    which was the same set of values until one generated site's laboratory feed
    began sending no national identifier: those subjects are keyed on a record
    number within the institution, while their reports still state the codice
    fiscale the feed withheld. So the annotations name values that keyed
    nobody, and a set built from them expects directories no build produces.
    The two halves are pinned against their own derivation, which keeps the
    equality exact rather than retreating to a subset.
    """
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out)
    pseudonymiser = Pseudonymiser(KEY)
    keys = [subject.key for subject in read_corpus(raw).subjects]
    national = [key for key in keys if key.kind is KeyKind.NATIONAL_ID]
    scoped = [key for key in keys if key.kind is not KeyKind.NATIONAL_ID]

    assert national and scoped, "this corpus no longer exercises both label spaces"

    expected = {
        f"{layout.SUBJECT_PREFIX}{pseudonymiser.subject_label(key.value)}" for key in national
    }
    expected |= {f"{layout.SUBJECT_PREFIX}{pseudonymiser.subject_label_for(key)}" for key in scoped}

    assert _subject_dirs(out) == expected


def test_a_rebuild_without_a_permit_is_byte_identical(tmp_path: Path) -> None:
    """And the whole published tree is unchanged, not only the labels.

    Into the same destination both times, because `dct:identifier` is
    `urn:commissura:<directory name>` -- two destinations differ in exactly one
    file for a legitimate reason, which is the trap the cross-platform
    reproducibility job was built to catch.
    """
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out)
    first = _manifest(out)["integrity"]
    assert isinstance(first, dict)
    files = dict(first["files"])
    _build(tmp_path, raw, out)

    second = _manifest(out)["integrity"]
    assert isinstance(second, dict)
    assert second["files"] == files


def test_two_permits_produce_two_sets_of_subject_directories(tmp_path: Path) -> None:
    """End to end, from one corpus and one key file.

    The requirement is about what a data user receives, so it is checked on the
    published tree rather than on the derivation.
    """
    raw = _corpus(tmp_path)
    a, b = tmp_path / "permit-a", tmp_path / "permit-b"
    _build(tmp_path, raw, a, "--permit", PERMIT_A)
    _build(tmp_path, raw, b, "--permit", PERMIT_B)

    first, second = _subject_dirs(a), _subject_dirs(b)
    assert len(first) == len(second) > 0
    assert not first & second


def test_a_scoped_build_records_the_permit_in_the_manifest(tmp_path: Path) -> None:
    """Which is what lets `verify` and a reader work out the scope afterwards."""
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out, "--permit", PERMIT_A)

    section = _manifest(out)["pseudonymisation"]
    assert isinstance(section, dict)
    assert section["permit_reference"] == PERMIT_A
    assert section["scope"] == "permit-scoped"
    assert _manifest(out)["key_fingerprint"] == scope_to_permit(KEY, PERMIT_A).fingerprint


def test_verify_authenticates_a_scoped_dataset_from_the_root_key(tmp_path: Path) -> None:
    """No --permit on `verify`, because the dataset already says which one.

    A flag here is a flag an operator can get wrong, and getting it wrong would
    report a sound dataset as unauthenticated -- which reads as tampering.
    """
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out, "--permit", PERMIT_A)

    result = runner.invoke(
        app, ["verify", str(out), "--key-file", str(_key_file(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["manifest_authenticated"] is True


def test_verify_still_authenticates_an_unscoped_dataset(tmp_path: Path) -> None:
    """The other half: a manifest naming no permit leaves the key alone."""
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out)

    result = runner.invoke(
        app, ["verify", str(out), "--key-file", str(_key_file(tmp_path)), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["manifest_authenticated"] is True


def test_whois_under_the_right_permit_finds_the_published_subject(tmp_path: Path) -> None:
    """The opt-out path, which is the reason `whois` exists at all.

    A person objects; the holder derives their label and goes looking. Under a
    permit-scoped build that derivation needs the permit, and the failure mode
    without it is the silent one this command's other guards were written for:
    a label for nobody looks exactly like a person who is not in the dataset.
    """
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out, "--permit", PERMIT_A)
    # Any identifier the corpus actually used, taken from its ground truth.
    identifier = next(
        span["text"]
        for span in json.loads(
            (raw / "_generator" / "phi_annotations.json").read_text(encoding="utf-8")
        )["spans"]
        if span["category"] == "national_id"
    )

    scoped = runner.invoke(
        app,
        [
            "whois",
            identifier,
            "--key-file",
            str(_key_file(tmp_path)),
            "--permit",
            PERMIT_A,
            "--json",
        ],
    )
    unscoped = runner.invoke(
        app, ["whois", identifier, "--key-file", str(_key_file(tmp_path)), "--json"]
    )

    assert scoped.exit_code == 0, scoped.output
    found = json.loads(scoped.output)
    assert found["permit_reference"] == PERMIT_A
    assert found["subject_directory"] in _subject_dirs(out)
    # And the wrong scope gives a label for nobody, which is why the permit has
    # to be passed and why the fingerprint is printed beside the answer.
    assert json.loads(unscoped.output)["subject_directory"] not in _subject_dirs(out)


@pytest.mark.parametrize("command", ["build", "whois"])
def test_the_permit_is_an_option_and_the_key_still_is_not(command: str) -> None:
    """Asked of click rather than of the help text, as this project's rule says.

    A rendered-help assertion was green in CI for weeks while checking nothing,
    because rich styles the token and a negative substring test then always
    passes. The convention is in the brief: assert on the thing, not its picture.
    """
    from typer.main import get_command

    params = {p.name for p in get_command(app).commands[command].params}  # type: ignore[attr-defined]

    assert "permit" in params
    assert "key" not in params
    assert "key_file" in params


# --------------------------------------------------------------------------
# Reading the scope back off a dataset
# --------------------------------------------------------------------------


def test_the_permit_is_read_from_a_real_manifest(tmp_path: Path) -> None:
    """Which is what makes `verify` self-describing rather than flag-driven."""
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out, "--permit", PERMIT_A)

    assert _permit_of(out) == PERMIT_A


def test_an_unscoped_dataset_reads_back_as_unscoped(tmp_path: Path) -> None:
    """`None`, so the key is left alone -- which is what those builds used."""
    raw = _corpus(tmp_path)
    out = tmp_path / "dataset"
    _build(tmp_path, raw, out)

    assert _permit_of(out) is None


@pytest.mark.parametrize(
    ("contents", "why"),
    [
        ("{ not json", "unreadable"),
        ("[]", "valid JSON but not a manifest"),
        ('{"pseudonymisation": "a string"}', "the section is not an object"),
        ('{"pseudonymisation": {"permit_reference": 7}}', "the reference is not a string"),
        ('{"schema_version": "6.0.0"}', "a manifest older than the section"),
    ],
)
def test_a_manifest_that_names_no_permit_leaves_the_key_unscoped(
    tmp_path: Path, contents: str, why: str
) -> None:
    """Every way the read can come back empty, including the absent file.

    These are the branches nobody watches, and the shape this project has found
    latent four times: an empty or malformed collection is not evidence that
    what fills it is safe. Scoping a key from a half-read manifest would
    authenticate against the wrong secret and report a sound dataset as
    tampered with.
    """
    out = tmp_path / "dataset"
    (out / layout.DEIDENT_DIR).mkdir(parents=True)
    (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text(contents, encoding="utf-8")

    assert _permit_of(out) is None, why


def test_a_missing_dataset_names_no_permit(tmp_path: Path) -> None:
    """Left to `verify_dataset`, which reports a missing manifest properly.

    Failing here would replace that message with a worse one.
    """
    assert _permit_of(tmp_path / "nowhere") is None


# --------------------------------------------------------------------------
# What an operator sees
# --------------------------------------------------------------------------


def test_whois_prints_the_permit_it_derived_under(tmp_path: Path) -> None:
    """The text output, not the JSON, because that is what an operator reads.

    Acting on an objection under the wrong scope gives a label for nobody, which
    looks exactly like a person who is not in the dataset. Printing the scope
    beside the label is how they notice.
    """
    key_file = _key_file(tmp_path)
    scoped = runner.invoke(
        app, ["whois", "RSSMRA80A01X000Z", "--key-file", str(key_file), "--permit", PERMIT_A]
    )
    unscoped = runner.invoke(app, ["whois", "RSSMRA80A01X000Z", "--key-file", str(key_file)])

    assert scoped.exit_code == 0, scoped.output
    assert PERMIT_A in scoped.output
    assert unscoped.exit_code == 0, unscoped.output
    assert "unscoped key" in unscoped.output
