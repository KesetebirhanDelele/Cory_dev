# app/data/queries/variant_attribution.py
from typing import List, Dict, Any
from app.data.db import supabase  # uses the already-initialized Supabase client

def fetch_variant_attribution() -> List[Dict[str, Any]]:
    """
    Returns rows from the public view v_variant_attribution.
    Expected columns include: variant_id, delivery_rate, ...
    """
    resp = (
        supabase
        .table("v_variant_attribution")   # must be in the public schema
        .select("*")
        .order("variant_id", desc=False)
        .execute()
    )
    return resp.data or []
