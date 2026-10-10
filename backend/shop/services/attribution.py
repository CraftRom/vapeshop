"""Bounded attribution metadata shared by checkout, CRM and reporting."""
import re

SOURCE_RE = re.compile(r"[^a-z0-9._-]+")


def clean_attribution(data: dict | None) -> dict:
    data = data or {}
    source = SOURCE_RE.sub("_", str(data.get("source") or "unknown").lower().strip())[:80] or "unknown"
    return {
        "source": source,
        **{k: str(data.get(k) or "").strip()[:160] for k in ("medium", "campaign", "content", "term")},
    }



def order_attribution(attribution, snapshot=None):
    local = clean_attribution(attribution)
    if isinstance(attribution, dict) and attribution.get('session_id'):
        local['session_id'] = str(attribution['session_id'])[:64]
    if local['source'] != 'unknown':
        return local
    utm = (snapshot or {}).get('utm') or {}
    if not isinstance(utm, dict) or not utm.get('source'):
        return local
    return clean_attribution(utm)
