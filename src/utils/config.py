# src/utils/config.py
import os

class Config:
    SMS_API_BASE_URL = os.getenv("SMS_API_BASE_URL")
    SMS_API_KEY = os.getenv("SMS_API_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:///shining_smiles.db")
    DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

def get_config():
    return Config()