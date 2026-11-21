"""Pattern files beyond the vectors (spec/formats.md): round trips of cells and metadata
through every writer, what the writers refuse, text decoding, numbers of any size, the
timeline writer's rules, and the image readers checked against images Pillow writes."""

from __future__ import annotations

import gzip
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from heaton_life.ca.hashlife import (
    HashLife,
    read_timeline,
    read_universe,
    write_timeline,
)
from heaton_life.ca.hashlife.macrocell import _power, read_macrocell
from heaton_life.core.decimal_text import digits_of, int_of_digits
from heaton_life.init import (
    PatternMetadata,
    detect_format,
    read_pattern,
    rle_decode,
    rle_encode,
    rle_metadata,
)
from heaton_life.init.metadata import metadata_lines, text_from_bytes

GLIDER = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)
NOTES = PatternMetadata("Glider", "R. K. Guy", ("one", "", "  three  "))


def _random_metadata(rng: np.random.Generator) -> PatternMetadata:
    words = ["glider", "Café", "x = 3", "#N", "!Name:", "  ", "", "ą Å —", "$!bo"]

    def text() -> str:
        return " ".join(rng.choice(words, size=int(rng.integers(0, 4))))

    name = text() if rng.random() < 0.7 else None
    author = text() if rng.random() < 0.7 else None
    comments = tuple(text() for _ in range(int(rng.integers(0, 5))))
    return PatternMetadata(name, author, comments)


def _stripped(m: PatternMetadata) -> PatternMetadata:
    """What a reader gives back for metadata a writer was handed."""
    return PatternMetadata(
        (m.name or "").strip() or None,
        (m.author or "").strip() or None,
        tuple(c.strip() for c in m.comments),
    )


# -- metadata ---------------------------------------------------------------------------------


def test_rle_round_trips_cells_and_metadata() -> None:
    rng = np.random.default_rng(10)
    for _ in range(200):
        height, width = (int(v) for v in rng.integers(1, 12, size=2))
        top = int(rng.choice([1, 2, 24]))
        grid = rng.integers(0, top + 1, size=(height, width)).astype(np.uint8)
        notes = _random_metadata(rng)
        text = rle_encode(grid, "B3/S23" if top == 1 else "WireWorld", metadata=notes)
        decoded, _ = rle_decode(text)
        assert np.array_equal(decoded[:height, :width], grid)
        assert rle_metadata(text) == _stripped(notes)
        assert read_pattern(text).metadata == _stripped(notes)


def test_universe_writers_round_trip_metadata() -> None:
    rng = np.random.default_rng(11)
    for _ in range(40):
        u = HashLife("B36/S23")
        u.fill_random(-9, -5, 8, 6, density=0.4, seed=int(rng.integers(1 << 30)))
        u.step(int(rng.integers(0, 50)))
        notes = _random_metadata(rng)
        for text in (u.to_rle(notes), u.to_macrocell(notes)):
            found = read_universe(text)
            assert found.metadata == _stripped(notes)
            assert found.universe.to_macrocell() == u.to_macrocell()


def test_no_metadata_writes_exactly_what_it_did() -> None:
    u = HashLife()
    u.set_rect(3, -2, GLIDER)
    for notes in (None, PatternMetadata(), PatternMetadata("", "  ", ())):
        assert rle_encode(GLIDER, metadata=notes) == rle_encode(GLIDER)
        assert u.to_rle(notes) == u.to_rle()
        assert u.to_macrocell(notes) == u.to_macrocell()


def test_metadata_lines_are_canonical() -> None:
    assert metadata_lines(NOTES) == ["#N Glider", "#O R. K. Guy", "#C one", "#C", "#C three"]
    text = rle_encode(GLIDER, metadata=NOTES)
    assert text.startswith("#N Glider\n#O R. K. Guy\n#C one\n#C\n#C three\nx = 3, y = 3")
    u = HashLife()
    u.set_rect(0, 0, GLIDER)
    assert u.to_rle(NOTES).startswith("#CXRLE Pos=0,0\n#N Glider\n")
    assert u.to_macrocell(NOTES).startswith("[M2] (heaton-life)\n#R B3/S23\n#N Glider\n")


