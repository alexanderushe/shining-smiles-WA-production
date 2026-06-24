-- Multi-tenant school_id migration.
-- Idempotent (safe to re-run), partial-DB safe (skips absent tables via
-- to_regclass), and atomic (whole thing commits or rolls back).
--
-- Scope: tags every bot-owned row with school_id so the scoped query layer
-- isolates tenants. Per-school UNIQUENESS of student_id / invoice_number is
-- intentionally DEFERRED: the global unique on student_contacts.student_id is
-- referenced by FKs (gate_passes, transport_passes), so converting it to a
-- composite (school_id, student_id) needs a coordinated FK rebuild. It is only
-- needed once two schools can share a student_id — do it in a dedicated
-- migration at 2nd-school onboarding. school_id + scoped queries already isolate
-- tenants without it.
BEGIN;

-- 1. Add school_id, backfill existing rows to 'default', enforce NOT NULL.
DO $$
DECLARE
  t text;
  tbls text[] := ARRAY[
    'student_contacts','gate_passes','gate_pass_scans','failed_syncs',
    'user_states','gate_pass_request_logs','transport_pass_request_log',
    'invoices','transport_passes','verification_codes'
  ];
BEGIN
  FOREACH t IN ARRAY tbls LOOP
    IF to_regclass('public.'||t) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS school_id VARCHAR(64) DEFAULT ''default''', t);
      EXECUTE format('UPDATE %I SET school_id = ''default'' WHERE school_id IS NULL', t);
      EXECUTE format('ALTER TABLE %I ALTER COLUMN school_id SET NOT NULL', t);
    END IF;
  END LOOP;
END $$;

-- 2. user_states primary key -> (school_id, phone_number). No FK depends on it,
--    so this is safe. Lets the same phone exist once PER school.
DO $$
BEGIN
  IF to_regclass('public.user_states') IS NOT NULL THEN
    ALTER TABLE user_states DROP CONSTRAINT IF EXISTS user_states_pkey;
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints
                   WHERE table_name = 'user_states' AND constraint_name = 'user_states_pkey') THEN
      ALTER TABLE user_states ADD CONSTRAINT user_states_pkey PRIMARY KEY (school_id, phone_number);
    END IF;
  END IF;
END $$;

COMMIT;
