"""Location import and framing conversions -- spec/locations.md.

Every other deep-zoom program frames a location by the frame's HEIGHT; heaton-life by
its width. A location's portable scale is therefore its half-height ``h`` (center to
top edge, plane units), and ``Location.viewport(size)`` frames it in heaton-life so
the vertical extent matches: ``zoom_log10 = log10(fl(2H/W)) - log10 h``. The
conversions use log10, so they are not bit-exact; they run once, when a location
enters, and the zoom they produce is stored with the viewport from then on.

Parsers: Kalles Fraktaler ``.kfr``, Fraktaler-3 ``.f3.toml``, and Heaton Fractal's
preset JSON, hunt result ``.txt`` and hunt ``journal.jsonl``. Centers come back in the
shared decimal grammar, rewritten positionally (same value and places, no exponent).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from heaton_life.core import decimal_text
from heaton_life.core.viewport import Viewport

__all__ = [
    "Location",
    "decimal_log10",
    "hf_journal",
    "hf_preset",
    "hf_seed",
    "parse_fraktaler3",
    "parse_hf_journal",
    "parse_hf_preset",
    "parse_hf_result",
    "parse_kfr",
]

# Warning codes, in the order a record lists them.
WARNINGS = (
    "rotation-ignored",
    "stretch-ignored",
    "reflect-ignored",
    "exponential-map-ignored",
    "old-style-skew",
    "no-scale",
)
MAX_BUDGET = 2**63 - 1  # the largest iteration budget a file may state (the C# port's long)
_F3_DEFAULT_ITERATIONS = 1024  # Fraktaler-3 omits a key that holds its default
_LOG10_2 = math.log10(2.0)


@dataclass(frozen=True)
class Location:
    """A location as a file gave it (spec/locations.md "The location record")."""

    center_re: str
    center_im: str
    half_height_log10: float | None
    format: str
    max_iter: int | None = None
    reference: tuple[str, str] | None = None
    warnings: tuple[str, ...] = ()

    def viewport(self, size: tuple[int, int]) -> Viewport:
        """The heaton-life viewport of a ``width x height`` frame whose vertical extent
        matches the source's: zoom = log10(fl(2H/W)) - half_height_log10."""
        if self.half_height_log10 is None:
            raise ValueError(f"this {self.format} location gives no scale")
        width, height = size
        if width < 1 or height < 1:
            raise ValueError(f"frame must be at least 1x1, got {width}x{height}")
        zoom = math.log10(2.0 * height / width) - self.half_height_log10
        return Viewport(self.center_re, self.center_im, zoom)


def decimal_log10(text: str) -> float:
    """log10 of a positive decimal of any size: log10 of its first 15 significant digits
    (exact in a double) plus the power of ten they stand for."""
    negative, digits, net_exponent = decimal_text.scan(text)
    if negative or digits == 0:
        raise ValueError(f"must be positive: {text!r}")
    spelled = decimal_text.digits_of(digits)
    kept = spelled[:15]
    return math.log10(float(int(kept))) + (net_exponent + len(spelled) - len(kept))


def hf_preset(
    center_real: str,
    center_imag: str,
    base_half_height: str,
    target_depth_log10: float | None,
    max_iterations: int | None = None,
) -> Location:
    """A Heaton Fractal preset from its fields: h = h0 * 10^-d, or no scale when the file
    states no depth (HF itself would render at its app default)."""
    h0_log10 = decimal_log10(base_half_height)
    return Location(
        center_re=_center(center_real),
        center_im=_center(center_imag),
        half_height_log10=(
            None
            if target_depth_log10 is None
            else h0_log10 - _finite(target_depth_log10, "targetDepthLog10")
        ),
        format="hf-preset",
        max_iter=_budget_int(max_iterations),
        warnings=("no-scale",) if target_depth_log10 is None else (),
    )


def hf_seed(real: str, imaginary: str, depth_log10: float | None, fmt: str) -> Location:
    """A Heaton Fractal hunt result or journal seed: hunts frame with h0 = 1, so the
    depth is -log10 h (the nucleus's size fills the half-height)."""
    return Location(
        center_re=_center(real),
        center_im=_center(imaginary),
        half_height_log10=None if depth_log10 is None else -_finite(depth_log10, "depth"),
        format=fmt,
        warnings=() if depth_log10 is not None else ("no-scale",),
    )


