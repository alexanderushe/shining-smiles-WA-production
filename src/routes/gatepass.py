from flask import Blueprint, request, Response, send_from_directory, jsonify
from services.gatepass_service import generate_gatepass, verify_gatepass
from utils.logger import setup_logger
import traceback
import uuid

gatepass_bp = Blueprint('gatepass', __name__)
logger = setup_logger(__name__)

@gatepass_bp.route("/generate-gatepass", methods=["POST"])
def generate_gatepass_route():
    request_id = str(uuid.uuid4())

    # Safely parse JSON payload
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        logger.debug(
            f"Received request for /generate-gatepass with args: {request.args}, body: {data}",
            extra={"request_id": request_id}
        )
    else:
        logger.debug(
            f"Received malformed JSON or no JSON in request body: {request.data}",
            extra={"request_id": request_id}
        )
        data = {}  # fallback to empty dict if parsing failed

    # Attempt to extract parameters from JSON, fallback to query params
    student_id = data.get("student_id") or request.args.get("student_id")
    term = data.get("term") or request.args.get("term")
    payment_amount = data.get("payment_amount") or request.args.get("payment_amount")
    total_fees = data.get("total_fees") or request.args.get("total_fees")

    if not student_id or not term:
        logger.error(
            f"Missing required parameters: student_id={student_id}, term={term}",
            extra={"request_id": request_id}
        )
        return jsonify({"error": "student_id and term are required"}), 400

    try:
        payment_amount = float(payment_amount) if payment_amount else 0.0
        total_fees = float(total_fees) if total_fees else 1000.0

        result, status_code = generate_gatepass(
            student_id,
            term,
            payment_amount,
            total_fees,
            request_id
        )
        return jsonify(result), status_code

    except ValueError as e:
        logger.error(
            f"Invalid payment amount or total fees: {str(e)}",
            extra={"request_id": request_id}
        )
        return jsonify({"error": "Invalid payment amount or total fees"}), 400

    except Exception as e:
        logger.error(
            f"Error generating gate pass: {str(e)}\n{traceback.format_exc()}",
            extra={"request_id": request_id}
        )
        return jsonify({"error": f"Failed to generate gate pass: {str(e)}"}), 500


@gatepass_bp.route("/verify-gatepass", methods=["GET"])
def verify_gatepass_route():
    logger.debug(f"Received request for /verify-gatepass with args: {request.args}")

    pass_id = request.args.get("pass_id")
    whatsapp_number = request.args.get("whatsapp_number")

    if not pass_id or not whatsapp_number:
        logger.error(
            f"Missing required parameters: pass_id={pass_id}, whatsapp_number={whatsapp_number}"
        )
        return jsonify({"error": "pass_id and whatsapp_number are required"}), 400

    try:
        result, status_code = verify_gatepass(pass_id, whatsapp_number)
        return jsonify(result), status_code
    except Exception as e:
        logger.error(
            f"Error verifying gate pass: {str(e)}\n{traceback.format_exc()}"
        )
        return jsonify({"error": f"Failed to verify gate pass: {str(e)}"}), 500


@gatepass_bp.route("/temp/<path:filename>", methods=["GET"])
def serve_temp_file(filename):
    try:
        return send_from_directory("temp", filename)
    except Exception as e:
        logger.error(f"Error serving temp file {filename}: {str(e)}")
        return jsonify({"error": "File not found"}), 404
