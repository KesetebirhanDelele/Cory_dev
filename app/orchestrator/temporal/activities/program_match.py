# app/orchestrator/temporal/activities/program_match.py
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
import urllib.parse
from dataclasses import dataclass
from functools import wraps
from typing import Any, Dict, List, Optional

from temporalio import activity

# ---------------------------------------------
# Optional asyncpg (we'll prefer REST if blocked)
# ---------------------------------------------
try:
    import asyncpg  # optional; used only if DATABASE_URL* present
except Exception:  # pragma: no cover
    asyncpg = None  # type: ignore

# ---------------------------------------------
# Tracing decorator (no-op fallback)
# ---------------------------------------------
try:
    from app.common.tracing import trace  # type: ignore
except Exception:

    def trace(_name: str):
        def deco(fn):
            if asyncio.iscoroutinefunction(fn):
                @wraps(fn)
                async def aw(*a, **k):
                    return await fn(*a, **k)

                return aw
            else:
                @wraps(fn)
                def sw(*a, **k):
                    return fn(*a, **k)

                return sw

        return deco


# ---------------------------------------------
# Budget & thresholds (robust imports w/ env fallbacks)
# ---------------------------------------------
try:
    from app.policy.guards_budget import LLM_DAILY_BUDGET_CENTS as _IMPORTED_LLM_BUDGET_CENTS
    LLM_BUDGET_CENTS = int(_IMPORTED_LLM_BUDGET_CENTS)
except Exception:
    LLM_BUDGET_CENTS = int(os.getenv("LLM_DAILY_BUDGET_CENTS", "500"))

try:
    from app.policy.guards import CONFIDENCE_THRESHOLD as _IMPORTED_CONF_T
    CONFIDENCE_THRESHOLD = float(_IMPORTED_CONF_T)
except Exception:
    CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))

# ---------------------------------------------
# Rules engine
# ---------------------------------------------
from app.policy.matching_dsl import evaluate_ruleset

# ---------------------------------------------
# Supabase REST config (HTTPS/443)
# ---------------------------------------------
_SB_URL = os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_PROJECT_URL")
_SB_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")


# ---------------------------------------------
# Minimal async HTTP (stdlib only)
# ---------------------------------------------
import json as _json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


async def _http_request(method: str, url: str, headers: Dict[str, str], body: Optional[dict] = None) -> Any:
    def _do():
        data = None
        if body is not None:
            data = _json.dumps(body).encode("utf-8")
        req = Request(url, data=data, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if not raw:
                    return None
                try:
                    return _json.loads(raw.decode("utf-8"))
                except Exception:
                    return raw.decode("utf-8")
        except HTTPError as e:
            # Read error payload so we can see PostgREST/PG failure details
            err_body = e.read().decode("utf-8", "ignore")
            try:
                err_json = _json.loads(err_body)
            except Exception:
                err_json = {"raw": err_body}
            # Raise a descriptive error so Temporal logs show the reason
            raise RuntimeError(f"HTTP {e.code} on {url} :: {err_json}") from e

    return await asyncio.to_thread(_do)

def _sb_headers() -> Dict[str, str]:
    if not _SB_URL or not _SB_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for REST mode"
        )
    return {
        "apikey": _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }


def _q(params: Dict[str, str]) -> str:
    return urllib.parse.urlencode(params, doseq=True, safe="*.,()")


# ---------------------------------------------
# asyncpg pool helper + selector
# ---------------------------------------------
_POOL_CACHE = None


