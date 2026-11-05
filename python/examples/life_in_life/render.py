"""Render the Life-in-Life Short: 1080×1920, 30 fps, H.264.

A glider of OTCA metapixels glides on the 6×6 board. When its inner generation 3 appears,
the camera dives into one of its live metapixels at a steady exponential zoom while time
slows from about 66,000 generations per second to 2, so something is always moving. The
zoom lands on a real glider framed exactly like the opening glider, so the video loops.

Frames are HashLife density renders at the power-of-two magnification just finer than the
output, averaged over sub-steps (motion blur), box-filtered to the exact zoom, and
tone-mapped by scale: far out a lit display (~1.3% live) reads as a lit cell; up close it
is nearly linear. A faint cell grid fades in at the end to echo the metapixel outlines.

Usage: python render.py [--speed 2] [--out out/life_in_life_30s.mp4]
       python render.py --frames 300 --stills out/stills   (a 10 s preview with stills)
"""

from __future__ import annotations

import argparse
import importlib
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from board import GLIDER_AT, OUT, PERIOD, PITCH, SIZE, inner_cells, life_step
from numpy.typing import NDArray

from heaton_life.ca.hashlife import MAX_MAG, HashLife, LifeView

if TYPE_CHECKING:
    from PyQt6.QtGui import QFont, QGuiApplication, QImage

# -- layout ----------------------------------------------------------------------------------
W, H, FPS = 1080, 1920, 30
SQ = 1080  # the square viewport, centered vertically
SQ_Y = (H - SQ) // 2
MARGIN = 24  # pixels around the board at the start
BG = np.array([6, 8, 11], dtype=np.float32)
FG = np.array([236, 242, 248], dtype=np.float32)
GRID_ALPHA = 0.22  # cell grid brightness once cells are large

# -- the board ---------------------------------------------------------------------------------
FLIP_MID = 6912  # phase at which a display is half switched
BOARD = PITCH * SIZE
S0 = BOARD / (SQ - 2 * MARGIN)  # cells per output pixel at the start

# -- schedule (60 s; --speed plays it faster) ----------------------------------------------------
N_FRAMES = 60 * FPS
OPEN_RATE = PERIOD / 16  # 2,208 generations per frame: 16 frames per inner generation
ZOOM_DOUBLINGS = 11  # 2^11 = one metapixel: the end shows 6 cells as the start shows 6 tiles
ZOOM_END_T = 60.0  # the zoom lands on the last frame
RAMP_IN, RAMP_OUT = 0.6, 4.0  # the zoom speed eases in and out (seconds)
RATE_AFTER_1 = 150.0  # generations per frame one doubling in
END_RATE = 2.0 / FPS  # 2 generations per second at the end
PAN_DOUBLINGS = 4.0  # the landing spot reaches the screen center by here
MAX_SUBSTEPS = 8
LEAN_MAX = 0.5  # how far the camera leans toward the final glider…
LEAN_T = (38.0, 46.0)  # …easing in over these seconds

# The landing spot: pick_glider.py's choice for this board and schedule (re-pick if either
# changes). On the last frame a NW glider sits at (2181..2183, 3852..3854) in the opening
# glider's phase; the view centers one cell in from its box, as the opening centers one
# metapixel in. It flies free from its gun 10.75 cells SE of there.
TARGET = (2182.0, 3853.0)
LEAN_CELLS = 10.75


def smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


