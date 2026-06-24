from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    or_,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
import boto3
import datetime
import json
import os
from time import sleep
from urllib.parse import urlparse

from utils.logger import setup_logger
from utils.tenant_context import get_current_tenant

logger = setup_logger(__name__)
Base = declarative_base()


def resolve_school_id(explicit_school_id=None):
    if explicit_school_id:
        return str(explicit_school_id)
    tenant = get_current_tenant() or {}
    return str(
        tenant.get("school_id")
        or os.getenv("WHATSAPP_DEFAULT_SCHOOL_ID")
        or os.getenv("SCHOOL_ID")
        or "default"
    )


class StudentContact(Base):
    __tablename__ = "student_contacts"
    __table_args__ = (
        UniqueConstraint("school_id", "student_id", name="uq_student_contacts_school_student_id"),
    )

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    student_id = Column(String, nullable=False)
    firstname = Column(String, nullable=True)
    lastname = Column(String, nullable=True)
    email = Column(String, nullable=True)
    address = Column(String, nullable=True)
    student_mobile = Column(String, nullable=True)
    guardian_mobile_number = Column(String, nullable=False)
    preferred_phone_number = Column(String, nullable=True)
    outstanding_balance = Column(Float, nullable=True)
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_api_sync = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_total_paid = Column(Float, default=0.0)


class GatePass(Base):
    __tablename__ = "gate_passes"

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    student_id = Column(String, ForeignKey("student_contacts.student_id"), nullable=False)
    pass_id = Column(String, unique=True, nullable=False)
    issued_date = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expiry_date = Column(DateTime(timezone=True), nullable=False)
    payment_percentage = Column(Integer, nullable=False)
    whatsapp_number = Column(String, nullable=False)
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    pdf_path = Column(String, nullable=True)
    qr_path = Column(String, nullable=True)


class GatePassScan(Base):
    __tablename__ = "gate_pass_scans"

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    pass_id = Column(String, nullable=False)
    scanned_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    scanned_by_number = Column(String, nullable=True)
    matched_registered_number = Column(Boolean, default=False)


class FailedSync(Base):
    __tablename__ = "failed_syncs"

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    student_id = Column(String, nullable=False)
    error = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class UserState(Base):
    __tablename__ = "user_states"

    school_id = Column(String(64), primary_key=True, nullable=False, default=resolve_school_id)
    phone_number = Column(String, primary_key=True)
    state = Column(String, nullable=False, default="INITIAL")
    student_id = Column(String, nullable=True)
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    reminder_count = Column(Integer, default=0)
    query_count = Column(Integer, default=0)


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    phone_number = Column(String, nullable=False)
    student_id = Column(String, nullable=False)
    code = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)


class GatePassRequestLog(Base):
    __tablename__ = "gate_pass_request_logs"

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    student_id = Column(String, nullable=False)
    week_start_date = Column(DateTime(timezone=True), nullable=False)
    request_count = Column(Integer, default=0)
    last_request_date = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class TransportPassRequestLog(Base):
    __tablename__ = "transport_pass_request_log"

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    student_id = Column(String, nullable=False)
    week_start_date = Column(DateTime(timezone=True), nullable=False)
    request_count = Column(Integer, default=0)
    last_request_date = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("school_id", "invoice_number", name="uq_invoices_school_invoice_number"),
    )

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    invoice_number = Column(String(50), nullable=False)
    student_id = Column(String(20), nullable=False)
    term = Column(String(10), nullable=False)
    issued_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    whatsapp_number = Column(String(20))
    total_amount = Column(Float)
    pdf_path = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


class TransportPass(Base):
    __tablename__ = "transport_passes"

    id = Column(Integer, primary_key=True)
    school_id = Column(String(64), nullable=False, default=resolve_school_id)
    pass_id = Column(String, unique=True, nullable=False)
    student_id = Column(String, ForeignKey("student_contacts.student_id"), nullable=False)
    term = Column(String, nullable=False)
    route_type = Column(String, nullable=False)
    service_type = Column(String, nullable=False)
    amount_paid = Column(Float, nullable=False)
    issued_date = Column(DateTime(timezone=True), nullable=False)
    expiry_date = Column(DateTime(timezone=True), nullable=False)
    whatsapp_number = Column(String)
    pdf_path = Column(String)
    qr_path = Column(String)
    status = Column(String, default="active")
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))


