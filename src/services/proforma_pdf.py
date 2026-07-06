"""Pro-forma (quotation) invoice PDF for an upcoming term.

Mirrors the (paused) billed-invoice layout — school letterhead, bill-to,
line-items table, banking details, and the authorized digital stamp — but as a
forward PRO-FORMA a parent hands their employer/sponsor. Keeps the ongooo footer.
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from services.invoice_service import SCHOOL_INFO, BRANCH_ADDRESSES, create_digital_stamp

VALIDITY_DAYS = 5


def _money(amt):
    try:
        return f"${Decimal(str(amt)):,.2f}"
    except Exception:
        return f"${amt}"


def generate_proforma_pdf(data, output_path):
    """data: student_name, student_id, grade_label, term_label, currency,
    items [{name, amount}], total, reference. Returns output_path."""
    from fpdf import FPDF

    issued = datetime.now(timezone.utc)
    issued_str = issued.strftime("%d %b %Y")
    valid_until = (issued + timedelta(days=VALIDITY_DAYS)).strftime("%d %b %Y")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)  # single page; footer is pinned to the bottom

    # --- Header: logo + school identity ---
    logo = "static/school_logo.png"
    if os.path.exists(logo):
        pdf.image(logo, x=10, y=10, w=30)
        hx = 50
    else:
        hx = 10
    pdf.set_xy(hx, 10)
    pdf.set_font("Helvetica", "B", 16); pdf.set_text_color(0, 0, 139)
    pdf.cell(0, 6, SCHOOL_INFO["name"], ln=True)
    pdf.set_xy(hx, 18); pdf.set_font("Helvetica", "", 9); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 5, BRANCH_ADDRESSES.get("default", "Harare, Zimbabwe"), ln=True)
    pdf.set_xy(hx, 23)
    pdf.cell(0, 5, f"Email: {SCHOOL_INFO['email_info']} | {SCHOOL_INFO['email_admin']}", ln=True)
    pdf.set_xy(hx, 28)
    pdf.cell(0, 5, f"Tel: {SCHOOL_INFO['tel']}", ln=True)
    pdf.ln(20)

    # --- Title ---
    pdf.set_font("Helvetica", "B", 18); pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, "PRO-FORMA INVOICE", ln=True, align="C")
    pdf.ln(5)

    # --- Ref / date / validity ---
    y = pdf.get_y()
    pdf.set_xy(10, y); pdf.set_font("Helvetica", "B", 11)
    pdf.cell(30, 6, "Ref No:", 0, 0)
    pdf.set_font("Helvetica", "", 11); pdf.cell(65, 6, data.get("reference", "-"), 0, 0)
    pdf.set_font("Helvetica", "B", 11); pdf.cell(0, 6, f"Date: {issued_str}", 0, 1, "R")
    pdf.set_xy(10, pdf.get_y()); pdf.set_font("Helvetica", "B", 11)
    pdf.cell(30, 6, "Term:", 0, 0)
    pdf.set_font("Helvetica", "", 11); pdf.cell(65, 6, data.get("term_label", ""), 0, 0)
    pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(183, 121, 31)
    pdf.cell(0, 6, f"Valid until: {valid_until}", 0, 1, "R")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(8)

    # --- Bill to ---
    pdf.set_font("Helvetica", "B", 11); pdf.cell(0, 6, "Bill To:", 0, 1)
    pdf.set_font("Helvetica", "", 10); pdf.cell(35, 6, "Parent/Guardian of ", 0, 0)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(0, 6, data.get("student_name", "-"), 0, 1)
    pdf.set_font("Helvetica", "", 10); pdf.cell(20, 6, "Student ID: ", 0, 0)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(0, 6, data.get("student_id", "-"), 0, 1)
    pdf.set_font("Helvetica", "", 10); pdf.cell(20, 6, "Class: ", 0, 0)
    pdf.set_font("Helvetica", "B", 10); pdf.cell(0, 6, data.get("grade_label", "-"), 0, 1)
    pdf.ln(8)

    # --- Line items (Description | Amount) ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(200, 220, 255); pdf.set_draw_color(100, 100, 100)
    pdf.cell(140, 8, "DESCRIPTION", 1, 0, "L", True)
    pdf.cell(40, 8, f"AMOUNT ({SCHOOL_INFO['currency']})", 1, 1, "R", True)
    pdf.set_font("Helvetica", "", 10)
    for it in (data.get("items") or []):
        pdf.cell(140, 8, f"  {it.get('name', 'Fee')}", 1, 0, "L")
        pdf.cell(40, 8, _money(it.get("amount", 0)), 1, 1, "R")
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(140, 8, "TOTAL DUE:", 1, 0, "R")
    pdf.cell(40, 8, _money(data.get("total", 0)), 1, 1, "R")
    pdf.ln(10)

    # --- Banking details ---
    pdf.set_font("Helvetica", "B", 11); pdf.cell(0, 6, "Payment Details:", 0, 1)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, f"Bank Name: {SCHOOL_INFO['bank_name']}", 0, 1)
    pdf.cell(0, 5, f"Account Name: {SCHOOL_INFO['account_name']}", 0, 1)
    pdf.cell(0, 5, f"Account Number: {SCHOOL_INFO['account_number']}", 0, 1)
    pdf.cell(0, 5, f"Reference: {data.get('student_id', '')}", 0, 1)
    pdf.ln(12)

    # --- Authorization + digital stamp ---
    stamp_y = pdf.get_y()
    pdf.set_font("Helvetica", "I", 9); pdf.cell(0, 5, "Authorized by:", 0, 1)
    create_digital_stamp(pdf, 10, stamp_y + 5, issued_str)
    pdf.ln(45)

    # --- Footer: pro-forma note + ongooo trademark (kept) ---
    pdf.set_y(-28)
    pdf.set_font("Helvetica", "I", 7.5); pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 4, "Pro-forma estimate for the upcoming term - subject to final billing. "
                         "Valid for company/sponsor reimbursement.", align="C")
    pdf.set_y(-20)
    W, site, lw = 210, "www.ongororo.com", 18
    pdf.set_font("Helvetica", "", 9); st = "  |  " + site
    tw = pdf.get_string_width(st); fy = pdf.get_y(); x0 = (W - (lw + tw)) / 2
    brand = "static/official_logo.png"
    if os.path.exists(brand):
        pdf.image(brand, x=x0, y=fy, w=lw)
    pdf.set_xy(x0 + lw, fy + lw / 2 - 2.5); pdf.set_text_color(120, 120, 120)
    pdf.cell(tw, 5, st)

    pdf.output(output_path)
    return output_path
