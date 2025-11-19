# src/routes/payments.py
from flask import Blueprint, request, jsonify
from services.payment_service import check_new_payments
from services.reminder_service import send_balance_reminders
from utils.database import init_db
from utils.logger import setup_logger

payments_bp = Blueprint('payments', __name__)
logger = setup_logger(__name__)

@payments_bp.route("/trigger-payments", methods=["POST"])
def trigger_payments():
    session = init_db()
    try:
        student_id = request.args.get("student_id_number")
        term = request.args.get("term")
        phone_number = request.args.get("phone_number")
        test_mode = request.args.get("test_mode", "false").lower() == "true"
        test_payment_percentage = request.args.get("test_payment_percentage", type=float)

        if not student_id or not term:
            logger.error(f"Missing required parameters: student_id={student_id}, term={term}")
            return jsonify({"error": "student_id and term are required"}), 400

        logger.debug(f"Triggering payment check for {student_id}, term={term}, phone={phone_number}, test_mode={test_mode}")
        result = check_new_payments(student_id, term, phone_number=phone_number, session=session, test_mode=test_mode, test_payment_percentage=test_payment_percentage)
        if "error" in result:
            logger.error(f"Error in check_new_payments: {result['error']}")
            return jsonify({"status": "Payment check failed", "error": result['error']}), 400
        logger.info(f"Payment check triggered for {student_id}")
        return jsonify({"status": "Payment check triggered", "result": result}), 200
    except Exception as e:
        logger.error(f"Error triggering payments: {str(e)}")
        return jsonify({"error": f"Failed to trigger payments: {str(e)}"}), 500
    finally:
        session.remove()

@payments_bp.route("/trigger-reminders", methods=["POST"])
def trigger_reminders():
    session = init_db()
    try:
        student_id = request.args.get("student_id_number")
        term = request.args.get("term")
        phone_number = request.args.get("phone_number")

        if not student_id or not term:
            logger.error(f"Missing required parameters: student_id={student_id}, term={term}")
            return jsonify({"error": "student_id and term are required"}), 400

        logger.debug(f"Triggering reminder for {student_id}, term={term}, phone={phone_number}")
        result = send_balance_reminders(student_id, term, phone_number)
        if "error" in result:
            logger.error(f"Error in send_balance_reminders: {result['error']}")
            return jsonify({"status": "Reminder failed", "error": result['error']}), 400
        logger.info(f"Balance reminder triggered for {student_id}")
        return jsonify({"status": "Balance reminder triggered", "result": result}), 200
    except Exception as e:
        logger.error(f"Error triggering reminders: {str(e)}")
        return jsonify({"error": f"Failed to trigger reminders: {str(e)}"}), 500
    finally:
        session.remove()