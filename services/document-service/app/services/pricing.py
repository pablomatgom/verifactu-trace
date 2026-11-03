from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


@dataclass
class LineData:
    """A line of any document, with what is needed to price it."""

    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal


def _round(amount: Decimal) -> Decimal:
    """Round to cents the way invoices do: half up, not the banker's rounding of round()."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_totals(lines: list[LineData]) -> tuple[Decimal, Decimal, Decimal]:
    """Return (net, vat, total). VAT is rounded per line so the totals add up to the lines."""
    net = Decimal("0.00")
    vat = Decimal("0.00")
    for line in lines:
        line_net = _round(line.quantity * line.unit_price)
        net += line_net
        vat += _round(line_net * line.vat_rate / 100)
    return net, vat, net + vat
