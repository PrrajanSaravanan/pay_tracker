from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from paytracker.db import migrate
from paytracker.db.models import (
    Company,
    GoodsReceipt,
    GRNLineItem,
    Invoice,
    InvoiceLineItem,
    POLineItem,
    PurchaseOrder,
    Vendor,
)
from paytracker.db.seed import SeedRefused, seed
from paytracker.gst import is_valid_gstin, make_gstin


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def summary(session, po_number):
    """po_line_receipt_summary rows for one PO, as {line_number: row}."""
    rows = session.execute(
        text(
            "SELECT s.* FROM po_line_receipt_summary s "
            "JOIN purchase_orders po ON po.id = s.po_id "
            "WHERE po.po_number = :po"
        ),
        {"po": po_number},
    ).mappings()
    return {row["line_number"]: row for row in rows}


def make_vendor(**overrides):
    fields = dict(
        name="Test Vendor",
        gstin=make_gstin("33", "AAAFT1234A"),
        state_code="33",
        bank_account_name="TEST VENDOR",
        bank_account_number="000123456789",
        bank_ifsc="HDFC0000001",
    )
    return Vendor(**{**fields, **overrides})


def assert_rejected(session, obj):
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(obj)
        session.flush()


# --- Seed contents ---------------------------------------------------------


def test_seed_counts(session):
    assert count(session, Company) == 2
    assert count(session, Vendor) == 8
    assert count(session, PurchaseOrder) == 40
    assert count(session, GoodsReceipt) == 41
    assert count(session, Invoice) == 20


def test_seeded_gstins_have_valid_checksums(session):
    gstins = session.scalars(select(Company.gstin).union_all(select(Vendor.gstin))).all()
    assert len(gstins) == 10
    assert all(is_valid_gstin(g) for g in gstins)


def test_po_status_agrees_with_receipts(session):
    rows = session.execute(
        text(
            "SELECT po.po_number, po.status, "
            "  bool_and(s.accepted_qty = s.ordered_qty) AS all_accepted, "
            "  bool_and(s.received_qty = 0) AS none_received "
            "FROM purchase_orders po JOIN po_line_receipt_summary s ON s.po_id = po.id "
            "GROUP BY po.po_number, po.status"
        )
    ).all()
    for po_number, status, all_accepted, none_received in rows:
        if status in ("received", "closed"):
            assert all_accepted, po_number
        elif status == "partially_received":
            assert not all_accepted and not none_received, po_number
        else:  # open, cancelled
            assert none_received, po_number


def test_historical_invoices_add_up(session):
    for inv in session.scalars(select(Invoice)):
        assert inv.subtotal == sum(line.taxable_value for line in inv.lines)
        taxes = inv.cgst_amount + inv.sgst_amount + inv.igst_amount
        assert inv.subtotal + taxes + inv.round_off == inv.total_amount
        assert abs(inv.round_off) <= Decimal("0.50")
        assert inv.total_amount == inv.total_amount.to_integral_value()


def test_tax_type_follows_vendor_and_branch_state(session):
    for inv in session.scalars(select(Invoice)):
        if inv.vendor.state_code == inv.company.state_code:
            assert inv.igst_amount == 0 and inv.cgst_amount == inv.sgst_amount > 0
        else:
            assert inv.cgst_amount == inv.sgst_amount == 0 and inv.igst_amount > 0


def test_same_vendor_gets_different_tax_per_branch(session):
    """Lakshmi Steel (TN) bills the Chennai branch CGST+SGST and the Bengaluru branch IGST."""
    lakshmi = session.scalars(
        select(Invoice).join(Vendor).where(Vendor.name == "Lakshmi Steel Works")
    ).all()
    by_branch = {inv.company.state_code: inv for inv in lakshmi}
    assert by_branch["33"].igst_amount == 0 and by_branch["33"].cgst_amount > 0
    assert by_branch["29"].cgst_amount == 0 and by_branch["29"].igst_amount > 0


def test_known_invoice_total(session):
    # 500 kg x 92.00 @ 5% + 120 rolls x 118.00 @ 18%, inter-state.
    inv = session.scalar(select(Invoice).where(Invoice.invoice_number == "ST/26-27/0164"))
    assert inv.subtotal == Decimal("60160.00")
    assert inv.igst_amount == Decimal("4848.80")
    assert inv.round_off == Decimal("0.20")
    assert inv.total_amount == Decimal("65009.00")


def test_unpaid_balance_for_sharma_traders(session):
    owed = session.scalar(
        select(func.sum(Invoice.total_amount))
        .join(Vendor)
        .where(Vendor.name == "Sharma Traders", Invoice.paid_at.is_(None))
    )
    assert owed == Decimal("65009.00")


# --- Views -----------------------------------------------------------------


