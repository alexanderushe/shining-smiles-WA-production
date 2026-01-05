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
        # 2025 terms (historical data)
        "2025-1": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "2025-2": datetime(2025, 5, 5, tzinfo=timezone.utc),
        "2025-3": datetime(2025, 9, 1, tzinfo=timezone.utc),
        # 2026 terms (current academic year)
        # Note: Term 2026-1 starts Jan 4 to allow early fee payments before school opens
        "2026-1": datetime(2026, 1, 4, tzinfo=timezone.utc),
        "2026-2": datetime(2026, 5, 4, tzinfo=timezone.utc),
        "2026-3": datetime(2026, 9, 7, tzinfo=timezone.utc),
    }
    TERM_END_DATES = {
        # 2025 terms (historical data)
        "2025-1": datetime(2025, 3, 31, tzinfo=timezone.utc),
        "2025-2": datetime(2025, 7, 31, tzinfo=timezone.utc),
        "2025-3": datetime(2025, 12, 15, tzinfo=timezone.utc),
        # 2026 terms (current academic year)
        "2026-1": datetime(2026, 4, 2, tzinfo=timezone.utc),
        "2026-2": datetime(2026, 8, 6, tzinfo=timezone.utc),
        "2026-3": datetime(2026, 12, 3, tzinfo=timezone.utc),
    }

    @classmethod
    def get_current_term(cls):
        """Returns the currently active term based on today's date, or None if between terms."""
        today = datetime.now(timezone.utc).date()
        for term, start in cls.TERM_START_DATES.items():
            if start.date() <= today <= cls.TERM_END_DATES[term].date():
                return term
        return None

    @classmethod
    def get_most_recent_completed_term(cls):
        """Returns the most recently completed term."""
        today = datetime.now(timezone.utc).date()
        completed_terms = [
            (term, end) for term, end in cls.TERM_END_DATES.items()
            if end.date() < today
        ]
        if completed_terms:
            return max(completed_terms, key=lambda x: x[1])[0]
        return None

    @classmethod
    def get_next_term(cls):
        """Returns the next upcoming term, or None if in current/last term."""
        today = datetime.now(timezone.utc).date()
        upcoming_terms = [
            (term, start) for term, start in cls.TERM_START_DATES.items()
            if start.date() > today
        ]
        if upcoming_terms:
            return min(upcoming_terms, key=lambda x: x[1])[0]
        return None

    @classmethod
    def is_between_terms(cls):
        """Returns True if currently between terms (on break), False otherwise."""
        return cls.get_current_term() is None

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
