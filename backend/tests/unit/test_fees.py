from decimal import Decimal

from app.services.trading import compute_fee


def test_fee_minimums_and_rates() -> None:
    assert compute_fee("NASDAQ", Decimal("100")) == Decimal("1.00")  # min $1
    assert compute_fee("NYSE", Decimal("100000")) == Decimal("50.00")  # 0.05 %
    assert compute_fee("KASE", Decimal("10000")) == Decimal("300.00")  # min 300 KZT
    assert compute_fee("KASE", Decimal("1000000")) == Decimal("1500.00")  # 0.15 %
    assert compute_fee("LSE", Decimal("10000")) == Decimal("10.00")  # 0.1 %