def parse_kfr(text: str) -> Location:
    """A Kalles Fraktaler ``.kfr`` (spec/locations.md "File formats")."""
    values: dict[str, str] = {}
    for line in _lines(text):
        s = line.strip(" \t")
        if not s or s[0] in ";#":
            continue
        cut = _first_of(s, ":=")
        if cut <= 0:
            continue
        values[s[:cut].strip(" \t").lower()] = s[cut + 1 :].strip(" \t")
    for key in ("re", "im"):
        if key not in values:
            raise ValueError(f"a .kfr needs {key.capitalize()}")
    warnings: set[str] = set()
    if _nonzero(values.get("rotateangle")):
        warnings.add("rotation-ignored")
    if _nonzero(values.get("stretchamount")):
        warnings.add("stretch-ignored")
    if not _nonzero(values.get("imagpointsup")):  # KF's default axis points down
        warnings.add("reflect-ignored")
    if _nonzero(values.get("rotate")) or ("ratio" in values and not _equals(values["ratio"], 360)):
        warnings.add("old-style-skew")
    zoom = values.get("zoom")
    if zoom is None:
        warnings.add("no-scale")
    iterations = values.get("iterations")
    return Location(
        center_re=_center(values["re"]),
        center_im=_center(values["im"]),
        half_height_log10=None if zoom is None else _LOG10_2 - decimal_log10(zoom),
        format="kfr",
        max_iter=None if iterations is None else _whole(iterations, "Iterations"),
        warnings=_ordered(warnings),
    )


def parse_fraktaler3(text: str) -> Location:
    """A Fraktaler-3 ``.f3.toml``, in the TOML subset F3 writes. F3 leaves out every key
    that holds its default, so a missing one means the default: center 0, zoom 1,
    1024 iterations, and a reference part equal to the location's."""
    values = _toml_subset(text)
    if values.get("program") != "fraktaler-3" and not any(
        k.startswith("location.") for k in values
    ):
        raise ValueError("not a Fraktaler-3 location: no location keys and no program line")
    warnings: set[str] = set()
    if _nonzero(_scalar(values.get("transform.rotate"))):
        warnings.add("rotation-ignored")
    if _nonzero(_scalar(values.get("transform.stretch_amount"))):
        warnings.add("stretch-ignored")
    if values.get("transform.reflect") is True:
        warnings.add("reflect-ignored")
    if values.get("transform.exponential_map") is True:
        warnings.add("exponential-map-ignored")
    real = _text(values.get("location.real", "0"))
    imag = _text(values.get("location.imag", "0"))
    reference = None
    if "reference.real" in values or "reference.imag" in values:
        reference = (
            _center(_text(values.get("reference.real", real))),
            _center(_text(values.get("reference.imag", imag))),
        )
    iterations = values.get("bailout.iterations")
    return Location(
        center_re=_center(real),
        center_im=_center(imag),
        half_height_log10=_LOG10_2 - decimal_log10(_text(values.get("location.zoom", "1"))),
        format="f3",
        max_iter=(
            _F3_DEFAULT_ITERATIONS
            if iterations is None
            else _whole(_text(iterations), "bailout.iterations")
        ),
        reference=reference,
        warnings=_ordered(warnings),
    )


def parse_hf_preset(text: str) -> Location:
    """A Heaton Fractal preset (the envelope) or its bare settings object (settings.json).
    ``baseHalfHeight`` is required, as HF's own decoder requires it; a missing depth is
    no scale."""
    document = _json(text)
    if not isinstance(document, dict):
        raise ValueError("a Heaton Fractal preset is a JSON object")  # noqa: TRY004 -- a bad file
    settings = document.get("settings")
    if not isinstance(settings, dict):
        settings = document
    location = settings.get("location")
    if not isinstance(location, dict):
        raise ValueError("a Heaton Fractal preset needs settings.location")  # noqa: TRY004
    zoom = _group(settings, "zoom")
    quality = _group(settings, "quality")
    return hf_preset(
        _json_str(location, "centerReal"),
        _json_str(location, "centerImag"),
        _json_str(location, "baseHalfHeight"),
        _json_number(zoom, "targetDepthLog10") if "targetDepthLog10" in zoom else None,
        quality.get("maxIterationsOverride"),
    )


def parse_hf_result(text: str) -> Location:
    """A Heaton Fractal hunt result ``.txt``: ``re = ...`` / ``im = ...`` lines, and a
    ``# ... depth 1e<d>`` comment for the scale."""
    values: dict[str, str] = {}
    depth: float | None = None
    for line in _lines(text):
        s = line.strip(" \t")
        if s.startswith("#"):
            at = s.find("depth 1e")
            if at >= 0 and depth is None:
                token = _word(s[at + len("depth 1e") :]).rstrip(",;")
                depth = decimal_text.to_float(token)
            continue
        cut = s.find("=")
        if cut > 0:
            values[s[:cut].strip(" \t").lower()] = s[cut + 1 :].strip(" \t")
    for key in ("re", "im"):
        if key not in values:
            raise ValueError(f"a Heaton Fractal result needs {key}")
    return hf_seed(values["re"], values["im"], depth, "hf-result")


