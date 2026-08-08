import numpy as np
import pytest
from PIL import Image

from heaton_life.ca import LifeLike
from heaton_life.render import animate, apply_colormap, get_colormap, to_image


def test_colormap_shape_and_endpoints() -> None:
    lut = get_colormap("gray")
    assert lut.shape == (256, 3)
    assert lut.dtype == np.uint8
    assert lut[0].tolist() == [0, 0, 0]
    assert lut[255].tolist() == [255, 255, 255]


def test_unknown_colormap_raises() -> None:
    with pytest.raises(ValueError):
        get_colormap("plasma-deluxe")


def test_apply_colormap_uint8_float_rgb() -> None:
    u8 = np.array([[0, 255]], dtype=np.uint8)
    assert apply_colormap(u8, "gray").tolist() == [[[0, 0, 0], [255, 255, 255]]]
    fl = np.array([[0.0, 1.0]])
    assert apply_colormap(fl, "gray").tolist() == [[[0, 0, 0], [255, 255, 255]]]
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    assert apply_colormap(rgb).shape == (2, 2, 3)


def test_apply_colormap_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError):
        apply_colormap(np.zeros((2, 2, 4), dtype=np.uint8))
    with pytest.raises(ValueError):
        apply_colormap(np.zeros((2,), dtype=np.uint8))


def test_to_image_scale() -> None:
    frame = np.zeros((8, 6), dtype=np.uint8)
    img = to_image(frame, scale=4)
    assert (img.width, img.height) == (24, 32)
    assert img.mode == "RGB"


def test_animate_frame_count_and_gif(tmp_path) -> None:
    sim = LifeLike(size=(32, 32), seed=1)
    anim = animate(sim, steps=10, every=2, fps=20)
    assert len(anim) == 6  # initial + 5 captures
    out = anim.save(tmp_path / "out.gif")
    with Image.open(out) as img:
        assert img.n_frames == 6
    assert sim.generation == 10


def test_animate_rejects_bad_args(tmp_path) -> None:
    sim = LifeLike(size=(16, 16))
    with pytest.raises(ValueError):
        animate(sim, steps=-1)
    anim = animate(sim, steps=1)
    with pytest.raises(ValueError):
        anim.save(tmp_path / "out.webm")


def test_mp4_export(tmp_path) -> None:
    pytest.importorskip("imageio")
    pytest.importorskip("imageio_ffmpeg")
    sim = LifeLike(size=(32, 32), seed=1)
    out = animate(sim, steps=5, fps=10).save(tmp_path / "out.mp4")
    assert out.exists() and out.stat().st_size > 0
