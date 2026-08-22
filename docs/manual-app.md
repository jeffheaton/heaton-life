# Heaton Life User Guide — Windows & macOS

Heaton Life is a desktop app for Windows and macOS for exploring **emergence** — simple rules that grow complex, organic-looking behavior. It brings the classic systems of artificial life together in one place: cellular automata (MergeLife, Conway-style Life, Elementary, Cyclic, Wireworld), three flavors of Lenia, Gray-Scott reaction-diffusion, flocking boids, and deep-zoom fractals (Mandelbrot, Julia, Burning Ship, Newton). Create worlds, paint and edit them with pattern tools, breed brand-new MergeLife rules with the built-in evolver, and keep everything in your worlds library.

Everything runs and stays on your computer — nothing is uploaded anywhere.

> **Keyboard shortcuts** are written as `Ctrl+O / ⌘O`: use the **Ctrl** key on Windows and the **Command (⌘)** key on a Mac.

There is a separate guide for [iPhone, iPad, and Android](manual-mobile.md).

---

## Families, Rules, and Worlds

Three words come up everywhere in Heaton Life:

- A **family** is a form of physics — MergeLife, Life-like, Wireworld, Classic Lenia, and so on. Each family is one tile in the New-world picker.
- A **rule** is the set of constants inside a family: a Life-like rulestring such as `B3/S23`, a MergeLife rule code such as `1c48-9004-8831-41be-2804-8f50-9901-db18`, a Cyclic state count. The same family with a different rule is a parallel universe with different physics — a pattern moved from one rule to another usually dies within a step. That is not a bug; hunting for the patterns that survive the move is half the fun.
- A **world** is one live instance of a rule: its parameters, its starting seed, its current state, and its generation (age). A world stays the same world through running, pausing, editing, saving, and reloading.

Families of rules create worlds. A world's family is fixed for its lifetime; the rule can change inside it.

## Getting Started

When you open Heaton Life, you'll see your **worlds library** — a card for every world you've created, each with a live thumbnail, its name, and its family, rule, and generation. The first time you launch the app this screen says **No worlds yet** and invites you to create your first world.

<!-- SCREENSHOT: the worlds library with a few cards -->

Along the bottom:

