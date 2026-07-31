"""Guardian-cache invalidation — the SaaS POSTs here when a guardian link changes.

The bot keeps a local phone->student cache (`student_contacts`) plus per-sender
sessions (`user_states`). That cache is what a WhatsApp conversation actually
reads, so until it is refreshed a number removed from a student in the admin app
carries on serving that child's records.

`_cache_is_stale` already bounds this with a TTL (CONTACT_CACHE_TTL_HOURS,
default 12). That closes the hole eventually, but twelve hours of continued
access to a child's data after a guardian was removed is too long to be the only
answer. This endpoint makes revocation immediate; the TTL stays as the backstop
for anything that never reaches us.

Auth: shared secret in `X-Guardian-Key`, same secret the receipt webhook uses.
"""
from flask import Blueprint, request, jsonify

from config import Config as AppConfig
from utils.database import init_db, StudentContact, UserState
from utils.logger import setup_logger

logger = setup_logger(__name__)
guardian_cache_bp = Blueprint("guardian_cache", __name__)


def _phone_variants(phone):
    """The stored forms a number might take, so a +263 push also clears 0-prefixed rows."""
    raw = (phone or "").strip()
    if not raw:
        return []
    digits = "".join(c for c in raw if c.isdigit())
    tail = digits[-9:] if len(digits) >= 9 else digits
    if not tail:
        return [raw]
    return list({raw, tail, f"+263{tail}", f"263{tail}", f"0{tail}"})


@guardian_cache_bp.post("/guardian-cache/invalidate")
def invalidate_guardian_cache():
    secret = AppConfig.RECEIPT_WEBHOOK_SECRET
    if not secret or request.headers.get("X-Guardian-Key") != secret:
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    phone = (payload.get("phone") or "").strip()
    if not phone:
        return jsonify({"error": "phone is required"}), 400

    variants = _phone_variants(phone)
    session = init_db()
    if session is None:
        logger.error("guardian-cache invalidate: no database session")
        return jsonify({"error": "database unavailable"}), 503

    try:
        # Drop the cached mapping. Deleting rather than editing is deliberate:
        # the next message re-resolves from the SaaS, which is the source of
        # truth, instead of the bot guessing what the new mapping should be.
        contacts = session.query(StudentContact).filter(
            (StudentContact.guardian_mobile_number.in_(variants))
            | (StudentContact.preferred_phone_number.in_(variants))
            | (StudentContact.student_mobile.in_(variants))
        ).all()
        for contact in contacts:
            session.delete(contact)

        # Clear the live session too. Without this the sender stays pinned to
        # whichever student they had already selected, and never re-resolves.
        states = session.query(UserState).filter(
            UserState.phone_number.in_(variants)
        ).all()
        for state in states:
            session.delete(state)

        session.commit()
        logger.info(
            "guardian-cache invalidated for %s: %s contact(s), %s session(s)",
            phone, len(contacts), len(states),
        )
        return jsonify({
            "ok": True,
            "phone": phone,
            "contacts_cleared": len(contacts),
            "sessions_cleared": len(states),
        })
    except Exception:
        session.rollback()
        logger.exception("guardian-cache invalidate failed for %s", phone)
        return jsonify({"error": "invalidation failed"}), 500
    finally:
        session.close()
