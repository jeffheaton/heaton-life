"""State palettes (spec/render.md "State palettes"): each family's default, a colormap's
palette, the named palettes, the shade and the zoom order that goes with a palette."""

import numpy as np
import pytest

from heaton_life.ca import (
    Cyclic,
    Elementary,
    Generations,
    HashLife,
    LargerThanLife,
    LifeLike,
    Wireworld,
)
from heaton_life.ca.hashlife import MultiStateHashLife
from heaton_life.rd import GrayScott
from heaton_life.render import (
    HISTORY_COLORS,
    HISTORY_ZOOM_ORDER,
    SUPER_COLORS,
    SUPER_ZOOM_ORDER,
    apply_colormap,
    colormap_palette,
    default_palette,
    default_zoom_order,
    frame_values,
    generations_palette,
    get_colormap,
    gradient_palette,
    history_palette,
    list_colormaps,
    multistate_palette,
    shade_colormap,
    super_palette,
)


def _worlds() -> list[tuple[object, np.ndarray]]:
    """(world, its byte frame of states) for every grid family with byte states."""
    life = LifeLike("B3/S23", size=(24, 20), seed=1)
    life.step(3)
    history = LifeLike("B3/S23History", size=(24, 20), seed=1)
    history.step(9)
    elementary = Elementary(30, size=(40, 24))
    elementary.step(30)
    cyclic = Cyclic(14, size=(24, 20), seed=4)
    cyclic.step(5)
    wire = Wireworld(size=(16, 16), init="clock")
    wire.step(4)
    generations = Generations("B2/S345/C6", size=(24, 20), seed=5)
    generations.step(6)
    return [
        (life, life.state),
        (history, history.state),
        (elementary, elementary.diagram),
        (cyclic, cyclic.state),
        (wire, wire.state),
        (generations, generations.state),
    ]


@pytest.mark.parametrize("cmap", list_colormaps())
def test_a_colormaps_palette_shows_the_states_as_the_colormap_shows_the_frame(cmap: str) -> None:
    for world, states in _worlds():
        frame = world.frame()  # type: ignore[attr-defined]
        palette = colormap_palette(world, cmap)
        assert np.array_equal(apply_colormap(states, palette), apply_colormap(frame, cmap))
        count = len(frame_values(world))
        assert not palette[count:].any(), "entries past the states are black"


def test_frame_values_are_each_states_frame_byte() -> None:
    for world, states in _worlds():
        values = np.asarray(frame_values(world), dtype=np.uint8)
        assert values[0] == 0
        assert np.array_equal(values[states], world.frame())  # type: ignore[attr-defined]
    assert frame_values(HashLife("B3/S23")) == (0, 255)
    assert frame_values(MultiStateHashLife("WireWorld")) == (0, 1, 2, 3)
    assert frame_values(Cyclic(1 + 1, size=(8, 8))) == (0, 255)


def test_each_family_has_the_default_the_spec_gives() -> None:
    worlds = {type(w).__name__ + str(getattr(w, "states", "")): w for w, _ in _worlds()}
    assert np.array_equal(
        default_palette(worlds["LifeLike2"]), colormap_palette(worlds["LifeLike2"], "phosphor")
    )
    assert default_palette(worlds["LifeLike2"])[:2].tolist() == [[6, 10, 6], [170, 255, 190]]
    assert np.array_equal(default_palette(worlds["LifeLike7"]), history_palette())
    for world, _ in _worlds():
        name = type(world).__name__
        expected = {
            "Elementary": colormap_palette(world, "gray"),
            "Cyclic": colormap_palette(world, "rainbow"),
            "Wireworld": colormap_palette(world, "wireworld"),
        }.get(name)
        if expected is not None:
            assert np.array_equal(default_palette(world), expected)
        if name == "Generations":
            states = world.states  # type: ignore[attr-defined]
            assert np.array_equal(default_palette(world), generations_palette(states))
            assert np.array_equal(default_palette(world), colormap_palette(world, "fire"))
    assert np.array_equal(default_palette(HashLife("B3/S23")), default_palette(worlds["LifeLike2"]))


def test_a_universes_palette_is_its_rules_on_a_grid() -> None:
    wire = Wireworld(size=(16, 16), init="clock")
    assert np.array_equal(default_palette(MultiStateHashLife("WireWorld")), default_palette(wire))
    assert np.array_equal(default_palette(MultiStateHashLife("B36/S23History")), history_palette())
    for rule, count in (("B2/S/C3", 3), ("B2/S345/C4", 4), ("B3/S23/C256", 256)):
        grid = Generations(rule, size=(8, 8))
        plane = MultiStateHashLife(rule)
        assert np.array_equal(default_palette(plane), default_palette(grid))
        assert np.array_equal(default_palette(plane), generations_palette(count))


