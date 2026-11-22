# Changelog

Both packages, `heaton-life` on PyPI and `HeatonLife.Core` on NuGet, share one version
number, and from 1.1.0 on each release ships both from one commit. Every entry applies to
both unless it names a port. The spec version (the `spec_version` field of the conformance
vectors) moves on its own; each release lists the one it implements.

## 1.2.0 (unreleased)

Implements spec version 0.16.0 (1.1.0 implemented 0.13.0). Every conformance vector that
existed at 1.1.0 is byte-identical; the new behavior comes with new vector cases. The
public APIs of both packages are backward compatible: nothing was removed or renamed.
Behaviors that changed are listed under Changed below; the three most likely to matter are
canonical RLE's form (its row ends and its rule's spelling), RLE decoding's new size limit,
and an RLE header naming any Life-like rule making the file two-state.

### Added

- **HashLife: Life on an unbounded plane** (`heaton_life.ca.hashlife.HashLife`, .NET
  `HashLife`; [spec/hashlife.md](spec/hashlife.md)). Any Life-like rule, B0 included (below),
  runs on a hash-consed quadtree whose nodes memoize their own future, so regular patterns of
  trillions of cells fit in memory and one step can jump any number of generations below
  2⁵¹⁰. Generations, populations, and coordinates are big integers. Editing (cells,
  rectangles pasted by copy, or, or xor, clearing, PCG32 random fill) reaches
  |x|, |y| ≤ 10⁹; queries and rendering reach everywhere. Snapshots, cancellation at
  sub-step boundaries, and a memory budget (`max_memory_mb`, default 500 MiB, minimum 10)
  that changes speed, never results.
- **Pattern files for the unbounded universe:** Macrocell (`.mc`, `.mc.gz`) reading and
  canonical writing ([spec/macrocell.md](spec/macrocell.md)), and RLE whose `#CXRLE
  Pos=x,y Gen=n` line places a pattern anywhere in the editing box.
- **Views and frames** (`LifeView`): exact integer pan, zoom at a pixel, fit, and center
  readouts, and frames from 32 pixels per cell to any distance out, in `any` or `density`
  mode, at a cost that does not grow with the population. .NET: `Step` and `WriteFrame`
  allocate nothing once warm.
- **The giants:** the Caterpillar and Annelid (2026) load, run, and return to their own
  shape after one period. .NET runs a period of either in about 5 seconds; the Python
  reference needs a 2–8 GB budget and about a minute. `python/tools/fetch_patterns.py`
  downloads pinned copies into a git-ignored cache; neither file states a license, so
  neither ships.
- Python playground: a HashLife view: open and save `.rle`, `.mc`, and `.mc.gz`, paint,
  zoom at the cursor, step 2^k generations at a time, and set the memory budget.
- Python playground: Life-like starts from a pattern (a built-in, or a `.rle`, `.mc`, or
  `.mc.gz` file) and saves its cells as RLE. A file too large for a grid is offered to
  HashLife instead of being loaded, and one that merely suits HashLife better is the
  user's choice.
- Self-check: a `hashlife` check (22 checks now), the Gosper gun to 2²⁰⁰ generations, for
  the 64-bit and big-integer arithmetic past 2⁶⁴.
- Python: `rle_runs` and `RleInfo` stream an RLE file's runs, position, and generation
  without building a grid.
- **Measuring a pattern before decoding it** (`rle_measure`, `Patterns.RleMeasure`;
  [spec/patterns.md](spec/patterns.md) "Extent"): the size a decode would give, the live
  cells' box, and their count, as exact integers and without a grid. A few bytes of RLE
  can describe more cells than memory holds, so measure a file that came from outside.
- **Trimmed decoding** (`rle_decode(..., trim=True)`, `Patterns.RleDecode(text, limit,
  trim: true)`): only the live cells' bounding box, the header's size and dead margins
  dropped. It is the decode for loading a pattern file into a world.
- **HashLife view helpers** (`resized`, `frame_map`; `LifeView.Resized`,
  `LifeView.FrameMap`): the view that keeps its center when the frame is resized, and
  where one view's frame lies in another, in exact integers. A viewer draws the frame it
  has through the map until the new one is rendered, so a pan or zoom answers at once.
- **The evolver's restart search** (`RestartSeeds`, `Evolver.converged` /
  `Evolver.Converged`; [spec/evolve.md](spec/evolve.md) "Restart search"): a search
  breeds run after run, each from a fresh population, and run n's seed comes from PCG32
  stream 2, so any run replays on either implementation from the search's seed and its
  number. [spec/rng.md](spec/rng.md) now lists the streams in use.
- **Pattern files in every common format, recognized by content**
  ([spec/formats.md](spec/formats.md)): plaintext (`.cells`), Life 1.05, Life 1.06, and
  PNG and BMP images (a white pixel is dead, any other alive) join RLE and Macrocell,
  and any of them may be gzip-compressed. `detect_format` / `PatternFiles.Detect` names a
  file's format from its bytes; `read_pattern` / `PatternFiles.Read` gives its cells as a
  grid with their position, rule, generation, and metadata, under the decode limit and
  optionally trimmed; `read_universe` / `PatternFiles.ReadUniverse` places any two-state
  file in a HashLife universe. PNG covers every color type, bit depth, and interlacing;
  BMP the core and info headers, 1- to 32-bit pixels, and the common bit-field masks.
- **Pattern metadata** (`PatternMetadata`; [spec/formats.md](spec/formats.md)
  "Metadata"): the readers return a file's name, author, and comment lines (RLE and
  Macrocell `#N`, `#O`, `#C`; plaintext `!Name:`, `!Author:`, `!`; Life 1.0x `#D`)
  instead of skipping them, and the RLE and Macrocell writers write them back
  (`rle_metadata` / `Patterns.RleMetadata`; a `metadata` argument on `rle_encode`,
  `HashLife.to_rle`, `to_macrocell`, and `save`, and new overloads of
  `Patterns.RleEncode`, `HashLife.ToRle`, `ToMacrocell`, `EncodeFile`, and
  `Macrocell.Write`). Without metadata every writer gives exactly the text it did.
- **Macrocell timelines** ([spec/macrocell.md](spec/macrocell.md) "Timelines"): frames
  of one universe at evenly spaced generations, sharing one node table in one file
  (`#FRAMES` and `#FRAME` lines). `read_timeline` / `Macrocell.ReadTimeline` gives each
  frame as a snapshot of one universe; `write_timeline` / `Macrocell.WriteTimeline` writes
  a file from snapshots, canonically, with its root and `#G` set to the last frame so
  readers without timelines load that. `read_universe` / `PatternFiles.ReadUniverse` give
  a timeline file's frames too (`frames` and `step` on `PatternUniverse`), so one read
  opens one, and refuse a malformed timeline as `read_timeline` does; the plain Macrocell
  readers (`HashLife.from_macrocell`, `Macrocell.Read`) still skip timeline lines.