async def _get_pg_pool_or_none():
    """Create/use asyncpg pool if DATABASE_URL/SUPABASE_DB_URL/POSTGRES_URL exists."""
    global _POOL_CACHE
    if _POOL_CACHE is not None:
        return _POOL_CACHE

    db_url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("POSTGRES_URL")
    )
    if not db_url or asyncpg is None:
        return None

    u = urllib.parse.urlparse(db_url)
    host = (u.hostname or "").lower()
    q = dict(urllib.parse.parse_qsl(u.query or ""))
    sslctx = None
    if "supabase.co" in host or q.get("sslmode") in {"require", "verify-ca", "verify-full"}:
        sslctx = ssl.create_default_context()
        sslctx.check_hostname = True
        sslctx.verify_mode = ssl.CERT_REQUIRED

    try:
        _POOL_CACHE = await asyncpg.create_pool(
            dsn=db_url,
            min_size=1,
            max_size=5,
            timeout=45.0,
            command_timeout=60.0,
            ssl=sslctx,
        )
        return _POOL_CACHE
    except Exception:
        return None


async def _use_rest() -> bool:
    """Prefer PG if a pool is available; otherwise REST if configured."""
    pool = await _get_pg_pool_or_none()
    if pool is not None:
        return False
    if _SB_URL and _SB_KEY:
        return True
    raise RuntimeError(
        "No DB connectivity: asyncpg pool not available and Supabase REST not configured. "
        "Set DATABASE_URL *or* SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY."
    )


# ---------------------------------------------
# REST helpers (specific queries)
# ---------------------------------------------
async def _rest_select_programs_active():
    url = f"{_SB_URL}/rest/v1/programs?{_q({'select':'id,code,name', 'active':'is.true', 'order':'code'})}"
    return await _http_request("GET", url, _sb_headers())


async def _rest_select_rules_latest():
    url = f"{_SB_URL}/rest/v1/persona_rules?{_q({'select':'id,version,rule_name,priority,dsl', 'order':'version.desc,priority.asc'})}"
    return await _http_request("GET", url, _sb_headers())


async def _rest_select_lead_by_id(lead_id: str):
    url = f"{_SB_URL}/rest/v1/leads?{_q({'select':'*', 'id': f'eq.{lead_id}', 'limit':'1'})}"
    rows = await _http_request("GET", url, _sb_headers())
    return rows[0] if rows else None


async def _rest_select_rules_by_version(version: int):
    url = f"{_SB_URL}/rest/v1/persona_rules?{_q({'select':'dsl,priority', 'version': f'eq.{version}', 'order':'priority.asc'})}"
    return await _http_request("GET", url, _sb_headers())


async def _rest_select_program_ids_by_codes(codes: List[str]) -> Dict[str, str]:
    if not codes:
        return {}
    in_list = "(" + ",".join(codes) + ")"
    url = f"{_SB_URL}/rest/v1/programs?{_q({'select':'id,code', 'code': f'in.{in_list}'})}"
    rows = await _http_request("GET", url, _sb_headers())
    return {str(r["code"]): str(r["id"]) for r in (rows or [])}

async def _rest_upsert_lead_program_scores(rows: List[Dict[str, Any]]):
    # ensure we don't send duplicates in a single statement
    rows = _dedupe_lps_rows(rows)

    bulk_url = (
        f"{_SB_URL}/rest/v1/lead_program_scores"
        f"?on_conflict=lead_id,program_id,fingerprint"
    )
    headers = dict(_sb_headers())
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"

    # First, try bulk upsert
    try:
        return await _http_request("POST", bulk_url, headers, body=rows)
    except RuntimeError as e:
        msg = str(e)
        # Postgres 21000: "cannot affect row a second time" (duplicate targets in same batch)
        if " 21000" in msg or "cannot affect row a second time" in msg:
            out = []
            for r in rows:
                try:
                    res = await _http_request("POST", bulk_url, headers, body=[r])
                    out.append(res)
                except RuntimeError as e2:
                    raise RuntimeError(f"Upsert failed for row {r}: {e2}") from e2
            return out
        raise

def _dedupe_lps_rows(rows):
    """Keep only the highest score per (lead_id, program_id, fingerprint)."""
    best = {}
    for r in rows:
        key = (r["lead_id"], r["program_id"], r["fingerprint"])
        cur = best.get(key)
        if (cur is None
            or float(r["score"]) > float(cur["score"])
            or (float(r["score"]) == float(cur["score"])
                and cur.get("source") == "llm" and r.get("source") == "rules")):
            best[key] = r
    return list(best.values())

