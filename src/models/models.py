# src/models/models.py
from sqlalchemy import Column, String, DateTime, Float, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone

Base = declarative_base()

class StudentContact(Base):
    __tablename__ = 'student_contacts'
    student_id = Column(String, primary_key=True)
    firstname = Column(String)
    lastname = Column(String)
    email = Column(String)
    address = Column(String)
    student_mobile = Column(String)
    guardian_mobile_number = Column(String)
    preferred_phone_number = Column(String)
    last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_api_sync = Column(DateTime)

class GatePass(Base):
    __tablename__ = 'gate_passes'
    pass_id = Column(String, primary_key=True)
    student_id = Column(String)
    issued_date = Column(DateTime)
    expiry_date = Column(DateTime)
    payment_percentage = Column(Float)
    whatsapp_number = Column(String)
    last_updated = Column(DateTime)
    pdf_path = Column(String)
    qr_path = Column(String)

class UserState(Base):
    __tablename__ = 'user_states'
    phone_number = Column(String, primary_key=True)
    state = Column(String, default='main_menu')
    student_id = Column(String)
    last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class VerificationCode(Base):
    __tablename__ = 'verification_codes'
    code = Column(String, primary_key=True)
    phone_number = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class TransportPass(Base):
    __tablename__ = 'transport_passes'
    pass_id = Column(String, primary_key=True)  # UUID
    student_id = Column(String, nullable=False)
    term = Column(String, nullable=False)  # e.g., "Term 1 - 2026"
    route_type = Column(String, nullable=False)  # e.g., "local", "chitungwiza", "cbd"
    service_type = Column(String, nullable=False)  # "2_way", "1_way", "either_way"
    amount_paid = Column(Float, nullable=False)  # Amount paid for transport
    issued_date = Column(DateTime, nullable=False)
    expiry_date = Column(DateTime, nullable=False)  # End of term
    whatsapp_number = Column(String)
    pdf_path = Column(String)  # S3 path
    qr_path = Column(String)  # S3 path for QR code
    status = Column(String, default='active')  # 'active', 'expired', 'revoked'
    last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    used = Column(Boolean, default=False)

class FailedSync(Base):
    __tablename__ = 'failed_syncs'
    id = Column(Integer, primary_key=True)
    student_id = Column(String)
    error = Column(String)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Invoice(Base):
    __tablename__ = 'invoices'
    id = Column(Integer, primary_key=True)
    invoice_number = Column(String(50), unique=True, nullable=False)
    student_id = Column(String(20), nullable=False)
    term = Column(String(10), nullable=False)
    issued_date = Column(DateTime, nullable=False)
    due_date = Column(DateTime, nullable=False)
    whatsapp_number = Column(String(20))
    total_amount = Column(Float)
    pdf_path = Column(String(255))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))