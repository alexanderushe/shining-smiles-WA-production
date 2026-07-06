"""Pro-forma invoice conversational flow (WhatsApp menu 4).

Parent picks the term's fees their employer/sponsor will pay; the bot lists the
available fee items, captures the selection, rate-limits (1 / 7 days per student),
generates a branded pro-forma PDF, and sends it.

The SaaS returns a deterministically ordered item list, so we re-fetch it on the
selection step instead of persisting the list between messages.
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from utils.database import ProformaRequestLog, resolve_school_id, school_scoped_query
from utils.logger import setup_logger
from utils.whatsapp import send_whatsapp_message
from config import make_s3_client, Config as AppConfig
from services.proforma_pdf import generate_proforma_pdf

logger = setup_logger(__name__)

RATE_LIMIT_DAYS = 7


def _fmt_items(items):
    lines = []
    for idx, it in enumerate(items, 1):
        tag = "" if it.get("mandatory") else ""
        lines.append(f"{idx}. {it['name']}  ${Decimal(str(it['amount'])):,.2f}{tag}")
    return "\n".join(lines)


def list_fees(student_id, sms_client):
    """Fetch the pro-forma items and return (message, ok). ok=True means we should
    move to the selection state."""
    data = sms_client.get_proforma(student_id)
    if not data or not data.get("available"):
        reason = (data or {}).get("reason", "")
        if reason == "fees_not_published":
            return ("📋 Fees for the upcoming term aren't published yet. "
                    "Please check back closer to the term.", False)
        if reason == "no_grade":
            return ("⚠️ We couldn't determine the student's grade. "
                    "Please contact _admin@shiningsmilescollege.ac.zw_.", False)
        return ("⚠️ Pro-forma invoices aren't available right now. "
                "Please try again later.", False)

    items = data.get("items", [])
    body = (
        f"🧾 *Pro-forma Invoice — {data.get('term_label', 'Upcoming Term')}*\n"
        f"{data.get('grade_label', '')}\n\n"
        "Reply with the numbers of the fees to include (e.g. *1,3*), "
        "or *ALL* for everything, or *CANCEL*:\n\n"
        f"{_fmt_items(items)}"
    )
    return (body, True)


def _parse_selection(message_body, count):
    m = (message_body or "").strip().lower()
    if m in ("cancel", "menu", "back"):
        return "cancel"
    if m in ("all", "everything"):
        return list(range(count))
    picked = []
    for tok in m.replace(" ", ",").split(","):
        tok = tok.strip()
        if tok.isdigit():
            i = int(tok) - 1
            if 0 <= i < count and i not in picked:
                picked.append(i)
    return picked


def _rate_limited(session, student_id, school_id):
    log = school_scoped_query(session, ProformaRequestLog, school_id).filter(
        ProformaRequestLog.student_id == student_id
    ).order_by(ProformaRequestLog.last_request_date.desc()).first()
    if log and log.last_request_date:
        elapsed = datetime.now(timezone.utc) - log.last_request_date
        if elapsed < timedelta(days=RATE_LIMIT_DAYS):
            nxt = (log.last_request_date + timedelta(days=RATE_LIMIT_DAYS)).strftime("%d %b %Y")
            return nxt
    return None


def _record_request(session, student_id, school_id):
    session.add(ProformaRequestLog(
        school_id=school_id, student_id=student_id,
        last_request_date=datetime.now(timezone.utc),
    ))
    session.commit()


def _upload(local_path, reference):
    s3 = make_s3_client()
    bucket = getattr(AppConfig, "RECEIPT_S3_BUCKET", "shining-smiles-receipts")
    key = f"proforma/{reference}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
    s3.upload_file(local_path, bucket, key, ExtraArgs={"ContentType": "application/pdf"})
    return s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)


def generate_and_send(student_id, message_body, sms_client, session, whatsapp_number, contact):
    """Parse the selection, rate-limit, build + send the pro-forma. Returns a
    short confirmation/error text for the caller to reply with."""
    school_id = resolve_school_id()
    data = sms_client.get_proforma(student_id)
    if not data or not data.get("available"):
        return "⚠️ Those fees are no longer available. Please start again with *menu*."

    items = data.get("items", [])
    sel = _parse_selection(message_body, len(items))
    if sel == "cancel":
        return "Cancelled. Reply *menu* for options."
    if not sel:
        return ("I didn't catch that. Reply with the fee numbers (e.g. *1,3*), "
                "*ALL*, or *CANCEL*.")

    blocked_until = _rate_limited(session, student_id, school_id)
    if blocked_until:
        return (f"⏳ You've already requested a pro-forma recently. "
                f"You can request another on *{blocked_until}*.")

    chosen = [items[i] for i in sel]
    total = sum(Decimal(str(it["amount"])) for it in chosen)
    student_name = " ".join(p for p in [getattr(contact, "firstname", ""),
                                        getattr(contact, "lastname", "")] if p) or student_id
    reference = f"PF-{student_id}-{datetime.now(timezone.utc).strftime('%y%m%d')}"

    tmp = os.path.join(tempfile.gettempdir(), f"proforma_{reference}.pdf")
    try:
        generate_proforma_pdf({
            "student_name": student_name,
            "student_id": student_id,
            "grade_label": data.get("grade_label", ""),
            "term_label": data.get("term_label", "Upcoming Term"),
            "currency": data.get("currency") or "$",
            "items": chosen,
            "total": f"{total:.2f}",
            "reference": reference,
        }, tmp)
        url = _upload(tmp, reference)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    caption = (f"🧾 *Pro-forma Invoice — {data.get('term_label','')}*\n"
               f"{student_name} ({student_id})\nTotal due: ${total:,.2f}\n"
               "Valid 5 days. Give this to your employer/sponsor to pay.")
    send_whatsapp_message(to=whatsapp_number, message=caption, media_url=url,
                          filename=f"ProForma_{student_id}.pdf")
    _record_request(session, student_id, school_id)
    logger.info(f"Pro-forma sent to {whatsapp_number} for {student_id} ({len(chosen)} items, ${total})")
    return None  # PDF already sent; no extra text needed
