"""The playground's live view (playground/navigator.py, Qt-free): gestures move the view with
the spec's exact arithmetic, and the last frame maps into the new view cell for cell, so
the canvas can preview it until the engine renders anew."""

from __future__ import annotations

import math

from heaton_life.ca.hashlife import MAX_MAG, LifeView, cell_at, center_cell, pan, zoom_at
from heaton_life.playground.navigator import MIN_MAG, FrameMap, ViewNavigator

SIZE = (768, 512)


def _lands_at(where: FrameMap, u: float, v: float) -> tuple[float, float]:
    return u * where.scale + where.dx, v * where.scale + where.dy


def test_zoom_is_the_spec_arithmetic_and_keeps_the_pixel_under_the_pointer() -> None:
    start = LifeView(-300, 41, -3)
    nav = ViewNavigator(start, SIZE)
    assert nav.zoom_at(100, 200, 1)
    assert nav.view == zoom_at(start, 100, 200, 1)
    where = nav.frame_map(start, SIZE)
    assert where is not None and where.scale == 2.0
    assert _lands_at(where, 100, 200) == (100, 200)


def test_zoom_stops_at_the_deepest_zoom_and_the_mag_floor() -> None:
    nav = ViewNavigator(LifeView(0, 0, MAX_MAG), SIZE)
    assert not nav.zoom_at(5, 5, 1)
    nav = ViewNavigator(LifeView(0, 0, MIN_MAG + 1), SIZE)
    assert nav.zoom_at(5, 5, -3)
    assert nav.view.mag == MIN_MAG
    assert not nav.zoom_at(5, 5, -1)


def test_pan_carries_fractions_into_the_next_drag() -> None:
    start = LifeView(10, 20, 0)
    nav = ViewNavigator(start, SIZE)
    assert not nav.pan(0.4, -0.4)
    assert nav.pan(0.7, -0.7)  # 1.1 each way: one whole pixel, 0.1 carried
    assert nav.view == pan(start, 1, -1)
    assert not nav.pan(0.85, -0.85)  # 0.95: still short of the next pixel
    assert nav.pan(0.1, -0.1)
    assert nav.view == pan(start, 2, -2)
    where = nav.frame_map(start, SIZE)
    assert where is not None and (where.scale, where.dx, where.dy) == (1.0, 2.0, -2.0)


def test_recenter_brings_the_pixel_to_the_center() -> None:
    nav = ViewNavigator(LifeView(-17, 9, 2), SIZE)
    target = cell_at(nav.view, 10, 30)
    assert nav.recenter(10, 30)
    assert cell_at(nav.view, SIZE[0] // 2, SIZE[1] // 2) == target


def test_a_resize_keeps_the_center_and_the_last_frame_lands_in_the_middle() -> None:
    for start in (LifeView(-300, 41, -3), LifeView(17, -9, 2)):
        nav = ViewNavigator(start, SIZE)
        assert not nav.resize(SIZE)
        bigger = (1001, 700)
        assert nav.resize(bigger)
        assert nav.size == bigger
        assert center_cell(nav.view, bigger) == center_cell(start, SIZE)
        where = nav.frame_map(start, SIZE)
        assert where is not None
        assert (where.scale, where.dx, where.dy) == (1.0, 1001 // 2 - 768 // 2, 700 // 2 - 512 // 2)
        assert nav.resize(SIZE) and nav.view == start, "the old size brings back the old view"


def test_zoomed_in_every_frame_pixel_lands_on_its_own_cell() -> None:
    frame = LifeView(-1001, 77, 0)
    for steps, pixel in ((1, (321, 123)), (3, (0, 0)), (5, (767, 511))):
        nav = ViewNavigator(frame, SIZE)
        assert nav.zoom_at(*pixel, steps)
        nav.pan(13, -7)
        where = nav.frame_map(frame, SIZE)
        assert where is not None and where.scale == 2.0**steps
        for u, v in ((0, 0), (5, 9), pixel, (700, 500)):
            i, j = _lands_at(where, u, v)
            if 0 <= i < SIZE[0] and 0 <= j < SIZE[1]:
                assert cell_at(nav.view, int(i), int(j)) == cell_at(frame, u, v)


def test_zoomed_out_every_frame_pixel_lands_in_its_block() -> None:
    frame = LifeView(-50, 33, 1)
    nav = ViewNavigator(frame, SIZE)
    assert nav.zoom_at(400, 300, -4)  # mag -3: 8 × 8 cells a pixel
    where = nav.frame_map(frame, SIZE)
    assert where is not None and where.scale == 2.0**-4
    for u, v in ((0, 0), (17, 401), (400, 300), (767, 511)):
        i, j = _lands_at(where, u, v)
        bx, by = cell_at(nav.view, math.floor(i), math.floor(j))  # the block's top-left cell
        cx, cy = cell_at(frame, u, v)
        assert bx <= cx < bx + 8 and by <= cy < by + 8


def test_frames_far_away_or_far_off_scale_have_no_preview() -> None:
    frame = LifeView(0, 0, 0)
    assert ViewNavigator(LifeView(10**6, 0, 0), SIZE).frame_map(frame, SIZE) is None
    assert ViewNavigator(LifeView(0, 0, -13), SIZE).frame_map(frame, SIZE) is None
    assert ViewNavigator(LifeView(0, 0, -12), SIZE).frame_map(frame, SIZE) is not None
    far = 3**300  # past float range: the miss is decided exactly
    assert ViewNavigator(LifeView(far, -far, 0), SIZE).frame_map(frame, SIZE) is None
