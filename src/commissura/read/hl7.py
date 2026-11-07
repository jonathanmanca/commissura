r"""Read HL7 v2 messages back into facts.

The writer in :mod:`commissura.hl7` takes field numbers and emits text. This is
the other direction, and the asymmetry between them is deliberate: the writer
refuses anything irregular, because it controls what it produces, while a reader
has to cope with whatever a hospital interface actually sent.

So this module is **tolerant by construction**. A missing field returns an empty
string rather than raising; a segment that is not there returns ``None``; a
message with fewer fields than expected is not an error. Every one of those is a
defect the generator can inject on purpose — a cleared unit, an absent PV1 — and
a reader that raised on them could not be used to measure how a dataset copes
with them. What the reader does instead is report what it found, and let a rule
decide whether that is acceptable.

**Unescaping happens here, before any offset is taken.** The writer refuses
reserved delimiters rather than escaping them, precisely so that recorded PHI
offsets match the bytes on disk. A reader has no such luxury: real messages
contain ``\F\`` for a pipe and ``\S\`` for a caret, and they have to be
turned back into characters. Doing it at parse time means everything downstream
works in real characters and never has to wonder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from commissura.hl7 import (
    COMPONENT_SEPARATOR,
    ESCAPE_CHARACTER,
    FIELD_SEPARATOR,
    REPETITION_SEPARATOR,
    SEGMENT_TERMINATOR,
    SUBCOMPONENT_SEPARATOR,
)

_ESCAPE_SEQUENCES: Final[dict[str, str]] = {
    "F": FIELD_SEPARATOR,
    "S": COMPONENT_SEPARATOR,
    "T": SUBCOMPONENT_SEPARATOR,
    "R": REPETITION_SEPARATOR,
    "E": ESCAPE_CHARACTER,
}
r"""HL7's escape table for the characters it reserves.