- **Editing primitives** for selection and run tools ([spec/patterns.md](spec/patterns.md)
  "Extract and stamp" and "Editing a region", [spec/hashlife.md](spec/hashlife.md)
  "Editing"):
  - Paste modes: grid stamps take a `mode` (`stamp(..., mode=...)`, .NET `StampMode`):
    `copy`, `or` (the old `transparent`), and the two-state `xor` and `and`, which refuse
    any cell other than 0 or 1 and change nothing. HashLife's `set_rect` gains `and`
    (`HashLifePasteMode.And`).
  - The counter-clockwise turn: `rotate90_ccw`, `Patterns.Rotate90Ccw` and
    `Rotate90CcwPlanes`.
  - Random fill of a region of a life-like grid (`LifeLike.fill_random`, `fill_random`;
    `LifeLike.FillRandom`, `Patterns.FillRandom`): the soup of a world the region's size,
    from PCG32 stream 0 ([spec/rng.md](spec/rng.md) now lists the fills there), so it
    fills a rectangle exactly as HashLife's `fill_random` does. `check_region` /
    `Patterns.CheckRegion` validate a region.
  - Advance Selection and Advance Outside (`advance_selection`, `advance_outside`;
    `AdvanceSelection`, `AdvanceOutside`) on life-like, wireworld, and cyclic grids and in
    HashLife: the selection evolves n generations on its own, the rest of the world
    blank, and is clipped back; or the outside evolves as if the selection were empty.
    The generation counter stays. A grid's copy keeps the world's boundary, so a torus
    wraps; in HashLife the selection is an isolated plane, a jump costs what `step`
    costs, and a canceled or failed advance leaves the universe as it was.
  - HashLife rectangle tools: `bounding_box_in` / `BoundingBoxIn` (for Shrink Selection;
    any coordinates), `clear_outside` / `ClearOutside`, `rotate_rect` / `RotateRect` in
    either direction (about the rectangle's center, never drifting, returning where the
    cells land) and `flip_rect` / `FlipRect`, all on the tree, with no dense copy, at any
    area or population; and `set_generation` / `SetGeneration`, which changes only the
    counter.

- **Every two-state rule over the 3×3 neighborhood** (`compile_rule` and `LifeRule` in
  `heaton_life.ca.rulestring`, .NET `RuleString.Compile` and `LifeRule`;
  [spec/rules.md](spec/rules.md)). A Life-like rule is now one 512-entry transition table,
  compiled from outer-totalistic `B…/S…` rules, isotropic non-totalistic rules in Hensel
  notation (`B3/S2-i34q`, `B2-a/S12`), `MAP` strings (any table), and hexagonal (`H`) and
  von Neumann (`V`) rules. Life-like grids and HashLife both run the table, so every rule
  runs on a grid and on the unbounded plane. Each rule has one canonical
  spelling: letters in alphabetical order, the shorter of the plain and `-` forms, a full
  letter set as the bare digit, and MAP strings without padding and with their unused bits
  zero. B0 rules still run as written on grids. Preset
  names such as `life` are for rules people type (the Python reference's `HashLife("life")`
  still works): a file names its rule, so a Macrocell `#R life`, or a Life 1.05 or 1.06
  `#R life` read into HashLife, is refused in both ports, as an RLE header's preset already
  was.

- **Measuring any pattern file before reading it** (`measure_pattern`, .NET
  `PatternFiles.Measure`, giving a `PatternExtent`; [spec/formats.md](spec/formats.md)
  "Measuring"): what an untrimmed `read_pattern` / `PatternFiles.Read` would give, except
  the cells (the format, the grid's size and position, the rule, the generation, and the
  metadata), and whether the file is two-state, all found without making the grid. RLE is
  measured by its counted extent, plaintext by its rows, Life 1.05 and 1.06 by their cells'
  coordinates, Macrocell from its tree without building a universe (the Caterpillar and
  Annelid each in under a second in .NET), and PNG and BMP from their headers: a picture's extent
  is the whole picture, and its pixels are not decoded. Gzip around any of them is fine. A
  file too large for any grid can now be sent to HashLife, or refused, by its size, before
  a reader asks for memory.
- **Turned rectangles for grids** (`turned_rect`, .NET `Patterns.TurnedRect`;
  [spec/patterns.md](spec/patterns.md) "Editing a region"): the rectangle a quarter turn
  about its center sends a rectangle to, for any integers. It is the rectangle HashLife's
  `rotate_rect` / `RotateRect` returns, by one shared formula, so a grid that pastes
  `rotate90` (or `rotate90_ccw`) of a region there turns it onto the same cells as the
  unbounded world.
- **Why a rule is refused, without an exception** (`try_compile_rule`, .NET
  `RuleString.TryCompile(text, out rule, out reason)`; [spec/rules.md](spec/rules.md)
  "Reasons"): the compiled rule, or the reason for the first problem in the text, such as
  `expected '/' after the birth counts`. Every reason is listed in the spec and gives the
  same text in both ports; compiling's error message carries the same reason.
