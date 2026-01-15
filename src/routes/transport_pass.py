from flask import Blueprint, request, Response, jsonify
from services.transport_pass_service import (
    generate_transport_pass, 
    verify_transport_pass,
    get_student_transport_passes
)
from utils.logger import setup_logger
import traceback
import uuid

transport_pass_bp = Blueprint('transport_pass', __name__)
logger = setup_logger(__name__)


@transport_pass_bp.route("/generate-transport-pass", methods=["POST"])
def generate_transport_pass_route():
    """Generate a transport pass for a student."""
    request_id = str(uuid.uuid4())
    
    # Parse JSON payload
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        logger.debug(
            f"Received request for /generate-transport-pass with args: {request.args}, body: {data}",
            extra={"request_id": request_id}
        )
    else:
        logger.debug(
            f"Received malformed JSON in request body: {request.data}",
            extra={"request_id": request_id}
        )
        data = {}
    
    # Extract parameters from JSON or query params
    student_id = data.get("student_id") or request.args.get("student_id")
    term = data.get("term") or request.args.get("term")
    route_type = data.get("route_type") or request.args.get("route_type")
    service_type = data.get("service_type") or request.args.get("service_type")
    amount_paid = data.get("amount_paid") or request.args.get("amount_paid")
    whatsapp_number = data.get("whatsapp_number") or request.args.get("whatsapp_number")
    skip_whatsapp = data.get("skip_whatsapp", False)
    
    # Validate required parameters
    if not all([student_id, term, route_type, service_type, amount_paid]):
        logger.error(
            f"Missing required parameters",
            extra={"request_id": request_id}
        )
        return jsonify({"error": "Missing required parameters: student_id, term, route_type, service_type, amount_paid"}), 400
    
    try:
        amount_paid = float(amount_paid)
        
        result, status_code = generate_transport_pass(
            student_id=student_id,
            term=term,
            route_type=route_type,
            service_type=service_type,
            amount_paid=amount_paid,
            request_id=request_id,
            whatsapp_number=whatsapp_number,
            skip_whatsapp=skip_whatsapp
        )
        
        return jsonify(result), status_code
        
    except ValueError as e:
        logger.error(
            f"Invalid amount_paid: {str(e)}",
            extra={"request_id": request_id}
        )
        return jsonify({"error": "Invalid amount_paid value"}), 400
    
    except Exception as e:
        logger.error(
            f"Error generating transport pass: {str(e)}\\n{traceback.format_exc()}",
            extra={"request_id": request_id}
        )
        return jsonify({"error": f"Failed to generate transport pass: {str(e)}"}), 500


@transport_pass_bp.route("/verify-transport-pass", methods=["GET"])
def verify_transport_pass_route():
    """Verify a transport pass."""
    logger.debug(f"Received request for /verify-transport-pass with args: {request.args}")
    
    pass_id = request.args.get("pass_id")
    whatsapp_number = request.args.get("whatsapp_number")
    
    if not pass_id or not whatsapp_number:
        logger.error(
            f"Missing required parameters: pass_id={pass_id}, whatsapp_number={whatsapp_number}"
        )
        return jsonify({"error": "pass_id and whatsapp_number are required"}), 400
    
    try:
        result, status_code = verify_transport_pass(pass_id, whatsapp_number)
        return jsonify(result), status_code
    except Exception as e:
        logger.error(
            f"Error verifying transport pass: {str(e)}\\n{traceback.format_exc()}"
        )
        return jsonify({"error": f"Failed to verify transport pass: {str(e)}"}), 500


@transport_pass_bp.route("/student-transport-passes", methods=["GET"])
def get_student_transport_passes_route():
    """Get all transport passes for a student for a given term."""
    student_id = request.args.get("student_id")
    term = request.args.get("term")
    
    if not student_id or not term:
        logger.error(f"Missing required parameters: student_id={student_id}, term={term}")
        return jsonify({"error": "student_id and term are required"}), 400
    
    try:
        passes = get_student_transport_passes(student_id, term)
        
        passes_data = []
        for tp in passes:
            passes_data.append({
                "pass_id": tp.pass_id,
                "route_type": tp.route_type,
                "service_type": tp.service_type,
                "amount_paid": tp.amount_paid,
                "issued_date": tp.issued_date.isoformat(),
                "expiry_date": tp.expiry_date.isoformat(),
                "status": tp.status
            })
        
        return jsonify({
            "student_id": student_id,
            "term": term,
            "passes": passes_data,
            "count": len(passes_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching transport passes: {str(e)}\\n{traceback.format_exc()}")
        return jsonify({"error": f"Failed to fetch transport passes: {str(e)}"}), 500
