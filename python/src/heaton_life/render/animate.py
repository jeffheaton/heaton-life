"""Run a simulation and export the frames as an animation (GIF; MP4 arrives with the video extra)."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from heaton_life.core.protocols import Simulation
from heaton_life.render.colormap import apply_colormap
from heaton_life.render.image import to_image


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
        try:
            import imageio.v2 as imageio
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                'MP4 export needs imageio-ffmpeg: pip install "heaton-life[video]"'
            ) from exc
        writer = imageio.get_writer(path, fps=self.fps, codec="libx264", quality=8)
        try:
            for image in self._images():
                # libx264 requires even dimensions
                width = image.width - image.width % 2
                height = image.height - image.height % 2
                if (width, height) != (image.width, image.height):
                    image = image.crop((0, 0, width, height))
                writer.append_data(np.asarray(image))
        finally:
            writer.close()

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