def test_larger_than_life_takes_phosphor_or_generations() -> None:
    two = LargerThanLife("R5,C0,M1,S34..58,B34..45,NM", size=(40, 32), seed=2)
    two.step(2)
    many = LargerThanLife("R2,C5,M0,S3..8,B4..6,NM", size=(40, 32), seed=3)
    many.step(6)
    assert frame_values(two) == (0, 255)
    assert frame_values(many) == (0, 1, 2, 3, 4)
    assert np.array_equal(default_palette(two), colormap_palette(two, "phosphor"))
    assert np.array_equal(default_palette(many), generations_palette(5))
    assert default_zoom_order(two) == () and default_zoom_order(many) == ()
    assert np.unique(two.state).tolist() == [0, 1]
    assert np.unique(many.state).tolist() == [0, 1, 2, 3, 4]  # every state is shown
    for world in (two, many):
        for cmap in ("phosphor", "fire", "rainbow"):
            assert np.array_equal(
                apply_colormap(world.state, colormap_palette(world, cmap)),
                apply_colormap(world.frame(), cmap),
            )


def test_historys_colors() -> None:
    palette = history_palette()
    assert [tuple(c) for c in palette[:7].tolist()] == list(HISTORY_COLORS)
    assert HISTORY_COLORS == (
        (0, 0, 0),
        (0, 255, 0),
        (0, 0, 160),
        (255, 255, 255),
        (255, 0, 0),
        (255, 255, 0),
        (128, 128, 128),
    )
    assert not palette[7:].any()


