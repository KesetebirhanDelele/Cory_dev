from __future__ import annotations
from typing import Any, Dict, List

# Rule row shape: {"dsl": {"if": {...}, "then": {"program_code": "X", "score": 0.9}}}

def evaluate_ruleset(lead: Dict[str, Any], rules: List[Dict[str, Any]]):
    scores, gaps, seen = [], [], set()
    interest = (lead.get("interest") or "").lower()
    zipc = (lead.get("zip") or "")
    gpa = float(lead.get("gpa") or 0)

    for r in rules:
        dsl = r.get("dsl", {})
        cond = dsl.get("if", {})
        ok = True
        if "interest_contains" in cond:
            ok &= cond["interest_contains"].lower() in interest
        if "zip_in" in cond:
            ok &= any(zipc.startswith(p.rstrip("*")) for p in cond["zip_in"])
        if "min_gpa" in cond:
            ok &= gpa >= float(cond["min_gpa"])

        code = dsl.get("then", {}).get("program_code")
        base = float(dsl.get("then", {}).get("score", 0.8))
        if ok and code and code not in seen:
            scores.append({"program_code": code, "score": base, "source": "rules"})
            seen.add(code)
        elif code:
            gaps.append(code)

    # Collapse duplicates by max score
    merged = {}
    for s in scores:
        merged[s["program_code"]] = max(merged.get(s["program_code"], 0.0), float(s["score"]))
    result = [{"program_code": k, "score": v, "source": "rules"} for k, v in merged.items()]
    return result, sorted(set(gaps))