# ---------------------------------------------
# Normalization helpers
# ---------------------------------------------
async def _normalize_scores_to_ids(
    scores: List[dict],
    *,
    use_rest: bool,
) -> List[dict]:
    """
    Normalize items to:
      {'program_id': <uuid>, 'score': <float>, 'source': 'rules'|'llm'}
    Accept input shapes per item:
      {'program_id': 'uuid', 'score': 0.9, 'source': 'rules'}
      {'program_code': 'BUS-BA', 'score': 0.9, 'source': 'rules'}
      {'code': 'BUS-BA', 'score': 0.9, 'source': 'rules'}
    """
    if not scores:
        return []

    # If already normalized
    if all("program_id" in s for s in scores):
        return [
            {
                "program_id": str(s["program_id"]),
                "score": float(s["score"]),
                "source": s.get("source", "rules"),
            }
            for s in scores
            if s.get("program_id") is not None
        ]

    # Collect codes that need mapping
    code_keys = ("program_code", "code")
    codes: List[str] = []
    for s in scores:
        for k in code_keys:
            if k in s and s[k]:
                codes.append(str(s[k]))
                break

    id_by_code: Dict[str, str] = {}
    if codes:
        if use_rest:
            id_by_code = await _rest_select_program_ids_by_codes(codes)
        else:
            pool = await _get_pg_pool_or_none()
            assert pool is not None
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "select id, code from programs where code = any($1)", codes
                )
                id_by_code = {str(r["code"]): str(r["id"]) for r in rows}

    normalized: List[dict] = []
    for s in scores:
        if s.get("program_id"):
            normalized.append(
                {
                    "program_id": str(s["program_id"]),
                    "score": float(s["score"]),
                    "source": s.get("source", "rules"),
                }
            )
            continue
        code = s.get("program_code") or s.get("code")
        if code and code in id_by_code:
            normalized.append(
                {
                    "program_id": id_by_code[code],
                    "score": float(s["score"]),
                    "source": s.get("source", "rules"),
                }
            )
        # If code is unknown, skip silently (no-op)
    return normalized


# ---------------------------------------------
# Activities
# ---------------------------------------------
@dataclass
class RuleBundle:
    version: int
    programs: List[Dict[str, Any]]
    rules: List[Dict[str, Any]]  # ordered by priority


@activity.defn
@trace("match.load_rules")
async def load_rules() -> Dict[str, Any]:
    if await _use_rest():
        prows = await _rest_select_programs_active()
        rules_all = await _rest_select_rules_latest()
        latest_version = rules_all[0]["version"] if rules_all else 1
        ruleset = [dict(r) for r in rules_all if r["version"] == latest_version]
        return {
            "version": latest_version,
            "programs": [dict(r) for r in (prows or [])],
            "rules": ruleset,
        }

    # asyncpg path
    pool = await _get_pg_pool_or_none()
    assert pool is not None
    async with pool.acquire() as conn:
        prows = await conn.fetch(
            "select id, code, name from programs where active=true order by code"
        )
        rules = await conn.fetch(
            """
            select id, version, rule_name, priority, dsl
            from persona_rules
            order by version desc, priority asc
        """
        )
    latest_version = rules[0]["version"] if rules else 1
    ruleset = [dict(r) for r in rules if r["version"] == latest_version]
    return {
        "version": latest_version,
        "programs": [dict(r) for r in prows],
        "rules": ruleset,
    }


