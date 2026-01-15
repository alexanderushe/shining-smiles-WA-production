# src/utils/whatsapp.py - FIXED VERSION
import re
import time
import requests
from utils.logger import setup_logger
from config import get_config

config = get_config()
logger = setup_logger(__name__)

# Accepts any international number in E.164 format (e.g., +263..., +1..., +44...)
PHONE_REGEX = re.compile(r'^\+[1-9]\d{7,14}$')

def sanitize_phone_number(number):
    """Remove spaces and invisible characters from phone number."""
    return re.sub(r"\s+", "", number)

def send_whatsapp_message(to, message, media_url=None, max_attempts=3, delay=2, use_cloud_api=True, filename="GatePass.pdf"):
    """
    Send a WhatsApp message using WhatsApp Cloud API.
    """
    to = sanitize_phone_number(to)
    extra_log = {"phone_number": to}

    # Auto-correct if user forgot the '+'
    if not to.startswith('+') and to.replace(' ', '').isdigit():
        to = f'+{to}'

    if not PHONE_REGEX.match(to):
        logger.error(f"Invalid phone number format: '{to}'", extra=extra_log)
        raise ValueError(f"Invalid phone number format: '{to}'")

    # WhatsApp Cloud API
    url = f"https://graph.facebook.com/v19.0/{config.WHATSAPP_CLOUD_NUMBER}/messages"
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_CLOUD_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    if media_url:
        payload.pop("text", None)
        # Check if it's a PDF (simple heuristic for pre-signed URLs)
        if ".pdf" in media_url.lower():
            payload["type"] = "document"
            payload["document"] = {"link": media_url, "caption": message, "filename": filename}
        else:
            payload["type"] = "image"
            payload["image"] = {"link": media_url, "caption": message}

    for attempt in range(max_attempts):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code >= 200 and response.status_code < 300:
                resp_json = response.json()
                logger.info(f"WhatsApp Cloud message sent to {to}: {resp_json.get('messages')}", extra=extra_log)
                return {"status": "sent", "response": resp_json}
            else:
                logger.warning(f"Cloud API error {response.status_code}: {response.text}", extra=extra_log)
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    continue
                response.raise_for_status()
        except Exception as e:
            logger.error(f"Error sending Cloud API message to {to} on attempt {attempt + 1}: {str(e)}", extra=extra_log)
            if attempt < max_attempts - 1:
                time.sleep(delay)
                continue
            raise