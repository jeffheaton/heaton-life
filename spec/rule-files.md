# Rule files

Conformance tier: **bit-exact**. Vectors: [`vectors/ruletable-files/`](../vectors/ruletable-files/).

A **rule file** defines a cellular automaton of 2 to 256 states on the 3 × 3 block: its
name, its transition function as a **table** (`@TABLE`) or a **tree** (`@TREE`), and data
for showing it: colors (`@COLORS`), state names (`@NAMES`) and icons (`@ICONS`). It is the
`.rule` format the Life community shares rules in, as LifeWiki and the rule table
repository's wiki describe it; this page was written from those published descriptions,
and where they are silent it says what this library decided. The [rule-table
family](ruletable.md) runs the rules; this page is the format: how a file reads, what a
table means, how a table compiles to a tree, and why a text is no rule file.

## Lines and sections

- A file is text. Lines end at `\n`, `\r\n` or `\r`; a byte-order mark at the start is
  dropped. A line is **trimmed** when the whitespace of [rules.md](rules.md#grammar) at
  its two ends is removed, and **blank** when nothing is left.
- A **section line** is a trimmed line that starts with `@` and one or more uppercase
  ASCII letters, `A`–`Z`, that end the line or are followed by whitespace. The letters
  name the section; everything after them on the line is the section's **argument**. The
  section's lines are those that follow, up to the next section line.
- The first line that isn't blank is a `@RULE` section line, or the text is no rule
  file. The sections read are `RULE`, `TABLE`, `TREE`, `COLORS`, `NAMES` and `ICONS`; a
  section of any other name is skipped with its lines, and so is a second section of a
  name already seen.
- **`@TABLE` or `@TREE`**: the first of the two in the file gives the transition
  function, and the other is skipped. A file with neither is refused.
- The argument of every section but `@RULE` is ignored.

## `@RULE`

- The **name** is the argument. It is required, has no whitespace inside, and is
  printable ASCII without `,` or `:` (a comma ends an RLE header's field and a colon starts
  a [bounded-grid suffix](topology.md#the-bounded-grid-suffix)). The name is the rule's
  canonical name ([hashlife-multistate.md](hashlife-multistate.md#state-rules)), written
  as the file writes it; readers match names ignoring ASCII case.
- The **description** is the section's lines as written (without their line ends), with
  the blank lines at its start and end dropped, joined by `\n`.

## `@TABLE`

### Lines

In each line of the section, a `#` and everything after it is a comment, and goes; the
rest is trimmed, and a blank line is skipped. Each remaining line is a **setting**, a
**variable** or a **transition**:

- a line whose first word (up to whitespace) is `var` is a variable;
- otherwise a line that holds a `:` is a setting;
- otherwise it is a transition.

### Settings

A setting is `key:value`, with any whitespace around the `:` and at the ends. The key is
matched ignoring ASCII case; so are the values of `neighborhood` and `symmetries`, which
are kept in the spellings below.

| Key | Value |
|---|---|
| `n_states` | S, the number of states, state 0 included: decimal digits, 2 to 256 |
| `neighborhood` | `vonNeumann`, `Moore`, `hexagonal` or `oneDimensional` |
| `symmetries` | one of the neighborhood's symmetries, below |

All three are required, each once, and they come before the first variable or
transition. A table with no variables and no transitions is allowed: every cell keeps its
state.

### Neighborhoods and fields

A transition lists the **center**, the **neighbors** in the neighborhood's order, and the
**output**, the center's next state:

| Neighborhood | Fields | Ring of neighbors |
|---|---|---|
| `vonNeumann` | C, N, E, S, W, C′ | N E S W |
| `Moore` | C, N, NE, E, SE, S, SW, W, NW, C′ | N NE E SE S SW W NW |
| `hexagonal` | C, N, E, SE, S, W, NW, C′ | N E SE S W NW |
| `oneDimensional` | C, W, E, C′ | W E |

N is the cell above (y − 1), E the cell to the right, and so on. The hexagonal
neighborhood is [rules.md](rules.md#neighborhoods)'s: the Moore block without NE and SW,
whose six cells are the hexagon's corners in the order of the ring. A one-dimensional
rule runs each row by itself.

### Symmetries

A transition stands for **variants**: the transition with its neighbors moved around the
ring. With the ring's positions numbered 0 to k − 1 in the order above, the variant of a
**rotation by r** takes the neighbor at position (i + r) mod k from the transition's
position i, and the **reflection** takes it from position (k − i) mod k: it swaps east and
west and keeps north and south. In the one-dimensional neighborhood the reflection swaps
W and E. The variants of each symmetry, in the order they are tried:

| Neighborhood | Symmetry | Variants |
|---|---|---|
| all | `none` | the transition |
| `vonNeumann` | `rotate4` | rotations by 0, 1, 2, 3 |
| `vonNeumann` | `rotate4reflect` | rotations by 0, 1, 2, 3, then the reflection of each |
| `vonNeumann` | `reflect_horizontal` (also `reflect`) | the transition, then its reflection |
| `vonNeumann` | `permute` | every order of the 4 neighbors |
| `Moore` | `rotate4` | rotations by 0, 2, 4, 6 |
| `Moore` | `rotate8` | rotations by 0 to 7 |
| `Moore` | `rotate4reflect` | rotations by 0, 2, 4, 6, then the reflection of each |
| `Moore` | `rotate8reflect` | rotations by 0 to 7, then the reflection of each |
| `Moore` | `reflect_horizontal` (also `reflect`) | the transition, then its reflection |
| `Moore` | `permute` | every order of the 8 neighbors |
| `hexagonal` | `rotate2` | rotations by 0, 3 |
| `hexagonal` | `rotate3` | rotations by 0, 2, 4 |
| `hexagonal` | `rotate6` | rotations by 0 to 5 |
| `hexagonal` | `rotate6reflect` | rotations by 0 to 5, then the reflection of each |
| `hexagonal` | `permute` | every order of the 6 neighbors |
| `oneDimensional` | `reflect` (also `reflect_horizontal`) | the transition, then its reflection |
| `oneDimensional` | `permute` | the same two |

"The reflection of each" applies the reflection after the rotation. `permute` lists the
orders lexicographically by the positions they take each neighbor from, the transition
itself first. A variant that equals an earlier variant of the same transition adds
nothing. The order matters only where it can: when two variants of one transition match
the same block and its output is a variable they bind differently, the earlier wins.

### Variables

`var name = {a, b, …}`, with any whitespace around its tokens:

- The **name** is printable ASCII without `,`, `{`, `}`, `=` or `:`, and isn't all
  digits (that would be a state). A name is defined once.
- The **members** are separated by commas: a state (decimal digits, below S) or the name
  of a variable defined on an earlier line, which stands for all its states. The set has
  at least one state; repeats change nothing.

### Transitions

The line's fields are separated by commas or by whitespace (a comma with whitespace
around it is one separator). A field is a state (decimal digits, below S) or the name of a
variable defined on an earlier line. When S is at most 10, a transition may also be one
word of digits, one state per digit, with nothing between them (`012345`).

The output is a state, or a variable that also appears among the inputs, or a variable of
one state.

### Meaning

A cell's next state is found by trying the transitions in the file's order, each as its
variants in the order above. A variant **matches** a block when each input field matches
its cell: a state matches that state; a variable matches any of its states, and **every
field of one variable takes the same state** (the variable is bound). The first variant
that matches gives the next state: its output state, or the state its output variable is
bound to, or the one state of a single-state variable. **A block that no variant matches
keeps its center's state.**

## `@TREE`

A tree gives the function directly. The section's lines, after comments (`#` to the end of
a line) go, are trimmed, and blank ones are skipped:

- Three settings, `key=value` with any whitespace around the `=`, keys matched ignoring
  ASCII case, each once, before the first node: `num_states` (S, 2 to 256),
  `num_neighbors` (4 or 8) and `num_nodes` (how many node lines follow, at least 1).
- Then the **nodes**, one a line, numbered from 0 in the order they come: a node's
  **level** and its S **children**, all decimal numbers separated by whitespace. A level-1
  node's children are states below S; a node of level L ≥ 2 has children that are earlier
  nodes of level L − 1. The levels run from 1 to `num_neighbors` + 1, and the **root** is
  the last node, at level `num_neighbors` + 1.
- A cell's next state is found by walking from the root, taking at each level the child
  that the state of one cell of the block picks. With 8 neighbors the cells are taken in
  the order NW, NE, SW, SE, N, W, E, S, C; with 4, in the order N, W, E, S, C. The level-1
  node reached gives the next state as its child at the center's state.

A tree of 4 neighbors reads the von Neumann cells, and one of 8 the Moore block.

## Compiling a table to a tree

Both kinds of file run as a tree: a table is compiled into the tree of the same function,
a von Neumann or one-dimensional table to 4 neighbors and a Moore or hexagonal table to 8.
A one-dimensional table ignores N and S, and a hexagonal one NE and SW: every node at
such a level has its children all alike.

Every tree, compiled or read, is kept in its **canonical form**: nodes that are alike
(the same level and the same children) are one node, nodes the root can't reach are gone,
and the nodes are numbered in post-order from the root, children taken in the order of
their states, each node numbered once, when its last child is done. A function has one
canonical tree, whichever file gave it. Its **canonical text** is

```
num_states=S
num_neighbors=K
num_nodes=M
```

and then the nodes in their order, each as its level and children separated by single
spaces, every line ending in `\n`.

## `@COLORS`

Each line that isn't blank and doesn't start with `#` is split at whitespace, and its
first words that are decimal numbers are counted:

- six or more: a **gradient**, from `r1 g1 b1` (the first three) to `r2 g2 b2` (the next
  three), over states 1 to S − 1;
- four or five: a **state color**, `state r g b`;
- fewer: the line is refused.

Words after the counted numbers are a note and are ignored. Every color component is 0 to
255. A state color for a state not below S is ignored. The entries are kept in the
file's order (a later one overrides an earlier one where they meet). A rule table's
default palette applies them over the multi-state palette
([render.md](render.md#default-palettes)); which colors a host draws is its own
choice.

## `@NAMES`

Each line that isn't blank and doesn't start with `#` is a state (decimal digits) and,
after whitespace, a **name**: the rest of the line, trimmed and not empty. A name for a
state not below S is ignored. Entries are kept in order.

## `@ICONS`

Blank lines and lines that start with `#` or `/` are skipped (so `/* … */` comments are
too). The rest is either one **style**, one of the words `circles`, `diamonds`, `hexagons`
or `triangles` (ASCII case ignored), or one or more **XPM sets**:

- A line `XPM` starts a set. The set's strings are the lines after it that start with
  `"`, each the text up to the next `"` (what follows it is ignored), until the set has
  1 + colors + height of them; a string before the next `XPM` line beyond those is
  ignored.
- The first string is four numbers: the icons' **width**, the set's **height**, the
  number of **colors**, and the **characters per pixel** (1 or 2). The height is a
  positive multiple of the width.
- Each color string is a **key** of that many characters, whitespace, `c`, whitespace, and
  a color: `#RRGGBB` (hexadecimal) or `None` (no color). Keys are distinct.
- Each row string is width × characters-per-pixel characters, each pixel a key.
- The rows hold height ÷ width icons stacked top to bottom: icon k is for state k + 1, and
  a state past the last icon has the last icon. State 0 has none.
- A set whose width is not 7, 15 or 31 is read and then dropped. The sets kept, in file
  order, are each its width, its colors and its rows as written.

## Why a text is no rule file

The first problem found, reading from the top, is reported with its line (counted from 1),
or with none where the whole file is at fault. A section's settings are checked when its
first variable, transition or node arrives, or at its end. A port's error carries the
reason and the line; its message is `invalid rule file: line N: reason
(spec/rule-files.md)`, or without `line N: ` where there is none. The reasons, with
`{…}` filled in:

| Where | Reason |
|---|---|
| file | `a rule file starts with '@RULE' and the rule's name` (the first line that isn't blank; none when every line is blank) |
| `@RULE` | `'@RULE' has no name` |
| `@RULE` | `a rule's name has no spaces` |
| `@RULE` | `a rule's name is printable ASCII without ',' or ':'` |
| file | `no '@TABLE' or '@TREE' section` |
| `@TABLE` | `unknown setting '{key}'` |
| `@TABLE` | `'{key}' is set twice` (the key in its canonical spelling) |
| `@TABLE` | `'{key}' comes before the variables and transitions` |
| `@TABLE` | `'{key}' is missing` (`n_states`, then `neighborhood`, then `symmetries`; the line of the first variable or transition, or none at the section's end) |
| `@TABLE` | `n_states is a whole number from 2 to 256` |
| `@TABLE` | `unknown neighborhood '{value}': expected vonNeumann, Moore, hexagonal or oneDimensional` |
| `@TABLE` | `the {neighborhood} neighborhood has no '{value}' symmetries: expected {list}` (the symmetries line; the list as in the table above, comma-separated, with its aliases) |
| `@TABLE` | `expected 'var name = {states}'` |
| `@TABLE` | `a variable's name can't be a number` |
| `@TABLE` | `a variable's name is printable ASCII without ',', '{', '}', '=' or ':'` |
| `@TABLE` | `variable '{name}' is defined twice` |
| `@TABLE` | `variable '{name}' has no states` |
| `@TABLE` | `unknown variable '{name}'` |
| `@TABLE` | `state {n} is not below n_states {S}` (a member or a field, `{n}` as written) |
| `@TABLE` | `a transition has an empty field` |
| `@TABLE` | `a {neighborhood} transition has {F} fields, not {n}` |
| `@TABLE` | `the output '{name}' has several states and no input binds it` |
| `@TREE` | `expected 'num_states', 'num_neighbors' or 'num_nodes' and '='` |
| `@TREE` | `'{key}' is set twice` |
| `@TREE` | `'{key}' is missing` (`num_states`, `num_neighbors`, `num_nodes`; the first node's line, or none at the end) |
| `@TREE` | `num_states is a whole number from 2 to 256` |
| `@TREE` | `num_neighbors is 4 or 8` |
| `@TREE` | `num_nodes is a positive whole number` |
| `@TREE` | `a node is its level and {S} children, all whole numbers` |
| `@TREE` | `a node's level is 1 to {K + 1}` |
| `@TREE` | `a level-1 node's children are states below {S}` |
| `@TREE` | `a level-{L} node's children are earlier nodes of level {L − 1}` |
| `@TREE` | `the tree has more than num_nodes nodes` |
| `@TREE` | `the tree has {n} nodes, not num_nodes {M}` (no line) |
| `@TREE` | `the root, the last node, is at level {K + 1}` (no line) |
| `@COLORS` | `a '@COLORS' line is 'state r g b' or 'r1 g1 b1 r2 g2 b2'` |
| `@COLORS` | `a color component is 0 to 255` |
| `@NAMES` | `a '@NAMES' line is a state and its name` |
| `@ICONS` | `an '@ICONS' line is 'XPM', a quoted string, or circles, diamonds, hexagons or triangles` |
| `@ICONS` | `'@ICONS' holds one style or XPM sets, not both` |
| `@ICONS` | `a quoted string has no closing '"'` |
| `@ICONS` | `an XPM set's first string is its width, height, colors and characters per pixel` |
| `@ICONS` | `an XPM color is a key, 'c' and #RRGGBB or None` |
| `@ICONS` | `an XPM row is {width × cpp} characters, a color's key for each of its {width} pixels` |
| `@ICONS` | `the XPM set has {n} strings, not {needed}` (the `XPM` line, once the strings the set has are checked) |

A number in a setting or a node may have leading zeros; a value past the largest allowed
is refused with that setting's reason however many digits it has. A file the reasons don't
refuse is a rule file.

## Vector encoding

Each case under `vectors/ruletable-files/` has a `params.json` with
`family: "ruletable-files"`, `tier: "bit-exact"`, `spec_version` and a `kind`:

| kind | inputs | expected |
|---|---|---|
| `compile` | `input.rule` | `name`, `states`, `neighbors` (4 or 8), `neighborhood` and `symmetries` (a table's; null for a tree), `source` (`table` or `tree`), `description`, `colors` (each entry `{"state", "rgb"}` or `{"from", "to"}`), `names` (`{"state", "name"}`), `icons` (`{"style"}`, or `{"sets": [{"width", "colors": [[key, "#RRGGBB" or null], …], "rows"}]}`, or null), and `tree.txt`, the canonical text of its tree |
| `reasons` | `cases`: each a file's `text` | each case's `reason` and `line` (null for none) |

Runners are strict: an unknown key, kind or `spec_version` fails the case.
