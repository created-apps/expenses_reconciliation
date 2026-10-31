from datetime import date, datetime

from pydantic import BaseModel, Field


class CycleCreate(BaseModel):
    label: str | None = Field(default=None, max_length=100)


class CycleOut(BaseModel):
    id: str
    label: str | None
    status: str
    statement_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    matched_lines: int | None = None
    total_lines: int | None = None
    open_items: int | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class FileCounts(BaseModel):
    """Files in a cycle by what they are (duplicates are counted separately)."""

    statement: int = 0
    invoices: int = 0
    ignored: int = 0
    duplicates: int = 0
    amazon_reports: int = 0
    zips: int = 0
    total: int = 0


class CycleDetail(CycleOut):
    files: FileCounts
    last_exported_at: datetime | None = None
    edited_since_export: bool = False  # exported before, and edited since (the Excel is out of date)


class FileOut(BaseModel):
    id: str
    cycle_id: str
    kind: str
    original_name: str
    size_bytes: int | None = None
    mime_type: str | None = None
    parent_file_id: str | None = None
    status: str
    note: str | None = None
    error: str | None = None
    has_copy: bool = False  # false for duplicates: the bytes are stored once, under the first file
    created_at: datetime


class RejectedFile(BaseModel):
    name: str
    message: str


class UploadResponse(BaseModel):
    files: list[FileOut]
    rejected: list[RejectedFile]


class JobOut(BaseModel):
    status: str  # running | done | failed
    progress: int | None = None
    message: str | None = None


class StatementLineOut(BaseModel):
    id: str
    ser_no: str
    txn_date: date
    description: str
    card_last4: str | None = None
    foreign_amount_minor: int | None = None
    foreign_currency: str | None = None
    amount_paise: int  # always positive; is_credit marks credits
    is_credit: bool


class StatementSummaryOut(BaseModel):
    """The figures the statement prints on page 1 (paise)."""

    previous_paise: int | None = None
    purchases_paise: int | None = None
    credits_paise: int | None = None
    total_due_paise: int | None = None


class StatementCheckOut(BaseModel):
    lines: int
    debits_paise: int
    credits_paise: int
    printed_debits_paise: int | None = None
    printed_credits_paise: int | None = None
    debits_ok: bool
    credits_ok: bool
    debits_difference_paise: int | None = None  # lines read minus printed
    credits_difference_paise: int | None = None
    cards: list[str]
    ok: bool
    problems: list[str]


class StatementOut(BaseModel):
    status: str
    statement_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    summary: StatementSummaryOut
    job: JobOut | None = None
    check: StatementCheckOut | None = None
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    lines: list[StatementLineOut]


class InvoiceEntryOut(BaseModel):
    """One row of the Invoices step: an invoice, or a file that has none (duplicate, ignored, unread...).
    Money is in minor units of `currency` (paise for INR, cents for USD)."""

    key: str
    file_id: str
    file_name: str
    file_kind: str
    file_status: str
    file_note: str | None = None
    mime_type: str | None = None
    has_copy: bool = False
    can_restore: bool = False  # a file set aside with "Not an invoice" can be brought back
    state: str  # ok | needs_check | pending | failed | duplicate | ignored | unread
    invoice_id: str | None = None
    block_index: int | None = None
    vendor_key: str | None = None
    vendor_name: str | None = None
    invoice_no: str | None = None
    order_id: str | None = None
    invoice_date: date | None = None
    order_date: date | None = None
    currency: str | None = None
    total_minor: int | None = None
    is_credit_note: bool = False
    source: str | None = None
    problems: list[str] = []
    duplicate_of_name: str | None = None


class InvoiceCountsOut(BaseModel):
    files: int  # invoice files in the list (including duplicates and ignored)
    unread: int
    invoices: int  # read invoices (ok or needs check)
    pending: int  # images and scans waiting to be read by the vision model
    needs_check: int
    failed: int
    duplicate_files: int  # byte-identical copies found at upload
    duplicate_invoices: int  # same vendor + number + total as an earlier invoice
    ignored: int


class VendorOut(BaseModel):
    key: str
    name: str


class InvoicesOut(BaseModel):
    status: str
    job: JobOut | None = None
    counts: InvoiceCountsOut
    vendors: list[VendorOut]
    entries: list[InvoiceEntryOut]


class VendorCreate(BaseModel):
    name: str = Field(max_length=200)
    # How the vendor appears on the card statement, when that differs from its name (for example "OPENAI.COM").
    statement_text: str | None = Field(default=None, max_length=200)


class VendorOut(BaseModel):
    key: str
    name: str


class InvoicePatch(BaseModel):
    """Fields a person can correct; only the ones sent are changed (null clears a field)."""

    vendor_key: str | None = None
    invoice_no: str | None = Field(default=None, max_length=100)
    order_id: str | None = Field(default=None, max_length=100)
    invoice_date: date | None = None
    order_date: date | None = None
    currency: str | None = None
    total_minor: int | None = None


class StatusCountOut(BaseModel):
    status: str
    count: int
    amount_paise: int  # signed: debits positive, credits negative


