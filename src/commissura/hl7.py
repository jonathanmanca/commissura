r"""A small HL7 v2 writer that keeps identifier offsets intact.

HL7 v2 is a delimited text format, and writing it by hand means counting pipe
characters. Counting pipes is how people get PID-19 confused with PID-18: the
field numbers are one-indexed, empty fields still need their separators, and
MSH is numbered differently from every other segment. So this module takes
field *numbers* and renders the separators itself.

The MSH quirk, since it catches everybody: MSH-1 *is* the field separator, and
MSH-2 is the string of encoding characters. In the serialised form the first
separator after ``MSH`` therefore counts as field one, so MSH-3 appears where
field two would sit in any other segment.

**On escaping.** HL7 reserves five characters and escapes them in data as
``\F\``, ``\S\`` and so on. This writer does not escape: it *refuses* a
value containing a delimiter. That is a deliberate choice, and the reason is the
PHI ground truth. Escaping would rewrite the characters of a value after its
offsets had been recorded, so a name containing a delimiter would end up with
spans pointing at the wrong text — the one failure mode that would quietly
corrupt every measurement built on this corpus. Refusing is loud, and for
generated data the condition never arises. A reader for real-world input will
need the full escape table; that belongs with the reader, where unescaping
happens before offsets are ever taken.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from commissura.annotate import AnnotatedText, Phi, Piece
from commissura.models import PhiSpan

FIELD_SEPARATOR = "|"
COMPONENT_SEPARATOR = "^"
REPETITION_SEPARATOR = "~"
ESCAPE_CHARACTER = "\\"
SUBCOMPONENT_SEPARATOR = "&"
SEGMENT_TERMINATOR = "\r"
"""HL7 v2 terminates segments with a carriage return, not a newline.

