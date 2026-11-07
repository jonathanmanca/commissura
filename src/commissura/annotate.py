"""A string builder that remembers where it wrote identifiers.

This is the mechanism that makes de-identification *measurable* rather than
assumed, and it is worth explaining why it is built this way.

The obvious approach is to generate the text first and locate the identifiers
afterwards with ``str.find``. That approach is quietly wrong, in three ways that
all bite in practice:

- **Repeats.** A patient name appears in the HL7 PID segment and again in the
  report body. ``find`` returns the first occurrence, so every later one is
  invisible to the scoring.
- **Substrings.** The surname ``Russo`` occurs inside ``Russolo``, and the city
  ``Bari`` inside ``Barisone``. Searching produces spans that point at text
  which is not an identifier, inflating the denominator.
- **Collisions with clinical language.** A patient named ``Rene`` collides with
  ``rene`` (Italian for kidney). No amount of post-hoc searching can tell the
  two apart, because the information needed, *which one did I write on purpose*,
  was thrown away.

:class:`AnnotatedText` keeps that information instead. It is the only thing that
knows the current offset, so the invariant ``text == content[start:end]`` holds
by construction rather than by search. Write an identifier through :class:`Phi`
and the span is recorded exactly; write it as a plain string and it is treated
as clinical prose.

Typical use::

    text = AnnotatedText("reports/0012345_1.txt")
    text.write("Paziente: ", Phi("MARIO ROSSI", PhiCategory.PERSON_NAME)).newline()
    content, spans = text.finish()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from commissura.models import PhiCategory, PhiSpan


@dataclass(frozen=True, slots=True)
class Phi:
    """A piece of text that is an identifier, and must be recorded as such.

    Attributes:
        text: The literal characters to write.
        category: Which kind of identifier this is.
        note: Optional explanation of *why* this location is interesting, for
            example that the identifier is hidden in a vendor private tag. It
            travels into the annotation file and makes the ground truth readable
            by a human reviewer.
    """

    text: str
    category: PhiCategory
    note: str | None = None

    def __post_init__(self) -> None:
        """Reject an empty identifier.

        A zero-length span can never be found by a scrubber, so recording one
        would silently depress recall. This is a generator bug, not valid input.
        """
        if not self.text:
            raise ValueError("Phi.text must not be empty")


Piece = str | Phi
"""Anything writable: plain prose, or an identifier to be recorded."""


class AnnotatedText:
    """Accumulate text while recording the position of every identifier.

    The builder is append-only by design. There is no way to rewrite earlier
    content, because doing so would invalidate every span already recorded, and
    an API that can corrupt its own output is worse than one that cannot express
    the operation.
    """

    __slots__ = ("_offset", "_parts", "_path", "_spans")

    def __init__(self, path: str) -> None:
        """Start an empty document.

        Args:
            path: The corpus-relative path this content will be written to. It
                is stored on every span so annotations stay meaningful once the
                content has left the builder.
        """
        self._path = path
        self._parts: list[str] = []
        self._spans: list[PhiSpan] = []
        self._offset = 0

    @property
    def path(self) -> str:
        """Return the corpus-relative path of the document being built."""
        return self._path

    def __len__(self) -> int:
        """Return the number of characters written so far."""
        return self._offset

    def write(self, *pieces: Piece) -> Self:
        """Append pieces in order, recording a span for each :class:`Phi`.

        Returns ``self`` so calls can be chained, which keeps the renderers
        close in shape to the output they produce.

        Args:
            *pieces: Plain strings are written as prose. :class:`Phi` instances
                are written and recorded.

        Returns:
            This builder.
        """
        for piece in pieces:
            if isinstance(piece, Phi):
                start = self._offset
                self._parts.append(piece.text)
                self._offset += len(piece.text)
                self._spans.append(
                    PhiSpan(
                        path=self._path,
                        start=start,
                        end=self._offset,
                        text=piece.text,
                        category=piece.category,
                        note=piece.note,
                    )
                )
            else:
                self._parts.append(piece)
                self._offset += len(piece)
        return self

    def write_joined(self, separator: str, *pieces: Piece) -> Self:
        """Append pieces with ``separator`` between them.

        Useful for delimited formats: HL7 v2 components are joined with ``^``,
        and the separator itself is never part of an identifier.

        Args:
            separator: Written between consecutive pieces, never before the
                first or after the last.
            *pieces: The pieces to join.

        Returns:
            This builder.
        """
        for index, piece in enumerate(pieces):
            if index:
                self.write(separator)
            self.write(piece)
        return self

    def newline(self, ending: str = "\n") -> Self:
        r"""Append a line ending.

        Args:
            ending: The line terminator. HL7 v2 needs ``\r``, which is why this
                is a parameter rather than a hard-coded newline.

        Returns:
            This builder.
        """
        return self.write(ending)

    def line(self, *pieces: Piece, ending: str = "\n") -> Self:
        """Append pieces followed by a line ending.

        Args:
            *pieces: Passed to :meth:`write`.
            ending: The line terminator.

        Returns:
            This builder.
        """
        return self.write(*pieces).newline(ending)

    def render(self) -> str:
        """Return the accumulated content.

        A single join at the end rather than repeated concatenation: building a
        string by ``+=`` in a loop is quadratic, because each step copies
        everything written so far.
        """
        return "".join(self._parts)

    def spans(self) -> tuple[PhiSpan, ...]:
        """Return the recorded identifier spans, in the order they were written."""
        return tuple(self._spans)

    def finish(self) -> tuple[str, tuple[PhiSpan, ...]]:
        """Return the content and its spans together, self-checked.

        Verifying here rather than trusting the arithmetic means a future change
        to this class cannot silently corrupt the ground truth: it fails loudly
        at the moment the document is closed.

        Returns:
            The rendered content and the recorded spans.

        Raises:
            AssertionError: If any span does not quote the content it points at.
        """
        content = self.render()
        spans = self.spans()
        check_spans(content, spans)
        return content, spans


def check_spans(content: str, spans: tuple[PhiSpan, ...]) -> None:
    """Assert that every span quotes exactly the text it points at.

    This is the invariant the whole measurement story rests on. It is cheap to
    check and catastrophic to get wrong: spans that are off by one would make a
    perfect de-identifier look broken, or a broken one look perfect.

    Args:
        content: The document the spans refer to.
        spans: The spans to verify.

    Raises:
        AssertionError: On the first span that does not match.
    """
    for span in spans:
        found = content[span.start : span.end]
        if found != span.text:
            raise AssertionError(
                f"span mismatch in {span.path} at [{span.start}:{span.end}]: "
                f"recorded {span.text!r} but content holds {found!r}"
            )