- **What snapshots hold, and letting them go** (`HashLife.measure_snapshots`, giving a
  `SnapshotFootprint`, and `Snapshot.release`; .NET `HashLife.MeasureSnapshots` and
  `HashLifeSnapshot.Release`; [spec/hashlife.md](spec/hashlife.md) "Snapshots", "What
  snapshots hold"). The measure counts the nodes a list of snapshots holds in a universe's
  store beyond its current state, and what each one adds to those before it. The counts
  are exact and the same in both ports: a state's nodes are its canonical Macrocell node
  lines. Each port adds its own estimate in bytes. With the list newest first, the last k
  counts add up to what releasing those k snapshots frees, so an undo history can be held
  to a byte budget. `release()` lets a snapshot's nodes go at the universe's next
  collection, without waiting for the object to be dropped and, in .NET, found by the
  managed collector.
- **Reading a file into a universe that exists** (`HashLife.read_snapshot`, giving a
  `PatternSnapshot`; .NET `HashLife.ReadSnapshot` and `PatternFiles.ReadSnapshot`;
  [spec/formats.md](spec/formats.md) "Reading into a universe that exists"). Any file
  `read_universe` reads goes into the universe's own store as a snapshot, with its
  format, rule, metadata and a timeline's frames, and shares the nodes the store already
  holds. The universe's state, rule and earlier snapshots stay as they were, so a host
  can go back to a start that lives in a file and keep its undo history.
- **A world's state without moving its start** ([spec/README.md](spec/README.md) "A
  world's state and its start"): Python's grid families gain
  `set_state(state, generation, keep_start=False)`, and .NET adds
  `SetState(state, generation, keepStart)` and `StateCodec.Load(sim, bytes, generation,
  keepStart)`. By default the state also becomes the start that Reset returns to, as
  .NET's `SetState` always made it. With `keep_start` the start stays and nothing is
  copied for it, so a host that shows a timeline frame or puts back an undo point leaves
  Reset where it was. .NET allocates nothing doing it.
- **Rules with B0 on the unbounded plane** ([spec/hashlife.md](spec/hashlife.md) "Rules
  with B0", [spec/rules.md](spec/rules.md) "B0 and the background"). A rule with B0 lights
  the whole plane, so its universe holds the cells that differ from the **background**,
  which the rule and the generation fix: alive at every generation for B0 with Smax (S8 in
  a Moore rule, S6 hexagonal, S4 von Neumann), which then runs as its black/white reversal
  (`B0123478/S01234678` runs as Life), and alive at odd generations only for B0 without
  Smax, which alternates two phase tables with every step of two or more generations
  starting at an even generation. Every notation and neighborhood works, and steps of any
  size, editing, snapshots, frames, and the Macrocell, RLE and timeline readers and writers
  all work on those cells, so files round-trip. New: `HashLife.background` (0 or 1; .NET
  `BackgroundAlive`), `LifeRule.has_smax` and `LifeRule.background(generation)` (.NET
  `HasSmax`, `BackgroundAlive(generation)`). A frame shows the universe's cells; where the
  background is alive it shows the plane in negative, and a viewer may swap its colors.
- **Grid topologies** ([spec/topology.md](spec/topology.md)): Life-like and Wireworld
  grids run on the plane (`dead`), the torus with an optional shift along one axis, the
  Klein bottle (one pair of edges twisted, optionally shifted), the cross-surface, and the
  sphere (square grids). The params gain `shift` and `axis`, left out of a vector's params
  at 0 and `x`, so every earlier run reads as it did; `Topology` (a Python dataclass, a
  .NET struct) says where any point past an edge lands. One halo fill (`Halo`, any radius)
  is how a grid's step reads past its edges, so the grid families still to come take every
  topology with it. .NET's `Step` still allocates nothing.
- **Bounded grids in RLE** ([spec/topology.md](spec/topology.md) "The bounded-grid
  suffix"): an RLE header's rule may carry the suffix Life programs share for a bounded
  world, `rule = B3/S23:T30,20` (`:P` plane, `:T` torus with `+n`/`-n` shifts, `:K` Klein
  bottle with a `*` twist, `:C` cross-surface, `:S` sphere), read in either case and written
  canonically: `parse_bounded_grid`, `try_parse_bounded_grid` and `split_rule_suffix`
  (.NET `BoundedGrid.Parse`, `TryParse` and `SplitRule`), every refusal with its reason.
  `read_pattern` / `PatternFiles.Read` reads a bounded file as its whole world, the world
  centered on the origin and the pattern at its `#CXRLE Pos` or centered too, and reports
  the world as `bounded_grid` (`BoundedGrid`), as `measure_pattern` / `Measure` does; the
  encoders take a `topology` and write the world with its suffix. A side of 0 (the
  notation's unbounded strip or tube) is refused.
- **Multi-state HashLife** (`heaton_life.ca.hashlife.MultiStateHashLife`, .NET
  `MultiStateHashLife`; [spec/hashlife-multistate.md](spec/hashlife-multistate.md)): rules
  whose cells have more than two states, on the unbounded plane, by the two-state engine's
  algorithm on a quadtree of 2 × 2 state leaves. A rule is a `StateRule`
  (`heaton_life.ca.state_rules`; .NET `StateRule` and `StateRules`): a number of states (2
  to 256), a canonical name, and a cell function of the 3 × 3 block. The base case is
  computed from the cell function and memoized, so any family of the 3 × 3 block plugs in
  without engine changes. Wireworld runs today, named `WireWorld` (`WireworldRule`);
  Generations, History and Super, and rule tables plug in as they land. Everything the
  two-state universe does, this one does with states: steps of any size below 2⁵¹⁰, the
  memory budget, garbage collection and cancellation; editing in the ±10⁹ box (cells and
  rectangles of states pasted by copy or or, the two-state xor and and where every cell
  involved is 0 or 1, clearing, Clear Outside, turns and flips, Advance Selection and
  Advance Outside, Set Generation, the bounds Shrink Selection uses); snapshots in the
  shared snapshot type (`measure_snapshots`, `release`, `read_snapshot`), which each kind
  of universe refuses from the other; `LifeView` navigation; and frames. A frame's pixel
  is a state zoomed in; zoomed out it is the state of the block that comes first in the
  universe's zoom order (`zoom_order`, .NET `ZoomOrder`; lowest first by default), or the
  density of its non-zero cells. Changing the rule keeps the cells and refuses a rule with
  fewer states than the universe holds. .NET `Step` and `WriteFrame` allocate nothing once
  warm.
- **Multi-state files** ([spec/macrocell.md](spec/macrocell.md) "Multi-state files"):
  Macrocell's `1 <nw> <ne> <sw> <se>` leaves of four states, read and written canonically
  (two-state leaf lines read too, as states 0 and 1), with timelines
  (`heaton_life.ca.hashlife.multistate.read_timeline` and `write_timeline`, .NET
  `MultiStateMacrocell`); RLE of either dialect, placed by `#CXRLE`; and both loaded by
  content, gzip-compressed or not (`read_multistate_universe`, .NET
  `MultiStateFiles.ReadUniverse`). A file names its rule; one that names none takes the
  reader's (`WireWorld` by default).
- The new `hashlife-multistate/` vectors run Wireworld on the plane beside the grid
  family's own runs: a pattern evolves cell for cell as on a grid with dead edges,
  wherever the grid lies.
- **Grid Advance Selection and Advance Outside can be canceled**
  ([spec/patterns.md](spec/patterns.md) "Canceling"), as HashLife's always could:
  .NET's `LifeLike`, `Wireworld` and `Cyclic` `AdvanceSelection` / `AdvanceOutside` take an
  optional `CancellationToken`, polled every row, and Python's grid families gain
  `cancel()`, honored between generations from another thread. A canceled advance throws
  what a canceled HashLife step throws (`OperationCanceledException`, `StepCanceled`) and
  leaves the world exactly as it was, so a host can offer Cancel instead of capping the
  work. Without a cancel, every result is as before.
- **History rules** ([spec/history.md](spec/history.md); [spec/rules.md](spec/rules.md)
  "Variants"). A `History` suffix on any Life-like rule, in every notation and
  neighborhood (`B3/S23History`, `B2/S34HHistory`, `MAP…History`; `LifeHistory` is
  `B3/S23History`), gives seven states: off, on, envelope, marked on, marked off, start on
  and boundary. The on cells (the odd states) run the base rule exactly; the envelope
  records every cell once on; marks survive birth and death; boundary cells never change
  and keep every cell beside them off. The states read and write as RLE's letters `.` and
  `A`–`F`, so LifeHistory files shared online open as they were written.
  - The rule compiler takes a variant only when asked (`compile_rule(text,
    variants=True)`, .NET `RuleString.Compile(text, variants: true)` and the new
    `TryCompile(text, variants, out rule, out reason)`); without it a History rule is
    refused with the reason `a History rule has 7 states, not 2`, so every two-state
    engine, reader and dialect check works as before. `LifeRule` gains `variant` (.NET
    `Variant`, `RuleVariant`), `states`, `base`, `same_base` (.NET `SameBase`: a host's
    native-or-alien check compares bases, so a Life part is at home in a History world)
    and `convert_cells` (.NET `ConvertCells`: a state the rule lacks becomes on or off by
    its parity, so a History pattern pastes into a two-state world by its on cells).
  - Life-like grids run History rules on every topology (`LifeLike.states`, .NET
    `States` and `CompiledRule`); their frames are the states themselves, for a color per
    state. .NET `Step` and `WriteFrame` allocate nothing. Random fill writes the base
    rule's soup, states 0 and 1.
  - On the unbounded plane, the multi-state universe runs every History rule whose base
    has no B0 (`MultiStateHashLife("B3/S23History")`, `HistoryRule`), with random fill
    (`fill_random`, .NET `FillRandom`); the two-state `HashLife` refuses History rules
    with a reason. The canonical RLE encoder writes a History rule's canonical name.
  - New vectors: the `lifelike-history/` family, `rules/history*`, and History cases
    under `patterns/`, `render/`, `formats/` and `hashlife-multistate/` (where the plane
    runs beside a History grid inside walls of boundary cells).
- **Generations** (`heaton_life.ca.Generations`, .NET `Generations`;
  [spec/generations.md](spec/generations.md)): a grid family whose cells take time to die.
  A rule pairs any Life-like rule ([spec/rules.md](spec/rules.md)), for births and
  survival, with a number of states C from 2 to 256: state 1 is alive and 2 … C − 1 are
  dying; a dying cell counts as a dead neighbor and moves one state on each generation,
  C − 1 to 0, and a live cell that doesn't survive starts dying. So isotropic, MAP,
  hexagonal and von Neumann Generations rules come with it, and with C = 2 a rule is its
  Life-like rule. Rules read in both common spellings, `B2/S345/C4` and survival/birth/count
  `345/2/4`, are written canonically as `B2/S345/C4`, and every refused text has its reason
  (`compile_generations_rule`, `try_compile_generations_rule`; .NET
  `GenerationsRule.Compile` and `TryCompile`). A rule with B0 runs as written. It runs on
  every topology, with the editing tools of the other grid families: paste modes, Clear,
  turns, random fill (the life-like soup, each live cell state 1), Advance Selection and
  Advance Outside (cancelable, as on the other grids), and `set_state` with `keep_start`. A frame fades the dying states toward
  the background; per-state palettes come later. .NET `Step` and `WriteFrame` allocate
  nothing.
- **Generations on the unbounded plane**: a Generations rule is a state rule, so
  `MultiStateHashLife` runs every one, of any count, named in either spelling, and
  multi-state Macrocell and RLE files that name one read into it. A rule with B0 is refused
  there, its background being one that changes. The two-state `HashLife` refuses a
  Generations rule with that reason, pointing to `MultiStateHashLife`.
- **RLE states past 24** ([spec/patterns.md](spec/patterns.md)): extended RLE's two-letter
  tags, `pA` to `yO` for states 25 to 255, read by the grid decoders and by multi-state
  HashLife, whitespace ignored inside a tag as between tags. A header naming a Generations
  rule makes a file extended, and a bounded-grid suffix works on it as on any rule:
  `rule = B2/S345/C4:T64,48` reads as that world.
- The new `generations/` and `generations-rules/` vectors, and Generations cases in
  `patterns/`, `formats/` and `hashlife-multistate/`: on the plane a pattern evolves cell
  for cell as on a grid with dead edges, for as long as it stays inside the grid.
- **State palettes** ([spec/render.md](spec/render.md#state-palettes)): a color for each
  state of a world, a 256-entry table indexed by state, so the colormap lookup colors a
  world's states (`heaton_life.render`; .NET `StatePalettes`). Each family has a default
  (`default_palette` / `StatePalettes.Default`): History's seven colors for a History
  rule, a `fire` fade for Generations and for Larger than Life of three states or more, a
  multi-state universe its rule's (any other rule the new multi-state palette), and
  elsewhere the palette of the colormap the family is shown with, so nothing looks
  different. `frame_values` and `colormap_palette` /
  `FromColormap` turn a colormap into an editable palette that shows the states as the
  colormap shows the frames; `gradient_palette` / `Gradient` is the form a rule file's
  `@COLORS` gradient takes; `shade_colormap` / `Shade` colors frames that count live cells.
  `default_zoom_order` / `DefaultZoomOrder` gives the zoom order that goes with a palette:
  History's keeps live and marked cells over the envelope, for a host to set. Python's
  `Elementary` gains `diagram`, as .NET's has.
- **Sampling a window of a grid** ([spec/render.md](spec/render.md#sampling-a-window-of-a-grid)):
  `sample_window` / `GridWindow.Sample` read a window of a grid's states into fewer pixels,
  by nearest cell, by the zoom order (a lone live cell never vanishes) or by density, with
  exact integer bounds; the .NET one allocates nothing.
- The new `render/palette-*`, `palette-shade-*` and `window-*` vectors.

- **Larger than Life** ([spec/ltl.md](spec/ltl.md); `LargerThanLife`, `LtlRule`,
  `parse_ltl_rule` / `try_parse_ltl_rule`, .NET `LargerThanLife` and `LtlRule.Parse` /
  `TryParse`): Life over a Moore box, a von Neumann diamond or a circle of range 1 to 500,
  birth and survival as ranges of counts, the middle cell counted or not, and two states or
  up to 256 that decay as Generations rules do. Rule text in the published notation
  (`R5,C0,M1,S34..58,B34..45,NM`, Bosco's Rule, or the five-number short form), with a
  canonical form and a reason for every refusal. Counts are exact integers from summed-area
  tables and row prefix sums. LtL runs on bounded grids of any topology, read through the
  radius-r halo, and has every grid editing tool, cancelable Advance included; RLE files
  naming an LtL rule (with a bounded-grid suffix or not) read into it, a world past 24
  states writing its dying states with RLE's two-letter tags, and both HashLife universes
  refuse an LtL rule with that reason. .NET's `Step` and `WriteFrame` allocate nothing.
- **Rule tables** ([spec/ruletable.md](spec/ruletable.md),
  [spec/rule-files.md](spec/rule-files.md)). Any rule a `.rule` file defines, up to 256
  states, runs on grids of every topology and on the unbounded plane.
  - Rule files read in full (`parse_rule_file`, .NET `RuleTable.Parse` and `TryParse`):
    `@RULE`, `@TABLE` (von Neumann, Moore, hexagonal and one-dimensional neighborhoods,
    every symmetry, bound variables, first match wins, unlisted blocks keep their state),
    `@TREE`, and `@COLORS`, `@NAMES` and `@ICONS` (XPM) kept for showing. A table is
    compiled to its canonical tree, so both kinds evaluate the same way and a function
    has one tree text (`tree_text`, .NET `TreeText`). A text that is no rule file is
    refused with one of the page's reasons and its line (`RuleFileError`, .NET
    `RuleFileException`).
  - The grid family `RuleTableCA` (inits `starter`, `blank`, `soup`, `array`; frames are
    the states; editing and cancelable Advance as for the other grid families). Python
    walks the tree for all cells at once; .NET's `Step` and `WriteFrame` allocate
    nothing.
  - A rule table is a state rule, so `MultiStateHashLife` runs it; the starter set's
    names resolve wherever a state rule's name does. No registry: other rules are given
    as objects, and an RLE file may carry its own (`embedded_rule` and `append_rule`,
    .NET `RuleTables.Embedded` and `Append`; the multi-state RLE reader takes a rule
    appended under the header's name).
  - A starter set re-authored from the original publications, each with its starter
    pattern: `Langtons-Loops` (Langton 1984, Table I and Fig. 6), `Byl-Loop` (Byl 1989,
    Table II, with the one transition Fig. 3 needs), `Evoloop` (Sayama 2004, Appendix
    A.1), and the ants `Langtons-Ant`, `Ant-LLRR` and `Ant-RLR`, generated from their
    definitions by `python/tools/gen_rule_tables.py`. Their runs reproduce the
    publications' figures (Langton's Fig. 9 at generation 151, every generation of
    Byl's Fig. 3) and the ant's highway after step 9,976.
  - A rule table's default state palette ([spec/render.md](spec/render.md#default-palettes))
    is the multi-state palette of its S with its file's `@COLORS` applied in order
    (`rule_table_palette`, .NET `StatePalettes.ForRuleTable`), on its grid and on the plane;
    `frame_values` and `default_palette` take a `RuleTableCA` world.
  - New vectors: the `ruletable/` and `ruletable-files/` families,
    `hashlife-multistate/*-ruletable-*`, and `render/palette-*ruletable*`.
- **Super rules** ([spec/super.md](spec/super.md); [spec/rules.md](spec/rules.md)
  "Variants"). A `Super` suffix on any Life-like rule, in every notation and neighborhood
  (`B3/S23Super`, `B2/S34HSuper`, `MAP…Super`; `LifeSuper` is `B3/S23Super`), gives 26
  states: History's seven, which behave exactly as under the History rule, and on cells
  that leave no trail, two more trails with envelopes of their own, a no-trail pair of
  marks, and labels that vanish, wait to be cleared, cycle, or appear when touched. The on
  cells run the base rule exactly, and a newborn takes its state from its parents: parents
  that agree pass their state on, a mixture of no-trail cells gives 13, and any other
  mixture 1. The states read and write as RLE's letters with `pA` for 25, so LifeSuper
  files shared online open as they were written.
  - The rule compiler takes it as it takes History (`variants=True`, .NET `variants:
    true`); without variants it is refused with the reason `a Super rule has 26 states,
    not 2`. `RuleVariant.Super` and `LifeRule.SuperStates` are new in .NET.
  - Life-like grids run Super rules on every topology, their frames the states
    themselves; .NET `Step` and `WriteFrame` allocate nothing, and an advance cancels
    within a generation. `convert_cells` takes a Super pattern into a two-state world (odd
    states on) or a History world (states 0–6 kept), and a History pattern pastes into a
    Super world unchanged; `same_base` makes a Life pattern native there.
  - On the unbounded plane, the multi-state universe runs every Super rule whose base has
    no B0 (`MultiStateHashLife("LifeSuper")`, .NET `SuperRule` and the `Super` class), with
    random fill; the two-state `HashLife` refuses Super rules with a reason. Random fill
    there now works under Generations rules too.
  - Super's default state palette (`super_palette`, .NET `StatePalettes.ForSuper`):
    History's colors for states 0–6 and a color of its own for each other state, the
    colors published for LifeSuper but for state 13, whose white is marked on's here. Its
    zoom order extends History's, the live and marked cells showing over trails and
    labels. `default_palette` and `default_zoom_order` give both on grids and the plane.
  - New vectors: the `lifelike-super/` family, `rules/super*`, and Super cases under
    `patterns/`, `render/` (among them `palette-*super*` and `window-super-*`), `formats/`
    and `hashlife-multistate/`, and `hashlife-multistate/edit-generations-fill-random`.

- **MCell files** (`.mcl`; [spec/formats.md](spec/formats.md) "MCell"; `mcell_encode`, .NET
  `Patterns.McellEncode`, and the `mcell` format of every reader): files of MCell's Life,
  Generations and Larger than Life families read into grids, measured, and written back. A
  Life rule's survival/birth digits read as `B…/S…`, a Generations rule's
  survival/birth/states digits through the Generations family, and a Larger than Life rule
  through its own; `#BOARD` and `#WRAP` make a bounded world (the torus or the plane), `#D`
  lines are comments, and `#L` cell data holds states up to 255 (`aA` to `jO` past 24).
  The two-state universe reads a Life file and the multi-state universe a Generations file,
  both refusing a file with a board. Every other family (Weighted Life, Vote for Life,
  Rules table, Cyclic CA, and the rest) is refused, and every refusal has a reason, the same
  in both ports. MCell has no History rules: its "history" is the Generations families'
  dying states.

- **Why a name names no state rule** (`try_state_rule`, .NET `StateRules.TryCompile`;
  [spec/hashlife-multistate.md](spec/hashlife-multistate.md) "Names"). Like
  `try_compile_rule`, it gives the rule, or the reason without raising: a bare phrase, the
  same in both ports, with no page in parentheses and no .NET note of the parameter. A host
  can show it as it stands. `state_rule` (`StateRules.Compile`) still raises (throws), its
  message the reason and the page that says why. New vectors:
  `hashlife-multistate/names`.
- .NET: `History.Names` and `Super.Names`, each state's name, as Python's `NAMES` and the
  tables of spec/history.md and spec/super.md give them.
- **The multi-state universe's live cells** (`live_population` and `live_population_in`,
  .NET `LivePopulation` and `LivePopulationIn`;
  [spec/hashlife-multistate.md](spec/hashlife-multistate.md) "Observables"): under a
  History or Super rule the on cells, the odd states, so the envelope, the marks that are
  off, boundary cells and labels aren't counted; under every other rule the non-zero
  cells, which `population` counts. A History plane's population includes its envelope, so
  a host asking whether a pattern has died asks for its live cells.
- **Measuring a file for the multi-state universe** (`measure_multistate_pattern`, .NET
  `MultiStateFiles.Measure`; spec/hashlife-multistate.md "Measuring"): what loading it
  would give, except the cells, found without building a universe, as a `PatternExtent`:
  the non-zero cells' bounding box where the universe would hold them, the canonical name of
  the rule the file names (or none), the generation, the metadata, and whether the cells
  are written in a two-state format. It refuses what loading refuses, so a file that
  measures also loads. A Macrocell file of more than two states, which `measure_pattern`
  refuses, measures here.
- **Whether a file named its rule**: `read_multistate_universe` gives `rule_named` (.NET
  `MultiStatePatternUniverse.RuleNamed`), false when the file named none and the universe
  took the reader's rule.
- .NET: `StateCodec` saves and loads rule-table worlds (`RuleTableCA`), the grid verbatim as
  for every byte family, so a world saved through its own `State` before loads through the
  codec. The rule isn't in the bytes: the host keeps it, or its rule file.
- New vectors: `hashlife-multistate/edit-live-population-*` (the edit ops
  `live_population` and `live_population_in`) and `hashlife-multistate/measure-*` (kind
  `measure`).
- **Macrocell files carry a rule table** outside the starter set
  ([spec/ruletable.md](spec/ruletable.md) "Files", [spec/macrocell.md](spec/macrocell.md)
  "Multi-state files"), as RLE files do: the rule file follows the tree, from a line that
  starts with `@RULE` to the end, and the multi-state readers (and the measure) take it
  when `#R` names it. `embedded_rule` (.NET `RuleTables.Embedded`) finds it in either
  format, and `append_rule` (`RuleTables.Append`) appends one to either; the canonical
  Macrocell text stays the cells'. A carried rule has one text, its `text`, whichever file
  carries it and in either port: the rest of the file from the `@RULE` line, a final line
  end included, its CRLF and CR read as LF. New vectors:
  `hashlife-multistate/macrocell-ruletable-*`, `macrocell-error-appended-not-a-rule-file`,
  `evolve-ruletable-macrocell-appended`, `measure-macrocell-appended-rule` and
  `carried-rule-*` (kind `carried-rule`).
- **Converting a Life-like world between the engines** without its cells becoming a grid
  ([spec/hashlife-multistate.md](spec/hashlife-multistate.md) "Converting between the
  engines"): `HashLife.to_multistate(rule)` (.NET `ToMultiState`) gives a History or Super
  universe of the live cells as state 1; `MultiStateHashLife.to_two_state(rule)`
  (`ToTwoState`) a two-state universe of the on cells, the odd states; and
  `MultiStateHashLife.to_multistate(rule)` another History or Super universe, the states
  the rule lacks turned into their parity (Super to History). The generation is kept, the
  old universe is unchanged, and the tree is converted node by node, so a world of any
  size converts in the time and memory its tree takes. A background that is alive (a rule
  with B0) is refused, and so is any rule that isn't Life-like. New vectors:
  `hashlife-multistate/convert-*` (kind `convert`).

### Changed

- **A Generations rule with B0 names no state rule** (`state_rule`, `StateRules.Compile`):
  it is refused at its name, with the reason History and Super rules with B0 are given
  (`B03/S23/C3 has B0: its first generation would turn the whole plane on, …`). It used to
  compile, and then the universe's check refused it, so a host that asked only the name
  took a rule the universe would not run. Every rule a name gives now runs. A grid still
  runs such a rule as written.
- State-rule refusals end with the page that says why, in parentheses (History's and
  Super's B0 refusal used to carry it mid-sentence), and Python quotes a text that names
  no rule as written, not as a Python literal, as .NET always has.

- **Canonical RLE writes a run of k ≥ 2 row ends as one `k$`** (`rle_encode`,
  `Patterns.RleEncode`), so empty rows cost one token however many there are. Files read
  back exactly as before, and no existing vector had such a run, but the text differs
  wherever two `$` used to meet: `$$` is now `2$`.

- **RLE decoding refuses a grid past 2²⁶ cells by default** (8192 × 8192; `max_cells`,
  `Patterns.DefaultMaxCells`), before allocating anything. It used to try: a header
  declaring `x = 1000000000, y = 1000000000`, or one run of a billion dead cells, asked
  for memory no machine has, and .NET overflowed its `int` sizes on the way. Pass a
  larger limit, or `None` / `null` to lift it, to decode a bigger grid on purpose.
- **An RLE header naming any Life-like rule makes the file two-state**, in any of the
  notations above, so uppercase `B` and `O` are dead and alive there as in a `B…/S…` file.
  Such a header used to mark the file extended, which HashLife refuses. Preset names such
  as `life` are not rules in a file and still read as extended.
- **Canonical RLE names a Life-like rule in its canonical form** (`rle_encode`,
  `Patterns.RleEncode`), so the header reads back as the same rule however it was spelled:
  `b3 / s32` is written `B3/S23`. It used to be written as given, and a rule spelled with
  spaces read back as `B3` in the extended dialect. Any other rule is written as given.
- Python: a refused rule's message now reads as .NET's always has: it quotes the text as
  written, not as a Python literal, and names the first letter its digit doesn't define
  (`k is not a letter class of 1` for `B1kn/S`, which used to say `kn`). The two ports now
  give the same reason for every text.
- `parse_rule` (.NET `RuleString.Parse`) still gives the birth and survival counts of an
  outer-totalistic Moore rule; for a rule that has none, such as an isotropic or hexagonal
  one, it raises (throws) and points to `compile_rule` (`RuleString.Compile`).
- Python: `rle_runs` reads its tokens one at a time. It used to list every token of the
  file first, which held a large file in memory several times over.
- **`HashLife.from_file` / `HashLife.Load` read every two-state format** by content, not
  just RLE and Macrocell.
- **Pattern file bytes are UTF-8 when they are valid UTF-8**, otherwise Latin-1 as before
  ([spec/formats.md](spec/formats.md) "Bytes and text"). Under Latin-1, a byte `85` inside
  an accented letter (Å, ą) split its comment line in two, and the second half could then
  be read as cells.
- **Gzip input is checked whole**: one member, its CRC-32 and length verified. A
  truncated `.mc.gz` used to load partially in .NET (Python refused it), and a file of two
  concatenated members is now refused in both.
- Macrocell readers skip blank lines before the `[M2]` header (detection already allowed
  them).
- .NET: RLE decoding splits lines and skips whitespace exactly as the Python reference
  does. A file with old Mac (CR-only) line ends decoded as one long line, an empty
  pattern, instead of the pattern it holds.
- Python: generations and positions of any length read and write. CPython refuses to
  convert integers past 4,300 digits, so a Macrocell `#G` or an RLE `#CXRLE Gen` that long
  failed in Python but not in .NET.
- .NET: `Wireworld.SetState` and `Cyclic.SetState` check every value before they write
  any, so a refused grid changes nothing. They used to write the cells before the bad one.
- **An RLE header's bounded-grid suffix is read as one** ([spec/patterns.md](spec/patterns.md)
  "Bounded grids"): the rule the decoders report is the text before the `:`, and the
  dialect is that rule's, so `rule = B3/S23:T30,20` heads a two-state file. The whole token
  used to be the rule, which no rule compiler accepts, so such a file read as extended RLE
  (uppercase `B` and `O` as states 2 and 15) and HashLife refused it as extended. A
  malformed suffix is now an error of the decode, and HashLife refuses a bounded file as
  bounded.
- **Reading a bounded RLE file into a grid gives its whole world** (`read_pattern`,
  `PatternFiles.Read`, and their measures): the world's size, its top-left at
  (−⌊W/2⌋, −⌊H/2⌋), the pattern placed in it. It used to give the pattern at its declared
  size, at (0, 0).
- **An RLE header's rule in survival/birth order reads as `B…/S…`**
  ([spec/formats.md](spec/formats.md) "Rules in survival/birth order"), as Life 1.05's
  `#R` line already did: `rule = 23/3` is `B3/S23`, after any bounded-grid suffix comes off
  (`rule = 23/3:T30,20`). Such a file is two-state, HashLife reads it, and canonical RLE
  writes the rule as `B3/S23`. The header used to name a rule no compiler accepts, so the
  file read as extended RLE and HashLife refused it.
- Elementary refuses a boundary other than `torus` or `dead`. Python read any other name
  as `dead`; .NET's `Boundary` enum now names the other topologies too.
- Python: `moore_index` and `moore_sum` read through the halo and take a `Topology` as
  well as a boundary's name; their torus and dead results are unchanged.
- Python playground: the Life-like and Wireworld forms offer every topology, with its
  shift and axis.
- **Canonical RLE writes every state up to 255** (`rle_encode`, `Patterns.RleEncode`),
  those past 24 as two-letter tags. A cell above 24 used to be refused; Python still
  refuses a value past 255.
- **Canonical RLE names a Generations rule in its canonical form**, as it does a Life-like
  rule: a header given `345/2/4` is written `rule = B2/S345/C4`. It used to be written as
  given.

## 1.1.0 (2026-09-25)

Implements spec version 0.13.0 (1.0.0 implemented 0.2.0). Every conformance vector that
existed at 1.0.0 is byte-identical; the new behavior comes with new vector cases. The
public APIs of both packages are backward compatible: nothing was removed or renamed,
and new parameters are optional.

### Added

- **Deep zoom to 10⁹⁰⁰⁰.** A floatexp perturbation tier (T2) takes Mandelbrot and Julia
  from 10²⁹⁰, where 1.0.0 stopped, to 10⁹⁰⁰⁰. The Burning Ship still stops at 10²⁹⁰ and
  Newton at 10¹². Each family reports its ceiling (`max_zoom_log10` / `MaxZoomLog10`),
  and `tier_of` / `FractalEngine.TierOf` names a zoom's tier.
- **Bilinear approximation (BLA)** for Mandelbrot at T1 and T2, opt-in
  (`Mandelbrot(bla=True)`; in .NET `new Mandelbrot(maxIter, escapeRadius, workers,
  bla: true)`), which skips many iterations at once on deep frames.
- **Navigation:** off-center reference points; exact decimal pan and zoom
  (`heaton_life.fractal.navigation` / `Navigation`); location import from Kalles
  Fraktaler, Fraktaler-3, and Heaton Fractal (`fractal.locations` / `Locations`); and a
  nucleus finder (`find_nucleus` / `NucleusFinder`).
- **Escape fields:** pixel status, interior shortcuts, a distance estimate, and an
  iteration policy that picks a frame's `max_iter`.
- **Fractal color:** the measured stretch, a depth phase that holds a point's color
  still through a dive, distance shading, and four cyclic palettes (`deep`, `classic`,
  `embers`, `glacier`).
- **Zoom movies:** schedules, plans, and measured iteration budgets in both ports. The
  Python package also renders them (`render_zoom_movie`, to an MP4 or a resumable
  folder of PNG frames).
- **Platform self-check** (`heaton_life.self_check.run()` / `SelfCheck.Run`): 21 checks
  against answers embedded in the package, which a host runs on its own runtime to
  confirm it reproduces the bit-exact results, each scoped to what its failure would
  invalidate ([spec/self-check.md](spec/self-check.md)).
- A resumable reference-orbit cache: a longer orbit for a cached point and precision (a
  higher `max_iter` at the same zoom, or panning on a fixed reference) extends the cached
  one instead of starting over.
- .NET: `CancellationToken` overloads for the fractal renders, reference-orbit progress
  in `RenderProgress`, and a low-allocation orbit step.
- Python playground: the fractal zoom reaches each family's ceiling (10⁹⁰⁰⁰ for
  Mandelbrot and Julia), `max_iter` goes to 1,000,000 for Mandelbrot, Julia, and the
  Burning Ship, and click and wheel navigation is exact decimal arithmetic.

### Changed

- **Julia deep frames (past 10¹²) render correctly now, so they differ from 1.0.0.**
  1.0.0 restarted rebased pixels on the center's own orbit instead of Julia's critical
  orbit, and got 439 of the 1,024 pixels of `julia/deep-zoom13-32` wrong. Its orbits,
  computed at the frame's own zoom, were also too coarse near preimages of 0: on their own
  they cost 51 of 144 pixels at c = i and 10¹⁰⁰, where 1.0.0 got 98 wrong. Rebased pixels
  now restart on the critical orbit, and both orbits are computed at twice the frame's
  zoom. .NET: a caller that supplies its own orbits must compute them at twice the frame's
  zoom (`ReferenceOrbit.Julia` / `JuliaCritical` with `2 × ZoomLog10`).
- **Python: NumPy 2.0.2 or newer is required** (1.0.0 allowed `numpy>=1.24`). The
  reference relies on NumPy's complex multiply being fused. Before 2.0.2, NumPy counted
  an output that merely touched an input's memory as overlapping (numpy#27077) and took a
  plain C loop that is unfused in most builds, so results depended on where the
  allocator placed arrays; NumPy 1.24 had no fused complex kernel at all. The
  self-check's `numpy-fma` check now catches both.
- Newton's roots come from exact integer turns instead of the platform's `cos`/`sin`.
  Python's `Newton.roots` values can differ from 1.0.0 by up to about 4 × 10⁻¹⁶
  (-0.49999999999999983 is now -0.5, and 6.1e-17 is now 0); basins and renders were
  unchanged in every case tested.
- Viewport centers follow one strict decimal grammar in both ports: NaN, infinities, `_`
  separators, non-ASCII digits, exponents beyond ±100,000, and centers longer than
  10,000 digits are rejected.
- Fail-fast validation: an escape radius whose square is not finite (NaN and infinities
  included) is rejected, and in Python a Newton degree that is not an `int` (3.0
  included) raises `TypeError`.
- Reference orbits take enough precision for the center's own digits, not only for the
  zoom.
- Python: reference orbits run the spec's fixed-point arithmetic, as the .NET port
  already did, instead of floating point (gmpy2 or mpmath). The two had parted after
  enough iterations (at sample 38 of one deep Julia orbit, and 67,941 at a 10¹⁶⁰
  Mandelbrot location), so Python deep frames with long orbits can differ from 1.0.0;
  both ports now agree bit for bit at any length.
- Python: MP4 export no longer rescales frames to a multiple of 16 (1.0.0 stretched 1080
  rows to 1088; an odd width or height still loses one column or row), and it fails with
  a clear error when ffmpeg or the target file is unusable.
- Python: `mpmath` is no longer installed with the package. 1.1.0 no longer uses it,
  because reference orbits are integer arithmetic now; it moved to the dev extra, for the
  tests. The `[fast]` extra, which did nothing, is gone.
- Python: saved Mandelbrot parameters now include `bla`, which 1.0.0 rejects when
  loading them.
- Python internals outside every `__all__`: `fractal.engine.escape_time` returns
  `(counts, final, status)`, and `core.bignum.reference_orbit` returns read-only arrays
  and is no longer an `lru_cache` wrapper.
- .NET: `StateCodec` saves an Elementary world's space-time diagram after its tape, and
  `Elementary.SetState(tape, diagram, generation)` restores it. 1.1.0 loads 1.0.0 saves,
  but 1.0.0 cannot load an Elementary world saved by 1.1.0. `SetState(tape, generation)`
  now places the tape in its generation's row of the diagram.
- .NET: `RenderProgress.Started` is true from the reference-orbit phase on, and each
  render resets the progress object it is given.
- .NET: the `InternalsVisibleTo` grants to `HeatonLife.Core.EditorTests` and
  `HeatonLife.Unity` are gone; hosts use the public API, `SelfCheck` included.

### Fixed

- .NET: the software fma, which stands in for the hardware one on netstandard2.1, was
  not a correctly rounded fused multiply-add. For products below 2⁻⁹⁶⁸ and for huge
  operands its error-free transforms were not exact, so deep Julia smooth renders could
  disagree with Python (by about 3 × 10⁻⁷ on `render/fractal-render-julia-deep157`). And
  everywhere else it rounded twice, so a tie in the sum that only the product's rounding
  error breaks went the wrong way (fma(1 + 2⁻³⁰, 2⁻⁵³(1 − 2⁻³⁰), 1 + 2⁻⁵²) gave
  1 + 2⁻⁵¹, not 1 + 2⁻⁵²): C#'s complex multiply could then disagree with NumPy's in the
  last place. Both are fixed (exact integer arithmetic in the far ranges, the error terms
  rounded to odd in the common one), pinned bitwise against the hardware instruction,
  cases built to be such ties included.
- .NET: the software fma returned NaN for finite factors whose product overflows, where
  IEEE gives an infinity (or the addend, when it is the infinity); a Julia center near
  2 × 10¹⁵⁴ reached it.
- .NET: a render with `maxIter = int.MaxValue` could run forever (a 32-bit loop counter
  wrapped); the loop counters are 64-bit now.
- .NET: a deep frame whose center lies within about 10⁻²⁹² of an axis threw
  `ArgumentOutOfRangeException` past a zoom of about 10²⁶⁹ (converting an orbit sample
  that small needed a power of two below the normal range); it renders now.
- .NET: a deep Julia frame whose center lies beyond about 10¹⁶² threw
  `ArgumentOutOfRangeException` (an orbit sample overflowed a power of two); an orbit
  that overflows is infinite now, as in Python.

## 1.0.0 (2026-08-22)

The first release: MergeLife, Life-like, Elementary, Cyclic, and Wireworld automata;
Classic, Asymptotic, and Flow Lenia; Mandelbrot, Julia, and Burning Ship with
perturbation deep zoom to 10²⁹⁰, and Newton's basins; Reynolds boids in 2D and 3D; Gray-Scott
reaction-diffusion; the rendering pipeline; and the MergeLife evolver. Spec version
0.2.0. The NuGet package was built from commit `234075b` and the PyPI wheel from
`59da437`; the Python sources are identical at both.
