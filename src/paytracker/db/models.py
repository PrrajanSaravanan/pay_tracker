"""SQLAlchemy models. See docs/phase1-schema.md for the design rationale."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Money = Numeric(14, 2)
Quantity = Numeric(14, 3)
Rate = Numeric(5, 2)

GSTIN_REGEX = "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
IFSC_REGEX = "^[A-Z]{4}0[A-Z0-9]{6}$"
# Pre- and post-GST 2.0 (Sept 2025) slabs, so historical documents still fit.
GST_RATES = (0, 0.25, 1.5, 3, 5, 12, 18, 28, 40)

PO_STATUSES = ("open", "partially_received", "received", "closed", "cancelled")
INVOICE_STATUSES = (
    "received",
    "extracting",
    "extracted",
    "validating",
    "awaiting_approval",
    "query_sent",
    "escalated",
    "approved",
    "rejected",
    "posted",
    "paid",
    "failed",
)
INVOICE_SOURCES = ("file", "email", "seed")
DECISIONS = ("approve", "vendor_query", "escalate")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {datetime: DateTime(timezone=True)}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def _id() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


class Company(TimestampMixin, Base):
    """One row per GST registration, i.e. per branch: each branch has its own GSTIN."""

    __tablename__ = "company"
    __table_args__ = (
        CheckConstraint(f"gstin ~ '{GSTIN_REGEX}'", name="gstin_format"),
        CheckConstraint("LEFT(gstin, 2) = state_code", name="gstin_state"),
    )

    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(Text)
    gstin: Mapped[str] = mapped_column(String(15), unique=True)
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)


class Vendor(TimestampMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        CheckConstraint(f"gstin ~ '{GSTIN_REGEX}'", name="gstin_format"),
        CheckConstraint("gstin IS NULL OR LEFT(gstin, 2) = state_code", name="gstin_state"),
        CheckConstraint(f"bank_ifsc ~ '{IFSC_REGEX}'", name="ifsc_format"),
        Index("ix_vendors_lower_name", text("lower(name)")),
    )

    id: Mapped[int] = _id()
    name: Mapped[str] = mapped_column(Text)
    legal_name: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True)
    pan: Mapped[str | None] = mapped_column(String(10))
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    bank_account_name: Mapped[str] = mapped_column(Text)
    bank_account_number: Mapped[str] = mapped_column(Text)
    bank_ifsc: Mapped[str] = mapped_column(String(11))
    bank_name: Mapped[str | None] = mapped_column(Text)
    payment_terms_days: Mapped[int] = mapped_column(server_default="30")
    is_active: Mapped[bool] = mapped_column(server_default="true")

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="vendor")


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (CheckConstraint(_in("status", PO_STATUSES), name="status"),)

    id: Mapped[int] = _id()
    po_number: Mapped[str] = mapped_column(Text, unique=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    po_date: Mapped[date]
    expected_delivery_date: Mapped[date | None]
    place_of_supply_state_code: Mapped[str] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3), server_default="INR")
    status: Mapped[str] = mapped_column(Text, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    vendor: Mapped[Vendor] = relationship(back_populates="purchase_orders")
    lines: Mapped[list["POLineItem"]] = relationship(
        back_populates="purchase_order", order_by="POLineItem.line_number"
    )
    goods_receipts: Mapped[list["GoodsReceipt"]] = relationship(back_populates="purchase_order")


class POLineItem(TimestampMixin, Base):
    __tablename__ = "po_line_items"
    __table_args__ = (
        UniqueConstraint("po_id", "line_number"),
        CheckConstraint("hsn_sac ~ '^[0-9]{4,8}$'", name="hsn_sac_format"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(_in("gst_rate", GST_RATES), name="gst_rate"),
    )

    id: Mapped[int] = _id()
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    line_number: Mapped[int]
    description: Mapped[str] = mapped_column(Text)
    hsn_sac: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal] = mapped_column(Quantity)
    unit: Mapped[str] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Rate)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class GoodsReceipt(TimestampMixin, Base):
    __tablename__ = "goods_receipts"

    id: Mapped[int] = _id()
    grn_number: Mapped[str] = mapped_column(Text, unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    received_date: Mapped[date]
    received_by: Mapped[str | None] = mapped_column(Text)
    vendor_challan_number: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="goods_receipts")
    lines: Mapped[list["GRNLineItem"]] = relationship(back_populates="goods_receipt")


class GRNLineItem(TimestampMixin, Base):
    __tablename__ = "grn_line_items"
    __table_args__ = (
        CheckConstraint("quantity_received >= 0", name="quantity_received_non_negative"),
        CheckConstraint(
            "quantity_rejected >= 0 AND quantity_rejected <= quantity_received",
            name="quantity_rejected_range",
        ),
    )

    id: Mapped[int] = _id()
    grn_id: Mapped[int] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True
    )
    po_line_item_id: Mapped[int] = mapped_column(ForeignKey("po_line_items.id"), index=True)
    quantity_received: Mapped[Decimal] = mapped_column(Quantity)
    quantity_rejected: Mapped[Decimal] = mapped_column(Quantity, server_default="0")

    goods_receipt: Mapped[GoodsReceipt] = relationship(back_populates="lines")


class Invoice(TimestampMixin, Base):
    """An invoice as the vendor presented it. Columns are loose on purpose."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(_in("status", INVOICE_STATUSES), name="status"),
        CheckConstraint(_in("source_type", INVOICE_SOURCES), name="source_type"),
        CheckConstraint(_in("decision", DECISIONS), name="decision"),
        # Not unique: duplicates must be stored so they can be escalated.
        Index("ix_invoices_vendor_number", "vendor_id", text("lower(invoice_number)")),
        Index("ix_invoices_vendor_amount_date", "vendor_id", "total_amount", "invoice_date"),
    )

    id: Mapped[int] = _id()
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    # Branch billed, resolved from buyer_gstin_on_invoice. NULL = GSTIN matches no branch.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id"), index=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    status: Mapped[str] = mapped_column(Text, index=True)

    # As printed on the invoice
    invoice_number: Mapped[str | None] = mapped_column(Text)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    po_number_on_invoice: Mapped[str | None] = mapped_column(Text)
    vendor_name_on_invoice: Mapped[str | None] = mapped_column(Text)
    vendor_gstin_on_invoice: Mapped[str | None] = mapped_column(Text)
    buyer_gstin_on_invoice: Mapped[str | None] = mapped_column(Text)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(String(3), server_default="INR")
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    cgst_amount: Mapped[Decimal | None] = mapped_column(Money)
    sgst_amount: Mapped[Decimal | None] = mapped_column(Money)
    igst_amount: Mapped[Decimal | None] = mapped_column(Money)
    cess_amount: Mapped[Decimal | None] = mapped_column(Money)
    round_off: Mapped[Decimal | None] = mapped_column(Money)
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    bank_account_name: Mapped[str | None] = mapped_column(Text)
    bank_account_number: Mapped[str | None] = mapped_column(Text)
    bank_ifsc: Mapped[str | None] = mapped_column(Text)

    # Source and pipeline
    source_type: Mapped[str] = mapped_column(Text)
    source_file_path: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_results: Mapped[list[Any] | None] = mapped_column(JSONB)
    match_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decision: Mapped[str | None] = mapped_column(Text)
    decision_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    workflow_thread_id: Mapped[str | None] = mapped_column(Text, unique=True)
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None]
    due_date: Mapped[date | None]
    paid_at: Mapped[datetime | None]

    vendor: Mapped[Vendor | None] = relationship()
    company: Mapped[Company | None] = relationship()
    purchase_order: Mapped[PurchaseOrder | None] = relationship()
    lines: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice", order_by="InvoiceLineItem.line_number"
    )


class InvoiceLineItem(TimestampMixin, Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (UniqueConstraint("invoice_id", "line_number"),)

    id: Mapped[int] = _id()
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    line_number: Mapped[int]
    description: Mapped[str | None] = mapped_column(Text)
    hsn_sac: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    unit: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    discount_amount: Mapped[Decimal | None] = mapped_column(Money)
    taxable_value: Mapped[Decimal | None] = mapped_column(Money)
    gst_rate: Mapped[Decimal | None] = mapped_column(Rate)
    cgst_amount: Mapped[Decimal | None] = mapped_column(Money)
    sgst_amount: Mapped[Decimal | None] = mapped_column(Money)
    igst_amount: Mapped[Decimal | None] = mapped_column(Money)
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    po_line_item_id: Mapped[int | None] = mapped_column(ForeignKey("po_line_items.id"), index=True)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
