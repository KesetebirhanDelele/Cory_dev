create or replace function public.resolve_handoff(
  p_handoff    uuid,
  p_resolution jsonb
)
returns jsonb
language plpgsql
security definer
as $$
declare
  rec jsonb;
begin
  update public.handoffs
     set status = 'resolved',
         -- put resolution under payload.resolution
         payload = jsonb_set(
                     coalesce(payload, '{}'::jsonb),
                     '{resolution}',
                     coalesce(p_resolution, '{}'::jsonb),
                     true
                   ),
         resolved_at = now()
   where id = p_handoff
   returning to_jsonb(handoffs.*) into rec;

  if rec is null then
    raise exception 'handoff % not found', p_handoff using errcode = 'P0002';
  end if;

  return rec;
end
$$;

grant execute on function public.resolve_handoff(uuid, jsonb)
  to anon, authenticated, service_role;

-- refresh PostgREST schema cache
notify pgrst, 'reload schema';
