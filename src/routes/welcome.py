"""Welcome-on-registration webhook — the SaaS POSTs here when a new student is
registered, and the bot sends the parent a welcome + how-to-use message.

Auth: shared secret in X-Receipt-Key (reuses RECEIPT_WEBHOOK_SECRET). A welcome is
business-initiated, so outside a 24h window it must go via an approved template
(WELCOME_TEMPLATE_NAME); until that's set it falls back to a plain text message
(delivers when the parent already has an open conversation — fine for staging).
"""
from flask import Blueprint, request, jsonify

from config import Config as AppConfig
from utils.whatsapp import send_whatsapp_message, send_whatsapp_template
from utils.logger import setup_logger

logger = setup_logger(__name__)
welcome_bp = Blueprint("welcome", __name__)

_FALLBACK = (
    "👋 Welcome to Shining Smiles College! {name} has been registered.\n\n"
    "You can now use our WhatsApp assistant to help yourself anytime — check your "
    "balance, request a statement, a pro-forma invoice, a gate pass, or a transport "
    "pass.\n\nJust reply *menu* to this chat to begin. 🎓"
)


@welcome_bp.post("/welcome")
def welcome():
    secret = AppConfig.RECEIPT_WEBHOOK_SECRET
    if not secret or request.headers.get("X-Receipt-Key") != secret:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    name = (data.get("student_name") or "your child").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    template = getattr(AppConfig, "WELCOME_TEMPLATE_NAME", "") or ""
    lang = getattr(AppConfig, "WELCOME_TEMPLATE_LANG", "en_US")
    try:
        if template:
            result = send_whatsapp_template(
                to=phone, template_name=template, language=lang, body_params=[name],
            )
        else:
            result = send_whatsapp_message(to=phone, message=_FALLBACK.format(name=name))
        logger.info(f"Welcome sent to {phone} for {data.get('student_id')}")
        return jsonify({"status": "sent", "result": result}), 200
    except Exception as exc:
        logger.error(f"welcome failed for {phone}: {exc}")
        return jsonify({"error": str(exc)}), 500
