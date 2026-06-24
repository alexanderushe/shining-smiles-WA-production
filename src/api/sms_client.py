import json
import os
import time
import uuid
from urllib.parse import urljoin

import requests
from ratelimit import RateLimitException, limits

from config import get_config
from utils.logger import setup_logger
from utils.tenant_context import get_current_tenant

config = get_config()
logger = setup_logger(__name__)


class LegacyCollection(list):
    """List-like payload that also supports legacy `.get(alias)` access."""

    def __init__(self, items=None, alias=None):
        super().__init__(items or [])
        self.alias = alias

    def get(self, key, default=None):
        if key == self.alias:
            return list(self)
        return default


class SaaSClient:
    """Compatibility client that reads from the Shining Smiles SaaS integration API."""

    def __init__(self, request_id=None, use_cloud_api=None, tenant_config=None):
        self.tenant_config = tenant_config or get_current_tenant()
        raw_base_url = ((self.tenant_config or {}).get("sms_api_base_url") or config.SMS_API_BASE_URL or "").rstrip("/") + "/"
        self.api_key = (self.tenant_config or {}).get("sms_api_key") or config.SMS_API_KEY
        self.request_id = request_id or str(uuid.uuid4())

        if use_cloud_api is not None:
            self.use_cloud_api = use_cloud_api
        else:
            self.use_cloud_api = os.getenv("USE_CLOUD_API", "False").lower() == "true"

        if not raw_base_url:
            logger.error("SMS_API_BASE_URL not set", extra={"request_id": self.request_id})
            raise ValueError("SMS_API_BASE_URL environment variable is required")
        if not self.api_key:
            logger.error("SMS_API_KEY not set", extra={"request_id": self.request_id})
            raise ValueError("SMS_API_KEY environment variable is required")

        marker = "/api/v1/integrations/whatsapp/"
        if marker in raw_base_url:
            root, _sep, _rest = raw_base_url.partition(marker)
            self.root_base_url = root.rstrip("/") + "/"
            self.integration_base_url = root.rstrip("/") + marker
        else:
            self.root_base_url = raw_base_url
            self.integration_base_url = urljoin(raw_base_url, "api/v1/integrations/whatsapp/")

        self.headers = {
            "Authorization": f"Api-Key {self.api_key.strip()}",
            "User-Agent": "ShiningSmilesWhatsApp/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-ID": self.request_id,
        }
        self.verify_ssl = getattr(config, "SMS_API_VERIFY_SSL", False)
        self.twilio_client = None

        logger.info(
            "Initializing SaaSClient with integration_base_url: %s, use_cloud_api: %s, request_id: %s, school_id: %s",
            self.integration_base_url,
            self.use_cloud_api,
            self.request_id,
            (self.tenant_config or {}).get("school_id"),
        )

        if not self.use_cloud_api:
            twilio_sid = getattr(config, "TWILIO_ACCOUNT_SID", None)
            twilio_token = getattr(config, "TWILIO_AUTH_TOKEN", None)
            if twilio_sid and twilio_token:
                from twilio.rest import Client as TwilioClient

                self.twilio_client = TwilioClient(twilio_sid, twilio_token)
                logger.info("Twilio client initialized", extra={"request_id": self.request_id})
            else:
                logger.warning("Twilio credentials missing", extra={"request_id": self.request_id})

    def safe_json_response(self, response):
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse JSON response: %s. Raw response: %s",
                str(exc),
                response.text,
                extra={"request_id": self.request_id},
            )
            return {"error": "Invalid JSON response", "raw": response.text}

    def _integration_path(self, path):
        return urljoin(self.integration_base_url, path.lstrip("/"))

    def _get(self, path, params=None, student_id=None):
        url = path if path.startswith("http") else self._integration_path(path)
        extra_log = {"request_id": self.request_id}
        if student_id:
            extra_log["student_id"] = student_id

        for attempt in range(3):
            try:
                logger.debug(
                    "Requesting %s | Params: %s | Headers: %s",
                    url,
                    params,
                    self.headers,
                    extra=extra_log,
                )
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=60,
                    verify=self.verify_ssl,
                )
                logger.debug("Response [%s]: %s", response.status_code, response.text, extra=extra_log)
                response.raise_for_status()
                return self.safe_json_response(response)
            except requests.HTTPError as exc:
                if exc.response.status_code == 429:
                    logger.warning("Rate limit hit on %s, attempt %s", url, attempt + 1, extra=extra_log)
                    raise RateLimitException("too many calls", 60)
                if exc.response.status_code == 404:
                    logger.warning("Resource not found: %s", url, extra=extra_log)
                    raise ValueError(f"Resource not found at {url}")
                logger.error("HTTP error on %s: %s", url, str(exc), extra=extra_log)
                raise
            except requests.RequestException as exc:
                if attempt < 2:
                    logger.warning(
                        "Transient error on %s, attempt %s: %s",
                        url,
                        attempt + 1,
                        str(exc),
                        extra=extra_log,
                    )
                    time.sleep(2)
                    continue
                logger.error("Failed after retries on %s: %s", url, str(exc), extra=extra_log)
                raise

    def _term_params(self, term):
        if not term:
            return {}
        parts = str(term).split("-", 1)
        if len(parts) == 2 and parts[0].isdigit():
            year, term_part = parts
            digits = "".join(ch for ch in term_part if ch.isdigit())
            if digits:
                return {"academic_year": year, "term": f"Term-{digits}"}
        return {"term": term}

    def _student_display_name(self, profile_data, fallback_student_id):
        firstname = (profile_data or {}).get("firstname", "")
        lastname = (profile_data or {}).get("lastname", "")
        full_name = f"{firstname} {lastname}".strip()
        if full_name:
            return f"[{fallback_student_id}] {full_name}"
        return fallback_student_id

    @limits(calls=10, period=60)
    def check_whatsapp_number(self, phone_number):
        extra_log = {"request_id": self.request_id, "phone_number": phone_number}
        try:
            if getattr(self, "use_cloud_api", False):
                logger.info(
                    "Cloud API mode: skipping Twilio lookup for %s",
                    phone_number,
                    extra=extra_log,
                )
                return True

            if not self.twilio_client:
                logger.warning("Twilio client not initialized — cannot verify number", extra=extra_log)
                return False

            lookup = self.twilio_client.lookups.v2.phone_numbers(phone_number).fetch(fields="whatsapp")
            is_registered = lookup.whatsapp.get("valid", False)
            logger.info(
                "[Twilio] %s WhatsApp lookup: %s",
                phone_number,
                "registered" if is_registered else "not registered",
                extra=extra_log,
            )
            return is_registered
        except Exception as exc:
            logger.error("Error checking WhatsApp number %s: %s", phone_number, exc, extra=extra_log)
            return getattr(self, "use_cloud_api", False)

    def check_api_health(self):
        try:
            health_url = urljoin(self.root_base_url, "api/v1/version/")
            logger.debug(
                "Checking API health: %s | Headers: %s",
                health_url,
                self.headers,
                extra={"request_id": self.request_id},
            )
            response = requests.get(
                health_url,
                headers=self.headers,
                timeout=5,
                verify=self.verify_ssl,
            )
            logger.info(
                "Health check response status: %s, Response: %s",
                response.status_code,
                response.text,
                extra={"request_id": self.request_id},
            )
            return response.status_code == 200
        except requests.RequestException as exc:
            logger.error("API health check failed: %s", str(exc), extra={"request_id": self.request_id})
            return False

    @limits(calls=10, period=60)
    def get_all_students(self, page=1, page_size=60):
        logger.warning(
            "get_all_students is deprecated against the SaaS integration API; returning no records. "
            "This path is removed in W2.4 with profile sync decommissioning.",
            extra={"request_id": self.request_id, "page": page, "page_size": page_size},
        )
        if False:
            yield None
        return

    @limits(calls=10, period=60)
    def resolve_by_phone(self, phone_number):
        """Phone -> student(s) live from the SaaS (replaces the dead profile sync
        / local-cache lookup). Returns bot-friendly contact dicts; a guardian
        number can map to several siblings."""
        try:
            payload = self._get("resolve/", params={"phone": phone_number})
        except ValueError:
            return {"count": 0, "students": [], "data": []}
        students = payload.get("students", []) if isinstance(payload, dict) else []
        results = []
        for s in students:
            results.append({
                "student_id": s.get("student_number") or str(s.get("id")),
                "firstname": s.get("first_name"),
                "lastname": s.get("last_name"),
                "current_grade": s.get("current_grade"),
                "status": s.get("status"),
                "outstanding_balance": s.get("outstanding_balance"),
                "preferred_phone_number": phone_number,
            })
        return {"count": len(results), "students": results, "data": results}

    @limits(calls=10, period=60)
    def get_student_profile(self, student_id):
        try:
            return self._get(f"students/{student_id}/profile/", student_id=student_id)
        except RateLimitException:
            logger.warning(
                "Rate limit hit on get_student_profile for %s",
                student_id,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except ValueError:
            logger.warning(
                "Profile not found for %s: 404 Not Found",
                student_id,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            return None
        except requests.RequestException as exc:
            logger.error(
                "Error fetching profile: %s",
                str(exc),
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise

    @limits(calls=10, period=60)
    def get_student_account_statement(self, student_id, term):
        try:
            statement = self._get(
                f"students/{student_id}/statement/",
                params=self._term_params(term),
                student_id=student_id,
            )
            profile = self.get_student_profile(student_id) or {"data": {}}
            profile_data = profile.get("data", {})
            student = statement.get("student", {}) if isinstance(statement, dict) else {}
            invoices = statement.get("invoices", []) if isinstance(statement, dict) else []
            total_fees = sum(float(invoice.get("total_amount", 0) or 0) for invoice in invoices)
            balance = statement.get("outstanding_balance", 0) if isinstance(statement, dict) else 0
            return {
                "data": {
                    "student_name": self._student_display_name(profile_data, student_id),
                    "current_grade": profile_data.get("current_grade") or student.get("current_grade") or "Unknown",
                    "total_fees": total_fees,
                    "balance": float(balance or 0),
                    "student_id": student_id,
                    "student_number": student.get("student_number") or student_id,
                    "invoices": invoices,
                }
            }
        except RateLimitException:
            logger.warning(
                "Rate limit hit on get_student_account_statement for %s, term %s",
                student_id,
                term,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except ValueError:
            logger.warning(
                "Account statement not found for student_id: %s, term: %s",
                student_id,
                term,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except requests.RequestException as exc:
            logger.error(
                "Error fetching account statement: %s",
                str(exc),
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise

    @limits(calls=10, period=60)
    def get_student_payments(self, student_id, term):
        try:
            payload = self._get(
                f"students/{student_id}/payments/",
                params=self._term_params(term),
                student_id=student_id,
            )
            payments = payload.get("payments", []) if isinstance(payload, dict) else []
            wrapped = LegacyCollection(payments, alias="payments")
            return {"data": wrapped, "payments": payments, "student_id": student_id}
        except RateLimitException:
            logger.warning(
                "Rate limit hit on get_student_payments for %s, term %s",
                student_id,
                term,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except ValueError:
            logger.warning(
                "Payments not found for student_id: %s, term: %s",
                student_id,
                term,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except requests.RequestException as exc:
            logger.error(
                "Error fetching payments: %s",
                str(exc),
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise

    @limits(calls=10, period=60)
    def get_student_billed_fees(self, student_id, term):
        try:
            payload = self._get(
                f"students/{student_id}/billed-fees/",
                params=self._term_params(term),
                student_id=student_id,
            )
            invoices = payload.get("invoices", []) if isinstance(payload, dict) else []
            bills = []
            for invoice in invoices:
                items = invoice.get("items") or []
                if items:
                    for item in items:
                        bills.append(
                            {
                                "fee_type": item.get("description") or "Fee",
                                "amount": item.get("amount") or "0",
                                "term": invoice.get("term"),
                                "academic_year": invoice.get("academic_year"),
                            }
                        )
                else:
                    bills.append(
                        {
                            "fee_type": f"Invoice {invoice.get('term', '')}".strip(),
                            "amount": invoice.get("total_amount") or "0",
                            "term": invoice.get("term"),
                            "academic_year": invoice.get("academic_year"),
                        }
                    )
            wrapped = LegacyCollection(bills, alias="bills")
            return {"data": wrapped, "bills": bills, "student_id": student_id}
        except RateLimitException:
            logger.warning(
                "Rate limit hit on get_student_billed_fees for %s, term %s",
                student_id,
                term,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except ValueError:
            logger.warning(
                "Billed fees not found for student_id: %s, term: %s",
                student_id,
                term,
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except requests.RequestException as exc:
            logger.error(
                "Error fetching billed fees: %s",
                str(exc),
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise

    @limits(calls=10, period=60)
    def get_students_in_debt(self, student_id=None):
        try:
            offset = 0
            limit = 500
            debtors = []
            while True:
                payload = self._get(
                    "debtors/",
                    params={"limit": limit, "offset": offset},
                    student_id=student_id,
                )
                page = payload.get("debtors", []) if isinstance(payload, dict) else []
                for debtor in page:
                    if student_id and debtor.get("student_number") != student_id:
                        continue
                    debtors.append(
                        {
                            "student": {
                                "student_number": debtor.get("student_number"),
                                "full_name": debtor.get("full_name"),
                                "current_grade": debtor.get("current_grade"),
                            },
                            "outstanding_balance": debtor.get("outstanding_balance"),
                            "days_overdue": debtor.get("days_overdue"),
                            "parent_phone": debtor.get("parent_phone"),
                            "guardian1_phone": debtor.get("guardian1_phone"),
                        }
                    )
                count = payload.get("count", len(debtors)) if isinstance(payload, dict) else len(debtors)
                offset += len(page)
                if student_id or not page or offset >= count:
                    break
            return {"data": debtors, "count": len(debtors)}
        except RateLimitException:
            logger.warning(
                "Rate limit hit on get_students_in_debt for %s",
                student_id or "all students",
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except ValueError:
            logger.warning(
                "Debt data not found for %s",
                student_id or "all students",
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise
        except requests.RequestException as exc:
            logger.error(
                "Error fetching debt data: %s",
                str(exc),
                extra={"request_id": self.request_id, "student_id": student_id},
            )
            raise


class SMSClient(SaaSClient):
    """Backward-compatible name kept while the bot migrates to SaaSClient imports."""

    pass
