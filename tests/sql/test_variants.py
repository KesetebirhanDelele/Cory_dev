# tests/sql/test_variants.py
from app.data.db import fetch_due_actions, fetch_due_sms
from app.data.queries.variant_attribution import fetch_variant_attribution

def test_variant_attribution_query():
    due_actions = fetch_due_actions()
    due_sms = fetch_due_sms()
    assert isinstance(due_actions, list)
    assert isinstance(due_sms, list)

    results = fetch_variant_attribution()  # sync call now
    assert isinstance(results, list)
    assert all("variant_id" in r for r in results)
    assert all("delivery_rate" in r for r in results)
    if results:
        sample = results[0]
        assert 0 <= sample["delivery_rate"] <= 100