@pytest.mark.parametrize("count", [2, 3, 4, 5, 17, 64, 255, 256])
def test_generations_palette_is_fire_at_the_fade(count: int) -> None:
    fire = get_colormap("fire")
    palette = generations_palette(count)
    assert palette[0].tolist() == [0, 0, 0]
    assert palette[1].tolist() == fire[255].tolist()  # alive: pale yellow
    for s in range(1, count):
        assert palette[s].tolist() == fire[255 * (count - s) // (count - 1)].tolist()
    assert not palette[count:].any()


@pytest.mark.parametrize("count", [2, 3, 4, 8, 20, 100, 256])
def test_the_multistate_palette_gives_every_state_its_own_hue(count: int) -> None:
    rainbow = get_colormap("rainbow")
    palette = multistate_palette(count)
    assert palette[0].tolist() == [0, 0, 0]
    for s in range(1, count):
        assert palette[s].tolist() == rainbow[255 * (s - 1) // (count - 1)].tolist()
    colors = {tuple(c) for c in palette[1:count].tolist()}
    assert len(colors) == count - 1 and (0, 0, 0) not in colors
    assert not palette[count:].any()


def test_a_gradient_runs_from_first_to_last_rounding_half_to_even() -> None:
    palette = gradient_palette(6, (255, 0, 0), (0, 0, 255))
    assert palette[:6].tolist() == [
        [0, 0, 0],
        [255, 0, 0],
        [191, 0, 64],
        [128, 0, 128],
        [64, 0, 191],
        [0, 0, 255],
    ]
    # Four states share two steps: the middle state sits exactly halfway, 0.5 and 1.5.
    ties = gradient_palette(4, (0, 0, 3), (1, 3, 0), background=(9, 8, 7))
    assert ties[:4].tolist() == [[9, 8, 7], [0, 0, 3], [0, 2, 2], [1, 3, 0]]
    assert gradient_palette(2, (1, 2, 3), (4, 5, 6))[:3].tolist() == [
        [0, 0, 0],
        [1, 2, 3],
        [0, 0, 0],
    ]
    big = gradient_palette(256, (0, 0, 0), (100, 100, 100))
    assert [c[0] for c in big[1:].tolist()] == [round(100 * k / 254) for k in range(255)]


def test_the_shade_is_the_two_anchor_colormap() -> None:
    assert np.array_equal(shade_colormap((0, 0, 0), (255, 255, 255)), get_colormap("gray"))
    rng = np.random.default_rng(7)
    xs = np.linspace(0.0, 1.0, 256)
    for _ in range(200):
        b, c = rng.integers(0, 256, 3), rng.integers(0, 256, 3)
        built = np.stack(
            [np.interp(xs, [0.0, 1.0], [b[k], c[k]]) for k in range(3)], axis=1
        ).round()
        assert np.array_equal(shade_colormap(b, c), built.astype(np.uint8))
    shade = shade_colormap((6, 10, 6), (170, 255, 190))
    assert shade[0].tolist() == [6, 10, 6] and shade[255].tolist() == [170, 255, 190]


def test_the_zoom_order_goes_with_the_palette() -> None:
    assert HISTORY_ZOOM_ORDER == (3, 5, 1, 4, 6, 2)
    assert default_zoom_order(LifeLike("B3/S23History", size=(8, 8))) == HISTORY_ZOOM_ORDER
    assert default_zoom_order(LifeLike("B2/S34HHistory", size=(8, 8))) == HISTORY_ZOOM_ORDER
    assert default_zoom_order(MultiStateHashLife("LifeHistory")) == HISTORY_ZOOM_ORDER
    for world in (
        LifeLike("B3/S23", size=(8, 8)),
        Generations("B2/S/C3", size=(8, 8)),
        Wireworld(size=(16, 16)),
        Cyclic(5, size=(8, 8)),
        Elementary(90, size=(8, 8)),
        HashLife("B3/S23"),
        MultiStateHashLife("WireWorld"),
        MultiStateHashLife("B2/S/C3"),
    ):
        assert default_zoom_order(world) == ()
    universe = MultiStateHashLife("B3/S23History")
    universe.zoom_order = default_zoom_order(universe)  # the host sets it
    assert universe.zoom_order == HISTORY_ZOOM_ORDER


def test_worlds_without_byte_states_have_no_palette() -> None:
    for call in (frame_values, default_palette, default_zoom_order):
        with pytest.raises(TypeError, match="no byte states"):
            call(GrayScott(size=(8, 8)))
    with pytest.raises(TypeError):
        colormap_palette(GrayScott(size=(8, 8)), "gray")


@pytest.mark.parametrize("count", [0, 1, 257, -3])
def test_a_palette_is_for_2_to_256_states(count: int) -> None:
    for build in (generations_palette, multistate_palette):
        with pytest.raises(ValueError, match="2 to 256 states"):
            build(count)
    with pytest.raises(ValueError, match="2 to 256 states"):
        gradient_palette(count, (0, 0, 0), (1, 1, 1))


def test_colors_are_three_bytes() -> None:
    for bad in ((0, 0), (0, 0, 0, 0), (0, 256, 0), (-1, 0, 0)):
        with pytest.raises(ValueError, match="three bytes"):
            gradient_palette(3, bad, (0, 0, 0))
        with pytest.raises(ValueError, match="three bytes"):
            shade_colormap((0, 0, 0), bad)
    with pytest.raises(ValueError, match="uint8"):
        colormap_palette(LifeLike("B3/S23", size=(8, 8)), np.zeros((256, 3), dtype=np.int64))


def test_supers_palette_and_zoom_order() -> None:
    """Super's 26 colors (spec/render.md "Default palettes"): History's for states 0–6 and
    none twice; its zoom order extends History's, every on state before every off one and
    the envelopes last ("Zoomed out")."""
    palette = super_palette()
    assert [tuple(c) for c in palette[:26].tolist()] == list(SUPER_COLORS)
    assert SUPER_COLORS[:7] == HISTORY_COLORS and len(set(SUPER_COLORS)) == 26
    assert SUPER_COLORS[13] == (255, 216, 255)  # pale pink: white is marked on's (state 3)
    assert not palette[26:].any()
    assert sorted(SUPER_ZOOM_ORDER) == list(range(1, 26))
    assert tuple(s for s in SUPER_ZOOM_ORDER if s < 7) == HISTORY_ZOOM_ORDER
    on = sum(1 for s in SUPER_ZOOM_ORDER if s & 1)
    assert all(s & 1 for s in SUPER_ZOOM_ORDER[:on])
    assert SUPER_ZOOM_ORDER[-3:] == (2, 10, 12)
    for world in (
        LifeLike("B3/S23Super", size=(8, 8)),
        LifeLike("B2/S013VSuper", size=(8, 8)),
        MultiStateHashLife("LifeSuper"),
    ):
        assert np.array_equal(default_palette(world), palette)
        assert default_zoom_order(world) == SUPER_ZOOM_ORDER
        assert frame_values(world) == tuple(range(26))
    universe = MultiStateHashLife("B3/S23Super")
    universe.zoom_order = default_zoom_order(universe)  # the host sets it
    assert universe.zoom_order == SUPER_ZOOM_ORDER
    assert np.array_equal(default_palette(LifeLike("LifeHistory", size=(8, 8))), history_palette())