@pytest.mark.parametrize("end", list("\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"))
def test_a_metadata_value_with_a_line_end_is_refused(end: str) -> None:
    u = HashLife()
    for notes in (
        PatternMetadata(name=f"a{end}b"),
        PatternMetadata(author=f"a{end}"),
        PatternMetadata(comments=("fine", f"{end}x")),
    ):
        with pytest.raises(ValueError, match="line end"):
            rle_encode(GLIDER, metadata=notes)
        with pytest.raises(ValueError, match="line end"):
            u.to_macrocell(notes)
        with pytest.raises(ValueError, match="line end"):
            u.to_rle(notes)


def test_the_first_name_and_author_count() -> None:
    text = "#O first author\n#N first\n#N second\n#O second author\nx = 1, y = 1\no!\n"
    assert rle_metadata(text) == PatternMetadata("first", "first author", ())
    assert rle_metadata("#N\n#N named later\no!\n").name is None  # an empty name is none


def test_cxrle_is_a_comment_except_on_the_first_line() -> None:
    assert rle_metadata("\n#CXRLE Pos=1,2\n#CXRLE Pos=3,4\no!\n").comments == ("XRLE Pos=3,4",)


def test_plaintext_metadata() -> None:
    found = read_pattern("!Name: Block\n!Author:  me \n! Name: not a name\n!\nOO\nOO\n")
    assert found.metadata == PatternMetadata("Block", "me", ("Name: not a name", ""))


# -- bytes and text ---------------------------------------------------------------------------


def test_text_is_utf8_when_it_can_be_and_latin1_otherwise() -> None:
    assert text_from_bytes("Café".encode()) == "Café"
    assert text_from_bytes(b"\xef\xbb\xbfx") == "x"
    assert text_from_bytes(b"\xef\xbb\xbf\xef\xbb\xbfx") == "\ufeffx"  # one mark is dropped
    assert text_from_bytes(b"Caf\xe9") == "Café"
    for bad in (b"\xc0\xaf", b"\xed\xa0\x80", b"\xf4\x90\x80\x80", b"\xe2\x82", b"\x80"):
        assert text_from_bytes(bad) == bad.decode("latin-1")


def test_a_0x85_byte_inside_a_utf8_character_does_not_end_a_line() -> None:
    data = "#C Å\nx = 1, y = 1\no!\n".encode()
    assert b"\x85" in data
    assert read_pattern(data).metadata.comments == ("Å",)
    assert read_universe(data).universe.population == 1


def test_detection_of_text_skips_gzip_and_images() -> None:
    assert detect_format("bo$2bo$3o!") == "rle"
    assert detect_format("\x89PNG\r\n\x1a\n") == "rle"  # text is text
    assert detect_format(gzip.compress(b"#Life 1.06\n0 0\n", mtime=0)) == "life-1.06"
    with pytest.raises(ValueError, match="empty"):
        detect_format("\n \t\n")


@pytest.mark.parametrize("cut", [1, 4, 8, 20, 30])
def test_a_gzip_stream_cut_short_is_refused(cut: int) -> None:
    packed = gzip.compress(b"x = 3, y = 3\nbo$2bo$3o!\n" * 20, mtime=0)
    with pytest.raises(ValueError, match="gzip"):
        read_pattern(packed[:-cut])


def test_gzip_inside_every_reader() -> None:
    data = gzip.compress(b"!Name: g\n.O\n..O\nOOO\n", mtime=0)
    assert np.array_equal(read_pattern(data).cells, GLIDER)
    assert read_universe(data).universe.population == 5


# -- numbers of any size ----------------------------------------------------------------------


