from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError
import boto3
import json
import datetime
from time import sleep
from utils.logger import setup_logger
import os  # For os.getenv
from urllib.parse import urlparse  # For parsing DATABASE_URL

logger = setup_logger(__name__)
Base = declarative_base()

# Your models (StudentContact, GatePass, etc.) - keep as is
class StudentContact(Base):
    __tablename__ = "student_contacts"
    id = Column(Integer, primary_key=True)
    student_id = Column(String, unique=True, nullable=False)
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
    pass_id = Column(String, nullable=False)
    scanned_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    scanned_by_number = Column(String, nullable=True)
    matched_registered_number = Column(Boolean, default=False)

class FailedSync(Base):
    __tablename__ = "failed_syncs"
    id = Column(Integer, primary_key=True)
    student_id = Column(String, nullable=False)
    error = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

class UserState(Base):
    __tablename__ = "user_states"
    phone_number = Column(String, primary_key=True)
    state = Column(String, nullable=False, default='INITIAL')
    student_id = Column(String, nullable=True)
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    reminder_count = Column(Integer, default=0)
    query_count = Column(Integer, default=0)

class VerificationCode(Base):
    __tablename__ = "verification_codes"
    id = Column(Integer, primary_key=True)
    phone_number = Column(String, nullable=False)
    student_id = Column(String, nullable=False)
    code = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)

class GatePassRequestLog(Base):
    __tablename__ = "gate_pass_request_logs"
    id = Column(Integer, primary_key=True)
    student_id = Column(String, nullable=False)
    week_start_date = Column(DateTime(timezone=True), nullable=False)  # Monday of the week
    request_count = Column(Integer, default=0)
    last_request_date = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

class Invoice(Base):
    __tablename__ = 'invoices'
    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(50), unique=True, nullable=False)
    student_id = Column(String(20), nullable=False)
    term = Column(String(10), nullable=False)
    issued_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    whatsapp_number = Column(String(20))
    total_amount = Column(Float)
    pdf_path = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

def get_secret(secret_name):
    """Retrieve secret from AWS Secrets Manager with fallback to env var."""
    import signal
    from botocore.config import Config
    
    # Timeout handler
    def timeout_handler(signum, frame):
        raise TimeoutError("Secrets Manager call timed out after 15 seconds")
    
    # Configure boto3 with timeouts
    config = Config(
        connect_timeout=10,
        read_timeout=10,
        retries={'max_attempts': 1}
    )
    
    client = boto3.client('secretsmanager', region_name='us-east-2', config=config)
    
    # Set hard 15-second timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(15)
    
    try:
        logger.info("Fetching secret with 15s hard timeout...")
        response = client.get_secret_value(SecretId=secret_name)
        signal.alarm(0)  # Cancel alarm
        logger.info("Secret fetched successfully")
        return json.loads(response['SecretString'])
    except TimeoutError as e:
        signal.alarm(0)
        logger.error(f"Secret fetch TIMED OUT: {str(e)}")
        raise
    except Exception as e:
        signal.alarm(0)
        logger.warning(f"Secret fetch failed (using fallback DATABASE_URL): {str(e)}")
        # Fallback to env var DATABASE_URL
        db_url = os.getenv('DATABASE_URL')
        if db_url:
            # Parse env var to secret dict (postgresql://user:pass@host:port/db)
            parsed = urlparse(db_url)
            return {
                'username': parsed.username,
                'password': parsed.password,
                'host': parsed.hostname,
                'port': parsed.port or 5432,
                'dbname': parsed.path.lstrip('/')
            }
        raise

def init_db():
    """Initialize database connection with connection pooling and retry logic."""
    logger.info("START: init_db()")

    try:
        logger.info("Fetching secret from Secrets Manager...")
        secret = get_secret('shining-smiles-db-credentials')
        logger.info("Secret successfully fetched")
    except Exception as e:
        logger.error(f"SECRET FETCH FAILED: {e}")
        raise

    user = secret.get("username")
    password = secret.get("password")
    host = secret.get("host")
    dbname = secret.get("dbname")
    port = secret.get("port", 5432)

    if not all([user, password, host, dbname]):
        logger.error("Missing DB connection parameters in secret.")
        raise ValueError("Incomplete DB credentials in secret")

    # Use pg8000 (pure Python, no C extension)
    db_url = f"postgresql+pg8000://{user}:{password}@{host}:{port}/{dbname}"

    logger.info(f"Using DB URL: {db_url}")

    retries = 3
    for attempt in range(retries):
        try:
            logger.info(f"Connecting to DB (attempt {attempt+1}/{retries})...")
            engine = create_engine(
                db_url,
                pool_size=5,
                max_overflow=5,
                pool_timeout=30,
                pool_recycle=1800
            )
            with engine.connect() as conn:
                logger.info("✅ Database connection successful.")
            Base.metadata.create_all(engine)
            session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            logger.info("END: init_db()")
            return scoped_session(session_factory)
        except OperationalError as e:
            logger.warning(f"OperationalError: {e}")
            if "too many connections" in str(e) and attempt < retries - 1:
                sleep(2)
                continue
            raise
        except Exception as e:
            logger.error(f"Unexpected error during DB init: {str(e)}")
            raise