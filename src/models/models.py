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
    used = Column(Boolean, default=False)

class FailedSync(Base):
    __tablename__ = 'failed_syncs'
    id = Column(Integer, primary_key=True)
    student_id = Column(String)
    error = Column(String)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))