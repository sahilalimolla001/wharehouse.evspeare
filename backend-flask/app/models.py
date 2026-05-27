from datetime import datetime
from decimal import Decimal

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


user_warehouses = db.Table(
    "user_warehouses",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("warehouse_id", db.Integer, db.ForeignKey("warehouses.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow, nullable=False),
)


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30))
    role = db.Column(db.String(30), default="staff", nullable=False)
    picker_code = db.Column(db.String(5), unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    page_permissions = db.Column(db.Text)
    last_online_at = db.Column(db.DateTime)

    stock_ins = db.relationship("StockIn", back_populates="received_by", foreign_keys="StockIn.received_by_id")
    stock_outs = db.relationship("StockOut", back_populates="dispatched_by", foreign_keys="StockOut.dispatched_by_id")
    activity_logs = db.relationship("ActivityLog", back_populates="user")
    warehouses = db.relationship("Warehouse", secondary=user_warehouses, back_populates="users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.email}>"


class Category(TimestampMixin, db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)

    products = db.relationship("Product", back_populates="category")

    def __repr__(self):
        return f"<Category {self.name}>"


class Supplier(TimestampMixin, db.Model):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(180))
    address = db.Column(db.Text)
    gst_number = db.Column(db.String(40))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    products = db.relationship("Product", back_populates="supplier")
    stock_ins = db.relationship("StockIn", back_populates="supplier")

    def __repr__(self):
        return f"<Supplier {self.name}>"


class Warehouse(TimestampMixin, db.Model):
    __tablename__ = "warehouses"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    pincode = db.Column(db.String(12), nullable=False)
    address = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    locations = db.relationship("WarehouseLocation", back_populates="warehouse")
    users = db.relationship("User", secondary=user_warehouses, back_populates="warehouses")

    def __repr__(self):
        return f"<Warehouse {self.code}>"


class WarehouseLocation(TimestampMixin, db.Model):
    __tablename__ = "warehouse_locations"

    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=False)
    zone = db.Column(db.String(30), nullable=False)
    rack = db.Column(db.String(30), nullable=False)
    shelf = db.Column(db.String(30), nullable=False)
    bin_code = db.Column(db.String(30), nullable=False)
    barcode = db.Column(db.String(80))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_virtual = db.Column(db.Boolean, default=False, nullable=False)

    warehouse = db.relationship("Warehouse", back_populates="locations")
    inventory_items = db.relationship("Inventory", back_populates="location")

    __table_args__ = (
        db.UniqueConstraint("warehouse_id", "zone", "rack", "shelf", "bin_code", name="uq_location_warehouse_path"),
    )

    @property
    def full_code(self):
        warehouse_code = self.warehouse.code if self.warehouse else "Warehouse"
        return f"{warehouse_code} / Zone {self.zone} / Rack {self.rack} / Shelf {self.shelf} / Bin {self.bin_code}"

    def __repr__(self):
        return f"<WarehouseLocation {self.full_code}>"


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    sku = db.Column(db.String(80), unique=True, nullable=False, index=True)
    brand = db.Column(db.String(120))
    unit = db.Column(db.String(30), default="pcs", nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    purchase_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    selling_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    minimum_stock = db.Column(db.Integer, default=0, nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    category = db.relationship("Category", back_populates="products")
    supplier = db.relationship("Supplier", back_populates="products")
    inventory_items = db.relationship("Inventory", back_populates="product", cascade="all, delete-orphan")
    stock_ins = db.relationship("StockIn", back_populates="product")
    stock_outs = db.relationship("StockOut", back_populates="product")
    order_items = db.relationship("OrderItem", back_populates="product")
    barcodes = db.relationship("Barcode", back_populates="product", cascade="all, delete-orphan")

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.inventory_items)

    @property
    def available_quantity(self):
        return sum(item.available_quantity for item in self.inventory_items if not item.location.is_virtual)

    @property
    def stock_value(self):
        return Decimal(self.purchase_price or 0) * self.total_quantity

    @property
    def is_low_stock(self):
        return self.total_quantity <= self.minimum_stock

    def __repr__(self):
        return f"<Product {self.sku}>"


class Inventory(TimestampMixin, db.Model):
    __tablename__ = "inventory"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("warehouse_locations.id"), nullable=False)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    reserved_quantity = db.Column(db.Integer, default=0, nullable=False)

    product = db.relationship("Product", back_populates="inventory_items")
    location = db.relationship("WarehouseLocation", back_populates="inventory_items")

    __table_args__ = (
        db.UniqueConstraint("product_id", "location_id", name="uq_inventory_product_location"),
    )

    @property
    def available_quantity(self):
        return max(self.quantity - self.reserved_quantity, 0)

    def __repr__(self):
        return f"<Inventory product={self.product_id} location={self.location_id} qty={self.quantity}>"