def school_scoped_query(session, model, school_id=None):
    sid = resolve_school_id(school_id)
    if hasattr(model, "school_id"):
        return session.query(model).filter(model.school_id == sid)
    return session.query(model)


def get_student_contact(session, student_id, school_id=None):
    sid = resolve_school_id(school_id)
    return school_scoped_query(session, StudentContact, sid).filter(StudentContact.student_id == student_id).first()


def find_contacts_by_phone(session, phone_number, school_id=None):
    sid = resolve_school_id(school_id)
    return school_scoped_query(session, StudentContact, sid).filter(
        or_(
            StudentContact.student_mobile == phone_number,
            StudentContact.guardian_mobile_number == phone_number,
            StudentContact.preferred_phone_number == phone_number,
        )
    ).all()


def get_user_state(session, phone_number, school_id=None):
    sid = resolve_school_id(school_id)
    return school_scoped_query(session, UserState, sid).filter(UserState.phone_number == phone_number).first()


def get_secret(secret_name):
    """Retrieve secret from AWS Secrets Manager with fallback to env var."""
    import signal
    from botocore.config import Config

    def timeout_handler(signum, frame):
        raise TimeoutError("Secrets Manager call timed out after 15 seconds")

    config = Config(connect_timeout=10, read_timeout=10, retries={"max_attempts": 1})
    client = boto3.client("secretsmanager", region_name="us-east-2", config=config)

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(15)

    try:
        logger.info("Fetching secret with 15s hard timeout...")
        response = client.get_secret_value(SecretId=secret_name)
        signal.alarm(0)
        logger.info("Secret fetched successfully")
        return json.loads(response["SecretString"])
    except TimeoutError as exc:
        signal.alarm(0)
        logger.error(f"Secret fetch TIMED OUT: {str(exc)}")
        raise
    except Exception as exc:
        signal.alarm(0)
        logger.warning(f"Secret fetch failed (using fallback DATABASE_URL): {str(exc)}")
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            parsed = urlparse(db_url)
            return {
                "username": parsed.username,
                "password": parsed.password,
                "host": parsed.hostname,
                "port": parsed.port or 5432,
                "dbname": parsed.path.lstrip("/"),
            }
        raise


def init_db():
    """Initialize database connection with connection pooling and retry logic."""
    logger.info("START: init_db()")

    try:
        logger.info("Fetching secret from Secrets Manager...")
        secret = get_secret("shining-smiles-db-credentials")
        logger.info("Secret successfully fetched")
    except Exception as exc:
        logger.error(f"SECRET FETCH FAILED: {exc}")
        raise

    user = secret.get("username")
    password = secret.get("password")
    host = secret.get("host")
    dbname = secret.get("dbname")
    port = secret.get("port", 5432)

    if not all([user, password, host, dbname]):
        logger.error("Missing DB connection parameters in secret.")
        raise ValueError("Incomplete DB credentials in secret")

    db_url = f"postgresql+pg8000://{user}:{password}@{host}:{port}/{dbname}"
    logger.info(f"Using DB URL: {db_url}")

    retries = 3
    for attempt in range(retries):
        try:
            logger.info(f"Connecting to DB (attempt {attempt + 1}/{retries})...")
            engine = create_engine(db_url, pool_size=5, max_overflow=5, pool_timeout=30, pool_recycle=1800)
            with engine.connect() as conn:
                logger.info("✅ Database connection successful.")
            Base.metadata.create_all(engine)
            session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            logger.info("END: init_db()")
            return scoped_session(session_factory)
        except OperationalError as exc:
            logger.warning(f"OperationalError: {exc}")
            if "too many connections" in str(exc) and attempt < retries - 1:
                sleep(2)
                continue
            raise
        except Exception as exc:
            logger.error(f"Unexpected error during DB init: {str(exc)}")
            raise
