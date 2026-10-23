from decimal import Decimal

from paytracker.gst import is_valid_gstin, make_gstin, round_rupee, split_tax


def test_known_gstin_is_valid():
    # Widely published sample GSTIN with a correct checksum.
    assert is_valid_gstin("27AAPFU0939F1ZV")


def test_wrong_check_character_is_invalid():
    assert not is_valid_gstin("27AAPFU0939F1ZW")


def test_malformed_gstin_is_invalid():
    assert not is_valid_gstin("27AAPFU0939F1Z")
    assert not is_valid_gstin("27aapfu0939f1zv")


def test_make_gstin_round_trips():
    gstin = make_gstin("33", "AAKCK4821M")
    assert gstin.startswith("33AAKCK4821M1Z")
    assert is_valid_gstin(gstin)


def test_split_tax_intra_state_halves_rate():
    assert split_tax(Decimal("1000.00"), Decimal("18"), intra_state=True) == {
        "cgst": Decimal("90.00"),
        "sgst": Decimal("90.00"),
        "igst": Decimal("0.00"),
    }


def test_split_tax_inter_state_is_igst():
    assert split_tax(Decimal("1000.00"), Decimal("18"), intra_state=False) == {
        "cgst": Decimal("0.00"),
        "sgst": Decimal("0.00"),
        "igst": Decimal("180.00"),
    }


def test_split_tax_rounds_each_half_to_paise():
    # 2.5% of 10.10 = 0.2525 -> 0.25 each side.
    tax = split_tax(Decimal("10.10"), Decimal("5"), intra_state=True)
    assert tax["cgst"] == tax["sgst"] == Decimal("0.25")


def test_round_rupee_rounds_half_up():
    assert round_rupee(Decimal("100.50")) == Decimal("101")
    assert round_rupee(Decimal("100.49")) == Decimal("100")
