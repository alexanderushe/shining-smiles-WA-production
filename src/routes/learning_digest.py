"""Daily Learning summary — the SaaS POSTs here once per guardian per day, only for guardians
who agreed to Learning updates about that child (the SaaS checks consent and keeps the send log).

Auth: shared secret in X-Receipt-Key (reuses RECEIPT_WEBHOOK_SECRET). Business-initiated, so
outside a 24h window it needs the approved template (LEARNING_DIGEST_TEMPLATE_NAME). Template
parameters cannot contain line breaks, so the template gets the one-line `summary`; without a
template the full multi-line `message` goes as plain text.

The message is never logged: it is a child's schoolwork.
"""
import re

from flask import Blueprint, jsonify, request

from config import Config as AppConfig
from utils.logger import setup_logger
from utils.whatsapp import send_whatsapp_message, send_whatsapp_template

logger = setup_logger(__name__)
learning_digest_bp = Blueprint("learning_digest", __name__)

# Meta rejects template parameters with newlines, tabs or more than four consecutive spaces.
PARAM_MAX = 900


def template_param(text, limit=PARAM_MAX):
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def masked(phone):
    return f"{phone[:4]}…{phone[-3:]}" if len(phone) > 7 else "…"


@learning_digest_bp.post("/learning-digest")
def learning_digest():
    secret = AppConfig.RECEIPT_WEBHOOK_SECRET
    if not secret or request.headers.get("X-Receipt-Key") != secret:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    message = (data.get("message") or "").strip()
    if not phone or not message:
        return jsonify({"error": "phone and message required"}), 400

    template = AppConfig.LEARNING_DIGEST_TEMPLATE_NAME
    try:
        if template:
            params = [template_param(data.get("school_name") or "your school", 120),
                      template_param(data.get("day_label") or data.get("day") or "today", 40),
                      template_param(data.get("summary") or message)]
            result = send_whatsapp_template(to=phone, template_name=template,
                                            language=AppConfig.LEARNING_DIGEST_TEMPLATE_LANG, body_params=params)
        else:
            result = send_whatsapp_message(to=phone, message=message)
        logger.info(f"Learning digest sent to {masked(phone)} (school {data.get('school_id')}, {len(data.get('children') or [])} child(ren))")
        return jsonify({"status": "sent", "result": result}), 200
    except Exception as exc:
        logger.error(f"Learning digest failed for {masked(phone)}: {type(exc).__name__}")
        return jsonify({"error": "send failed"}), 500
