"""What a pattern file says besides its cells, and how its bytes become text
(spec/formats.md "Metadata" and "Bytes and text").

Every text format can name its pattern, credit an author, and carry comment lines. RLE
and Macrocell spell them ``#N``, ``#O`` and ``#C``; plaintext ``!Name:``, ``!Author:`` and
``!``; Life 1.05 and 1.06 ``#D``. Readers return them as a :class:`PatternMetadata`, and
the RLE and Macrocell writers write one back.
"""

from __future__ import annotations

import dataclasses
import zlib
from collections.abc import Iterable

GZIP_MAGIC = b"\x1f\x8b"

# The characters str.splitlines ends a line at: a metadata value holding one can't be
# written as a single line.
_LINE_ENDS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")


@dataclasses.dataclass(frozen=True)
class PatternMetadata:
    """A pattern's name, author, and comment lines (spec/formats.md "Metadata")."""

    name: str | None = None
    author: str | None = None
    comments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Accept any sequence of strings, but keep the frozen value hashable and immutable.
        object.__setattr__(self, "comments", tuple(self.comments))

    @property
    def empty(self) -> bool:
        """True when there is no name, no author, and no comment."""
        return self.name is None and self.author is None and not self.comments


class MetadataReader:
    """Collects metadata from a file's lines: the first name and author count, and the
    comments keep their order (spec/formats.md "Metadata")."""

    def __init__(self) -> None:
        self._name: str | None = None
        self._author: str | None = None
        self._named = False
        self._authored = False
        self._comments: list[str] = []

    def name(self, value: str) -> None:
        if not self._named:
            self._named = True
            self._name = value.strip() or None

    def author(self, value: str) -> None:
        if not self._authored:
            self._authored = True
            self._author = value.strip() or None

    def comment(self, value: str) -> None:
        self._comments.append(value.strip())

    def hash_line(self, line: str) -> None:
        """An RLE or Macrocell ``#`` line, stripped: ``#N`` names, ``#O`` credits, ``#C`` and
        ``#c`` comment; any other tag is not metadata."""
        tag = line[1:2]
        if tag == "N":
            self.name(line[2:])
        elif tag == "O":
            self.author(line[2:])
        elif tag in ("C", "c"):
            self.comment(line[2:])

    def result(self) -> PatternMetadata:
        return PatternMetadata(self._name, self._author, tuple(self._comments))


def metadata_lines(metadata: PatternMetadata | None) -> list[str]:
    """The ``#N``, ``#O`` and ``#C`` lines RLE and Macrocell write for ``metadata``
    (spec/formats.md "Metadata", "Writing"): values stripped, line ends refused."""
    if metadata is None:
        return []
    lines: list[str] = []
    if metadata.name is not None and (name := _value(metadata.name, "name")):
        lines.append(f"#N {name}")
    if metadata.author is not None and (author := _value(metadata.author, "author")):
        lines.append(f"#O {author}")
    for comment in metadata.comments:
        text = _value(comment, "comment")
        lines.append(f"#C {text}" if text else "#C")
    return lines


def _value(value: str, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"the metadata's {what} must be a string, not {type(value).__name__}")
    if any(ch in _LINE_ENDS for ch in value):
        raise ValueError(f"the metadata's {what} holds a line end: {value!r}")
    return value.strip()


def inflate(data: bytes) -> bytes:
    """Gzip bytes inflated, once; any other bytes as they are (spec/formats.md). The gzip
    stream is one member, whole: its CRC-32 and length are checked, and a stream cut short,
    damaged, or followed by more bytes is refused."""
    if data[:2] != GZIP_MAGIC:
        return data
    stream = zlib.decompressobj(wbits=31)  # 16 + 15: one gzip member, its trailer checked
    try:
        inflated = stream.decompress(data) + stream.flush()
    except zlib.error as error:
        raise ValueError(f"broken gzip data: {error}") from error
    if not stream.eof:
        raise ValueError("broken gzip data: the stream is cut short")
    if stream.unused_data:
        raise ValueError("gzip data goes on past its end (one member only)")
    return inflated


def text_from_bytes(data: bytes) -> str:
    """Bytes as text: UTF-8 when they are valid UTF-8 (one leading byte-order mark
    dropped), otherwise Latin-1, a character per byte (spec/formats.md)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")
    return text.removeprefix("\ufeff")


def first_text_line(lines: Iterable[str]) -> str:
    """The first non-blank line, stripped, or "" when every line is blank."""
    for line in lines:
        if stripped := line.strip():
            return stripped
    return ""
