import re


SKU_PREFIX_RE = re.compile(r"^\s*SKU\s*[:#_-]?\s*", re.IGNORECASE)


def normalize_sku(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    without_prefix = SKU_PREFIX_RE.sub("", raw)
    digits = "".join(re.findall(r"\d+", without_prefix))
    if digits:
        return digits[:80]
    return without_prefix[:80]


def sku_lookup_candidates(value):
    raw = str(value or "").strip()
    normalized = normalize_sku(raw)
    candidates = [raw, normalized]
    if normalized:
        candidates.extend(
            [
                f"SKU:{normalized}",
                f"SKU-{normalized}",
                f"SKU_{normalized}",
                f"SKU {normalized}",
                f"SKU{normalized}",
                f"SKU:SKU-{normalized}",
            ]
        )
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))
