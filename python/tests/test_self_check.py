"""The platform self-check (spec/self-check.md): its embedded data is exactly what the
generator derives from the vectors, every check passes here, a failure is reported
rather than raised, gating fails closed, and a run leaves the orbit cache alone."""

import dataclasses
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from heaton_life import _self_check_data as data
from heaton_life import self_check
from heaton_life.core import bignum
from heaton_life.self_check import NAMES, CheckResult, Scope, passed, run, run_all

REPO = Path(__file__).resolve().parents[2]


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_self_check", REPO / "python" / "tools" / "gen_self_check.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_self_check"] = module
    spec.loader.exec_module(module)
    return module


def test_data_files_are_what_the_generator_derives() -> None:
    """Both ports' embedded answers come from the vectors: a regenerated source vector
    (or a hand edit) fails here until tools/gen_self_check.py is rerun."""
    generator = _generator()
    built = generator.build()
    python_file = REPO / "python" / "src" / "heaton_life" / "_self_check_data.py"
    csharp_file = REPO / "dotnet" / "src" / "HeatonLife.Core" / "SelfCheckData.cs"
    assert python_file.read_text() == generator.render_python(built)
    assert csharp_file.read_text() == generator.render_csharp(built)


def test_every_check_passes() -> None:
    ok, report = run()
    assert ok, report
    assert report.splitlines()[0].startswith("heaton-life ")


def test_names() -> None:
    assert NAMES[0] == "fp-contract"  # first, so the first FAIL is the root cause
    # The same shared checks as the C# port (the generated list both suites assert).
    assert list(NAMES) == ["fp-contract", "numpy-fma", *data.SHARED_NAMES]
    assert len(set(NAMES)) == len(NAMES)
    # The names hosts already know keep their meaning.
    for name in (
        "pcg32",
        "pow10",
        "mergelife-upstream",
        "mandelbrot-t0",
        "center-projection",
        "grayscott-100",
        "reference-orbit",
    ):
        assert name in NAMES
    assert [r.name for r in run_all()] == list(NAMES)


def test_a_failure_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(data.PCG32, "draws", [0, *data.PCG32["draws"][1:]])
    results = {r.name: r for r in run_all()}
    assert not results["pcg32"].passed
    assert results["pcg32"].detail.startswith("draw 0: ")
    assert results["pow10"].passed and results["pow10"].detail == ""

    def boom() -> None:
        raise RuntimeError("the platform is on fire")

    checks = [(n, s, boom if n == "turns" else c) for n, s, c in self_check._CHECKS]
    monkeypatch.setattr(self_check, "_CHECKS", checks)
    turns = next(r for r in run_all() if r.name == "turns")
    assert not turns.passed and turns.detail == "RuntimeError: the platform is on fire"


def test_passed_gates_by_scope() -> None:
    results = run_all()
    assert passed(results, Scope.ALL)
    broken = [dataclasses.replace(r, passed=False) if r.name == "floatexp" else r for r in results]
    assert not passed(broken, Scope.T2)
    assert passed(broken, Scope.T0 | Scope.T1 | Scope.SIMULATIONS)
    missing = [r for r in results if r.name != "julia-t1"]
    assert not passed(missing, Scope.T1)  # a missing check fails closed
    assert passed(missing, Scope.T0)
    contract = [
        dataclasses.replace(r, passed=False) if r.name == "fp-contract" else r for r in results
    ]
    assert not any(passed(contract, scope) for scope in Scope)  # it invalidates everything
    # Results from several runs together: any FAIL for a check fails its scopes.
    failure = next(r for r in contract if r.name == "fp-contract")
    assert not passed([failure, *results], Scope.SIMULATIONS)
    assert not passed([*results, failure], Scope.SIMULATIONS)


def test_numpy_error_state_does_not_fail_the_platform() -> None:
    """The canaries underflow on purpose; a host that asks NumPy to raise on underflow
    still gets a PASS -- error reporting changes no IEEE result."""
    import numpy as np

    with np.errstate(all="raise"):
        results = {r.name: r for r in run_all()}
    assert results["fp-contract"].passed, results["fp-contract"].detail
    assert results["numpy-fma"].passed, results["numpy-fma"].detail


def test_numpy_fma_catches_the_numpy_1_touching_operand_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before 2.0.2, NumPy counted an output that merely touched an input's memory as
    overlapping (numpy#27077) and sent it to a plain C loop, which is unfused unless the
    wheel's compiler contracted it (NumPy 1.26's macOS wheel and Linux GCC builds do
    not). Consecutive large allocations often touch, so renders depended on the
    allocator. Replay that fallback: the check must fail, and must fail as itself, not
    only through a render digest further down."""
    import numpy as np

    fused = np.multiply

    def touches(x: np.ndarray, y: np.ndarray) -> bool:
        x0, y0 = x.ctypes.data, y.ctypes.data
        return x0 == y0 + y.nbytes or y0 == x0 + x.nbytes

    def numpy1_multiply(x: np.ndarray, y: np.ndarray, out: np.ndarray | None = None) -> object:
        if out is None or not (touches(out, x) or touches(out, y)):
            return fused(x, y, out=out)
        xr, xi, yr, yi = x.real.copy(), x.imag.copy(), y.real.copy(), y.imag.copy()
        out.real = xr * yr - xi * yi  # three ufunc calls, three roundings: no fma
        out.imag = xr * yi + xi * yr
        return out

    monkeypatch.setattr(self_check.np, "multiply", numpy1_multiply)
    results = {r.name: r for r in run_all()}
    assert not results["numpy-fma"].passed
    assert "output right" in results["numpy-fma"].detail
    assert results["fp-contract"].passed  # scalar and elementwise real arithmetic is fine


def test_a_run_leaves_the_orbit_cache_alone() -> None:
    bignum.clear_cache()
    host = bignum.reference_orbit("mandelbrot", "-0.75", "0.1", 20.0, 500)
    before = list(bignum._CACHE)
    assert all(r.passed for r in run_all())
    assert list(bignum._CACHE) == before
    assert bignum.reference_orbit("mandelbrot", "-0.75", "0.1", 20.0, 500) is not None
    assert len(host) > 0


def test_results_are_plain_values() -> None:
    result = run_all()[0]
    assert isinstance(result, CheckResult)
    assert result.scope == Scope.ALL and result.milliseconds >= 0.0
