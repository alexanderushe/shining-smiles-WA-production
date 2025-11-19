# src/routes/contacts.py
from flask import Blueprint, request, jsonify
from utils.database import init_db, StudentContact
from utils.logger import setup_logger
from datetime import datetime, timezone
import re

contacts_bp = Blueprint('contacts', __name__)
logger = setup_logger(__name__)

def normalize_phone_number(phone_number, request_id=None):
    """Normalize phone number to +263 followed by 9 digits."""
    if not phone_number:
        return None
    # Remove whitespace and special characters, keep +
    cleaned = re.sub(r'[^0-9+]', '', phone_number)
    # Handle various input formats
    if cleaned.startswith('+263263'):
        cleaned = '+263' + cleaned[7:]  # Remove duplicated +263
    elif cleaned.startswith('+263'):
        cleaned = cleaned  # Already correct
    elif cleaned.startswith('263'):
        cleaned = '+263' + cleaned[3:]  # Add +
    elif cleaned.startswith('0'):
        cleaned = '+263' + cleaned[1:]  # Replace leading 0 with +263
    elif cleaned.startswith('+'):
        cleaned = None  # Invalid country code
    else:
        cleaned = '+263' + cleaned  # Assume Zimbabwe number
    # Validate: +263 followed by 9 digits
    if not cleaned or not re.match(r'^\+263[0-9]{9}$', cleaned):
        logger.error(f"[Request {request_id}] Invalid phone number format: {phone_number}")
        return None
    return cleaned

@contacts_bp.route("/update-contact", methods=["POST"])
def update_contact():
    session = init_db()
    request_id = getattr(request, 'request_id', 'unknown')
    logger.debug(f"[Request {request_id}] /update-contact: args={request.args}, form={request.form}, headers={request.headers}")
    try:
        student_id = request.args.get("student_id")
        phone_number = request.args.get("phone_number")
        firstname = request.args.get("firstname")
        lastname = request.args.get("lastname")
        email = request.args.get("email")
        address = request.args.get("address")

        if not student_id or not phone_number:
            logger.error(f"[Request {request_id}] Missing student_id or phone_number")
            return jsonify({"error": "student_id and phone_number required", "received_args": dict(request.args)}), 400

        # Normalize phone number
        normalized_phone = normalize_phone_number(phone_number, request_id)
        if not normalized_phone:
            return jsonify({"error": "Invalid phone number format"}), 400

        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        if contact:
            contact.firstname = firstname or contact.firstname
            contact.lastname = lastname or contact.lastname
            contact.email = email or contact.email
            contact.address = address or contact.address
            contact.student_mobile = normalized_phone
            contact.guardian_mobile_number = normalized_phone if not contact.guardian_mobile_number else contact.guardian_mobile_number
            contact.preferred_phone_number = normalized_phone
            contact.last_updated = datetime.now(timezone.utc)
            logger.info(f"[Request {request_id}] Updated contact for {student_id}: {normalized_phone}")
        else:
            contact = StudentContact(
                student_id=student_id,
                firstname=firstname,
                lastname=lastname,
                email=email,
                address=address,
                student_mobile=normalized_phone,
                guardian_mobile_number=normalized_phone,
                preferred_phone_number=normalized_phone,
                last_updated=datetime.now(timezone.utc)
            )
            session.add(contact)
            logger.info(f"[Request {request_id}] Added contact for {student_id}: {normalized_phone}")

        session.commit()
        return jsonify({"status": "Contact updated"}), 200
    except Exception as e:
        logger.error(f"[Request {request_id}] Error updating contact for {student_id}: {str(e)}")
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.remove()

@contacts_bp.route("/get-student-profile", methods=["GET"])
def get_student_profile():
    session = init_db()
    request_id = getattr(request, 'request_id', 'unknown')
    logger.debug(f"[Request {request_id}] /get-student-profile: args={request.args}, headers={request.headers}")
    try:
        student_id = request.args.get("student_id")
        if not student_id:
            logger.error(f"[Request {request_id}] Missing student_id")
            return jsonify({"error": "student_id required", "received_args": dict(request.args)}), 400

        contact = session.query(StudentContact).filter_by(student_id=student_id).first()
        if contact and contact.last_api_sync and (datetime.now(timezone.utc) - contact.last_api_sync).total_seconds() < 24*3600:
            logger.info(f"[Request {request_id}] Found recent profile for {student_id} in database")
            return jsonify({
                "status": "success",
                "profile": {
                    "student_id": contact.student_id,
                    "firstname": contact.firstname,
                    "lastname": contact.lastname,
                    "student_mobile": contact.student_mobile,
                    "guardian_mobile_number": contact.guardian_mobile_number,
                    "preferred_phone_number": contact.preferred_phone_number,
                    "last_updated": contact.last_updated.isoformat()
                }
            }), 200

        from api.sms_client import SMSClient
        client = SMSClient(request_id=request_id)
        try:
            profile = client.get_student_profile(student_id)
            if not profile:
                logger.error(f"[Request {request_id}] No profile found for {student_id} in API")
                return jsonify({"error": "Profile not found"}), 404
            profile_data = profile.get("data", {})
            firstname = profile_data.get("firstname")
            lastname = profile_data.get("lastname")
            student_mobile = profile_data.get("student_mobile")
            guardian_mobile = profile_data.get("guardian_mobile_number")

            if student_mobile == "nan" or not student_mobile:
                logger.warning(f"[Request {request_id}] No valid student_mobile for {student_id}")
                return jsonify({"error": "No valid student_mobile in profile"}), 404

            # Normalize phone numbers
            student_mobile = normalize_phone_number(student_mobile, request_id)
            if not student_mobile:
                return jsonify({"error": "Invalid student_mobile format"}), 400
            guardian_mobile = normalize_phone_number(guardian_mobile, request_id) if guardian_mobile and guardian_mobile != "nan" else None
            preferred_phone = student_mobile

            if contact:
                contact.firstname = firstname or contact.firstname
                contact.lastname = lastname or contact.lastname
                contact.student_mobile = student_mobile
                contact.guardian_mobile_number = guardian_mobile or contact.guardian_mobile_number
                contact.preferred_phone_number = preferred_phone
                contact.last_updated = datetime.now(timezone.utc)
                contact.last_api_sync = datetime.now(timezone.utc)
            else:
                contact = StudentContact(
                    student_id=student_id,
                    firstname=firstname,
                    lastname=lastname,
                    student_mobile=student_mobile,
                    guardian_mobile_number=guardian_mobile,
                    preferred_phone_number=preferred_phone,
                    last_updated=datetime.now(timezone.utc),
                    last_api_sync=datetime.now(timezone.utc)
                )
                session.add(contact)
            session.commit()
            logger.info(f"[Request {request_id}] Cached profile for {student_id} from API")
            return jsonify({
                "status": "success",
                "profile": {
                    "student_id": contact.student_id,
                    "firstname": contact.firstname,
                    "lastname": contact.lastname,
                    "student_mobile": contact.student_mobile,
                    "guardian_mobile_number": contact.guardian_mobile_number,
                    "preferred_phone_number": contact.preferred_phone_number,
                    "last_updated": contact.last_updated.isoformat()
                }
            }), 200
        except Exception as e:
            logger.error(f"[Request {request_id}] Error fetching profile for {student_id} from API: {str(e)}")
            return jsonify({"error": f"Profile not found: {str(e)}"}), 404
    except Exception as e:
        logger.error(f"[Request {request_id}] Error retrieving profile for {student_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.remove()