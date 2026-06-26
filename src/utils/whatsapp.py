import re
import time

import requests

from config import get_config
from utils.logger import setup_logger
from utils.tenant_context import get_current_tenant

config = get_config()
logger = setup_logger(__name__)

PHONE_REGEX = re.compile(r'^\+[1-9]\d{7,14}$')


def sanitize_phone_number(number):
    return re.sub(r"\s+", "", number)


def _resolve_cloud_credentials(tenant_config=None):
    tenant = tenant_config or get_current_tenant()
    token = tenant.get("whatsapp_cloud_api_token") or config.WHATSAPP_CLOUD_API_TOKEN
    phone_number_id = tenant.get("whatsapp_cloud_number") or tenant.get("phone_number_id") or config.WHATSAPP_CLOUD_NUMBER
    return tenant, token, phone_number_id


def send_whatsapp_message(
    to,
    message,
    media_url=None,
    max_attempts=3,
    delay=2,
    use_cloud_api=True,
    filename="GatePass.pdf",
    tenant_config=None,
):
    to = sanitize_phone_number(to)
    tenant, token, phone_number_id = _resolve_cloud_credentials(tenant_config=tenant_config)
    extra_log = {"phone_number": to, "school_id": tenant.get("school_id")}

    if not to.startswith('+') and to.replace(' ', '').isdigit():
        to = f'+{to}'

    if not PHONE_REGEX.match(to):
        logger.error(f"Invalid phone number format: '{to}'", extra=extra_log)
        raise ValueError(f"Invalid phone number format: '{to}'")

    if not token or not phone_number_id:
        logger.error("Missing WhatsApp Cloud credentials for tenant", extra=extra_log)
        raise ValueError("Missing WhatsApp Cloud credentials")

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    if media_url:
        payload.pop("text", None)
        if ".pdf" in media_url.lower():
            payload["type"] = "document"
            payload["document"] = {"link": media_url, "caption": message, "filename": filename}
        else:
            payload["type"] = "image"
            payload["image"] = {"link": media_url, "caption": message}

    for attempt in range(max_attempts):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if 200 <= response.status_code < 300:
                resp_json = response.json()
                logger.info(
                    f"WhatsApp Cloud message sent to {to}: {resp_json.get('messages')}",
                    extra=extra_log,
                )
                return {"status": "sent", "response": resp_json}
            logger.warning(f"Cloud API error {response.status_code}: {response.text}", extra=extra_log)
            if attempt < max_attempts - 1:
                time.sleep(delay)
                continue
            response.raise_for_status()
        except Exception as exc:
            logger.error(
                f"Error sending Cloud API message to {to} on attempt {attempt + 1}: {str(exc)}",
                extra=extra_log,
            )
            if attempt < max_attempts - 1:
                time.sleep(delay)
                continue
            raise


def send_whatsapp_template(
    to,
    template_name,
    language,
    body_params,
    document_link=None,
    document_filename="document.pdf",
    max_attempts=3,
    delay=2,
    tenant_config=None,
):
    """Send an approved WhatsApp template (business-initiated, works outside the
    24h window). Optional DOCUMENT header carries a PDF link; body_params fill the
    positional {{1}}..{{n}} placeholders in order.
    """
    to = sanitize_phone_number(to)
    tenant, token, phone_number_id = _resolve_cloud_credentials(tenant_config=tenant_config)
    extra_log = {"phone_number": to, "school_id": tenant.get("school_id")}
    if not to.startswith("+") and to.replace(" ", "").isdigit():
        to = f"+{to}"
    if not token or not phone_number_id:
        raise ValueError("Missing WhatsApp Cloud credentials")

    components = []
    if document_link:
        components.append({
            "type": "header",
            "parameters": [{"type": "document",
                            "document": {"link": document_link, "filename": document_filename}}],
        })
    components.append({
        "type": "body",
        "parameters": [{"type": "text", "text": str(p)} for p in body_params],
    })

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": components,
        },
    }

    for attempt in range(max_attempts):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if 200 <= response.status_code < 300:
                resp_json = response.json()
                logger.info(f"WhatsApp template '{template_name}' sent to {to}: {resp_json.get('messages')}",
                            extra=extra_log)
                return {"status": "sent", "response": resp_json}
            logger.warning(f"Template send error {response.status_code}: {response.text}", extra=extra_log)
            if attempt < max_attempts - 1:
                time.sleep(delay)
                continue
            response.raise_for_status()
        except Exception as exc:
            logger.error(f"Error sending template to {to} attempt {attempt + 1}: {exc}", extra=extra_log)
            if attempt < max_attempts - 1:
                time.sleep(delay)
                continue
            raise