class MatchSummaryOut(BaseModel):
    ran: bool  # false until matching has run once
    total: int  # statement lines
    statuses: list[StatusCountOut]  # always the 8 statuses, in a fixed order
    job: JobOut | None = None  # the matching run: running | done | failed


class InvoiceRefOut(BaseModel):
    """An invoice as shown on a statement line or in the unused list. Money in minor units of `currency`."""

    id: str
    file_id: str
    file_name: str
    vendor_key: str | None = None
    vendor_name: str | None = None
    invoice_no: str | None = None
    order_id: str | None = None
    invoice_date: date | None = None
    order_date: date | None = None
    currency: str
    total_minor: int | None = None
    is_credit_note: bool = False
    needs_check: bool = False
    linked_by: str | None = None  # who attached it by hand; null when the system did


class ComparisonOut(BaseModel):
    attached_sum_paise: int
    difference_paise: int  # charge minus attached sum
    state: str  # none | matches | differs
    needs_note: bool  # invoices are attached and the difference is not zero: it needs a note
    note_missing: bool  # needs_note, and the note is still the system's own (or empty): saving is refused


class ForeignOut(BaseModel):
    amount_minor: int
    currency: str


class TransactionOut(BaseModel):
    id: str
    ser_no: str
    txn_date: date
    description: str
    card_last4: str | None = None
    vendor_key: str | None = None
    vendor_name: str | None = None
    foreign: ForeignOut | None = None
    amount_paise: int  # always positive; is_credit marks credits
    is_credit: bool
    status: str | None = None
    note: str = ""
    updated_by: str | None = None
    updated_at: datetime | None = None
    invoices: list[InvoiceRefOut]  # attached
    suggestions: list[InvoiceRefOut]  # offered by a Review, not attached
    comparison: ComparisonOut


class TransactionsOut(BaseModel):
    total: int  # every line in the reconciliation
    shown: int  # lines left after the filters
    vendors: list[VendorOut]  # vendors present on the lines (for the filter list)
    cards: list[str]
    items: list[TransactionOut]


class ResolveIn(BaseModel):
    """What a person does to one line. Anything left out stays as it is. `preview` changes nothing: it
    returns the line as it would be, so the drawer can show the new sum and difference."""

    attach_invoice_ids: list[str] = []
    detach_invoice_ids: list[str] = []
    status: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    preview: bool = False


class ExportSummaryOut(BaseModel):
    """What the Export step shows before the download (money in paise)."""

    sheet_name: str  # the month sheet, for example "June 2026"
    file_name: str
    sheets: list[str]
    lines: int
    statuses: list[StatusCountOut]
    needs_review: int  # Review plus Missing invoice
    unused_invoices: int
    debits_paise: int
    printed_debits_paise: int | None = None
    debits_difference_paise: int | None = None  # lines minus printed
    credits_paise: int
    printed_credits_paise: int | None = None
    credits_difference_paise: int | None = None
    totals_ok: bool
    last_exported_at: datetime | None = None
    edited_since_export: bool = False


class UnusedInvoiceOut(InvoiceRefOut):
    reason: str


class UnusedInvoicesOut(BaseModel):
    total: int  # unused invoices in the reconciliation
    items: list[UnusedInvoiceOut]


class AmazonReportFile(BaseModel):
    id: str
    name: str
    has_copy: bool = False


class AmazonGroupOut(BaseModel):
    """One card charge: the card-paid rows with the same Payment Reference ID (paise)."""

    payment_date: date | None = None
    reference: str
    card_last4: str | None = None
    orders: int
    amount_paise: int


class AmazonGiftOut(BaseModel):
    paid_on: date | None = None
    order_id: str | None = None
    amount_paise: int


class AmazonReportOut(BaseModel):
    file: AmazonReportFile | None = None
    rows: int  # every data row read from the report
    unpaid_rows: int  # rows with no payment method (not paid or not shipped): in neither list
    card_last4s: list[str]
    payment_date_from: date | None = None
    payment_date_to: date | None = None
    groups: list[AmazonGroupOut]
    gift: list[AmazonGiftOut]


class AmazonFetchItem(BaseModel):
    """An Amazon order that has no invoice, and the statement charge it was paid in."""

    order_id: str
    payment_date: date | None = None
    amount_paise: int  # the order's total in the report
    group_reference: str
    transaction_id: str
    ser_no: str
    charge_date: date
    charge_amount_paise: int
    description: str


class AmazonCoverageOut(BaseModel):
    """How the uploaded invoices cover the whole report."""

    card_orders: int
    with_invoice: int
    without_invoice: int
    partly_invoiced: int  # have an invoice, but it covers only part of the order (not listed)
    gift_orders: int
    gift_with_invoice: int


class AmazonFetchOut(BaseModel):
    has_report: bool
    matched: bool  # matching has run (the list needs it)
    payment_date_from: date | None = None
    payment_date_to: date | None = None
    coverage: AmazonCoverageOut | None = None
    items: list[AmazonFetchItem]
    total_orders: int
    total_paise: int
    invoices_without_order_id: int  # Amazon invoices whose Order ID is missing or misread (fix them first)


class FileUrl(BaseModel):
    url: str
    expires_in: int
    file_name: str
