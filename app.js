const STORAGE_KEY = "evsphere-warehouse-state-v1";

const iconMap = {
  "layout-dashboard": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>`,
  boxes: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M7 16.5 3.5 14.5v-5L7 7.5l3.5 2v5L7 16.5Z"/><path d="m3.5 9.5 3.5 2 3.5-2"/><path d="M17 16.5 13.5 14.5v-5L17 7.5l3.5 2v5L17 16.5Z"/><path d="m13.5 9.5 3.5 2 3.5-2"/><path d="M12 8.5 8.5 6.5v-4L12 .5l3.5 2v4L12 8.5Z"/></svg>`,
  repeat: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/></svg>`,
  "clipboard-list": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M8 11h8M8 16h8"/></svg>`,
  search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg>`,
  download: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>`,
  package: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m3 7 9-4 9 4-9 4-9-4Z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/></svg>`,
  "triangle-alert": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M10.3 4.1a2 2 0 0 1 3.4 0l8 14A2 2 0 0 1 20 21H4a2 2 0 0 1-1.7-2.9l8-14Z"/><path d="M12 9v4M12 17h.01"/></svg>`,
  truck: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M10 17H6V5h10v12h-2"/><path d="M16 8h3l3 4v5h-2"/><circle cx="7" cy="17" r="2"/><circle cx="18" cy="17" r="2"/></svg>`,
  "map-pin": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>`,
  save: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>`,
  "rotate-ccw": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v6h6"/></svg>`,
  plus: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14"/></svg>`,
  "clipboard-plus": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11v6M9 14h6"/></svg>`,
  pencil: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 15H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>`,
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m20 6-11 11-5-5"/></svg>`,
};

const seedState = {
  products: [
    { id: uid(), sku: "SKU-1001", name: "Barcode Scanner", category: "Electronics", location: "A-01", qty: 42, reorder: 12, supplier: "Metro Supply" },
    { id: uid(), sku: "SKU-1002", name: "Packing Tape Roll", category: "Packaging", location: "B-04", qty: 18, reorder: 50, supplier: "Packline" },
    { id: uid(), sku: "SKU-1003", name: "Safety Gloves", category: "Hardware", location: "C-02", qty: 86, reorder: 30, supplier: "SafePro" },
    { id: uid(), sku: "SKU-1004", name: "Office Chair Box", category: "Furniture", location: "D-07", qty: 9, reorder: 15, supplier: "Urban Works" },
    { id: uid(), sku: "SKU-1005", name: "Thermal Labels", category: "Packaging", location: "B-01", qty: 124, reorder: 40, supplier: "LabelKart" },
  ],
  movements: [],
  orders: [
    { id: uid(), customer: "Aarav Traders", productId: "", qty: 6, priority: "High", status: "Pending", createdAt: new Date().toISOString() },
    { id: uid(), customer: "North Retail", productId: "", qty: 12, priority: "Normal", status: "Picking", createdAt: new Date().toISOString() },
  ],
};

seedState.orders[0].productId = seedState.products[0].id;
seedState.orders[1].productId = seedState.products[4].id;

let state = loadState();
let currentView = "dashboard";
let inventoryFilter = "all";
let searchTerm = "";
let toastTimer;

const els = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  hydrateIcons();
  bindEvents();
  updateDate();
  render();

  if ("serviceWorker" in navigator && window.location.protocol.startsWith("http")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
});

function cacheElements() {
  [
    "view-title",
    "global-search",
    "export-button",
    "today-date",
    "warehouse-status",
    "hero-stock-value",
    "hero-alert-copy",
    "stat-stock",
    "stat-low",
    "stat-orders",
    "stat-zones",
    "low-stock-list",
    "activity-list",
    "product-form",
    "product-form-title",
    "product-id",
    "product-sku",
    "product-name",
    "product-category",
    "product-location",
    "product-qty",
    "product-reorder",
    "product-supplier",
    "reset-product-form",
    "inventory-table",
    "movement-form",
    "movement-product",
    "movement-type",
    "movement-qty",
    "movement-note",
    "movement-table",
    "order-form",
    "order-customer",
    "order-product",
    "order-qty",
    "order-priority",
    "order-board",
    "toast",
  ].forEach((id) => {
    els[toCamel(id)] = document.getElementById(id);
  });
}

function bindEvents() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });

  document.querySelectorAll("[data-view-jump]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.viewJump));
  });

  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      inventoryFilter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
      renderInventory();
    });
  });

  els.globalSearch.addEventListener("input", (event) => {
    searchTerm = event.target.value.trim().toLowerCase();
    render();
  });

  els.productForm.addEventListener("submit", handleProductSubmit);
  els.resetProductForm.addEventListener("click", resetProductForm);
  els.movementForm.addEventListener("submit", handleMovementSubmit);
  els.orderForm.addEventListener("submit", handleOrderSubmit);
  els.exportButton.addEventListener("click", exportData);
}

