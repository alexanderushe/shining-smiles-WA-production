import os
import requests
import json
import uuid
from utils.logger import setup_logger
from config import get_config
from ratelimit import limits, RateLimitException
import time
from urllib.parse import urljoin

config = get_config()
logger = setup_logger(__name__)

class SMSClient:
    """Client for Shining Smiles SMS and WhatsApp API."""
    def __init__(self, request_id=None):
        self.base_url = config.SMS_API_BASE_URL.rstrip("/") + "/"
        self.api_key = config.SMS_API_KEY
        self.request_id = request_id or str(uuid.uuid4())
        self.use_cloud_api = os.getenv("USE_CLOUD_API", "False").lower() == "true"
        logger.info(f"Initializing SMSClient with base_url: {self.base_url}, use_cloud_api: {self.use_cloud_api}, request_id: {self.request_id}")

        if not self.base_url:
            logger.error("SMS_API_BASE_URL not set", extra={"request_id": self.request_id})
            raise ValueError("SMS_API_BASE_URL environment variable is required")
        if not self.api_key:
            logger.error("SMS_API_KEY not set", extra={"request_id": self.request_id})
            raise ValueError("SMS_API_KEY environment variable is required")

        self.headers = {
            "Authorization": f"Api-Key {self.api_key.strip()}",
            "User-Agent": "ShiningSmilesWhatsApp/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-ID": self.request_id
        }

        self.verify_ssl = getattr(config, "SMS_API_VERIFY_SSL", False)
        self.twilio_client = None
        if not self.use_cloud_api:
            # Initialize Twilio only if not using Cloud API
            twilio_sid = getattr(config, 'TWILIO_ACCOUNT_SID', None)
            twilio_token = getattr(config, 'TWILIO_AUTH_TOKEN', None)
            if twilio_sid and twilio_token:
                from twilio.rest import Client as TwilioClient
                self.twilio_client = TwilioClient(twilio_sid, twilio_token)
                logger.info("Twilio client initialized", extra={"request_id": self.request_id})
            else:
                logger.warning("Twilio credentials missing", extra={"request_id": self.request_id})

    def safe_json_response(self, response):
        """Parse JSON response safely."""
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {str(e)}. Raw response: {response.text}", 
                         extra={"request_id": self.request_id})
            return {"error": "Invalid JSON response", "raw": response.text}

    def _get(self, path, params=None, student_id=None):
        """Centralized GET request handler with retry logic."""
        url = path if path.startswith("http") else urljoin(self.base_url, path.lstrip("/"))
        extra_log = {"request_id": self.request_id}
        if student_id:
            extra_log["student_id"] = student_id

        for attempt in range(3):
            try:
                logger.debug(f"Requesting {url} | Params: {params} | Headers: {self.headers}", extra=extra_log)
                response = requests.get(url, headers=self.headers, params=params, timeout=30, verify=self.verify_ssl)
                logger.debug(f"Response [{response.status_code}]: {response.text}", extra=extra_log)
                response.raise_for_status()
                return self.safe_json_response(response)
            except requests.HTTPError as e:
                if e.response.status_code == 429:
                    logger.warning(f"Rate limit hit on {url}, attempt {attempt + 1}", extra=extra_log)
                    raise RateLimitException("too many calls", 60)
                if e.response.status_code == 404:
                    logger.warning(f"Resource not found: {url}", extra=extra_log)
                    raise ValueError(f"Resource not found at {url}")
                logger.error(f"HTTP error on {url}: {str(e)}", extra=extra_log)
                raise
            except requests.RequestException as e:
                if attempt < 2:
                    logger.warning(f"Transient error on {url}, attempt {attempt + 1}: {str(e)}", extra=extra_log)
                    time.sleep(2)
                    continue
                logger.error(f"Failed after retries on {url}: {str(e)}", extra=extra_log)
                raise

    @limits(calls=10, period=60)
    def check_whatsapp_number(self, phone_number):
        """
        Check if a phone number is registered on WhatsApp.
        - Uses Twilio Lookup in sandbox/dev mode.
        - Uses Cloud API in production mode.
        """
        extra_log = {"request_id": self.request_id, "phone_number": phone_number}
        try:
            if getattr(self, "use_cloud_api", False):
                logger.info(f"Cloud API mode: skipping Twilio lookup for {phone_number}", extra=extra_log)
                # In Cloud API mode, assume WhatsApp number validity is handled by API response
                return True

            if not self.twilio_client:
                logger.warning("Twilio client not initialized — cannot verify number", extra=extra_log)
                return False

            lookup = self.twilio_client.lookups.v2.phone_numbers(phone_number).fetch(fields="whatsapp")
            is_registered = lookup.whatsapp.get("valid", False)
            logger.info(f"[Twilio] {phone_number} WhatsApp lookup: {'registered' if is_registered else 'not registered'}",
                        extra=extra_log)
            return is_registered

        except Exception as e:
            logger.error(f"Error checking WhatsApp number {phone_number}: {e}", extra=extra_log)
            # Fallback logic
            return getattr(self, "use_cloud_api", False)


    def check_api_health(self):
        """Check SMS API health status."""
        try:
            health_url = urljoin(self.base_url, "health")
            logger.debug(f"Checking API health: {health_url} | Headers: {self.headers}", extra={"request_id": self.request_id})
            response = requests.get(health_url, headers=self.headers, timeout=5, verify=self.verify_ssl)
            logger.info(f"Health check response status: {response.status_code}, Response: {response.text}",
                        extra={"request_id": self.request_id})
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"API health check failed: {str(e)}", extra={"request_id": self.request_id})
            return False

    @limits(calls=10, period=60)
    def get_all_students(self, page=1, page_size=60):
        """Fetch all students with pagination, yielding each student."""
        url = "school/students/data"  # Remove leading slash to ensure correct URL construction
        while url:
            for attempt in range(3):
                try:
                    params = {"page": page, "page_size": page_size}
                    data = self._get(url, params=params)
                    if data.get("error"):
                        logger.error(f"Error in response: {data['error']}", extra={"request_id": self.request_id})
                        return
                    for student in data.get("results", {}).get("data", []):
                        yield student
                    url = data.get("next")
                    page += 1
                    break
                except RateLimitException:
                    logger.warning(f"Rate limit hit on get_all_students, page {page}", extra={"request_id": self.request_id})
                    raise
                except ValueError as e:
                    logger.error(f"Error fetching students: {str(e)}", extra={"request_id": self.request_id})
                    return
                except requests.RequestException as e:
                    logger.error(f"Error fetching students: {str(e)}", extra={"request_id": self.request_id})
                    return

    @limits(calls=10, period=60)
    def get_student_account_statement(self, student_id, term):
        """Fetch student account statement."""
        try:
            params = {"student_id_number": student_id, "term": term}
            return self._get("student-account-statement/", params=params, student_id=student_id)
        except RateLimitException:
            logger.warning(f"Rate limit hit on get_student_account_statement for {student_id}, term {term}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except ValueError as e:
            logger.warning(f"Account statement not found for student_id: {student_id}, term: {term}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except requests.RequestException as e:
            logger.error(f"Error fetching account statement: {str(e)}",
                         extra={"request_id": self.request_id, "student_id": student_id})
            raise

    @limits(calls=10, period=60)
    def get_student_payments(self, student_id, term):
        """Fetch student payment data."""
        try:
            params = {"student_id_number": student_id, "term": term}
            return self._get("student/payments/", params=params, student_id=student_id)
        except RateLimitException:
            logger.warning(f"Rate limit hit on get_student_payments for {student_id}, term {term}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except ValueError as e:
            logger.warning(f"Payments not found for student_id: {student_id}, term: {term}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except requests.RequestException as e:
            logger.error(f"Error fetching payments: {str(e)}",
                         extra={"request_id": self.request_id, "student_id": student_id})
            raise

    @limits(calls=10, period=60)
    def get_student_billed_fees(self, student_id, term):
        """Fetch student billed fee types for a term."""
        try:
            params = {"student_id_number": student_id, "term": term}
            return self._get("student/billed-fee-types/", params=params, student_id=student_id)
        except RateLimitException:
            logger.warning(f"Rate limit hit on get_student_billed_fees for {student_id}, term {term}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except ValueError as e:
            logger.warning(f"Billed fees not found for student_id: {student_id}, term: {term}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except requests.RequestException as e:
            logger.error(f"Error fetching billed fees: {str(e)}",
                         extra={"request_id": self.request_id, "student_id": student_id})
            raise

    @limits(calls=10, period=60)
    def get_students_in_debt(self, student_id=None):
        """Fetch students with outstanding balances."""
        try:
            params = {"student_id_number": student_id} if student_id else {}
            return self._get("students/accounts-in-debt/", params=params, student_id=student_id)
        except RateLimitException:
            logger.warning(f"Rate limit hit on get_students_in_debt for {student_id or 'all students'}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except ValueError as e:
            logger.warning(f"Debt data not found for {student_id or 'all students'}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except requests.RequestException as e:
            logger.error(f"Error fetching debt data: {str(e)}",
                         extra={"request_id": self.request_id, "student_id": student_id})
            raise

    @limits(calls=10, period=60)
    def get_student_profile(self, student_id):
        """Fetch student profile."""
        try:
            params = {"student_id_number": student_id}
            return self._get("student/profile/", params=params, student_id=student_id)
        except RateLimitException:
            logger.warning(f"Rate limit hit on get_student_profile for {student_id}",
                          extra={"request_id": self.request_id, "student_id": student_id})
            raise
        except ValueError:
            logger.warning(f"Profile not found for {student_id}: 404 Not Found",
                          extra={"request_id": self.request_id, "student_id": student_id})
            return None
        except requests.RequestException as e:
            logger.error(f"Error fetching profile: {str(e)}",
                         extra={"request_id": self.request_id, "student_id": student_id})
            raise