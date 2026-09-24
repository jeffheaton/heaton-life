"""Run a simulation and export the frames as an animation (GIF; MP4 arrives with the video extra)."""

from __future__ import annotations

import base64
import importlib.util
import io
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from heaton_life.core.protocols import Simulation
from heaton_life.render.colormap import apply_colormap
from heaton_life.render.image import to_image


def mp4_target(path: str | Path) -> Path:
    """The file an .mp4 writer will write, resolved once exactly as imageio resolves it
    (os.path.expanduser, then os.path.abspath), so every check touches the file ffmpeg
    writes even if the working directory changes later."""
    return Path(os.path.abspath(os.path.expanduser(path)))


def open_mp4(path: str | Path, fps: int) -> Any:
    """An imageio writer for H.264 (libx264, yuv420p) at the frames' own size (the video
    extra). macro_block_size 1: imageio's default of 16 rescales any size that is not a
    multiple of 16, so 1080 rows would be stretched to 1088. ffmpeg itself starts only at
    the first frame, so the target is checked here: ffmpeg must be present, an existing
    target must be a regular file it can read and write, and a new one's directory must
    exist and be writable. Before the first frame goes in, empty the target with
    start_mp4; close with close_mp4, which confirms ffmpeg wrote a whole movie."""
    try:
        import imageio.v2 as imageio
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            'MP4 export needs imageio-ffmpeg: pip install "heaton-life[video]"'
        ) from exc
    if importlib.util.find_spec("imageio_ffmpeg") is None:  # imageio's .mp4 backend
        raise RuntimeError('MP4 export needs imageio-ffmpeg: pip install "heaton-life[video]"')
    exe = importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe()
    if shutil.which(exe) is None:
        raise FileNotFoundError(f"no ffmpeg at {exe}")
    target = mp4_target(path)
    if target.exists():
        if not target.is_file():
            raise OSError(f"{target} is not a regular file")
        if not os.access(target, os.R_OK | os.W_OK):  # ffmpeg overwrites it in place
            raise PermissionError(f"cannot read and write {target}")
    elif not target.parent.is_dir():
        raise FileNotFoundError(f"no directory {target.parent}")
    elif not os.access(target.parent, os.W_OK):
        raise PermissionError(f"cannot write {target}")
    return imageio.get_writer(
        target, fps=fps, codec="libx264", quality=8, macro_block_size=1, pixelformat="yuv420p"
    )


def start_mp4(path: str | Path) -> None:
    """Empty the target once the first frame is ready to go to ffmpeg (which would
    truncate it too), so close_mp4 never mistakes an old movie for a new one."""
    mp4_target(path).open("wb").close()


def close_mp4(writer: Any, path: str | Path, frames: int) -> None:
    """Close an open_mp4 writer and, when frames were written, confirm ffmpeg wrote a
    whole movie: imageio-ffmpeg never checks ffmpeg's exit status, so a failed encode
    would otherwise pass silently. The file must exist and be an MP4 whose top-level
    boxes cover it exactly and include the movie header (moov)."""
    writer.close()
    if frames == 0:
        return
    target = mp4_target(path)
    if not (target.is_file() and _whole_mp4(target)):
        raise OSError(f"ffmpeg wrote no whole movie to {target}; its own messages say why")


def _whole_mp4(path: Path) -> bool:
    """True if the file's top-level boxes (32-bit size and type; size 1: a 64-bit size
    follows; size 0: to the end of the file) tile it exactly and include moov."""
    size = path.stat().st_size
    offset, moov = 0, False
    with path.open("rb") as file:
        while offset < size:
            file.seek(offset)
            header = file.read(8)
            if len(header) < 8:
                return False
            length, kind = int.from_bytes(header[:4], "big"), header[4:]
            if length == 1:
                extended = file.read(8)
                if len(extended) < 8:
                    return False
                length = int.from_bytes(extended, "big")
            elif length == 0:
                length = size - offset
            if length < 8:
                return False
            moov = moov or kind == b"moov"
            offset += length
    return offset == size and moov


def even_crop(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """An .mp4 frame, checked and cropped to even dimensions (which yuv420p needs): a
    uint8 (height, width) or (height, width, 1-4) array at least 2 x 2."""
    rgb = np.asarray(rgb)
    if (
        rgb.dtype != np.uint8
        or rgb.ndim not in (2, 3)
        or (rgb.ndim == 3 and not 1 <= rgb.shape[2] <= 4)
    ):
        raise ValueError(
            f"an .mp4 frame is a uint8 (H, W) or (H, W, 1-4) array, got {rgb.dtype} {rgb.shape}"
        )
    height, width = rgb.shape[:2]
    if height < 2 or width < 2:
        raise ValueError(f"an .mp4 frame must be at least 2 x 2 pixels, got {width} x {height}")
    cropped: NDArray[np.uint8] = rgb[: height - height % 2, : width - width % 2]
    return cropped


class Animation:
    """A captured sequence of RGB frames."""

    def __init__(self, frames: list[NDArray[np.uint8]], *, fps: int = 30, scale: int = 1) -> None:
        if not frames:
            raise ValueError("animation needs at least one frame")
        self.frames = frames
        self.fps = fps
        self.scale = scale

    def __len__(self) -> int:
        return len(self.frames)

    def _images(self) -> list[Image.Image]:
        return [to_image(f, scale=self.scale) for f in self.frames]

    def _write_gif(self, target: io.BytesIO | str | Path) -> None:
        images = self._images()
        duration = max(20, round(1000 / self.fps))
        images[0].save(
            target,
            format="GIF",
            save_all=True,
            append_images=images[1:],
            duration=duration,
            loop=0,
        )

    def save(self, path: str | Path) -> Path:
        """Save as .gif (built in) or .mp4 (requires the video extra: imageio-ffmpeg)."""
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".gif":
            self._write_gif(path)
        elif suffix == ".mp4":
            self._write_mp4(path)
        else:
            raise ValueError(f"unsupported format {path.suffix!r} (use .gif or .mp4)")
        return path

    def _write_mp4(self, path: Path) -> None:
        target = mp4_target(path)
        frames = [even_crop(np.asarray(image)) for image in self._images()]  # all ready first
        writer = open_mp4(target, self.fps)
        try:
            start_mp4(target)
            for frame in frames:
                writer.append_data(frame)
        except BaseException:
            writer.close()
            raise
        close_mp4(writer, target, len(frames))

    def _repr_html_(self) -> str:
        buf = io.BytesIO()
        self._write_gif(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f'<img src="data:image/gif;base64,{b64}"/>'


def animate(
    sim: Simulation,
    steps: int,
    *,
    cmap: str | NDArray[np.uint8] = "gray",
    every: int = 1,
    scale: int = 1,
    fps: int = 30,
) -> Animation:
    """Capture the current frame, then step ``steps`` times, keeping every ``every``-th frame."""
    if steps < 0 or every < 1:
        raise ValueError("steps must be >= 0 and every >= 1")
    frames = [apply_colormap(sim.frame(), cmap)]
    for i in range(steps):
        sim.step()
        if (i + 1) % every == 0:
            frames.append(apply_colormap(sim.frame(), cmap))
    return Animation(frames, fps=fps, scale=scale)