This is the most common mistake made when writing v2 by hand, and it is
invisible in most editors. A receiver that splits on ``\n`` sees one enormous
segment and reports a malformed message with no useful detail.
"""

ENCODING_CHARACTERS = (
    COMPONENT_SEPARATOR + REPETITION_SEPARATOR + ESCAPE_CHARACTER + SUBCOMPONENT_SEPARATOR
)
"""The value of MSH-2, declaring the delimiters the message uses."""

_RESERVED = frozenset(
    FIELD_SEPARATOR
    + COMPONENT_SEPARATOR
    + REPETITION_SEPARATOR
    + ESCAPE_CHARACTER
    + SUBCOMPONENT_SEPARATOR
    + SEGMENT_TERMINATOR
)


@dataclass(frozen=True, slots=True)
class Raw:
    """A value written verbatim, exempt from the reserved-delimiter check.

    Exactly one field in HL7 v2 legitimately contains delimiters: MSH-2, whose
    whole purpose is to declare them. Marking that exemption at the call site
    rather than special-casing MSH-2 inside the renderer keeps the rule visible
    — a reader of :func:`new_msh` can see why the check is being waived, and
    nobody can waive it by accident.
    """

    text: str


@dataclass(frozen=True, slots=True)
class Repeated:
    """Several values for one field, joined with the repetition separator.

    Used for things a patient genuinely has more than one of, such as a
    telephone number and an email address in PID-13.
    """

    values: tuple[Field, ...]


Field = Piece | Raw | tuple[Piece | Raw, ...] | Repeated
"""A field is a single value, a tuple of components, or a set of repetitions."""


def format_timestamp(moment: datetime) -> str:
    """Return a datetime in the HL7 v2 TS format, ``YYYYMMDDHHMMSS``."""
    return moment.strftime("%Y%m%d%H%M%S")


def format_date(day: date) -> str:
    """Return a date in the HL7 v2 DT format, ``YYYYMMDD``."""
    return day.strftime("%Y%m%d")


def _check_safe(value: str) -> None:
    """Reject a value that contains a reserved delimiter.

    Args:
        value: The candidate text.

    Raises:
        ValueError: If the value contains a reserved character.
    """
    offending = _RESERVED.intersection(value)
    if offending:
        raise ValueError(
            f"value {value!r} contains reserved HL7 delimiter(s) {sorted(offending)!r}. "
            "This writer refuses rather than escapes, so that recorded PHI offsets "
            "always match the bytes on disk."
        )


class Segment:
    """One HL7 segment, addressed by field number rather than by position.

    Fields are set with their HL7 number, so ``segment.set(19, cf)`` writes
    PID-19 and the writer emits the eighteen separators in front of it.
    """

    __slots__ = ("_fields", "name")

    def __init__(self, name: str) -> None:
        """Create an empty segment.

        Args:
            name: Three-character segment identifier, such as ``PID``.
        """
        self.name = name
        self._fields: dict[int, Field] = {}

    def set(self, index: int, value: Field) -> Segment:
        """Set one field by its HL7 field number.

        Args:
            index: One-based HL7 field number.
            value: The field value.

        Returns:
            This segment, so calls can be chained.

        Raises:
            ValueError: If ``index`` is not positive.
        """
        if index < 1:
            raise ValueError(f"HL7 field numbers start at 1, got {index}")
        self._fields[index] = value
        return self

    def render(self, text: AnnotatedText) -> None:
        """Append this segment and its terminator to ``text``.

        Args:
            text: The builder to append to. Identifier positions are recorded
                as a side effect of writing them.
        """
        text.write(self.name)
        if not self._fields:
            text.write(SEGMENT_TERMINATOR)
            return

        highest = max(self._fields)
        first_field = 2 if self.name == "MSH" else 1
        for index in range(first_field, highest + 1):
            text.write(FIELD_SEPARATOR)
            if index in self._fields:
                self._write_field(text, self._fields[index])
        text.write(SEGMENT_TERMINATOR)

    def _write_field(self, text: AnnotatedText, value: Field) -> None:
        """Append one field, joining components and repetitions as needed."""
        if isinstance(value, Repeated):
            for position, repetition in enumerate(value.values):
                if position:
                    text.write(REPETITION_SEPARATOR)
                self._write_field(text, repetition)
            return
        if isinstance(value, tuple):
            for position, component in enumerate(value):
                if position:
                    text.write(COMPONENT_SEPARATOR)
                self._write_component(text, component)
            return
        self._write_component(text, value)

    @staticmethod
    def _write_component(text: AnnotatedText, component: Piece | Raw) -> None:
        """Append one component, checking it carries no reserved delimiter."""
        if isinstance(component, Raw):
            text.write(component.text)
            return
        _check_safe(component.text if isinstance(component, Phi) else component)
        text.write(component)


class Message:
    """An ordered list of segments that renders to one HL7 v2 message."""

    __slots__ = ("segments",)

    def __init__(self) -> None:
        """Create an empty message."""
        self.segments: list[Segment] = []

    def add(self, name: str) -> Segment:
        """Append a new segment and return it for field assignment.

        Args:
            name: Three-character segment identifier.

        Returns:
            The newly added segment.
        """
        segment = Segment(name)
        self.segments.append(segment)
        return segment

    def append(self, segment: Segment) -> None:
        """Append an already-built segment.

        Used when a segment has to be constructed before its position is known,
        for example when a defect decides whether PV1 is included at all.

        Args:
            segment: The segment to append.
        """
        self.segments.append(segment)

    def render(self, path: str) -> tuple[str, tuple[PhiSpan, ...]]:
        """Render the message and return it with its recorded identifier spans.

        Args:
            path: Corpus-relative path the message will be written to; stored on
                each span.

        Returns:
            The message text and the spans recorded while writing it.
        """
        text = AnnotatedText(path)
        for segment in self.segments:
            segment.render(text)
        return text.finish()


def new_msh(
    *,
    sending_application: str,
    sending_facility: Piece,
    receiving_application: str,
    receiving_facility: str,
    sent_at: datetime,
    message_type: tuple[str, str],
    control_id: str,
    version: str = "2.5.1",
) -> Segment:
    """Build a populated MSH segment.

    Args:
        sending_application: MSH-3.
        sending_facility: MSH-4. Accepts a :class:`~commissura.annotate.Phi`
            because an institution name is an identifier in its own right.
        receiving_application: MSH-5.
        receiving_facility: MSH-6.
        sent_at: MSH-7, the message timestamp.
        message_type: MSH-9 as ``(code, trigger_event)``, for example
            ``("ORU", "R01")``.
        control_id: MSH-10, unique per message within the sending system.
        version: MSH-12.

    Returns:
        The MSH segment.
    """
    segment = Segment("MSH")
    segment.set(2, Raw(ENCODING_CHARACTERS))
    segment.set(3, sending_application)
    segment.set(4, sending_facility)
    segment.set(5, receiving_application)
    segment.set(6, receiving_facility)
    segment.set(7, format_timestamp(sent_at))
    segment.set(9, message_type)
    segment.set(10, control_id)
    segment.set(11, "P")
    segment.set(12, version)
    return segment