@activity.defn
@trace("match.deterministic_score")
async def deterministic_score(params: Dict[str, Any]) -> Dict[str, Any]:
    lead_id = params["lead_id"]
    rules_version = params["rules_version"]

    if await _use_rest():
        lead = await _rest_select_lead_by_id(lead_id)
        if not lead:
            raise activity.ApplicationError(
                f"lead {lead_id} not found", non_retryable=True
            )

        # tolerant field extraction
        interest = (
            lead.get("interest")
            or lead.get("program_interest")
            or (lead.get("metadata") or {}).get("interest")
            or lead.get("notes")
            or ""
        )
        zipc = (
            lead.get("zip")
            or lead.get("postal_code")
            or (lead.get("metadata") or {}).get("zip")
            or (lead.get("address") or {}).get("postal_code")
        )

        fp_src = json.dumps(
            {
                "v": rules_version,
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "zip": zipc,
                "interest": interest,
            },
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fp_src.encode()).hexdigest()[:32]
        rules = await _rest_select_rules_by_version(rules_version)
        raw_scores, gaps = evaluate_ruleset(
            {**lead, "zip": zipc, "interest": interest}, [dict(r) for r in (rules or [])]
        )
        norm_scores = await _normalize_scores_to_ids(raw_scores, use_rest=True)
        return {"scores": norm_scores, "gaps": gaps, "fingerprint": fingerprint}

    # asyncpg path
    pool = await _get_pg_pool_or_none()
    assert pool is not None
    async with pool.acquire() as conn:
        lead = await conn.fetchrow("select * from leads where id=$1", lead_id)
        if not lead:
            raise activity.ApplicationError(
                f"lead {lead_id} not found", non_retryable=True
            )
        lead = dict(lead)

        interest = (
            lead.get("interest")
            or lead.get("program_interest")
            or (lead.get("metadata") or {}).get("interest")
            or lead.get("notes")
            or ""
        )
        zipc = (
            lead.get("zip")
            or lead.get("postal_code")
            or (lead.get("metadata") or {}).get("zip")
            or (lead.get("address") or {}).get("postal_code")
        )

        fp_src = json.dumps(
            {
                "v": rules_version,
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "zip": zipc,
                "interest": interest,
            },
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fp_src.encode()).hexdigest()[:32]
        rules = await conn.fetch(
            "select dsl, priority from persona_rules where version=$1 order by priority",
            rules_version,
        )

    raw_scores, gaps = evaluate_ruleset(
        {**lead, "zip": zipc, "interest": interest}, [dict(r) for r in (rules or [])]
    )
    norm_scores = await _normalize_scores_to_ids(raw_scores, use_rest=False)
    return {"scores": norm_scores, "gaps": gaps, "fingerprint": fingerprint}


@activity.defn
@trace("match.llm_score_fallback")
async def llm_score_fallback(params: Dict[str, Any]) -> Dict[str, Any]:
    if LLM_BUDGET_CENTS <= 0:
        return {"scores": []}

    lead_id = params["lead_id"]
    gaps: List[str] = params.get("gaps", [])

    if await _use_rest():
        # existence check
        lead = await _rest_select_lead_by_id(lead_id)
        if not lead:
            raise activity.ApplicationError(
                f"lead {lead_id} not found", non_retryable=True
            )

        # placeholder LLM scores per gap code
        resp_scores = {code: 0.65 for code in gaps}
        id_by_code = await _rest_select_program_ids_by_codes(gaps)
        final = [
            {"program_id": id_by_code[c], "score": s, "source": "llm"}
            for c, s in resp_scores.items()
            if c in id_by_code and float(s) >= float(CONFIDENCE_THRESHOLD)
        ]
        return {"scores": final}

    # asyncpg path
    pool = await _get_pg_pool_or_none()
    assert pool is not None
    async with pool.acquire() as conn:
        _ = await conn.fetchrow("select id from leads where id=$1", lead_id)
        prows = await conn.fetch(
            "select id, code from programs where code = any($1)", gaps
        )
        id_by_code = {str(r["code"]): str(r["id"]) for r in prows}
    resp_scores = {code: 0.65 for code in gaps}
    final = [
        {"program_id": id_by_code[c], "score": s, "source": "llm"}
        for c, s in resp_scores.items()
        if c in id_by_code and float(s) >= float(CONFIDENCE_THRESHOLD)
    ]
    return {"scores": final}

