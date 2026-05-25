import json

from .sku import normalize_sku


def build_product_barcode(product):
    return normalize_sku(product.sku) or product.sku


def build_location_barcode(location):
    parts = [location.zone, location.rack, location.shelf, location.bin_code]
    return "LOC:" + "-".join(str(part).strip() for part in parts if str(part or "").strip())


def product_payload(product):
    return json.dumps(
        {
            "type": "product",
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
        },
        separators=(",", ":"),
    )
