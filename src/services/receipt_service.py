"""Payment-receipt PDFs sent to parents over WhatsApp.

A payment is recorded in the SaaS, the SaaS pushes the details to the bot
(/payment-receipt), and this module renders a branded PDF receipt, uploads it to
object storage (R2), and returns a presigned link for delivery.
"""
import os
from datetime import datetime, timezone

from config import make_s3_client, Config as AppConfig
from services.invoice_service import SCHOOL_INFO
from utils.logger import setup_logger

logger = setup_logger(__name__)

s3 = make_s3_client()
bucket_name = AppConfig.RECEIPT_S3_BUCKET

_INK = (31, 41, 51)        # near-black text
_MUTE = (123, 135, 148)    # muted grey labels
_GREEN = (30, 132, 73)     # "paid" accent
_LINE = (225, 229, 234)    # hairline rules
_NAVY = (11, 42, 74)       # school name


def _money(currency, amount):
    try:
        return f"{currency}{float(amount):,.2f}"
    except (TypeError, ValueError):
        return f"{currency}{amount}"


def generate_receipt_pdf(data, output_path, extra_log=None):
    """Render a branded payment receipt to output_path. Returns the path.

    data keys: student_name, student_id, student_class, school_name, school_address,
    reference, date, currency, amount, items [{description, amount}], method,
    served_by, balance_after.
    """
    extra_log = extra_log or {}
    try:
        from fpdf import FPDF
    except ImportError as e:
        logger.error(f"fpdf2 not available: {e}", extra=extra_log)
        raise Exception("PDF generation dependencies not available")

    currency = data.get("currency") or "$"
    date_str = data.get("date") or datetime.now(timezone.utc).strftime("%d %b %Y")
    school_name = data.get("school_name") or SCHOOL_INFO.get("name", "Shining Smiles College")
    W = 210
    M = 16  # left/right margin

    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(M, 12, M)          # so line breaks return to the same left edge
    pdf.set_auto_page_break(auto=False)  # single page

    def rule(y, x0=M, x1=W - M):
        pdf.set_draw_color(*_LINE)
        pdf.set_line_width(0.3)
        pdf.line(x0, y, x1, y)

    def label(txt, x, y):
        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(*_MUTE)
        pdf.cell(0, 4, txt.upper(), ln=False)

    # ---- Header: school identity (left) + receipt meta (right) ----
    logo = "static/school_logo.png"
    if os.path.exists(logo):
        pdf.image(logo, x=M, y=14, w=22)
    tx = M + 27
    pdf.set_xy(tx, 14)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*_NAVY)
    pdf.cell(110, 7, school_name, ln=True)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*_INK)
    for line in [data.get("school_address"),
                 f"Tel: {SCHOOL_INFO.get('tel', '')}",
                 f"Email: {SCHOOL_INFO.get('email_admin', '')}"]:
        if line and str(line).strip():
            pdf.set_x(tx)
            pdf.cell(110, 4.6, str(line), ln=True)

    pdf.set_xy(W - M - 70, 14)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*_INK)
    pdf.cell(70, 7, "PAYMENT RECEIPT", ln=True, align="R")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_x(W - M - 70)
    pdf.cell(70, 5, f"Receipt No: {data.get('reference', '-')}", ln=True, align="R")
    pdf.set_x(W - M - 70)
    pdf.cell(70, 5, f"Date: {date_str}", ln=True, align="R")

    rule(46)

    # ---- Prominent amount paid ----
    pdf.set_xy(M, 58)
    pdf.set_font("Helvetica", "B", 19)
    pdf.set_text_color(*_GREEN)
    pdf.cell(0, 10, f"{_money(currency, data.get('amount', 0))} paid", ln=True)
    pdf.set_x(M)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTE)
    pdf.cell(0, 5, f"on {date_str}", ln=True)

    # ---- Student / billed-to block ----
    y = 94
    label("Student", M, y)
    label("Class", W / 2, y)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*_INK)
    pdf.set_xy(M, y + 4)
    pdf.cell(90, 6, data.get("student_name", "-"), ln=False)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(W / 2, y + 4)
    pdf.cell(80, 6, data.get("student_class") or "-", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_MUTE)
    pdf.set_xy(M, y + 11)
    pdf.cell(90, 5, f"Student ID: {data.get('student_id', '-')}", ln=True)

    # ---- Line items ----
    y = 132
    pdf.set_xy(M, y)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*_NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(W - 2 * M - 40, 8, "  Description", fill=True, ln=False)
    pdf.cell(40, 8, "Amount  ", fill=True, ln=True, align="R")

    pdf.set_text_color(*_INK)
    items = data.get("items") or [{"description": "Payment received", "amount": data.get("amount", 0)}]
    for it in items:
        pdf.set_font("Helvetica", "", 9.5)
        pdf.cell(W - 2 * M - 40, 7.5, "  " + str(it.get("description", "Payment")), border="B")
        pdf.cell(40, 7.5, _money(currency, it.get("amount", 0)) + "  ", border="B", ln=True, align="R")

    # ---- Total ----
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(W - 2 * M - 40, 9, "  TOTAL PAID", ln=False)
    pdf.set_text_color(*_GREEN)
    pdf.cell(40, 9, _money(currency, data.get("amount", 0)) + "  ", ln=True, align="R")
    pdf.set_text_color(*_INK)
    if data.get("balance_after") is not None:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(W - 2 * M - 40, 6.5, "  Outstanding balance", ln=False)
        pdf.cell(40, 6.5, _money(currency, data.get("balance_after")) + "  ", ln=True, align="R")

    # ---- Payment details ----
    pdf.ln(14)
    py = pdf.get_y()
    rule(py)
    py += 4
    label("Payment Method", M, py)
    label("Served By", W / 2, py)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_INK)
    pdf.set_xy(M, py + 4)
    pdf.cell(90, 6, (data.get("method") or "-").title(), ln=False)
    pdf.set_xy(W / 2, py + 4)
    pdf.cell(80, 6, data.get("served_by") or "-", ln=True)

    # ---- Footer: 'official receipt' note, then ongooo logo | website at the bottom ----
    pdf.set_y(-28)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*_MUTE)
    pdf.cell(0, 4, "Official computer-generated receipt - thank you for your payment.", align="C")

    pdf.set_y(-22)
    logo_w = 18
    site = "www.ongororo.com"
    pdf.set_font("Helvetica", "", 9)
    site_text = "  |  " + site
    tw = pdf.get_string_width(site_text)
    fy = pdf.get_y()
    x0 = (W - (logo_w + tw)) / 2
    brand = "static/official_logo.png"
    if os.path.exists(brand):
        try:
            pdf.image(brand, x=x0, y=fy, w=logo_w)
        except Exception as e:
            logger.warning(f"footer logo failed: {e}", extra=extra_log)
    pdf.set_xy(x0 + logo_w, fy + logo_w / 2 - 2.5)
    pdf.set_text_color(*_MUTE)
    pdf.cell(tw, 5, site_text)

    pdf.output(output_path)
    return output_path


def upload_and_sign(local_path, reference, extra_log=None):
    """Upload the receipt to R2 and return a presigned GET url (valid ~1h)."""
    extra_log = extra_log or {}
    key = f"receipts/{reference}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
    s3.upload_file(local_path, bucket_name, key, ExtraArgs={"ContentType": "application/pdf"})
    url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket_name, "Key": key}, ExpiresIn=3600)
    logger.info(f"Receipt uploaded: s3://{bucket_name}/{key}", extra=extra_log)
    return url