class Schedule:
    """The zoom (in doublings) and time rate (generations per frame) of the 60 s video."""

    def __init__(self) -> None:
        self.zoom_start_frame = math.ceil((3 * PERIOD + FLIP_MID) / OPEN_RATE)
        self.t0 = self.zoom_start_frame / FPS
        self.span = ZOOM_END_T - self.t0
        self.v = ZOOM_DOUBLINGS / (self.span - RAMP_IN / 2 - RAMP_OUT / 2)
        # log2(rate) against doublings: steep for the first doubling, then gentle; the
        # kinks are smoothed with a Gaussian 0.2 doublings wide.
        self.grid = np.linspace(-2, ZOOM_DOUBLINGS + 2, 2801)
        raw = np.interp(
            self.grid,
            [0, 1, ZOOM_DOUBLINGS],
            [math.log2(OPEN_RATE), math.log2(RATE_AFTER_1), math.log2(END_RATE)],
        )
        sigma = 0.2 / (self.grid[1] - self.grid[0])
        k = np.exp(-0.5 * (np.arange(-4 * int(sigma), 4 * int(sigma) + 1) / sigma) ** 2)
        k /= k.sum()
        self.log_rate = np.convolve(np.pad(raw, len(k) // 2, mode="edge"), k, mode="valid")

    def doublings(self, t: float) -> float:
        u = t - self.t0
        if u <= 0:
            return 0.0
        if u >= self.span:
            return float(ZOOM_DOUBLINGS)
        if u < RAMP_IN:
            return self.v * u * u / (2 * RAMP_IN)
        if u < self.span - RAMP_OUT:
            return self.v * RAMP_IN / 2 + self.v * (u - RAMP_IN)
        w = self.span - u
        return ZOOM_DOUBLINGS - self.v * w * w / (2 * RAMP_OUT)

    def rate(self, f: int) -> float:
        if f < self.zoom_start_frame:
            return OPEN_RATE
        return float(2 ** np.interp(self.doublings(f / FPS), self.grid, self.log_rate))

    def plan(self) -> tuple[list[float], list[float]]:
        """The generation each frame shows, and its rate (generations per frame)."""
        gens, rates = [0.0], [self.rate(0)]
        for f in range(1, N_FRAMES):
            rates.append(self.rate(f))
            gens.append(gens[-1] + rates[-1])
        return gens, rates


def inner_step(gen: int) -> int:
    """The inner generation the displays show at an outer generation."""
    return max(0, (gen - FLIP_MID) // PERIOD)


def dive_cell(end_step: int) -> tuple[int, int]:
    """The metapixel lit at the last inner generation that has been lit longest by then, so
    the cell the camera dives into stays lit from early in the zoom to the end."""
    states = [inner_cells()]
    for _ in range(end_step):
        states.append(life_step(states[-1]))
    best, best_run = (0, 0), -1
    for j, i in zip(*np.nonzero(states[end_step])):
        run = 0
        while end_step - run >= 0 and states[end_step - run][j, i]:
            run += 1
        if run > best_run:
            best, best_run = (int(i), int(j)), run
    return best


# -- frames ----------------------------------------------------------------------------------
def resample_axis(
    a: NDArray[np.floating[Any]], start: float, scale: float, n: int, axis: int
) -> NDArray[np.float64]:
    """Exact box filter: output k averages source [start + k·scale, start + (k+1)·scale)."""
    a = np.moveaxis(a, axis, -1)
    m = a.shape[-1]
    c = np.zeros(a.shape[:-1] + (m + 1,), dtype=np.float64)
    np.cumsum(a, axis=-1, out=c[..., 1:])
    edges = np.clip(start + scale * np.arange(n + 1), 0, m)
    i = np.floor(edges).astype(np.int64)
    cx = c[..., i] + (edges - i) * a[..., np.minimum(i, m - 1)]
    return np.moveaxis((cx[..., 1:] - cx[..., :-1]) / scale, -1, axis)


def grid_lines(lo: float, s: float, n: int) -> NDArray[np.float32]:
    """Coverage (0..1) of n output pixels by cell-boundary lines on one axis whose first
    pixel starts at cell coordinate ``lo``, ``s`` cells per pixel."""
    p = 1 / s
    width = max(1.0, p / 70)
    cov = np.zeros(n, dtype=np.float32)
    for c in range(math.ceil(lo), math.floor(lo + n * s) + 1):
        a = (c - lo) * p - width / 2
        b = a + width
        for k in range(max(0, math.floor(a)), min(n - 1, math.floor(b)) + 1):
            cov[k] += max(0.0, min(b, k + 1) - max(a, k))
    return np.minimum(cov, 1.0)


def grid_alpha(s: float) -> float:
    """The cell grid fades in between 24 and 96 pixels per cell."""
    return GRID_ALPHA * smoothstep((1 / s - 24) / (96 - 24))


def tone(d: NDArray[np.float64], s: float) -> NDArray[np.float64]:
    """Density (0..1) → brightness (0..1): saturating far out, nearly linear up close."""
    lo, hi = math.log(0.006), math.log(0.6)
    w = min(1.0, max(0.0, math.log(max(s, 1e-9)) / math.log(8.0)))
    d0 = math.exp(hi + (lo - hi) * w)
    return (1 - np.exp(-d / d0)) / (1 - math.exp(-1 / d0))


class Renderer:
    def __init__(self, u: HashLife) -> None:
        self.u = u

    def frame(self, gens: list[int], cx: float, cy: float, s: float) -> NDArray[np.float64]:
        """Brightness of the square viewport centered on cell coordinate (cx, cy) at ``s``
        cells per pixel, averaged over ``gens``."""
        m = min(MAX_MAG, math.ceil(math.log2(1 / s) - 1e-9))
        bs = 2.0 ** (-m)  # cells per buffer pixel
        half = SQ / 2 * s
        x_lo, y_lo = cx - half, (cy - 1) - half  # views use tree coordinates (cell y − 1)
        p0x, p0y = math.floor(x_lo / bs), math.floor(y_lo / bs)
        size = (
            math.ceil((cx + half) / bs) - p0x + 1,
            math.ceil(((cy - 1) + half) / bs) - p0y + 1,
        )
        view = LifeView(p0x, p0y, m)
        acc = np.zeros((size[1], size[0]), dtype=np.float32)
        for g in gens:
            if g > self.u.generation:
                self.u.step(g - self.u.generation)
            acc += self.u.render(view, size, "density")
        acc /= len(gens) * 255.0
        out = resample_axis(acc, x_lo / bs - p0x, s / bs, SQ, axis=1)
        out = resample_axis(out, y_lo / bs - p0y, s / bs, SQ, axis=0)
        b = tone(out, s)
        alpha = grid_alpha(s)
        if alpha > 0:
            gx, gy = grid_lines(cx - half, s, SQ), grid_lines(cy - half, s, SQ)
            b = b + (1 - b) * alpha * np.maximum(gx[None, :], gy[:, None])
        return b


class Hud:
    """The stats block above the viewport, drawn with Qt (the playground extra)."""

    def __init__(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtGui import QFont, QFontDatabase, QGuiApplication, QImage

        self.app: QGuiApplication = QGuiApplication.instance() or QGuiApplication([])  # type: ignore[assignment]
        family = None
        for path in ("/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc"):
            if Path(path).exists():
                fid = QFontDatabase.addApplicationFont(path)
                if fid >= 0:
                    family = QFontDatabase.applicationFontFamilies(fid)[0]
                    break
        self.font: QFont = (
            QFont(family)
            if family
            else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        self.font.setPixelSize(36)
        self.font.setWeight(QFont.Weight.Medium)
        self.image: QImage = QImage(W, H, QImage.Format.Format_RGB888)
        ptr = self.image.bits()
        assert ptr is not None
        ptr.setsize(self.image.sizeInBytes())
        self.pixels = np.frombuffer(ptr, dtype=np.uint8).reshape(H, self.image.bytesPerLine())  # type: ignore[call-overload]

    def draw(self, canvas: NDArray[np.uint8], lines: list[tuple[str, str]]) -> NDArray[np.uint8]:
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QColor, QPainter

        self.pixels[:, : W * 3] = canvas.reshape(H, W * 3)
        p = QPainter(self.image)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self.font)
        lh, bw = 54, 660
        x0 = (W - bw) / 2
        y = SQ_Y - 30 - lh * len(lines)
        for label, value in lines:
            box = QRectF(x0, y, bw, lh)
            p.setPen(QColor(128, 138, 152))
            p.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QColor(236, 242, 248))
            p.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
            y += lh
        p.end()
        out: NDArray[np.uint8] = self.pixels[:, : W * 3].reshape(H, W, 3).copy()
        return out


def fmt_rate(v: float) -> str:
    if v >= 100:
        q = 10 ** (math.floor(math.log10(v)) - 2)  # three significant figures
        return f"{round(v / q) * q:,.0f} gen/s"
    return f"{v:.0f} gen/s" if v >= 10 else f"{v:.1f} gen/s"


def ffmpeg_exe() -> str:
    """The ffmpeg the video extra installs (imageio-ffmpeg), else one on the PATH."""
    try:
        return str(importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe())
    except ImportError:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
    raise SystemExit('render.py needs ffmpeg: pip install "heaton-life[video]"')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", type=Path, default=OUT / "board.mc")
    ap.add_argument("--out", type=Path, default=None, help="default out/life_in_life_<N>s.mp4")
    ap.add_argument("--speed", type=float, default=1.0, help="2 plays it twice as fast (30 s)")
    ap.add_argument("--frames", type=int, default=None, help="render only this many frames")
    ap.add_argument("--start", type=int, default=0, help="first frame to render")
    ap.add_argument("--stills", type=Path, default=None, help="also save PNG stills here")
    ap.add_argument("--stills-every", type=int, default=30)
    ap.add_argument("--target", default=None, help="x,y: center of the final view (cells)")
    ap.add_argument("--lean", type=float, default=LEAN_CELLS, help="see LEAN_CELLS")
    args = ap.parse_args()

    sched = Schedule()
    gens60, rates60 = sched.plan()
    # --speed plays the 60 s run faster: output frame f shows 60 s frame idx[f], first to
    # last, so the generations, camera and landing stay the same and every rate scales.
    n_out = round(N_FRAMES / args.speed)
    idx = [round(f * (N_FRAMES - 1) / (n_out - 1)) for f in range(n_out)]
    gens = [gens60[i] for i in idx]
    frames = n_out if args.frames is None else min(args.frames, n_out)
    out = args.out or OUT / f"life_in_life_{n_out // FPS}s.mp4"
    end = int(gens[-1])
    print(
        f"{n_out} frames ({n_out / FPS:g} s): the zoom starts at {sched.t0 / args.speed:.2f} s; "
        f"the last frame shows generation {end:,}, inner generation {inner_step(end)}"
    )

    tx, ty = (float(v) for v in args.target.split(",")) if args.target else TARGET
    di, dj = dive_cell(inner_step(end))
    if not (PITCH * di <= tx < PITCH * (di + 1) and PITCH * dj <= ty < PITCH * (dj + 1)):
        print(f"note: the landing spot is outside the dive metapixel ({di}, {dj})")
    o0x, o0y = (tx - BOARD / 2) / S0, (ty - BOARD / 2) / S0  # its screen offset at the start
    gx, gy = GLIDER_AT
    assert (PITCH * (gx + 1), PITCH * (gy + 1)) == (BOARD / 2, BOARD / 2)  # framing rhyme

    u = HashLife.from_macrocell(args.board.read_text(), max_memory_mb=8000)
    renderer, hud = Renderer(u), Hud()
    if args.stills:
        args.stills.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
         "-crf", "14", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    assert ff.stdin is not None
    if args.start:
        u.step(int(gens[args.start - 1]))
    t_start = time.perf_counter()
    for f in range(args.start, frames):
        t60 = idx[f] / FPS
        L = sched.doublings(t60)
        s = S0 / 2**L
        keep = 1 - smoothstep(L / PAN_DOUBLINGS)
        # Lean toward the final glider: its gun until it flies free, then the glider
        # itself (a NW glider covers a cell diagonally every 4 generations).
        lean = LEAN_MAX * smoothstep((t60 - LEAN_T[0]) / (LEAN_T[1] - LEAN_T[0]))
        d = lean * min((gens[-1] - gens[f]) / 4, args.lean)
        cx, cy = tx + d - o0x * keep * s, ty + d - o0y * keep * s
        g_now = int(gens[f])
        g_prev = int(gens[f - 1]) if f else 0
        n = min(MAX_SUBSTEPS, g_now - g_prev)
        sub = [g_prev + (g_now - g_prev) * (k + 1) // n for k in range(n)] if n > 0 else [g_now]
        sq = BG + renderer.frame(sub, cx, cy, s)[..., None] * (FG - BG)
        canvas = np.empty((H, W, 3), dtype=np.uint8)
        canvas[:] = BG.astype(np.uint8)
        canvas[SQ_Y : SQ_Y + SQ] = np.clip(sq + 0.5, 0, 255).astype(np.uint8)
        img = hud.draw(
            canvas,
            [
                ("INNER STEP", f"{inner_step(g_now)}"),
                ("GENERATION", f"{g_now:,}"),
                ("SPEED", fmt_rate(rates60[idx[f]] * FPS * args.speed)),
            ],
        )
        ff.stdin.write(img.tobytes())
        if args.stills and f % args.stills_every == 0:
            hud.image.save(str(args.stills / f"frame{f:04d}.png"))
        if f % 150 == 0:
            print(
                f"frame {f:>4}: generation {g_now:>9,}, inner {inner_step(g_now)}, "
                f"zoom {L:5.2f} doublings [{time.perf_counter() - t_start:5.0f} s]",
                flush=True,
            )
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit(f"ffmpeg failed ({ff.returncode})")
    print(f"{frames - args.start} frames in {time.perf_counter() - t_start:.0f} s → {out}")


if __name__ == "__main__":
    main()
