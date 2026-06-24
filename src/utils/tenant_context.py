import json
import os
import re
from contextvars import ContextVar
from functools import lru_cache

_CURRENT_TENANT = ContextVar("whatsapp_current_tenant", default=None)
_PHONE_DIGITS = re.compile(r"\D+")


def normalize_display_phone_number(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("+"):
        digits = "+" + _PHONE_DIGITS.sub("", text)
        return digits if len(digits) > 1 else None
    digits = _PHONE_DIGITS.sub("", text)
    if not digits:
        return None
    if text.startswith("00"):
        digits = digits[2:]
    if text.startswith("0") and len(digits) == 10:
        digits = "263" + digits[1:]
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits if len(digits) > 1 else None


def _normalize_tenant_config(raw_config):
    config = dict(raw_config or {})
    phone_number_id = (
        config.get("phone_number_id")
        or config.get("whatsapp_cloud_number")
        or config.get("whatsapp_phone_number_id")
        or config.get("sender_phone_number_id")
        or ""
    )
    display_phone_number = normalize_display_phone_number(
        config.get("display_phone_number")
        or config.get("whatsapp_phone_number")
        or config.get("display_number")
        or config.get("phone_number")
    )
    normalized = {
        "school_id": config.get("school_id") or config.get("slug") or config.get("code"),
        "school_name": config.get("school_name") or config.get("name"),
        "sms_api_base_url": config.get("sms_api_base_url") or config.get("SMS_API_BASE_URL") or os.getenv("SMS_API_BASE_URL"),
        "sms_api_key": config.get("sms_api_key") or config.get("SMS_API_KEY") or os.getenv("SMS_API_KEY"),
        "whatsapp_cloud_api_token": config.get("whatsapp_cloud_api_token") or config.get("WHATSAPP_CLOUD_API_TOKEN") or os.getenv("WHATSAPP_CLOUD_API_TOKEN"),
        "phone_number_id": str(phone_number_id).strip() if phone_number_id is not None else "",
        "whatsapp_cloud_number": str(phone_number_id).strip() if phone_number_id is not None else "",
        "display_phone_number": display_phone_number,
        "meta": config,
    }
    return normalized


def _candidate_keys(config, fallback_key=None):
    keys = []
    if fallback_key:
        keys.append(str(fallback_key).strip())
        normalized_fallback = normalize_display_phone_number(fallback_key)
        if normalized_fallback:
            keys.append(normalized_fallback)
    if config.get("phone_number_id"):
        keys.append(str(config["phone_number_id"]).strip())
    if config.get("display_phone_number"):
        keys.append(config["display_phone_number"])
    unique = []
    for key in keys:
        if key and key not in unique:
            unique.append(key)
    return unique


@lru_cache(maxsize=1)
def load_tenant_config_map():
    raw = (
        os.getenv("WHATSAPP_TENANT_CONFIG")
        or os.getenv("WHATSAPP_TENANT_CONFIG_JSON")
        or os.getenv("WHATSAPP_TENANTS_JSON")
    )
    if not raw:
        return {}

    parsed = json.loads(raw)
    records = []
    if isinstance(parsed, list):
        records = parsed
    elif isinstance(parsed, dict):
        if isinstance(parsed.get("tenants"), list):
            records = parsed["tenants"]
        elif all(isinstance(value, dict) for value in parsed.values()):
            for key, value in parsed.items():
                record = dict(value)
                record.setdefault("lookup_key", key)
                records.append(record)
        else:
            records = [parsed]

    resolved = {}
    for record in records:
        normalized = _normalize_tenant_config(record)
        for key in _candidate_keys(normalized, fallback_key=record.get("lookup_key")):
            resolved[key] = normalized
    return resolved


def get_default_tenant_config():
    return _normalize_tenant_config({})


def resolve_tenant_config(metadata=None):
    metadata = metadata or {}
    phone_number_id = metadata.get("phone_number_id")
    display_phone_number = metadata.get("display_phone_number")
    lookup = load_tenant_config_map()

    candidates = []
    if phone_number_id:
        candidates.append(str(phone_number_id).strip())
    if display_phone_number:
        candidates.append(str(display_phone_number).strip())
        normalized_display = normalize_display_phone_number(display_phone_number)
        if normalized_display:
            candidates.append(normalized_display)

    for candidate in candidates:
        if candidate and candidate in lookup:
            tenant = dict(lookup[candidate])
            tenant["resolved_from"] = candidate
            return tenant

    # No match. If a tenant map IS configured (multi-tenant mode), an unknown
    # number must NOT fall back to the default school's credentials — that would
    # serve one school's data to another, or to a school we deliberately removed
    # to cut off. The SaaS kill switch can't catch this (wrong key = wrong school),
    # so fail closed: strip creds + flag, and isolate any local writes.
    if lookup:
        tenant = get_default_tenant_config()
        tenant["sms_api_key"] = None
        tenant["sms_api_base_url"] = None
        tenant["whatsapp_cloud_api_token"] = None
        tenant["school_id"] = "__unrecognized__"
        tenant["unrecognized"] = True
        tenant["resolved_from"] = "unrecognized"
        return tenant

    # No tenant map => single-school deployment: env credentials are correct.
    tenant = get_default_tenant_config()
    tenant["resolved_from"] = "default"
    return tenant


def set_current_tenant(tenant_config):
    return _CURRENT_TENANT.set(tenant_config)


def reset_current_tenant(token):
    _CURRENT_TENANT.reset(token)


def get_current_tenant():
    return _CURRENT_TENANT.get() or get_default_tenant_config()