class StockIn(TimestampMixin, db.Model):
    __tablename__ = "stock_ins"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    location_id = db.Column(db.Integer, db.ForeignKey("warehouse_locations.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    invoice_number = db.Column(db.String(120))
    received_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", back_populates="stock_ins")
    supplier = db.relationship("Supplier", back_populates="stock_ins")
    location = db.relationship("WarehouseLocation")
    received_by = db.relationship("User", back_populates="stock_ins", foreign_keys=[received_by_id])

    def __repr__(self):
        return f"<StockIn product={self.product_id} qty={self.quantity}>"


class StockOut(TimestampMixin, db.Model):
    __tablename__ = "stock_outs"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    location_id = db.Column(db.Integer, db.ForeignKey("warehouse_locations.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(40), default="sale", nullable=False)
    dispatched_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)
    dispatched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", back_populates="stock_outs")
    order = db.relationship("Order", back_populates="stock_outs")
    location = db.relationship("WarehouseLocation")
    dispatched_by = db.relationship("User", back_populates="stock_outs", foreign_keys=[dispatched_by_id])

    def __repr__(self):
        return f"<StockOut product={self.product_id} qty={self.quantity}>"


class Order(TimestampMixin, db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    external_source = db.Column(db.String(80), index=True)
    external_order_id = db.Column(db.String(120), index=True)
    source_payload = db.Column(db.Text)
    courier_provider = db.Column(db.String(40))
    courier_order_id = db.Column(db.String(120), index=True)
    courier_shipment_id = db.Column(db.String(120), index=True)
    courier_awb = db.Column(db.String(120))
    courier_status = db.Column(db.String(80))
    courier_response = db.Column(db.Text)
    package_length_cm = db.Column(db.Numeric(8, 2))
    package_breadth_cm = db.Column(db.Numeric(8, 2))
    package_height_cm = db.Column(db.Numeric(8, 2))
    package_weight_kg = db.Column(db.Numeric(8, 3))
    customer_name = db.Column(db.String(160), nullable=False)
    customer_phone = db.Column(db.String(30))
    customer_address = db.Column(db.Text)
    status = db.Column(db.String(40), default="pending", nullable=False)
    priority = db.Column(db.String(20), default="normal", nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=False)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    expected_dispatch_date = db.Column(db.Date)
    completed_at = db.Column(db.DateTime)

    warehouse = db.relationship("Warehouse")
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    stock_outs = db.relationship("StockOut", back_populates="order")
    shiprocket_events = db.relationship("ShiprocketWebhookEvent", back_populates="order")

    __table_args__ = (
        db.UniqueConstraint("external_source", "external_order_id", name="uq_order_external_reference"),
    )

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items)

    @property
    def total_value(self):
        return sum(Decimal(item.unit_price or 0) * item.quantity for item in self.items)

    def __repr__(self):
        return f"<Order {self.order_number}>"


class ShiprocketWebhookEvent(TimestampMixin, db.Model):
    __tablename__ = "shiprocket_webhook_events"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    event_type = db.Column(db.String(80))
    shiprocket_order_id = db.Column(db.String(120), index=True)
    shipment_id = db.Column(db.String(120), index=True)
    awb = db.Column(db.String(120), index=True)
    current_status = db.Column(db.String(120), index=True)
    previous_status = db.Column(db.String(120))
    status_code = db.Column(db.String(80))
    courier_name = db.Column(db.String(160))
    location = db.Column(db.String(180))
    event_time = db.Column(db.DateTime)
    payload_json = db.Column(db.Text, nullable=False)
    headers_json = db.Column(db.Text)
    received_ip = db.Column(db.String(80))

    order = db.relationship("Order", back_populates="shiprocket_events")

    def __repr__(self):
        return f"<ShiprocketWebhookEvent {self.id} {self.current_status}>"


class CustomerReturnOrder(TimestampMixin, db.Model):
    __tablename__ = "customer_return_orders"

    id = db.Column(db.Integer, primary_key=True)
    return_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    website_order_id = db.Column(db.String(120), index=True)
    customer_name = db.Column(db.String(160), nullable=False)
    customer_phone = db.Column(db.String(30))
    reason = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(40), default="requested", nullable=False, index=True)
    refund_status = db.Column(db.String(40), default="pending", nullable=False)
    notes = db.Column(db.Text)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    order = db.relationship("Order")
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    items = db.relationship("CustomerReturnItem", back_populates="return_order", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<CustomerReturnOrder {self.return_number}>"


class CustomerReturnItem(TimestampMixin, db.Model):
    __tablename__ = "customer_return_items"

    id = db.Column(db.Integer, primary_key=True)
    return_order_id = db.Column(db.Integer, db.ForeignKey("customer_return_orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    expected_quantity = db.Column(db.Integer, default=1, nullable=False)
    picked_quantity = db.Column(db.Integer, default=0, nullable=False)
    stocked_quantity = db.Column(db.Integer, default=0, nullable=False)
    issue_quantity = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(40), default="pending", nullable=False)
    notes = db.Column(db.Text)

    return_order = db.relationship("CustomerReturnOrder", back_populates="items")
    product = db.relationship("Product")

    @property
    def remaining_stock_in_quantity(self):
        return max(self.picked_quantity - self.stocked_quantity - self.issue_quantity, 0)

    def __repr__(self):
        return f"<CustomerReturnItem return={self.return_order_id} product={self.product_id}>"


class PaymentRefund(TimestampMixin, db.Model):
    __tablename__ = "payment_refunds"

    id = db.Column(db.Integer, primary_key=True)
    refund_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    website_order_id = db.Column(db.String(120), index=True)
    request_id = db.Column(db.String(120), unique=True, index=True)
    customer_name = db.Column(db.String(160), nullable=False)
    customer_phone = db.Column(db.String(30))
    gateway = db.Column(db.String(40), default="razorpay", nullable=False)
    gateway_payment_id = db.Column(db.String(120), index=True)
    gateway_transaction_id = db.Column(db.String(120), index=True)
    refund_token = db.Column(db.String(23), unique=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(8), default="INR", nullable=False)
    reason = db.Column(db.String(160))
    status = db.Column(db.String(40), default="requested", nullable=False, index=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    approved_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    gateway_response = db.Column(db.Text)
    source_payload = db.Column(db.Text)
    notes = db.Column(db.Text)

    order = db.relationship("Order")
    approved_by = db.relationship("User")

    def __repr__(self):
        return f"<PaymentRefund {self.refund_number}>"


class MoneyTransaction(TimestampMixin, db.Model):
    __tablename__ = "money_transactions"

    id = db.Column(db.Integer, primary_key=True)
    transaction_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    refund_id = db.Column(db.Integer, db.ForeignKey("payment_refunds.id"), index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), index=True)
    transaction_type = db.Column(db.String(40), nullable=False, index=True)
    direction = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(40), default="recorded", nullable=False, index=True)
    gateway = db.Column(db.String(40))
    reference = db.Column(db.String(160), index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(8), default="INR", nullable=False)
    customer_name = db.Column(db.String(160))
    customer_phone = db.Column(db.String(30))
    notes = db.Column(db.Text)
    payload_json = db.Column(db.Text)

    order = db.relationship("Order")
    refund = db.relationship("PaymentRefund")
    invoice = db.relationship("Invoice")


class Invoice(TimestampMixin, db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    invoice_type = db.Column(db.String(40), nullable=False, index=True)
    status = db.Column(db.String(40), default="issued", nullable=False, index=True)
    customer_name = db.Column(db.String(160), nullable=False)
    customer_phone = db.Column(db.String(30))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(8), default="INR", nullable=False)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    payload_json = db.Column(db.Text)

    order = db.relationship("Order")


class OrderItem(TimestampMixin, db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    picked_quantity = db.Column(db.Integer, default=0, nullable=False)
    packed_quantity = db.Column(db.Integer, default=0, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product", back_populates="order_items")

    def __repr__(self):
        return f"<OrderItem order={self.order_id} product={self.product_id}>"


class Barcode(TimestampMixin, db.Model):
    __tablename__ = "barcodes"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    code = db.Column(db.String(160), unique=True, nullable=False, index=True)
    barcode_type = db.Column(db.String(30), default="QR", nullable=False)
    payload = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    product = db.relationship("Product", back_populates="barcodes")

    def __repr__(self):
        return f"<Barcode {self.code}>"


class ActivityLog(TimestampMixin, db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(80))
    entity_id = db.Column(db.Integer)
    message = db.Column(db.String(255), nullable=False)
    meta_json = db.Column(db.Text)

    user = db.relationship("User", back_populates="activity_logs")

    def __repr__(self):
        return f"<ActivityLog {self.action}>"
