import math

from app.services import analytics as a


def test_simple_return() -> None:
    assert a.simple_return([100, 110], 1) == 0.10000000000000009
    assert a.simple_return([100], 1) is None
    assert a.simple_return([0, 1], 1) is None


def test_volatility_constant_growth_is_zero() -> None:
    closes = [100 * 1.01**i for i in range(30)]
    v = a.volatility(closes, 20)
    assert v is not None and v < 1e-9
    assert a.volatility([1, 2, 3], 20) is None


def test_volatility_alternating() -> None:
    closes = [100, 110] * 15
    v = a.volatility(closes, 20, annualize=False)
    assert v is not None and math.isclose(v, abs(math.log(1.1)), rel_tol=0.1)


def test_rsi_bounds() -> None:
    up = [float(i) for i in range(1, 30)]
    assert a.rsi(up) == 100.0
    down = list(reversed(up))
    assert a.rsi(down) == 0.0
    assert a.rsi([1, 2]) is None


def test_max_drawdown_and_average() -> None:
    assert a.max_drawdown([100, 120, 60, 130]) == -0.5
    assert a.max_drawdown([]) is None
    assert a.average([1, 2, 3]) == 2
    assert a.average([]) is None