def test_int_of_digits_has_no_limit() -> None:
    assert int_of_digits("1" + "0" * 6000) == 10**6000
    assert int_of_digits("9" * 9001) == 10**9001 - 1
    assert int_of_digits("0" * 5000 + "42") == 42
    value = 3**20000
    assert int_of_digits(digits_of(value)) == value


def test_life106_coordinates_of_any_size() -> None:
    big = 10**5000
    a, b, y = digits_of(big), digits_of(big + 1), digits_of(big)
    found = read_pattern(f"#Life 1.06\n{a} -{y}\n{b} -{y}\n")
    assert (found.x, found.y) == (big, -big)
    assert found.cells.tolist() == [[1, 1]]


def test_macrocell_generations_of_any_size() -> None:
    big = 10**5000 + 7
    u = HashLife()
    u.set_rect(0, 0, GLIDER)
    text = u.to_macrocell().replace("#R B3/S23\n", f"#R B3/S23\n#G {digits_of(big)}\n")
    again = read_macrocell(text)
    assert again.generation == big
    assert again.to_macrocell() == text
    rle = again.to_rle()
    assert read_universe(rle).universe.generation == big


# -- formats ----------------------------------------------------------------------------------


def test_life105_rules() -> None:
    def rule(line: str) -> str | None:
        return read_pattern(f"#Life 1.05\n{line}\n*\n").rule

    assert rule("#R 23/3") == "B3/S23"
    assert rule("#R 3223/663") == "B36/S23"
    assert rule("#R /3") == "B3/S"
    assert rule("#R 23/") == "B/S23"
    assert rule("#R 239/3") == "239/3"  # not Life 1.05's digits: as written
    assert rule("#R B3/S23") == "B3/S23"
    assert rule("#R") is None  # nothing after it: no rule
    assert rule("#N") == "B3/S23"
    assert read_pattern("#Life 1.05\n#R 23/3\n#R 23/36\n*\n").rule == "B36/S23"  # the last


def test_plaintext_trailing_blank_lines_are_not_rows() -> None:
    found = read_pattern("O\n\n.O\n\n\n  \n")
    assert found.cells.tolist() == [[1, 0], [0, 0], [0, 1]]


def test_bounding_box_formats_refuse_an_empty_pattern() -> None:
    for text in ("#Life 1.06\n", "#Life 1.05\n#P 0 0\n...\n", "[M2]\n$\n"):
        with pytest.raises(ValueError, match="no live cells"):
            read_pattern(text)


def test_universe_from_file_reads_every_format(tmp_path: Path) -> None:
    files = {
        "a.cells": b".O\n..O\nOOO\n",
        "a.lif": b"#Life 1.06\n1 0\n2 1\n0 2\n1 2\n2 2\n",
        "a.rle.gz": gzip.compress(b"x = 3, y = 3\nbo$2bo$3o!\n", mtime=0),
    }
    for name, data in files.items():
        path = tmp_path / name
        path.write_bytes(data)
        u = HashLife.from_file(path)
        assert u.population == 5
        assert u.bounding_box() == (0, 0, 2, 2)


def test_save_writes_metadata(tmp_path: Path) -> None:
    u = HashLife()
    u.set_rect(0, 0, GLIDER)
    notes = PatternMetadata("Glider", "Ångström", ("a comment",))
    for name in ("g.rle", "g.mc", "g.mc.gz"):
        u.save(tmp_path / name, notes)
        found = read_universe((tmp_path / name).read_bytes())
        assert found.metadata == notes
        assert found.universe.population == 5


# -- images -----------------------------------------------------------------------------------