def test_partial_receipt(session):
    lines = summary(session, "PO-2026-0025")
    assert (lines[1]["ordered_qty"], lines[1]["accepted_qty"]) == (100, 60)


def test_qc_rejection_reduces_accepted_qty(session):
    toner = summary(session, "PO-2026-0031")[1]
    assert (toner["received_qty"], toner["rejected_qty"], toner["accepted_qty"]) == (20, 3, 17)


def test_multiple_grns_are_summed(session):
    lines = summary(session, "PO-2026-0036")
    assert [lines[n]["accepted_qty"] for n in (1, 2, 3, 4)] == [15, 450, 0, 4]


def test_historical_lines_are_fully_invoiced(session):
    lines = summary(session, "PO-2026-0015")
    assert all(
        row["invoiced_qty"] == row["accepted_qty"] == row["ordered_qty"] for row in lines.values()
    )


def test_unapproved_invoices_do_not_count_as_invoiced(session):
    line = session.scalar(
        select(POLineItem)
        .join(PurchaseOrder)
        .where(PurchaseOrder.po_number == "PO-2026-0021", POLineItem.line_number == 1)
    )
    invoice = Invoice(status="awaiting_approval", source_type="file")
    invoice.lines.append(_invoice_line(line))
    session.add(invoice)
    session.flush()
    assert summary(session, "PO-2026-0021")[1]["invoiced_qty"] == 0

    invoice.status = "approved"
    session.flush()
    assert summary(session, "PO-2026-0021")[1]["invoiced_qty"] == line.quantity


def test_po_totals_view_matches_invoice_before_round_off(session):
    for inv in session.scalars(select(Invoice)):
        view_total = session.scalar(
            text("SELECT total FROM purchase_order_totals WHERE po_id = :id"), {"id": inv.po_id}
        )
        assert view_total == inv.total_amount - inv.round_off


# --- Constraints -----------------------------------------------------------


def test_bad_gstin_format_rejected(session):
    assert_rejected(session, make_vendor(gstin="33ABCDE1234F1Z"))


def test_gstin_state_must_match_state_code(session):
    assert_rejected(session, make_vendor(gstin=make_gstin("29", "AAAFT1234A")))


def test_branch_gstin_state_must_match_state_code(session):
    assert_rejected(
        session, Company(name="Bad", gstin=make_gstin("29", "AAKCK4821M"), state_code="33")
    )


def test_bad_ifsc_rejected(session):
    assert_rejected(session, make_vendor(bank_ifsc="HDFC1000001"))


def test_vendor_without_gstin_allowed(session):
    session.add(make_vendor(gstin=None))
    session.flush()


def test_invalid_gst_rate_rejected(session):
    po = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-2026-0032"))
    assert_rejected(
        session,
        POLineItem(
            po_id=po.id,
            line_number=99,
            description="x",
            hsn_sac="2815",
            quantity=1,
            unit="KGS",
            unit_price=1,
            gst_rate=7,
        ),
    )


def test_rejected_more_than_received_rejected(session):
    grn = session.scalar(select(GoodsReceipt).where(GoodsReceipt.grn_number == "GRN-2026-0033"))
    assert_rejected(
        session,
        GRNLineItem(
            grn_id=grn.id,
            po_line_item_id=grn.lines[0].po_line_item_id,
            quantity_received=5,
            quantity_rejected=6,
        ),
    )


def test_duplicate_invoices_can_be_stored(session):
    vendor = session.scalar(select(Vendor).where(Vendor.name == "Sharma Traders"))
    for _ in range(2):
        session.add(
            Invoice(
                vendor_id=vendor.id,
                invoice_number="ST/26-27/0164",
                status="received",
                source_type="file",
            )
        )
    session.flush()
    dupes = session.scalar(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.vendor_id == vendor.id, Invoice.invoice_number == "ST/26-27/0164")
    )
    assert dupes == 3


# --- Seeding and migrations ------------------------------------------------


def test_seed_is_repeatable(session):
    seed(session)
    assert count(session, PurchaseOrder) == 40
    assert count(session, Invoice) == 20
    first_po = session.scalar(select(PurchaseOrder).where(PurchaseOrder.id == 1))
    assert first_po.po_number == "PO-2026-0001"


def test_seed_refuses_to_delete_real_invoices(session):
    session.add(Invoice(status="received", source_type="email"))
    session.flush()
    with pytest.raises(SeedRefused):
        seed(session)
    assert count(session, Invoice) == 21


def test_migration_downgrades_and_reapplies(db_url):
    migrate.downgrade(db_url)
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT to_regclass('vendors')")) is None
        migrate.upgrade(db_url)
        with Session(engine) as session:
            seed(session)
            assert count(session, Vendor) == 8
    finally:
        engine.dispose()


def _invoice_line(po_line):
    return InvoiceLineItem(line_number=1, quantity=po_line.quantity, po_line_item_id=po_line.id)