def parse_hf_journal(text: str) -> Location:
    """A Heaton Fractal hunt ``journal.jsonl``: each line a JSON seed with string ``real``
    and ``imaginary`` and a finite ``depthLog10``; a line that is not one (a torn last
    write, NaN) is skipped. The choice among seeds is ``hf_journal``'s."""
    seeds: list[tuple[str, str, float]] = []
    for line in _lines(text):
        try:
            entry = _json(line)
            real, imaginary, depth = entry["real"], entry["imaginary"], entry["depthLog10"]
            if not (isinstance(real, str) and isinstance(imaginary, str)):
                continue
            seeds.append((real, imaginary, _finite(_number(depth, "depthLog10"), "depthLog10")))
        except (ValueError, KeyError, TypeError):
            continue
    return hf_journal(seeds)


def hf_journal(seeds: list[tuple[str, str, float]]) -> Location:
    """The deepest of a hunt's (real, imaginary, depthLog10) seeds, the latest among
    equals -- where the hunt got to."""
    best: tuple[str, str, float] | None = None
    for seed in seeds:
        if best is None or seed[2] >= best[2]:
            best = seed
    if best is None:
        raise ValueError("no seed in the journal")
    return hf_seed(best[0], best[1], best[2], "hf-journal")


# ---- helpers ------------------------------------------------------------------------


def _lines(text: str) -> list[str]:
    text = text.removeprefix("\ufeff")
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _word(s: str) -> str:
    """Text up to the first space or tab."""
    cuts = [i for i in (s.find(" "), s.find("\t")) if i >= 0]
    return s[: min(cuts)] if cuts else s


def _first_of(s: str, separators: str) -> int:
    cuts = [s.find(c) for c in separators if c in s]
    return min(cuts) if cuts else -1


def _center(text: str) -> str:
    return decimal_text.positional(text)


def _nonzero(text: str | None) -> bool:
    if text is None:
        return False
    _, digits, _ = decimal_text.scan(text)
    return digits != 0


def _equals(text: str, value: int) -> bool:
    negative, digits, net_exponent = decimal_text.scan(text)
    if negative:
        return False
    scale: int = 10 ** abs(net_exponent)
    return digits * scale == value if net_exponent >= 0 else digits == value * scale


def _whole(text: str, name: str) -> int:
    negative, digits, net_exponent = decimal_text.scan(text)
    scale: int = 10 ** abs(net_exponent)
    if net_exponent >= 0:
        value = digits * scale
    else:
        value, remainder = divmod(digits, scale)
        if remainder:
            raise ValueError(f"{name} must be a whole number: {text!r}")
    if negative or value < 1:
        raise ValueError(f"{name} must be positive: {text!r}")
    if value > MAX_BUDGET:
        raise ValueError(f"{name} is too large: {text!r}")
    return value


def _budget_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_BUDGET:
        raise ValueError(f"maxIterationsOverride must be a positive integer, got {value!r}")
    return value


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return value


def _ordered(warnings: set[str]) -> tuple[str, ...]:
    return tuple(code for code in WARNINGS if code in warnings)


def _group(settings: dict[str, Any], key: str) -> dict[str, Any]:
    """A settings group, or an empty one: HF decodes each group on its own."""
    group = settings.get(key)
    return group if isinstance(group, dict) else {}


def _json(text: str) -> Any:
    """json.loads without the non-JSON constants NaN and Infinity (HF's decoder refuses them)."""

    def refuse(constant: str) -> Any:
        raise ValueError(f"not JSON: {constant}")

    return json.loads(text, parse_constant=refuse)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number, got {value!r}")  # noqa: TRY004 -- a bad file
    try:
        return float(value)
    except OverflowError:
        raise ValueError(f"{name} is out of range: {value!r}") from None


def _json_number(obj: dict[str, Any], key: str) -> float:
    return _finite(_number(obj.get(key), key), key)


def _json_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise ValueError(f"a Heaton Fractal preset needs settings.location.{key}")  # noqa: TRY004
    return value


# ---- the TOML subset Fraktaler-3 writes -------------------------------------------

_Scalar = str | bool | tuple[str]  # strings; booleans; numbers as ("source text",)


def _text(value: _Scalar) -> str:
    """A string's value, or a number's source text."""
    if isinstance(value, tuple):
        return value[0]
    if isinstance(value, str):
        return value
    raise ValueError(f"expected a string or a number, got {value!r}")


