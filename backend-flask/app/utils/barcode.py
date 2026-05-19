import json


def build_product_barcode(product):
    return f"SKU:{product.sku}"


def build_location_barcode(location):
    return f"LOC:{location.zone}-{location.rack}-{location.shelf}-{location.bin_code}"


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
