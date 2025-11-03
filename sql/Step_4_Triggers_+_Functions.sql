-- ==========================================================
-- 🧩 CORY DATABASE REBUILD SCRIPT — STEP 4 (Functions + Triggers)
-- ==========================================================
BEGIN;

-- ----------------------------------------------------------
-- 1️⃣  Generic “set_updated_at()” utility
-- ----------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------
-- 2️⃣  Auto-create tenant when project inserted
-- ----------------------------------------------------------
CREATE OR REPLACE FUNCTION public._test_autocreate_tenant_for_project()
RETURNS TRIGGER AS $$
DECLARE
  new_tenant_id uuid;
BEGIN
  IF NEW.tenant_id IS NULL THEN
    INSERT INTO public.tenant(name, created_at)
    VALUES (CONCAT('Auto-tenant for ', NEW.name), NOW())
    RETURNING id INTO new_tenant_id;

    NEW.tenant_id := new_tenant_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------
-- 3️⃣  Block writes on telemetry views (read-only guard)
-- ----------------------------------------------------------
CREATE OR REPLACE FUNCTION public.telemetry_view_block_write()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'Writes are not allowed on telemetry views';
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------
-- 4️⃣  Attach triggers
-- ----------------------------------------------------------

-- 🔹 Update timestamp automatically
CREATE TRIGGER trg_handoffs_set_updated_at
BEFORE UPDATE ON public.handoffs
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 🔹 Auto-create tenant for new project if missing
CREATE TRIGGER trg_test_autocreate_tenant
BEFORE INSERT ON public.project
FOR EACH ROW EXECUTE FUNCTION public._test_autocreate_tenant_for_project();

-- 🔹 Block writes to telemetry views
CREATE TRIGGER telemetry_view_no_insert
INSTEAD OF INSERT ON public.telemetry_view
FOR EACH ROW EXECUTE FUNCTION public.telemetry_view_block_write();

CREATE TRIGGER telemetry_view_no_update
INSTEAD OF UPDATE ON public.telemetry_view
FOR EACH ROW EXECUTE FUNCTION public.telemetry_view_block_write();

CREATE TRIGGER telemetry_view_no_delete
INSTEAD OF DELETE ON public.telemetry_view
FOR EACH ROW EXECUTE FUNCTION public.telemetry_view_block_write();

CREATE TRIGGER trg_appointments_set_updated_at
BEFORE UPDATE ON public.appointments
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER trg_nurture_campaigns_set_updated_at
BEFORE UPDATE ON public.nurture_campaigns
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER trg_reengagement_campaigns_set_updated_at
BEFORE UPDATE ON public.reengagement_campaigns
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

COMMIT;
