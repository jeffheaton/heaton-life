"""Snapshots (spec/hashlife.md "Snapshots", "What snapshots hold"), a file read into a
universe that exists (spec/formats.md "Reading into a universe that exists"), and a
timeline's frames from the reader by content. The vectors pin the counts; these tests pin
the properties that make the counts useful."""

from __future__ import annotations

import gzip

import numpy as np
import pytest

from heaton_life.ca.hashlife import HashLife, read_timeline, read_universe, write_timeline
from heaton_life.ca.hashlife.store import NODE_BYTES
from heaton_life.init import PatternMetadata

GLIDER = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], np.uint8)
GUN = (
    "#CXRLE Pos=-18,-4\nx = 36, y = 9, rule = B3/S23\n"
    "24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$2o8bo3bob2o4bobo$"
    "10bo5bo7bo$11bo3bo$12b2o!\n"
)


def _node_lines(text: str) -> int:
    """The node lines of a Macrocell text (everything after the header but # lines)."""
    return sum(1 for line in text.splitlines()[1:] if not line.startswith("#"))


def test_a_states_nodes_are_its_canonical_macrocell_lines() -> None:
    u = HashLife.from_rle(GUN)
    for _ in range(6):
        assert u.measure_snapshots([]).universe_nodes == _node_lines(u.to_macrocell())
        u.step(37)
    assert HashLife().measure_snapshots([]).universe_nodes == 0  # its `$` is no node


def test_the_last_snapshots_counts_add_up_to_what_letting_them_go_frees() -> None:
    u = HashLife.from_rle(GUN)
    history = []
    for _ in range(7):
        history.append(u.snapshot())
        u.step(17)
        u.set_cell(40, 3 * len(history), True)  # every point a little different
    newest_first = history[::-1]
    whole = u.measure_snapshots(newest_first)
    assert whole.nodes == sum(whole.added)
    assert whole.estimated_bytes == whole.nodes * NODE_BYTES
    for k in range(len(newest_first) + 1):
        kept = newest_first[: len(newest_first) - k]
        freed = whole.nodes - u.measure_snapshots(kept).nodes
        assert freed == sum(whole.added[len(newest_first) - k :]), k


def test_a_snapshot_of_the_current_state_or_listed_twice_adds_nothing() -> None:
    u = HashLife.from_rle(GUN)
    old = u.snapshot()
    u.step(90)
    now = u.snapshot()
    footprint = u.measure_snapshots([now, old, old])
    assert footprint.added[0] == 0
    assert footprint.added[1] > 0
    assert footprint.added[2] == 0


def test_a_released_snapshot_lets_a_collection_free_its_nodes() -> None:
    u = HashLife.from_rle(GUN)
    old = u.snapshot()
    u.step(1000)
    u.collect_garbage()
    holding = u.node_count
    assert not old.released
    old.release()
    old.release()  # again does nothing
    assert old.released
    assert old.generation == 0  # still readable
    u.collect_garbage()
    assert u.node_count < holding
    assert u.measure_snapshots([old]).added == (0,)
    with pytest.raises(ValueError, match="released"):
        u.restore(old)
    with pytest.raises(ValueError, match="released"):
        write_timeline(u, [old])


def test_measuring_another_universes_snapshot_is_an_error() -> None:
    a, b = HashLife(), HashLife()
    with pytest.raises(ValueError, match="another universe"):
        a.measure_snapshots([b.snapshot()])


def test_advancing_part_of_the_universe_holds_no_snapshot_after() -> None:
    u = HashLife.from_rle(GUN)
    u.advance_selection(-18, -4, 0, 4, 30)
    u.advance_outside(-18, -4, 0, 4, 30)
    assert len(u._snapshots) == 0


def test_read_snapshot_keeps_the_universe_and_its_history() -> None:
    u = HashLife("B36/S23")
    u.set_rect(0, 0, GLIDER)
    first = u.snapshot()
    u.step(40)
    before = (u.to_macrocell(), u.generation, u.rule)
    found = u.read_snapshot(GUN.encode())
    assert (u.to_macrocell(), u.generation, u.rule) == before
    assert (found.format, found.rule, found.frames, found.step) == ("rle", "B3/S23", (), None)
    u.rule = found.rule
    u.restore(found.snapshot)
    assert u.to_macrocell() == read_universe(GUN).universe.to_macrocell()
    u.restore(first)  # the history from before the read still restores
    assert (u.generation, u.population) == (0, 5)


def test_a_refused_file_leaves_the_universe_and_its_snapshots() -> None:
    u = HashLife()
    u.set_rect(-3, 2, GLIDER)
    kept = u.snapshot()
    u.step(9)
    before = (u.to_macrocell(), u.generation, u.rule)
    for bad in (
        b"#Life 1.05\n#R 23/3/4\n#P 0 0\n**\n",  # not a Life-like rule
        b"#Life 1.06\n1000000001 0\n",  # outside the editing box
        b"x = 2, y = 1, rule = WireWorld\nAC!\n",  # extended
        b"[M2]\n#FRAMES 2 0 1\n*$\n#FRAME 0 1\n",  # a frame missing
        b"[M2]\n#R life\n*$\n",  # a preset
    ):
        with pytest.raises(ValueError):
            u.read_snapshot(bad)
        assert (u.to_macrocell(), u.generation, u.rule) == before
    u.restore(kept)
    assert u.generation == 0


def test_a_file_shares_the_nodes_the_store_already_holds() -> None:
    u = HashLife.from_rle(GUN)
    u.step(120)
    found = u.read_snapshot(u.to_macrocell())
    assert u.measure_snapshots([found.snapshot]).added == (0,)
    shifted = u.read_snapshot(GUN.replace("Pos=-18,-4", "Pos=-17,-4"))
    assert u.measure_snapshots([shifted.snapshot]).added[0] > 0


def test_a_timeline_gives_its_frames_to_both_readers() -> None:
    recorded = HashLife.from_rle(GUN)
    frames = []
    for generation in (0, 30, 60, 90):
        recorded.step(generation - recorded.generation)
        frames.append(recorded.snapshot())
    text = write_timeline(recorded, frames, metadata=PatternMetadata("Gun"))
    expected = []
    timeline = read_timeline(text)
    for frame in timeline.frames:
        timeline.universe.restore(frame)
        expected.append(timeline.universe.to_macrocell())
    for source in (text, gzip.compress(text.encode(), mtime=0)):
        found = read_universe(source)
        assert found.step == 30 and found.metadata == PatternMetadata("Gun")
        assert found.universe.generation == 90  # the file's own root and #G
        got = []
        for frame in found.frames:
            found.universe.restore(frame)
            got.append(found.universe.to_macrocell())
        assert got == expected
        host = HashLife("B36/S23")
        host.set_rect(5, 5, GLIDER)
        snap = host.read_snapshot(source)
        assert (snap.step, snap.rule, host.generation) == (30, "B3/S23", 0)
        host.rule = snap.rule
        got = []
        for frame in snap.frames:
            host.restore(frame)
            got.append(host.to_macrocell())
        assert got == expected


def test_frame_lines_without_a_frames_line_are_no_timeline() -> None:
    found = read_universe("[M2]\n*$\n#FRAME 0 1\n")
    assert found.frames == () and found.step is None
    # The plain Macrocell reader skips a broken timeline; the reader by content refuses it.
    broken = "[M2]\n#FRAMES 2 0 1\n*$\n#FRAME 1 1\n"
    assert HashLife.from_macrocell(broken).population == 1
    with pytest.raises(ValueError, match="frame 0"):
        read_universe(broken)
