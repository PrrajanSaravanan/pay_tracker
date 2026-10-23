"""Load the fixed seed data. Dev only: it empties every table first."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

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
from paytracker.db.seed_data.company import BRANCHES, COMPANY_PAN, RECEIVED_BY
from paytracker.db.seed_data.history import HISTORY
from paytracker.db.seed_data.purchase_orders import PURCHASE_ORDERS
from paytracker.db.seed_data.vendors import VENDORS
from paytracker.gst import make_gstin, round_paise, round_rupee, split_tax

IST = timezone(timedelta(hours=5, minutes=30))

TABLES = (
    "invoice_line_items",
    "invoices",
    "grn_line_items",
    "goods_receipts",
    "po_line_items",
    "purchase_orders",
    "vendors",
    "company",
)


class SeedRefused(RuntimeError):
    pass


def count_real_invoices(session: Session) -> int:
    """Invoices that came from files or email, i.e. would be lost by reseeding."""
    if session.scalar(text("SELECT to_regclass('invoices')")) is None:
        return 0
    return session.scalar(
        select(func.count()).select_from(Invoice).where(Invoice.source_type != "seed")
    )


def seed(session: Session, force: bool = False) -> None:
    real = count_real_invoices(session)
    if real and not force:
        raise SeedRefused(
            f"{real} non-seed invoice(s) exist and reseeding would delete them. "
            "Pass --force to do it anyway."
        )
    session.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))

    branches = {
        key: Company(gstin=make_gstin(b["state_code"], COMPANY_PAN), **b)
        for key, b in BRANCHES.items()
    }
    vendors = {
        key: Vendor(
            gstin=make_gstin(v["state_code"], v["pan"]),
            **{k: val for k, val in v.items() if k != "items"},
        )
        for key, v in VENDORS.items()
    }
    session.add_all([*branches.values(), *vendors.values()])
    session.flush()

    # History first, so PO-2026-0001.. get the lowest ids.
    for spec in [*HISTORY, *PURCHASE_ORDERS]:
        vendor = vendors[spec["vendor"]]
        branch = branches[spec["branch"]]
        po = _purchase_order(session, spec, vendor, branch)
        if "invoice" in spec:
            session.add(_invoice(spec["invoice"], po, vendor, branch))

    session.commit()


def _purchase_order(session: Session, spec: dict, vendor: Vendor, branch: Company) -> PurchaseOrder:
    catalogue = VENDORS[spec["vendor"]]["items"]
    po = PurchaseOrder(
        po_number=spec["po_number"],
        vendor_id=vendor.id,
        company_id=branch.id,
        po_date=spec["po_date"],
        expected_delivery_date=spec["expected_delivery_date"],
        place_of_supply_state_code=branch.state_code,
        status=spec["status"],
        notes=spec["notes"],
    )
    by_code = {}
    for number, (code, qty) in enumerate(spec["lines"], start=1):
        description, hsn_sac, unit, price, rate = catalogue[code]
        by_code[code] = POLineItem(
            line_number=number,
            description=description,
            hsn_sac=hsn_sac,
            quantity=Decimal(qty),
            unit=unit,
            unit_price=Decimal(price),
            gst_rate=Decimal(rate),
        )
        po.lines.append(by_code[code])
    session.add(po)
    session.flush()

    for g in spec["grns"]:
        grn = GoodsReceipt(
            grn_number=g["grn_number"],
            po_id=po.id,
            received_date=g["received_date"],
            received_by=RECEIVED_BY[spec["branch"]],
            vendor_challan_number=g["challan"],
            notes=g.get("notes"),
        )
        for code, qty in g["lines"].items():
            received, rejected = qty if isinstance(qty, tuple) else (qty, 0)
            grn.lines.append(
                GRNLineItem(
                    po_line_item_id=by_code[code].id,
                    quantity_received=Decimal(received),
                    quantity_rejected=Decimal(rejected),
                )
            )
        session.add(grn)
    return po


def _invoice(spec: dict, po: PurchaseOrder, vendor: Vendor, branch: Company) -> Invoice:
    """A historical invoice billing the whole PO at PO prices, already approved and posted."""
    intra = vendor.state_code == po.place_of_supply_state_code
    invoice_date: date = spec["date"]
    due_date = invoice_date + timedelta(days=vendor.payment_terms_days)

    invoice = Invoice(
        vendor_id=vendor.id,
        company_id=branch.id,
        po_id=po.id,
        status="paid" if spec["paid"] else "posted",
        invoice_number=spec["number"],
        invoice_date=invoice_date,
        po_number_on_invoice=po.po_number,
        vendor_name_on_invoice=vendor.legal_name,
        vendor_gstin_on_invoice=vendor.gstin,
        buyer_gstin_on_invoice=branch.gstin,
        place_of_supply_state_code=po.place_of_supply_state_code,
        currency="INR",
        cess_amount=Decimal("0.00"),
        bank_account_name=vendor.bank_account_name,
        bank_account_number=vendor.bank_account_number,
        bank_ifsc=vendor.bank_ifsc,
        source_type="seed",
        decision="approve",
        decision_reasons=["Seed data: historical invoice."],
        approved_by="seed",
        approved_at=datetime.combine(invoice_date + timedelta(days=2), time(10, 0), IST),
        due_date=due_date,
        paid_at=(
            datetime.combine(due_date - timedelta(days=3), time(11, 30), IST)
            if spec["paid"]
            else None
        ),
    )

    totals = dict.fromkeys(("subtotal", "cgst", "sgst", "igst"), Decimal("0.00"))
    for line in po.lines:
        taxable = round_paise(line.quantity * line.unit_price)
        tax = split_tax(taxable, line.gst_rate, intra)
        invoice.lines.append(
            InvoiceLineItem(
                line_number=line.line_number,
                description=line.description,
                hsn_sac=line.hsn_sac,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=line.unit_price,
                discount_amount=Decimal("0.00"),
                taxable_value=taxable,
                gst_rate=line.gst_rate,
                cgst_amount=tax["cgst"],
                sgst_amount=tax["sgst"],
                igst_amount=tax["igst"],
                line_total=taxable + sum(tax.values()),
                po_line_item_id=line.id,
            )
        )
        totals["subtotal"] += taxable
        for key in ("cgst", "sgst", "igst"):
            totals[key] += tax[key]

    exact = sum(totals.values())
    invoice.subtotal = totals["subtotal"]
    invoice.cgst_amount = totals["cgst"]
    invoice.sgst_amount = totals["sgst"]
    invoice.igst_amount = totals["igst"]
    invoice.total_amount = round_rupee(exact)
    invoice.round_off = invoice.total_amount - exact
    return invoice
