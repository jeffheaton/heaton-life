# Life in Life

A 60-second vertical video (1080×1920, a YouTube Short) of Conway's Game of Life running
inside itself. A glider walks across a 6×6 board whose every cell is an OTCA metapixel, a
2048×2048 Life pattern that behaves like one Life cell. Then the camera dives into one
of the glider's live metapixels, through its spaceship streams, signal circuits and glider
guns, and lands on a real glider framed exactly like the glider it started from, so the
video loops. Everything runs on heaton-life's HashLife.

## Running it

Needs the `playground` (Qt, for the overlay text) and `video` (ffmpeg) extras, about 2 GB
of memory, and a network connection the first time. From `python/` with the repository's
venv:

```bash
cd examples/life_in_life
../../.venv/bin/python tiles.py        # download the metapixel source, build out/tiles.npz
../../.venv/bin/python board.py        # lay out the 6×6 board → out/board.mc
../../.venv/bin/python verify.py       # check the metapixels compute Life (prints PASS)
../../.venv/bin/python render.py       # out/life_in_life_60s.mp4, about 7 minutes
../../.venv/bin/python render.py --speed 2   # the 30 s cut
```

Previews: `render.py --frames 300 --stills out/stills` renders the first 10 seconds and
saves a still every second.

## The files

| File | What it does |
| --- | --- |
| `tiles.py` | Builds the OFF and ON metapixel tiles programmed for B3/S23 |
| `board.py` | Lays out the board with the inner glider and writes it as Macrocell |
| `verify.py` | Runs the board and checks each metapixel's display against plain Life |
| `pick_glider.py` | Finds the glider the zoom can land on (`render.py`'s `TARGET`) |
| `render.py` | The schedule, camera, rendering, overlay and encoding |

`tiles.py` takes the tiles from Dave Greene's metafier script, which assembles them from
about a hundred RLE fragments. It downloads the script once from Golly's source repository
(pinned by commit and SHA-256) and reads it as data: Python's `ast` parses it and only an
allow-list of pattern operations is evaluated, so none of the downloaded code runs.

## How the video works

- **The board.** Each metapixel repeats every 35,328 generations; one inner generation
  per cycle after a first setup cycle, with each display filling or emptying about 6,900
  generations into the cycle. The inner glider starts in columns/rows 2..4, so the board
  is exact Life through inner generation 8; the video ends at generation 270,268, inner
  generation 7.
- **Time.** The opening runs 2,208 generations per frame (16 frames per inner
  generation). From inner generation 3 the zoom covers 11 doublings (2^11 is one
  metapixel) and time slows with it, steeply for the first doubling, then down to 2
  generations per second at the end. `--speed` plays the same run faster.
- **The dive.** The camera heads for metapixel (1, 1), which lights up early in the zoom
  and stays lit, and in the last 20 seconds leans toward the glider it will land on.
- **Rendering.** HashLife density frames at the power-of-two magnification just finer
  than the output, averaged over sub-steps for motion blur, box-filtered to the exact
  zoom, then tone-mapped by scale: far out a lit display (about 1.3% live cells) reads as
  a lit cell; up close the cells are cells. A faint grid fades in at the end to echo the
  metapixel outlines at the start.

## Credits and licensing

The OTCA metapixel is by Brice Due (2006); the metafier script that assembles it is by
Dave Greene. The metapixel carries no stated license, so like the giant test patterns
(`tools/fetch_patterns.py`) nothing derived from it is committed: `out/` (the downloaded
script, the tiles, the board, and the videos) is git-ignored. If you publish a video made
with this, please credit Brice Due for the metapixel.
