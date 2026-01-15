# src/routes/__init__.py
from utils.logger import setup_logger
from .gatepass import gatepass_bp
from .whatsapp import whatsapp_bp
from .payments import payments_bp
from .contacts import contacts_bp
from .transport_pass import transport_pass_bp

logger = setup_logger(__name__)

def register_routes(app):
    try:
        logger.info("Registering gatepass_bp")
        app.register_blueprint(gatepass_bp)
        logger.info("Registering whatsapp_bp")
        app.register_blueprint(whatsapp_bp)
        logger.info("Registering payments_bp")
        app.register_blueprint(payments_bp)
        logger.info("Registering contacts_bp")
        app.register_blueprint(contacts_bp)
        logger.info("Registering transport_pass_bp")
        app.register_blueprint(transport_pass_bp)
        logger.info("All blueprints registered successfully")
    except Exception as e:
        logger.error(f"Error registering blueprints: {str(e)}")