def _pil_bytes(image: Image.Image, fmt: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize("mode", ["1", "L", "P", "RGB"])
def test_bmp_reader_agrees_with_pillows_bmps(mode: str) -> None:
    rng = np.random.default_rng(12)
    rgb = rng.integers(0, 256, size=(9, 13, 3), dtype=np.uint8)
    rgb[rng.random((9, 13)) < 0.5] = 255
    image = Image.fromarray(rgb, "RGB").convert(mode)
    data = _pil_bytes(image, "BMP")
    expected = ~(np.asarray(image.convert("RGB")) == 255).all(axis=2)
    assert detect_format(data) == "bmp"
    assert np.array_equal(read_pattern(data).cells, expected)


@pytest.mark.parametrize("mode", ["1", "L", "P", "RGB", "RGBA", "LA", "I;16"])
def test_png_reader_agrees_with_pillows_pngs(mode: str) -> None:
    rng = np.random.default_rng(13)
    rgb = rng.integers(0, 256, size=(7, 10, 3), dtype=np.uint8)
    rgb[rng.random((7, 10)) < 0.5] = 255
    if mode == "I;16":
        values = rng.integers(65000, 65536, size=(7, 10)).astype(np.uint16)
        image = Image.fromarray(values)  # uint16: mode I;16
        expected = (values >> 8) != 255
    else:
        image = Image.fromarray(rgb, "RGB").convert(mode)
        expected = ~(np.asarray(image.convert("RGB")) == 255).all(axis=2)
    data = _pil_bytes(image, "PNG")
    assert np.array_equal(read_pattern(data).cells, expected)


def test_an_image_past_the_limit_is_refused_before_decoding() -> None:
    data = _pil_bytes(Image.new("1", (4096, 4097), 1), "PNG")
    with pytest.raises(ValueError, match="past the limit"):
        read_pattern(data, max_cells=4096 * 4096)


# -- timelines --------------------------------------------------------------------------------


def test_power_is_the_smallest_base() -> None:
    cases = {1: (2, 0), 2: (2, 1), 8: (2, 3), 9: (3, 2), 12: (12, 1), 36: (6, 2), 64: (2, 6)}
    cases.update({1000: (10, 3), 3**100: (3, 100), 6**50: (6, 50), 2**4095: (2, 4095)})
    cases[(2**61 - 1) ** 3] = (2**61 - 1, 3)
    for step, form in cases.items():
        assert _power(step) == form, step


def test_write_timeline_refuses_what_a_file_cannot_hold() -> None:
    u = HashLife()
    u.set_rect(0, 0, GLIDER)
    a = u.snapshot()
    u.step(2)
    b = u.snapshot()
    u.step(3)
    c = u.snapshot()
    other = HashLife().snapshot()
    with pytest.raises(ValueError, match="at least one"):
        write_timeline(u, [])
    with pytest.raises(ValueError, match="snapshot of the universe"):
        write_timeline(u, [a, other])
    with pytest.raises(ValueError, match="evenly"):
        write_timeline(u, [a, b, c])
    with pytest.raises(ValueError, match="at least 1"):
        write_timeline(u, [b, a])
    with pytest.raises(ValueError, match="at least 1"):
        write_timeline(u, [a, a])


def test_a_timeline_file_loads_its_last_frame_without_timelines() -> None:
    u = HashLife()
    u.set_rect(-1, 0, np.array([[1, 1, 1]], np.uint8))
    frames = []
    for _ in range(3):
        frames.append(u.snapshot())
        u.step(1)
    text = write_timeline(u, frames)
    plain = read_macrocell(text)
    u.restore(frames[-1])
    assert plain.to_macrocell() == u.to_macrocell()
    assert read_universe(text).universe.generation == 2


def test_timeline_frames_survive_garbage_collection() -> None:
    timeline = read_timeline(
        "[M2]\n#FRAMES 2 0 2^1\n.**$**$.*$\n$$$$$$$***$\n#FRAME 0 1\n#FRAME 1 2\n"
    )
    u = timeline.universe
    u.restore(timeline.frames[0])
    u.step(1000)
    u.collect_garbage()
    for frame, population in zip(timeline.frames, (5, 3), strict=True):
        u.restore(frame)
        assert u.population == population


def test_read_timeline_needs_frames() -> None:
    with pytest.raises(ValueError, match="no #FRAMES"):
        read_timeline("[M2]\n**$**$\n")