function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    const icon = iconMap[node.dataset.icon];
    if (icon) node.innerHTML = icon;
  });
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved?.products?.length) return saved;
  } catch (error) {
    console.warn("Could not load saved warehouse state", error);
  }

  return structuredClone(seedState);
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function render() {
  renderStats();
  renderProductOptions();
  renderLowStockList();
  renderActivityList();
  renderInventory();
  renderMovements();
  renderOrders();
}

function setView(view) {
  currentView = view;
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });

  const titles = {
    dashboard: "Warehouse Dashboard",
    inventory: "Inventory Manager",
    movements: "Stock Movement",
    orders: "Order Dispatch",
  };
  els.viewTitle.textContent = titles[view] || "Warehouse Dashboard";
}

function renderStats() {
  const totalStock = state.products.reduce((sum, product) => sum + Number(product.qty), 0);
  const lowItems = state.products.filter((product) => Number(product.qty) <= Number(product.reorder));
  const pendingOrders = state.orders.filter((order) => order.status !== "Completed").length;
  const zones = new Set(state.products.map((product) => product.location.trim()).filter(Boolean)).size;

  els.statStock.textContent = totalStock.toLocaleString("en-IN");
  els.statLow.textContent = lowItems.length;
  els.statOrders.textContent = pendingOrders;
  els.statZones.textContent = zones;
  els.heroStockValue.textContent = `${totalStock.toLocaleString("en-IN")} units`;
  els.heroAlertCopy.textContent = lowItems.length ? `${lowItems.length} items reorder level par hain` : "All zones updated";
  els.warehouseStatus.textContent = lowItems.length ? "Reorder required" : "System ready";
}

function renderLowStockList() {
  const lowItems = state.products
    .filter((product) => Number(product.qty) <= Number(product.reorder))
    .sort((a, b) => Number(a.qty) - Number(b.qty));

  if (!lowItems.length) {
    els.lowStockList.innerHTML = `<div class="empty-state">Low stock item nahi hai.</div>`;
    return;
  }

  els.lowStockList.innerHTML = lowItems
    .map(
      (product) => `
        <article class="compact-item">
          <div>
            <strong>${escapeHtml(product.name)}</strong>
            <span class="muted">${escapeHtml(product.sku)} / ${escapeHtml(product.location)}</span>
          </div>
          <span class="pill low">${product.qty} left</span>
        </article>
      `,
    )
    .join("");
}

function renderActivityList() {
  const rows = state.movements.slice(0, 6);

  if (!rows.length) {
    els.activityList.innerHTML = `<div class="empty-state">Abhi movement entry nahi hai.</div>`;
    return;
  }

  els.activityList.innerHTML = rows
    .map((movement) => {
      const product = findProduct(movement.productId);
      const typeCopy = movement.type === "in" ? "Stock In" : "Stock Out";
      return `
        <article class="timeline-item">
          <div>
            <strong>${escapeHtml(product?.name || "Deleted item")}</strong>
            <span class="muted">${formatDateTime(movement.createdAt)} / ${escapeHtml(movement.note || typeCopy)}</span>
          </div>
          <span class="pill ${movement.type}">${typeCopy} ${movement.qty}</span>
        </article>
      `;
    })
    .join("");
}