- **+ New world** — Opens the picker (see [Creating a World](#creating-a-world)).
- **Import** — Opens a file dialog to import a pattern file (see [Importing Patterns](#importing-patterns)).

A **MENU** button in the top-right corner opens **Evolve MergeLife**, this **Heaton Life Manual**, and the **About** screen.

On each card, **★** marks a favorite and **×** deletes the world after a confirmation. There is no trash and no undo for a delete.

Along the top of the window (Windows) or the top of the screen (Mac) is a standard menu bar:

- **File > Import RLE…** (`Ctrl+O / ⌘O`) — Import a pattern file.
- **Help > Heaton Life Manual** — Opens this guide.
- **About Heaton Life** (the app menu on a Mac; the Help menu on Windows) — The app version, when it was built, and the simulation library build it is running (`HeatonLife.Core <version>+<commit>`) — include these if you report a problem.

## Creating a World

**+ New world** opens the picker: four categories, each card fronted by a live preview.

- **Cellular Automata** — MergeLife, Life-like, Elementary, Cyclic, Wireworld.
- **Continuous Fields** — Classic, Asymptotic, and Flow (the three Lenia flavors) and Gray-Scott.
- **Swarms** — Reynolds (boids).
- **Fractals** — Mandelbrot, Julia, Burning Ship, Newton (see [Fractals](#fractals)).

Pick a category, then a family, and the world opens. MergeLife goes one step further: its card opens the **rule gallery** — a catalog of featured rules, each running live — and you pick the rule you want to start from. Every other family starts from its default rule with a fresh random seed.

| Family | What you get |
|---|---|
| **MergeLife** | Colorful cellular automata where every rule is an eight-group hex code. Thousands of rules exist; the gallery's featured ones are a starting point, and the [evolver](#evolving-mergelife-rules) breeds new ones. |
| **Life-like** | Conway's Game of Life and its relatives — rulestrings like `B3/S23` (born with 3 neighbors, survive with 2 or 3). Gliders, guns, and the whole LifeWiki pattern universe. |
| **Elementary** | Wolfram's one-dimensional rules 0–255 (Rule 30, Rule 90's Sierpinski triangle, Rule 110), drawn one row per generation. |
| **Cyclic** | N states that each consume the one before them, growing spirals and demons. |
| **Wireworld** | Electrons on wires: Empty, Head, Tail, and Conductor cells. Build circuits — the zoo ships a clock and a diode. |
| **Classic / Asymptotic / Flow** | Lenia — continuous-valued Life with smooth neighborhoods, where gliding solitons and other lifeforms emerge. |
| **Gray-Scott** | Reaction-diffusion chemistry: spots, stripes, and dividing blobs from two reacting substances. |
| **Reynolds** | Boids: flocking agents with no grid at all. |

Worlds are **born saved**: the new world joins your library immediately, is saved automatically whenever you go back to the library, and is saved again when the app quits. There is no Save button. New worlds are cut to the shape of your window, so they fill the screen.

## The World Screen

A world fills the center of the screen. The **world settings** panel sits to the right (or below the canvas in a tall window), the **transport bar** runs along the bottom, **< Worlds** in the top-left returns to the library, and the current **generation** shows in the top-right.

<!-- SCREENSHOT: a Life-like world with the settings panel and edit bar visible -->

### The transport bar

- **Play / Pause** — Runs or pauses the world.
- **Step** — Advances exactly one generation and pauses.
- **Speed** — Generations per second (the readout shows, for example, `30/s`). Slow families simply run slower than the slider asks rather than freezing. This setting is remembered across worlds.
- **Snapshot** — Saves a PNG of what's on screen (see [Snapshots](#snapshots)).
- **Tools** — Shows or hides the editing tools (the edit bar and the view controls) for full-bleed viewing. Also remembered.

### World settings

What you see here depends on the family:

- **Rule** — For MergeLife and Life-like, a text field holding the rule. Type a new rulestring or rule code and press Enter: a valid rule is applied (and tidied into its canonical spelling); an invalid one is rejected and the previous rule restored.
- **Preset** — Click to cycle through the family's presets (Life-like: Conway soup, HighLife, Seeds, Day & Night, Maze, Diamoeba; MergeLife: Red World, Frost, Diamond Mine, Mood Ring, a random rule; and so on). A preset resets the world to that starting recipe.
- **Colormap** — Click to cycle palettes, for families that use one.
- **Edges** — `wrap around` or `walls`, for families that offer the choice (Wireworld starts with walls).
- **Parameter sliders** — The family's own knobs: soup density, Lenia's μ and σ, Gray-Scott's feed and kill rates, the boids' steering weights, and so on.
- **Reseed** — A fresh random starting state with the same rule and parameters. **Defaults** — The family's default rule and parameters (the world keeps its size).
- **Name** — Rename the world.
- **Export PNG ×4** (MergeLife) — Saves the world's lattice as a PNG that can be imported again as a world, at four times its size.

### The world menu

The **☰** button on the world screen opens a menu of whole-world actions:

- **Rule lab — decode this rule** (MergeLife only) — See [The Rule Lab](#the-rule-lab).
- **Show grid lines** — Draws cell borders once you have zoomed in far enough to see individual cells.
- **Reset to start position** — Returns the world to its start state. **Set start position = current state** — Makes the current state the new start, so Reset comes back here.
- **Clear all cells** — Blanks the grid. **Fill all cells with current ink** — Floods it with the current paint ink. Both are single undo steps.

## Editing Worlds

The **edit bar** in the top-left corner of the canvas holds the direct-manipulation tools: **Paint**, **Select**, and **Pan**, plus **Undo**, **Paste**, and **Zoo**. (If it's hidden, click **Tools** on the transport bar.) Editing never resets the generation — a world you've drawn into is still the same world.

### Paint

Drag with the left button to paint with the current ink and brush size; drag with the **right button** to erase to the family's blank. The ink picker depends on the family:

- **Life-like** — Two swatches, on and off. **Wireworld** — Empty, Head, Tail, and Conductor. **Cyclic** — One swatch per state.
- **MergeLife** — **Hue** and **Bright** sliders (the ink is a color).
- **Classic / Asymptotic / Flow** — A **Value** slider; each dab is a soft bump of that intensity.
- **Gray-Scott** — **Seed** or **Substrate**.
- **Reynolds** — No ink: a left click scares the flock away from the pointer, a right click lures it in. **Elementary** has no painting.

Two controls are shared by every family: **Pick** (the next click picks up the ink under the pointer — or hold **Alt** and click) and the **Size** slider. The swatches are rendered through the same palette as the canvas, so what you see is what you paint.

### Select, copy, and cut

Choose **Select** and drag out a rectangle of cells. A row of actions appears: **Copy**, **Cut**, **Fill** (for families with a single "on" state: Life-like and Wireworld), **Clear**, **Zoo +** (save the selection to the zoo), and **Deselect**. Copy puts the pattern on Heaton Life's clipboard — and, for Life-like, Wireworld, and Cyclic, also puts its RLE text on the system clipboard, ready to paste into a text editor or share.

### Paste

**Paste** arms a translucent ghost of the clipboard pattern that follows the pointer, with **Rotate**, **Flip H**, **Flip V**, and **Cancel**. Click to stamp it — as many times as you like — and right-click (or Cancel) to put it away.

Paste takes Heaton Life's own clipboard first; if that is empty, it reads the system clipboard as RLE text. So a pattern copied straight from LifeWiki pastes right in. Two rules apply:

- **Patterns never cross families.** A Life glider cannot be pasted into Wireworld; the status line explains the rejection and names the pattern's home family.
- **Patterns may cross rules within a family** — and the ghost turns amber with a ⚠ note when they do. The paste is always allowed; the note is just a reminder that the pattern was captured under different physics and may not survive.

### The zoo

**Zoo** slides open the family's pattern library: built-in patterns (for Life, spaceships, oscillators, still lifes, methuselahs, and the Gosper glider gun; HighLife's replicator; Wireworld's clock and diode) plus every selection you've saved, marked "yours". Each card shows a thumbnail, the name, and the rule and size the pattern was captured under. Click a card to arm it for pasting. **×** deletes your own entries (built-ins stay). **Save selection to zoo** at the bottom captures the current selection. The zoo only ever shows patterns that belong to the current family.

### Undo

**Undo** steps back through the last 24 edits — brush strokes, stamps, fills, clears, and cuts — without touching the generation counter.

### Zooming and panning the grid

- **Scroll** (mouse wheel or trackpad) pans the grid in any direction, whatever tool is active.
- **`Ctrl`+scroll / `⌘`+scroll** zooms in and out around the pointer, from 1× to 32×.
- The **Pan** tool drags the grid; the **view controls** in the canvas's bottom-right corner hold the grid-lines toggle, **Fit** (back to the whole grid), and a zoom slider.

You can pan a little past the grid's edge, so cells sitting under the floating toolbar can always be pulled out from beneath it.

## The Rule Lab

For a MergeLife world, **☰ > Rule lab — decode this rule** opens a table of what the rule code actually says: each of the eight groups decoded into its α, range, key color, β, and γ values beside the raw octets. It is the same decoding the research paper describes, useful for understanding why a rule behaves as it does — or for reading a rule the evolver bred.

## Importing Patterns

Heaton Life reads the standard **RLE** pattern format used across the Life community (for example, patterns copied or downloaded from LifeWiki), plus PNG lattice exports of MergeLife worlds:

1. **File > Import RLE…** (`Ctrl+O / ⌘O`) — Choose an `.rle` or `.txt` pattern file, or a MergeLife `.png`. A pattern becomes a new Life-like world using the rule from its header, centered on a comfortable grid; a PNG becomes a MergeLife world with the image's exact lattice.
2. **The Import button** on the worlds library — The same file dialog.
3. **Paste inside a world** — Copy a pattern's RLE text anywhere, then use the edit bar's **Paste** tool in a matching world to stamp it wherever you like.

## Snapshots

**Snapshot** on the transport bar (or on a fractal's status bar) saves a PNG of the current view, named `heatonlife-<family>-<date>-<time>.png`; the status line confirms with `saved …`. Snapshots go to the app's **Snapshots** folder:

- **Windows:** `%USERPROFILE%\AppData\LocalLow\Jeff Heaton\Heaton Life\Snapshots`
- **macOS:** `~/Library/Application Support/Jeff Heaton/Heaton Life/Snapshots` — for the App Store version, inside the app's container: `~/Library/Containers/com.heatonresearch.heatonlife/Data/Library/Application Support/Jeff Heaton/Heaton Life/Snapshots` (in Finder, hold **Option** and choose **Go > Library**).

Your worlds library and pattern zoo live beside that folder. Everything stays on your computer.

## Fractals

Fractals are the picker's fourth category. Each one you open is an **expedition** — a viewpoint into the set that is saved in your library like any world, with its own thumbnail. Four sets are available, each with presets: **Mandelbrot** (Home, Seahorse valley), **Julia** (Classic, Douady rabbit, Dendrite), **Burning Ship** (Full ship, Antenna armada), and **Newton** (z³ − 1, z⁵ − 1).

<!-- SCREENSHOT: a deep Mandelbrot zoom with the status bar -->

Navigation is map-style:

- **Click** to recenter on a point — a crosshair marks the new center until the frame arrives.
- **Drag** to pan.
- **Scroll** to zoom in and out around the pointer.
- **Zoom In** and **Zoom Out** zoom at the center; **Home** returns to the set's home view.
- **Auto** starts a hands-free dive: the view drifts toward the nearest interesting boundary and zooms continuously, sharpening to full resolution the moment it stops. The button becomes **Stop**; any click, drag, or scroll also stops it, and the dive ends by itself at the maximum zoom.

The status line reads out the current zoom and center, for example `zoom 1.0e5x   center -0.745, 0.112`. Zoom goes to 10¹² — a trillion times — with the center tracked precisely enough that the image never smears at depth. Deep frames take longer: a **rendering…** chip shows the percentage done, with a **Cancel** button that abandons the frame and returns the iteration budget to its automatic setting.

In the settings panel: **Preset**, **Colormap**, and **Max iter**, the iteration budget. Heaton Life raises the budget automatically as you go deeper; once you move the slider by hand it stays where you put it, which is the usual reason a frame takes forever — Cancel resets it. Julia worlds add the constant **c (re)** and **c (im)**; Newton adds the polynomial **Degree** and uses its iteration slider directly.

## Evolving MergeLife Rules

**MENU > Evolve MergeLife** on the library screen opens the evolver: a genetic algorithm that breeds MergeLife rules and scores each one by how interesting its world stays over time, the way the original MergeLife research trainer did. Nothing here creates a world until you ask.

<!-- SCREENSHOT: the evolve screen mid-run -->

- **Start / Stop** — Starts a search with a fresh random population (and a fresh random seed each time). Stop ends it. The search keeps running while you switch to other windows, and only leaving the evolve screen with **< Catalog** stops it.
- **Population** (16–128, default 100), **Steps per run** (100–1000), and **Eval cycles** (1–5) — The search's size and patience; the defaults are the reference trainer's.
- **Keep above** — The score a rule must reach to be kept as a find. Scores run up to 5.0; the gallery's featured rules score between about 1.8 and 4.8, and the default of 3.5 is the historical "worth saving" bar. Raising it later never throws away what's already logged.

The big preview runs the current best rule live, and the leaderboard lists the population's top scores. A search runs in **restarts**: a population eventually stalls, so after 250 evaluations without a new best (the `run 7 · stall 120/250` row) the run is discarded and a fresh one begins, automatically, until you stop. On machines with many cores several runs breed at once (`runs 12-17`). Each run's champion is what gets kept.

- **Create world from best** — Opens the current best rule as a new, saved world in your library. **Copy rule** — Puts its rule code on the clipboard, ready to paste into any MergeLife world's **Rule** field.
- **Finds** — The catalog of every kept rule, best score first, each card running a live preview. The title announces new arrivals (`+3 new`); **Refresh** brings them in without shuffling the cards you're reading, **Clear** empties the log, and **×** removes one find. Click a card to open the rule as a **preview world** — the search keeps breeding underneath — and decide with the bar at the top of the canvas: **Create as World** keeps it in your library; **Delete World** (or **< Evolve**) discards it. Finds persist between launches, so a long search only ever improves the catalog.

## Tips & Troubleshooting

- **"Paste rejected"** — Patterns belong to a family. A Life pattern pastes into Life-like worlds only; check the status line for the pattern's home family.
- **A pasted pattern dies immediately** — It was captured under a different rule (the amber ⚠ ghost warned you). Same family, different physics. Try a world with the rule named on the zoo card.
- **A fractal frame never finishes** — Click **Cancel** on the rendering chip; it also resets a hand-cranked **Max iter** to automatic.
- **Worlds open with black bars** — Older worlds keep the size they were born with. New worlds are cut to your window; use **Fit** to frame any world.
- **The evolver is slow** — Each evaluation runs a world for up to **Steps per run** generations, **Eval cycles** times. Lower either for a faster (rougher) search.
- **Where is everything stored?** — In the app's data folder beside [Snapshots](#snapshots): `catalog` (worlds and expeditions), `zoo` (your patterns), and the evolver's finds. Nothing is sent over the internet.
- **Getting help** — **Help > Heaton Life Manual** opens this guide. **About Heaton Life** shows the version, build time, and library build to include in a report.

---

*Heaton Life is provided under the Apache 2.0 License. MergeLife is described in Jeff Heaton's 2017 paper, "Evolving Continuous Cellular Automata for Aesthetic Objectives" (arXiv:1809.00656).*
