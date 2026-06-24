"""LIVE end-to-end: bot SaaSClient -> running SaaS integration API (not mocked).

Requires the SaaS up on localhost:8000 + a valid school integration key.
Run:  E2E_KEY=<key> venv/bin/python tests/e2e_bot_saas.py
Not a unit test (needs live SaaS) — filename avoids unittest auto-discovery.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("USE_CLOUD_API", "true")

from api.sms_client import SaaSClient

BASE = os.getenv("E2E_SAAS_BASE", "http://localhost:8000/api/v1/integrations/whatsapp/")
KEY = os.getenv("E2E_KEY")
PHONE = os.getenv("E2E_PHONE", "+263798348393")
STUDENT = os.getenv("E2E_STUDENT", "SSC20236248")

assert KEY, "set E2E_KEY"

client = SaaSClient(
    tenant_config={"sms_api_base_url": BASE, "sms_api_key": KEY, "school_id": "3"},
    use_cloud_api=True,
)

print("1) resolve_by_phone ->", end=" ")
r = client.resolve_by_phone(PHONE)
assert r["count"] >= 1, f"expected >=1 student, got {r}"
names = [s["firstname"] for s in r["students"]]
print(f"OK count={r['count']} names={names}")

print("2) get_student_profile ->", end=" ")
p = client.get_student_profile(STUDENT)
assert p and p.get("data", {}).get("firstname"), f"no profile: {p}"
print(f"OK firstname={p['data']['firstname']} grade={p['data'].get('current_grade')}")

print("3) get_student_account_statement ->", end=" ")
st = client.get_student_account_statement(STUDENT, "2026-2")["data"]
assert isinstance(st["balance"], float), f"bad balance: {st}"
print(f"OK balance={st['balance']} total_fees={st['total_fees']} name={st['student_name']}")

print("\nE2E PASS — bot talks to live SaaS, returns real tenant-scoped data.")
