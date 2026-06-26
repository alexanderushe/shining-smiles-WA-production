"""Payment-receipt webhook — the SaaS POSTs here when a payment is recorded, and
the bot delivers a branded PDF receipt to the parent over WhatsApp.

Auth: shared secret in the `X-Receipt-Key` header (must equal
Config.RECEIPT_WEBHOOK_SECRET). Single-school for now — uses the env WhatsApp
credentials; multi-school routing by payload school_id is a later step.
"""
import os
import tempfile

from flask import Blueprint, request, jsonify

from config import Config as AppConfig
from utils.database import init_db, StudentContact
from utils.whatsapp import send_whatsapp_message, send_whatsapp_template
from utils.logger import setup_logger
from services.receipt_service import generate_receipt_pdf, upload_and_sign

logger = setup_logger(__name__)
receipts_bp = Blueprint("receipts", __name__)


def _parent_number(contact):
    for field in ("preferred_phone_number", "guardian_mobile_number", "student_mobile"):
        v = getattr(contact, field, None)
        if v and str(v).strip():
            return str(v).strip()
    return None


@receipts_bp.post("/payment-receipt")
def payment_receipt():
    # Auth — reject unless the shared secret is configured AND matches.
    secret = AppConfig.RECEIPT_WEBHOOK_SECRET
    if not secret or request.headers.get("X-Receipt-Key") != secret:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    student_id = str(data.get("student_id") or "").strip()
    amount = data.get("amount")
    if not student_id or amount is None:
        return jsonify({"error": "student_id and amount are required"}), 400

    session = None
    try:
        session = init_db()
        contact = session.query(StudentContact).filter(StudentContact.student_id == student_id).first()

        # Prefer the phone + name the SaaS sent (works even if this student was
        # never cached); fall back to the local contact.
        number = (data.get("phone") or "").strip() or (_parent_number(contact) if contact else None)
        if not number:
            return jsonify({"error": f"no phone for student {student_id}"}), 422

        student_name = (data.get("student_name") or "").strip()
        if not student_name:
            student_name = (" ".join(p for p in [getattr(contact, "firstname", ""),
                                                 getattr(contact, "lastname", "")] if p)
                            if contact else "") or student_id
        receipt = {
            "student_name": student_name,
            "student_id": student_id,
            "reference": data.get("reference") or "RCPT",
            "date": data.get("date"),
            "currency": data.get("currency") or "$",
            "amount": amount,
            "items": data.get("items"),
            "balance_after": data.get("balance_after"),
            "payer_name": data.get("payer_name"),
        }

        tmp = os.path.join(tempfile.gettempdir(), f"receipt_{receipt['reference']}.pdf")
        generate_receipt_pdf(receipt, tmp, extra_log={"student_id": student_id})
        url = upload_and_sign(tmp, receipt["reference"], extra_log={"student_id": student_id})
        try:
            os.remove(tmp)
        except OSError:
            pass

        cur = receipt["currency"]
        caption = (
            f"✅ *Payment Received — Shining Smiles College*\n"
            f"Thank you! We've received {cur}{float(amount):,.2f} for "
            f"{student_name} ({student_id}).\n"
            f"Receipt: {receipt['reference']}"
        )
        if receipt.get("balance_after") is not None:
            caption += f"\nOutstanding balance: {cur}{float(receipt['balance_after']):,.2f}"
        caption += "\n\nYour official receipt is attached. 📄"

        amount_str = f"{cur}{float(amount):,.2f}"
        filename = f"Receipt_{receipt['reference']}.pdf"
        if AppConfig.RECEIPT_TEMPLATE_NAME:
            # Business-initiated: deliver via the approved template (works outside 24h).
            # Body order matches the template: amount, student name, student ID, receipt no.
            result = send_whatsapp_template(
                to=number,
                template_name=AppConfig.RECEIPT_TEMPLATE_NAME,
                language=AppConfig.RECEIPT_TEMPLATE_LANG,
                body_params=[amount_str, student_name, student_id, receipt["reference"]],
                document_link=url,
                document_filename=filename,
            )
        else:
            result = send_whatsapp_message(
                to=number, message=caption, media_url=url, filename=filename,
            )
        logger.info(f"Payment receipt sent to {number} for {student_id}", extra={"student_id": student_id})
        return jsonify({"status": "sent", "to": number, "result": result}), 200
    except Exception as e:
        logger.error(f"payment-receipt failed for {student_id}: {e}", extra={"student_id": student_id})
        return jsonify({"error": str(e)}), 500
    finally:
        if session:
            session.close()
