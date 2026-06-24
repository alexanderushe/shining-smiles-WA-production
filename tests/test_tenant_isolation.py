"""Phase 2 multi-tenancy guardrails.

Self-contained (in-memory sqlite, no Postgres/pytest). Run:
    python3 tests/test_tenant_isolation.py
Covers the two security-critical behaviours that had no test:
  1. unknown WhatsApp number must NOT fall back to the default school's creds
  2. school-scoped queries must never return another school's rows
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils import tenant_context as tc
from utils.database import (
    Base,
    StudentContact,
    find_contacts_by_phone,
    get_student_contact,
)
from utils.tenant_context import (
    reset_current_tenant,
    resolve_tenant_config,
    set_current_tenant,
)

ONE_TENANT = '{"111":{"school_id":"alpha","sms_api_key":"k1","display_phone_number":"+263771111111"}}'


class TenantResolution(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("WHATSAPP_TENANT_CONFIG", None)
        tc.load_tenant_config_map.cache_clear()

    def test_unknown_number_fails_closed_in_multitenant(self):
        os.environ["WHATSAPP_TENANT_CONFIG"] = ONE_TENANT
        tc.load_tenant_config_map.cache_clear()
        unknown = resolve_tenant_config({"phone_number_id": "999"})
        self.assertTrue(unknown.get("unrecognized"))
        self.assertIsNone(unknown.get("sms_api_key"))
        self.assertEqual(unknown.get("school_id"), "__unrecognized__")

    def test_known_number_resolves_its_tenant(self):
        os.environ["WHATSAPP_TENANT_CONFIG"] = ONE_TENANT
        tc.load_tenant_config_map.cache_clear()
        known = resolve_tenant_config({"phone_number_id": "111"})
        self.assertEqual(known["school_id"], "alpha")
        self.assertEqual(known["sms_api_key"], "k1")

    def test_no_map_uses_single_school_default(self):
        os.environ.pop("WHATSAPP_TENANT_CONFIG", None)
        tc.load_tenant_config_map.cache_clear()
        d = resolve_tenant_config({"phone_number_id": "999"})
        self.assertEqual(d["resolved_from"], "default")
        self.assertFalse(d.get("unrecognized"))


class ScopedQueries(unittest.TestCase):
    PHONE = "+263770000001"

    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        # Same phone, two different schools — the cross-tenant collision case.
        self.session.add(StudentContact(
            school_id="alpha", student_id="S1",
            guardian_mobile_number=self.PHONE, preferred_phone_number=self.PHONE))
        self.session.add(StudentContact(
            school_id="beta", student_id="S2",
            guardian_mobile_number=self.PHONE, preferred_phone_number=self.PHONE))
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def test_find_by_phone_returns_only_current_school(self):
        tok = set_current_tenant({"school_id": "alpha"})
        try:
            res = find_contacts_by_phone(self.session, self.PHONE)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0].school_id, "alpha")
        finally:
            reset_current_tenant(tok)

    def test_get_contact_isolated_across_schools(self):
        tok = set_current_tenant({"school_id": "beta"})
        try:
            self.assertEqual(get_student_contact(self.session, "S2").school_id, "beta")
            # alpha's student must be invisible from the beta tenant
            self.assertIsNone(get_student_contact(self.session, "S1"))
        finally:
            reset_current_tenant(tok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