``\F\`` is a field separator inside data, ``\S\`` a component separator, and
so on. The sequences are delimited by the escape character on both sides.
"""


def unescape(value: str) -> str:
    r"""Turn HL7 escape sequences back into the characters they stand for.

    Unknown sequences are left exactly as found. HL7 defines others —
    ``\X..\`` for hex, ``\Z..\`` for locally agreed meanings, formatting
    commands — and silently dropping one would quietly corrupt a value, which is
    worse than passing through text somebody can see is wrong.

    Args:
        value: Raw field text.

    Returns:
        The unescaped value.
    """
    if ESCAPE_CHARACTER not in value:
        return value

    pieces: list[str] = []
    remainder = value
    while ESCAPE_CHARACTER in remainder:
        before, _, rest = remainder.partition(ESCAPE_CHARACTER)
        pieces.append(before)
        code, closed, after = rest.partition(ESCAPE_CHARACTER)
        if not closed:
            # An unterminated escape. Keep it verbatim rather than guessing.
            pieces.append(ESCAPE_CHARACTER + code)
            return "".join(pieces)
        replacement = _ESCAPE_SEQUENCES.get(code)
        pieces.append(
            replacement if replacement is not None else ESCAPE_CHARACTER + code + ESCAPE_CHARACTER
        )
        remainder = after
    pieces.append(remainder)
    return "".join(pieces)


@dataclass(frozen=True, slots=True)
class Segment:
    """One parsed HL7 segment, addressed by field number.

    Attributes:
        name: The three-character segment identifier.
        fields: Raw field text, indexed from 1 to match HL7's own numbering.
            Index 0 is unused and holds the segment name.
    """

    name: str
    fields: tuple[str, ...]

    def field(self, index: int) -> str:
        """Return one field's raw text, or an empty string if it is absent.

        Absent rather than missing: a short segment is normal HL7, and a reader
        that distinguished "empty" from "not sent" would push that distinction
        onto every caller for no benefit.

        Args:
            index: One-based HL7 field number.

        Returns:
            The field text, unescaped.
        """
        if index < 1 or index >= len(self.fields):
            return ""
        return unescape(self.fields[index])

    def component(self, index: int, component: int) -> str:
        """Return one component of one field.

        Args:
            index: One-based HL7 field number.
            component: One-based component number.

        Returns:
            The component text, unescaped, or an empty string if absent.
        """
        raw = self.fields[index] if 1 <= index < len(self.fields) else ""
        parts = raw.split(COMPONENT_SEPARATOR)
        if component < 1 or component > len(parts):
            return ""
        return unescape(parts[component - 1])

    def repetitions(self, index: int) -> tuple[str, ...]:
        """Return a field's repetitions, split on the repetition separator.

        Args:
            index: One-based HL7 field number.

        Returns:
            One entry per repetition; empty if the field is absent.
        """
        raw = self.fields[index] if 1 <= index < len(self.fields) else ""
        if not raw:
            return ()
        return tuple(raw.split(REPETITION_SEPARATOR))


@dataclass(frozen=True, slots=True)
class Message:
    """A parsed HL7 message."""

    segments: tuple[Segment, ...]

    def first(self, name: str) -> Segment | None:
        """Return the first segment with this name, or ``None``.

        Args:
            name: Segment identifier, such as ``PID``.

        Returns:
            The segment, or ``None`` when the message does not carry one.
        """
        for segment in self.segments:
            if segment.name == name:
                return segment
        return None

    def all(self, name: str) -> tuple[Segment, ...]:
        """Return every segment with this name, in order.

        Args:
            name: Segment identifier, such as ``OBX``.

        Returns:
            The matching segments.
        """
        return tuple(s for s in self.segments if s.name == name)

    def require(self, name: str) -> Segment:
        """Return the first segment with this name, or raise.

        For the segments a message is meaningless without. ``PID`` is one: a
        result with no patient cannot be attributed to a subject, so there is
        nothing useful to carry on with.

        Args:
            name: Segment identifier.

        Returns:
            The segment.

        Raises:
            ValueError: If the message has no such segment.
        """
        segment = self.first(name)
        if segment is None:
            raise ValueError(
                f"message has no {name} segment; found " + ", ".join(s.name for s in self.segments)
            )
        return segment


def parse_message(text: str) -> Message:
    r"""Parse HL7 v2 text into segments.

    Splits on carriage return, and tolerates line feeds alongside it: a message
    that has been through a text editor or a careless transfer arrives with
    ``\r\n`` or bare ``\n``, and refusing it would mean refusing most
    real-world samples.

    MSH is renumbered on the way in. In the serialised form the separator
    immediately after ``MSH`` counts as field one, so MSH-3 sits where field two
    would be in any other segment. Correcting that here means callers can ask
    for MSH-9 and get MSH-9.

    Args:
        text: The raw message.

    Returns:
        The parsed message.

    Raises:
        ValueError: If the text contains no segments at all.
    """
    normalised = text.replace("\r\n", SEGMENT_TERMINATOR).replace("\n", SEGMENT_TERMINATOR)
    segments: list[Segment] = []
    for line in normalised.split(SEGMENT_TERMINATOR):
        if not line.strip():
            continue
        parts = line.split(FIELD_SEPARATOR)
        name = parts[0]
        # For MSH the first separator is MSH-1 itself, so an extra slot is
        # inserted to keep the numbers a caller expects: fields[2] must be the
        # encoding characters, not the sending application.
        fields = (name, FIELD_SEPARATOR, *parts[1:]) if name == "MSH" else tuple(parts)
        segments.append(Segment(name=name, fields=fields))

    if not segments:
        raise ValueError("no HL7 segments found in the given text")
    return Message(segments=tuple(segments))


def parse_timestamp(value: str) -> datetime | None:
    """Parse an HL7 timestamp, returning ``None`` when it cannot be read.

    Accepts the lengths HL7 actually sends — year, month, day, then optional
    hour, minute, second — and also the ``DD/MM/YYYY`` a hand-built interface
    produces, which the generator models as a defect. Returning ``None`` instead
    of raising is what lets a validator report a malformed timestamp as a
    finding rather than a crash.

    Args:
        value: The field text.

    Returns:
        The parsed moment, or ``None``.
    """
    digits = value.strip()
    if not digits:
        return None

    for length, pattern in ((14, "%Y%m%d%H%M%S"), (12, "%Y%m%d%H%M"), (8, "%Y%m%d")):
        if len(digits) >= length:
            try:
                return datetime.strptime(digits[:length], pattern)
            except ValueError:
                continue

    for pattern in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(digits, pattern)
        except ValueError:
            continue
    return None


def parse_day(value: str) -> date | None:
    """Parse an HL7 date, returning ``None`` when it cannot be read.

    Args:
        value: The field text.

    Returns:
        The parsed date, or ``None``.
    """
    moment = parse_timestamp(value)
    return None if moment is None else moment.date()
