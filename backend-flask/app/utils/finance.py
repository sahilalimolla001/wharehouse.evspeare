import json
from datetime import datetime

from ..extensions import db
from ..models import Invoice, MoneyTransaction


def order_amount(order):
    return sum(float(item.unit_price or 0) * int(item.quantity or 0) for item in order.items)


def next_number(prefix):
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:17]}"


def ensure_invoice(order, invoice_type="sale", status="issued", payload=None):
    existing = Invoice.query.filter_by(order_id=order.id, invoice_type=invoice_type).first()
    if existing:
        return existing
    invoice = Invoice(
        invoice_number=next_number({"sale": "INV", "cancel": "CINV", "return": "RINV"}.get(invoice_type, "INV")),
        order_id=order.id,
        invoice_type=invoice_type,
        status=status,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        amount=order_amount(order),
        currency="INR",
        payload_json=json.dumps(payload or invoice_payload(order, invoice_type), default=str, separators=(",", ":"))[:20000],
    )
    db.session.add(invoice)
    db.session.flush()
    record_money_transaction(
        order=order,
        invoice=invoice,
        transaction_type=invoice_type,
        direction="credit" if invoice_type == "sale" else "debit",
        status=status,
        amount=invoice.amount,
        notes=f"{invoice_type.title()} invoice {invoice.invoice_number}",
    )
    return invoice


def record_money_transaction(order=None, refund=None, invoice=None, transaction_type="payment", direction="credit", status="recorded", amount=0, gateway="", reference="", notes="", payload=None):
    transaction = MoneyTransaction(
        transaction_number=next_number("MT"),
        order_id=order.id if order else None,
        refund_id=refund.id if refund else None,
        invoice_id=invoice.id if invoice else None,
        transaction_type=transaction_type,
        direction=direction,
        status=status,
        gateway=gateway,
        reference=reference,
        amount=amount or 0,
        currency=getattr(invoice, "currency", None) or "INR",
        customer_name=getattr(order, "customer_name", "") or getattr(refund, "customer_name", ""),
        customer_phone=getattr(order, "customer_phone", "") or getattr(refund, "customer_phone", ""),
        notes=notes,
        payload_json=json.dumps(payload or {}, default=str, separators=(",", ":"))[:20000],
    )
    db.session.add(transaction)
    db.session.flush()
    return transaction


def invoice_payload(order, invoice_type):
    return {
        "invoice_type": invoice_type,
        "order_number": order.order_number,
        "customer": {"name": order.customer_name, "phone": order.customer_phone, "address": order.customer_address},
        "items": [
            {
                "sku": item.product.sku,
                "name": item.product.name,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price or 0),
                "total": float(item.unit_price or 0) * int(item.quantity or 0),
            }
            for item in order.items
        ],
        "total": order_amount(order),
    }
