"""GST helpers shared by seeding, invoice generation, and validation."""

import re
from decimal import ROUND_HALF_UP, Decimal

GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_GSTIN_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

PAISE = Decimal("0.01")
RUPEE = Decimal("1")


def gstin_check_char(first14: str) -> str:
    """Return the checksum character for the first 14 characters of a GSTIN."""
    total = 0
    for i, char in enumerate(first14):
        product = _GSTIN_CHARSET.index(char) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARSET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str) -> bool:
    return bool(GSTIN_PATTERN.match(gstin)) and gstin[14] == gstin_check_char(gstin[:14])


def make_gstin(state_code: str, pan: str, entity_number: str = "1") -> str:
    first14 = f"{state_code}{pan}{entity_number}Z"
    return first14 + gstin_check_char(first14)


def round_paise(value: Decimal) -> Decimal:
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def round_rupee(value: Decimal) -> Decimal:
    return value.quantize(RUPEE, rounding=ROUND_HALF_UP)


def split_tax(taxable: Decimal, gst_rate: Decimal, intra_state: bool) -> dict[str, Decimal]:
    """Split GST on a taxable value into CGST/SGST (intra-state) or IGST (inter-state)."""
    zero = Decimal("0.00")
    if intra_state:
        half = round_paise(taxable * gst_rate / 200)
        return {"cgst": half, "sgst": half, "igst": zero}
    return {"cgst": zero, "sgst": zero, "igst": round_paise(taxable * gst_rate / 100)}
