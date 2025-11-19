# config.py
from datetime import datetime, timezone
import os

class Config:
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    SMS_API_BASE_URL = os.getenv("SMS_API_BASE_URL")
    SMS_API_KEY = os.getenv("SMS_API_KEY")
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    APP_BASE_URL = os.getenv("APP_BASE_URL", "https://api.shiningsmilescollege.ac.zw")
    # APP_BASE_URL = os.getenv("APP_BASE_URL", "http://shining-smiles-env.eba-nbbib23h.us-east-2.elasticbeanstalk.com")

    #CloudAPI setup
    #WhatsApp Cloud API
    WHATSAPP_CLOUD_API_TOKEN = os.getenv("WHATSAPP_CLOUD_API_TOKEN")
    WHATSAPP_CLOUD_NUMBER = os.getenv("WHATSAPP_CLOUD_NUMBER")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
    WHATSAPP_API_URL = "https://graph.facebook.com/v17.0"  # latest stable version
    #end CloudAPI setup
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-2")  # Match S3 region

    TERM_START_DATES = {
        "2025-1": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "2025-2": datetime(2025, 5, 5, tzinfo=timezone.utc),
        "2025-3": datetime(2025, 9, 1, tzinfo=timezone.utc),
    }
    TERM_END_DATES = {
        "2025-1": datetime(2025, 3, 31, tzinfo=timezone.utc),
        "2025-2": datetime(2025, 7, 31, tzinfo=timezone.utc),
        "2025-3": datetime(2025, 11, 30, tzinfo=timezone.utc),
    }

    @classmethod
    def get_term_window(cls, term_code: str):
        """Returns a tuple of (start_date, end_date) for a term."""
        if term_code not in cls.TERM_START_DATES:
            raise ValueError(f"Unknown term: {term_code}")
        return (cls.TERM_START_DATES[term_code], cls.TERM_END_DATES[term_code])

    @classmethod
    def weeks_remaining(cls, term_code: str):
        """Calculate weeks remaining in the term."""
        if term_code not in cls.TERM_START_DATES:
            raise ValueError(f"Unknown term: {term_code}")
        today = datetime.now(timezone.utc)
        _, end = cls.get_term_window(term_code)
        return max(0, (end - today).days // 7)

    @classmethod
    def weeks_elapsed(cls, term_code: str):
        """Calculate weeks elapsed in the term."""
        if term_code not in cls.TERM_START_DATES:
            raise ValueError(f"Unknown term: {term_code}")
        start, _ = cls.get_term_window(term_code)
        today = datetime.now(timezone.utc)
        return max(0, (today - start).days // 7)

    @classmethod
    def term_end_date(cls, term_code: str):
        """Return the end date for a term."""
        if term_code not in cls.TERM_START_DATES:
            raise ValueError(f"Unknown term: {term_code}")
        return cls.TERM_END_DATES[term_code]

def get_config():
    """Return config based on environment."""
    env = os.getenv("FLASK_ENV", "development")
    if env == "production":
        return ProductionConfig()
    return DevelopmentConfig()

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