def _scalar(value: _Scalar | None) -> str | None:
    return None if value is None or isinstance(value, bool) else _text(value)


def _toml_subset(text: str) -> dict[str, _Scalar]:
    """``[section]`` headers, ``key = value`` with dotted keys, ``#`` comments, basic and
    literal strings -- single-line, and the multi-line forms F3 writes for long
    coordinates (a triple quote, then chunks ending in a line-ending backslash) --
    numbers (``_`` separators dropped), booleans. Anything else -- arrays, inline tables,
    dates, the keys of ``[[array tables]]`` -- is skipped. Keys are case-insensitive; a
    later duplicate wins."""
    values: dict[str, _Scalar] = {}
    section: str | None = ""
    lines = _lines(text)
    i = 0
    while i < len(lines):
        s = lines[i].strip(" \t")
        i += 1
        if not s or s.startswith("#"):
            continue
        if s.startswith("["):
            if s.startswith("[["):
                section = None  # an array of tables: not a location's
                continue
            close = s.find("]")
            section = s[1:close].strip(" \t").lower() if close > 0 else None
            continue
        cut = s.find("=")
        if cut <= 0:
            continue
        key = s[:cut].strip(" \t").lower()
        rest = s[cut + 1 :].strip(" \t")
        if rest.startswith(('"""', "'''")):
            parsed, i = _toml_multiline(rest, lines, i)
        else:
            parsed = _toml_value(rest)
        if parsed is not None and section is not None:
            values[f"{section}.{key}" if section else key] = parsed
    return values


def _toml_multiline(rest: str, lines: list[str], i: int) -> tuple[_Scalar | None, int]:
    """A multi-line string opened on this line; returns it and the next line's index.
    The closer is the first unescaped triple delimiter (a basic string's backslash
    escapes are stepped over), and up to two more delimiter characters right before it
    belong to the value. The newline right after the opener is dropped; in a basic
    string a backslash at the end of a line removes itself, the newline and the
    whitespace that follows."""
    delimiter = rest[:3]
    content = rest[3:]
    close = _closer(content, delimiter)
    while close < 0 and i < len(lines):
        content += "\n" + lines[i]
        i += 1
        close = _closer(content, delimiter)
    if close < 0 or not _only_comment(content[close + 3 :]):
        return None, i
    raw = content[:close].removeprefix("\n")
    if delimiter == "'''":
        return raw, i
    out = []
    j = 0
    while j < len(raw):
        c = raw[j]
        if c == "\\":
            k = j + 1
            while k < len(raw) and raw[k] in " \t":
                k += 1
            if k < len(raw) and raw[k] == "\n":  # a line-ending backslash
                while k < len(raw) and raw[k] in " \t\n":
                    k += 1
                j = k
                continue
            if j + 1 < len(raw):
                out.append({"n": "\n", "t": "\t"}.get(raw[j + 1], raw[j + 1]))
                j += 2
                continue
        out.append(c)
        j += 1
    return "".join(out), i


def _closer(content: str, delimiter: str) -> int:
    """Where the closing delimiter starts in ``content``, or -1: the first run of three to
    five delimiter characters not escaped by a backslash (basic strings only), whose
    last three close the string."""
    quote = delimiter[0]
    j = 0
    while j < len(content):
        c = content[j]
        if c == "\\" and quote == '"':
            j += 2
            continue
        if content.startswith(delimiter, j):
            run = 3
            while j + run < len(content) and content[j + run] == quote and run < 5:
                run += 1
            return j + run - 3
        j += 1
    return -1


def _toml_value(s: str) -> _Scalar | None:
    if s.startswith('"'):
        out = []
        i = 1
        while i < len(s):
            c = s[i]
            if c == "\\" and i + 1 < len(s):
                out.append({"n": "\n", "t": "\t"}.get(s[i + 1], s[i + 1]))
                i += 2
                continue
            if c == '"':
                return "".join(out) if _only_comment(s[i + 1 :]) else None
            out.append(c)
            i += 1
        return None
    if s.startswith("'"):
        close = s.find("'", 1)
        return s[1:close] if close > 0 and _only_comment(s[close + 1 :]) else None
    token = s.split("#", 1)[0].strip(" \t")
    if token in ("true", "false"):
        return token == "true"
    token = token.replace("_", "")
    try:
        decimal_text.scan(token)
    except ValueError:
        return None  # arrays, inline tables, dates, inf/nan: not a location's
    return (token,)


def _only_comment(rest: str) -> bool:
    rest = rest.strip(" \t")
    return not rest or rest.startswith("#")