def _dedupe_lps_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate upsert rows by (lead_id, program_id, fingerprint), choosing the
    row with the higher score; prefer 'rules' over 'llm' on score ties.
    """
    best: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        key = (str(r["lead_id"]), str(r["program_id"]), str(r["fingerprint"]))
        cur = best.get(key)
        cand_score = float(r["score"])
        if (
            cur is None
            or cand_score > float(cur["score"])
            or (
                cand_score == float(cur["score"])
                and cur.get("source") == "llm"
                and r.get("source", "rules") == "rules"
            )
        ):
            best[key] = r
    return list(best.values())


def _best_by_program(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Collapse to one result per program_id for the payload we return to the workflow.
    Choose highest score; prefer 'rules' on ties.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        pid = str(r["program_id"])
        cur = best.get(pid)
        cand_score = float(r["score"])
        cand_source = r.get("source", "rules")
        if (
            cur is None
            or cand_score > float(cur["score"])
            or (cand_score == float(cur["score"]) and cur.get("source") == "llm" and cand_source == "rules")
        ):
            best[pid] = {"program_id": pid, "score": cand_score, "source": cand_source}
    return list(best.values())


# --- activity ----------------------------------------------------------------

@activity.defn
@trace("match.persist_scores")
async def persist_scores(params: Dict[str, Any]) -> Dict[str, Any]:
    lead_id = str(params["lead_id"])
    incoming_scores: List[Dict[str, Any]] = params.get("scores") or []
    fingerprint: str = str(params["fingerprint"])
    rules_version: int = int(params["rules_version"])

    # Normalize & validate input scores, drop malformed entries defensively
    scores = []
    for s in incoming_scores:
        if not isinstance(s, dict):
            continue
        pid = s.get("program_id")
        sc = s.get("score")
        if pid is None or sc is None:
            continue
        try:
            scores.append(
                {
                    "program_id": str(pid),
                    "score": float(sc),
                    "source": str(s.get("source", "rules")),
                }
            )
        except Exception:
            # skip non-castable rows
            continue

    if not scores:
        return {
            "lead_id": lead_id,
            "rules_version": rules_version,
            "fingerprint": fingerprint,
            "scores": [],
        }

    # Build upsert rows from normalized scores
    rows = [
        {
            "lead_id": lead_id,
            "program_id": s["program_id"],
            "rules_version": rules_version,
            "fingerprint": fingerprint,
            "score": float(s["score"]),
            "source": s.get("source", "rules"),
        }
        for s in scores
    ]

    # Deduplicate before writing to avoid PostgREST "affected twice" error
    rows = _dedupe_lps_rows(rows)

    if await _use_rest():
        await _rest_upsert_lead_program_scores(rows)
        result_scores = _best_by_program(rows)
        return {
            "lead_id": lead_id,
            "rules_version": rules_version,
            "fingerprint": fingerprint,
            "scores": result_scores,
        }

    # asyncpg path
    pool = await _get_pg_pool_or_none()
    assert pool is not None
    async with pool.acquire() as conn:
        async with conn.transaction():
            for r in rows:
                await conn.execute(
                    """
                    insert into lead_program_scores
                      (lead_id, program_id, rules_version, fingerprint, score, source)
                    values ($1, $2, $3, $4, $5, $6)
                    on conflict (lead_id, program_id, fingerprint)
                    do update set
                      score = excluded.score,
                      rules_version = excluded.rules_version,
                      source = excluded.source
                    """,
                    r["lead_id"],
                    r["program_id"],
                    r["rules_version"],
                    r["fingerprint"],
                    float(r["score"]),
                    r["source"],
                )

    result_scores = _best_by_program(rows)
    return {
        "lead_id": lead_id,
        "rules_version": rules_version,
        "fingerprint": fingerprint,
        "scores": result_scores,
    }