function renderInventory() {
  let rows = state.products.filter(matchesSearch);

  if (inventoryFilter === "low") rows = rows.filter((product) => Number(product.qty) <= Number(product.reorder));
  if (inventoryFilter === "ok") rows = rows.filter((product) => Number(product.qty) > Number(product.reorder));

  if (!rows.length) {
    els.inventoryTable.innerHTML = `<tr><td colspan="6"><div class="empty-state">Inventory match nahi mila.</div></td></tr>`;
    return;
  }

  els.inventoryTable.innerHTML = rows
    .map((product) => {
      const status = Number(product.qty) <= Number(product.reorder) ? "low" : "ok";
      const statusCopy = status === "low" ? "Low" : "OK";
      return `
        <tr>
          <td><strong>${escapeHtml(product.sku)}</strong></td>
          <td>
            <div class="item-title">
              <strong>${escapeHtml(product.name)}</strong>
              <span>${escapeHtml(product.category)} / ${escapeHtml(product.supplier || "No supplier")}</span>
            </div>
          </td>
          <td>${Number(product.qty).toLocaleString("en-IN")}</td>
          <td>${escapeHtml(product.location)}</td>
          <td><span class="pill ${status}">${statusCopy}</span></td>
          <td>
            <div class="row-actions">
              <button class="icon-button" type="button" title="Edit product" aria-label="Edit ${escapeHtml(product.name)}" data-edit-product="${product.id}">
                <span data-icon="pencil"></span>
              </button>
              <button class="icon-button" type="button" title="Delete product" aria-label="Delete ${escapeHtml(product.name)}" data-delete-product="${product.id}">
                <span data-icon="trash"></span>
              </button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  hydrateIcons(els.inventoryTable);
  els.inventoryTable.querySelectorAll("[data-edit-product]").forEach((button) => {
    button.addEventListener("click", () => editProduct(button.dataset.editProduct));
  });
  els.inventoryTable.querySelectorAll("[data-delete-product]").forEach((button) => {
    button.addEventListener("click", () => deleteProduct(button.dataset.deleteProduct));
  });
}

function renderProductOptions() {
  const options = state.products
    .map((product) => `<option value="${product.id}">${escapeHtml(product.sku)} - ${escapeHtml(product.name)} (${product.qty})</option>`)
    .join("");

  els.movementProduct.innerHTML = options;
  els.orderProduct.innerHTML = options;
}

function renderMovements() {
  const rows = state.movements.filter((movement) => {
    const product = findProduct(movement.productId);
    return !searchTerm || product?.sku.toLowerCase().includes(searchTerm) || product?.name.toLowerCase().includes(searchTerm) || movement.note?.toLowerCase().includes(searchTerm);
  });

  if (!rows.length) {
    els.movementTable.innerHTML = `<tr><td colspan="5"><div class="empty-state">Movement history khali hai.</div></td></tr>`;
    return;
  }

  els.movementTable.innerHTML = rows
    .map((movement) => {
      const product = findProduct(movement.productId);
      const typeCopy = movement.type === "in" ? "Stock In" : "Stock Out";
      return `
        <tr>
          <td>${formatDateTime(movement.createdAt)}</td>
          <td>${escapeHtml(product?.sku || "--")}</td>
          <td><span class="pill ${movement.type}">${typeCopy}</span></td>
          <td>${movement.qty}</td>
          <td>${escapeHtml(movement.note || "--")}</td>
        </tr>
      `;
    })
    .join("");
}

function renderOrders() {
  const rows = state.orders.filter((order) => {
    const product = findProduct(order.productId);
    const haystack = `${order.customer} ${order.priority} ${order.status} ${product?.name || ""} ${product?.sku || ""}`.toLowerCase();
    return haystack.includes(searchTerm);
  });

  if (!rows.length) {
    els.orderBoard.innerHTML = `<div class="empty-state">Order board khali hai.</div>`;
    return;
  }

  els.orderBoard.innerHTML = rows
    .map((order) => {
      const product = findProduct(order.productId);
      const priorityClass = order.priority.toLowerCase();
      const nextLabel = order.status === "Pending" ? "Start" : order.status === "Picking" ? "Complete" : "Done";
      const completed = order.status === "Completed";
      return `
        <article class="order-card">
          <div class="order-top">
            <div>
              <strong>${escapeHtml(order.customer)}</strong>
              <span class="muted">${formatDateTime(order.createdAt)}</span>
            </div>
            <span class="pill ${priorityClass}">${escapeHtml(order.priority)}</span>
          </div>
          <div class="order-meta">
            <span>${escapeHtml(product?.sku || "--")} / ${escapeHtml(product?.name || "Deleted item")}</span>
            <span>Qty ${order.qty} / ${escapeHtml(order.status)}</span>
          </div>
          <div class="order-actions">
            <button class="text-button" type="button" data-advance-order="${order.id}" ${completed ? "disabled" : ""}>${nextLabel}</button>
            <button class="icon-button" type="button" title="Delete order" aria-label="Delete order" data-delete-order="${order.id}">
              <span data-icon="trash"></span>
            </button>
          </div>
        </article>
      `;
    })
    .join("");

  hydrateIcons(els.orderBoard);
  els.orderBoard.querySelectorAll("[data-advance-order]").forEach((button) => {
    button.addEventListener("click", () => advanceOrder(button.dataset.advanceOrder));
  });
  els.orderBoard.querySelectorAll("[data-delete-order]").forEach((button) => {
    button.addEventListener("click", () => deleteOrder(button.dataset.deleteOrder));
  });
}

function handleProductSubmit(event) {
  event.preventDefault();
  const product = {
    id: els.productId.value || uid(),
    sku: els.productSku.value.trim(),
    name: els.productName.value.trim(),
    category: els.productCategory.value,
    location: els.productLocation.value.trim(),
    qty: Number(els.productQty.value),
    reorder: Number(els.productReorder.value),
    supplier: els.productSupplier.value.trim(),
  };

  const duplicateSku = state.products.some((item) => item.sku.toLowerCase() === product.sku.toLowerCase() && item.id !== product.id);
  if (duplicateSku) {
    showToast("SKU already exists.");
    return;
  }

  const index = state.products.findIndex((item) => item.id === product.id);
  if (index >= 0) {
    state.products[index] = product;
    showToast("Product updated.");
  } else {
    state.products.unshift(product);
    showToast("Product added.");
  }

  saveState();
  resetProductForm();
  render();
}

function handleMovementSubmit(event) {
  event.preventDefault();
  const product = findProduct(els.movementProduct.value);
  const qty = Number(els.movementQty.value);

  if (!product) {
    showToast("Product select karein.");
    return;
  }

  if (els.movementType.value === "out" && qty > Number(product.qty)) {
    showToast("Stock se zyada quantity out nahi ho sakti.");
    return;
  }

  product.qty = els.movementType.value === "in" ? Number(product.qty) + qty : Number(product.qty) - qty;
  state.movements.unshift({
    id: uid(),
    productId: product.id,
    type: els.movementType.value,
    qty,
    note: els.movementNote.value.trim(),
    createdAt: new Date().toISOString(),
  });

  saveState();
  els.movementForm.reset();
  render();
  showToast("Movement saved.");
}

function handleOrderSubmit(event) {
  event.preventDefault();
  const product = findProduct(els.orderProduct.value);
  const qty = Number(els.orderQty.value);

  if (!product) {
    showToast("Product select karein.");
    return;
  }

  if (qty > Number(product.qty)) {
    showToast("Order quantity available stock se zyada hai.");
    return;
  }

  state.orders.unshift({
    id: uid(),
    customer: els.orderCustomer.value.trim(),
    productId: product.id,
    qty,
    priority: els.orderPriority.value,
    status: "Pending",
    createdAt: new Date().toISOString(),
  });

  saveState();
  els.orderForm.reset();
  render();
  showToast("Order saved.");
}

function editProduct(id) {
  const product = findProduct(id);
  if (!product) return;

  els.productId.value = product.id;
  els.productSku.value = product.sku;
  els.productName.value = product.name;
  els.productCategory.value = product.category;
  els.productLocation.value = product.location;
  els.productQty.value = product.qty;
  els.productReorder.value = product.reorder;
  els.productSupplier.value = product.supplier;
  els.productFormTitle.textContent = "Edit Product";
  setView("inventory");
  els.productSku.focus();
}

function deleteProduct(id) {
  const product = findProduct(id);
  if (!product) return;

  const hasOrder = state.orders.some((order) => order.productId === id && order.status !== "Completed");
  if (hasOrder) {
    showToast("Active order ke product ko delete nahi kar sakte.");
    return;
  }

  state.products = state.products.filter((item) => item.id !== id);
  state.movements = state.movements.filter((movement) => movement.productId !== id);
  saveState();
  render();
  showToast("Product deleted.");
}

function resetProductForm() {
  els.productForm.reset();
  els.productId.value = "";
  els.productFormTitle.textContent = "Add Product";
}

function advanceOrder(id) {
  const order = state.orders.find((item) => item.id === id);
  if (!order) return;

  if (order.status === "Pending") {
    order.status = "Picking";
    showToast("Order picking mein move hua.");
  } else if (order.status === "Picking") {
    const product = findProduct(order.productId);
    if (!product || Number(product.qty) < Number(order.qty)) {
      showToast("Complete karne ke liye stock available nahi hai.");
      return;
    }

    product.qty = Number(product.qty) - Number(order.qty);
    order.status = "Completed";
    state.movements.unshift({
      id: uid(),
      productId: product.id,
      type: "out",
      qty: Number(order.qty),
      note: `Order: ${order.customer}`,
      createdAt: new Date().toISOString(),
    });
    showToast("Order completed.");
  }

  saveState();
  render();
}

function deleteOrder(id) {
  state.orders = state.orders.filter((order) => order.id !== id);
  saveState();
  render();
  showToast("Order deleted.");
}

function exportData() {
  const payload = JSON.stringify(state, null, 2);
  const blob = new Blob([payload], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `warehouse-export-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  showToast("Data export ready.");
}

function matchesSearch(product) {
  if (!searchTerm) return true;
  const haystack = `${product.sku} ${product.name} ${product.category} ${product.location} ${product.supplier}`.toLowerCase();
  return haystack.includes(searchTerm);
}

function findProduct(id) {
  return state.products.find((product) => product.id === id);
}

function uid() {
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function toCamel(value) {
  return value.replace(/-([a-z])/g, (_, char) => char.toUpperCase());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function updateDate() {
  els.todayDate.textContent = new Intl.DateTimeFormat("en-IN", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date());
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.remove("show"), 2400);
}
