from decimal import Decimal

from app.services.order_service import OrderLineData, calculate_totals


def line(quantity: str, unit_price: str, vat_rate: str = "21") -> OrderLineData:
    return OrderLineData("item", Decimal(quantity), Decimal(unit_price), Decimal(vat_rate))


def test_totals_of_a_single_line():
    net, vat, total = calculate_totals([line("2", "10.00")])

    assert (net, vat, total) == (Decimal("20.00"), Decimal("4.20"), Decimal("24.20"))


def test_totals_add_up_the_lines_with_their_own_vat_rate():
    net, vat, total = calculate_totals([line("1", "100.00", "21"), line("3", "10.00", "10")])

    assert net == Decimal("130.00")
    assert vat == Decimal("24.00")  # 21.00 + 3.00
    assert total == Decimal("154.00")


def test_amounts_are_rounded_half_up_to_cents():
    # 0.5 * 0.01 = 0.005: half up gives 0.01, whereas Python's round() would give 0.00.
    net, _, _ = calculate_totals([line("0.5", "0.01", "0")])

    assert net == Decimal("0.01")


def test_vat_is_rounded_per_line_so_the_totals_match_the_lines():
    # Each line has a VAT of 0.105, which rounds to 0.11: two lines make 0.22, not 0.21.
    _, vat, _ = calculate_totals([line("1", "0.50", "21"), line("1", "0.50", "21")])

    assert vat == Decimal("0.22")
