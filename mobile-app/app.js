const configuredApiBase = normalizeApiBase(window.WAREHOUSE_API_BASE || "");
const savedApiBase = normalizeApiBase(localStorage.getItem("warehouseMobileApi") || "");

const store = {
  apiBase: initialApiBase(),
  user: JSON.parse(localStorage.getItem("warehouseMobileUser") || "null"),
  token: localStorage.getItem("warehouseMobileToken") || "",
  orders: [],
  activeOrderId: Number(localStorage.getItem("warehouseActiveOrderId") || 0),
};

let videoStream = null;
let scanTimer = null;
let scanFillTarget = null;
let scanReturnScreen = null;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", () => {
  $("#api-base").value = store.apiBase;
  bindNavigation();
  bindActions();
  initializeSession();

  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
});

function bindNavigation() {
  $$(".bottom-nav [data-screen]").forEach((button) => {
    button.addEventListener("click", () => showScreen(button.dataset.screen));
  });
}

function bindActions() {
  $("#login-form").addEventListener("submit", login);
  $("#test-api").addEventListener("click", testApiConnection);
  $("#logout-btn").addEventListener("click", logout);
  $("#sync-btn").addEventListener("click", refreshAll);
  $("#refresh-orders").addEventListener("click", refreshAll);
  $$("[data-refresh-orders]").forEach((button) => button.addEventListener("click", refreshAll));
  $("#start-scan").addEventListener("click", startScanner);
  $("#stop-scan").addEventListener("click", stopScanner);
  $("#manual-scan").addEventListener("click", () => scanCode($("#manual-code").value.trim()));
  $("#back-to-orders").addEventListener("click", () => showScreen("orders-screen"));
  $("#mark-packed").addEventListener("click", markActiveOrderPacked);
  $("#stock-in-form").addEventListener("submit", (event) => submitStock(event, "stock-in"));
  $('#stock-in-form [name="product"]').addEventListener("change", () => loadStockProductPreview($('#stock-in-form [name="product"]').value.trim()));
  $('#stock-in-form [name="product"]').addEventListener("blur", () => loadStockProductPreview($('#stock-in-form [name="product"]').value.trim()));
  $("#location-form").addEventListener("submit", submitLocationUpdate);
  $$("[data-scan-fill]").forEach((button) => {
    button.addEventListener("click", () => {
      scanFillTarget = button.dataset.scanFill;
      scanReturnScreen = $(".screen.active")?.id || "orders-screen";
      showScreen("pick-screen");
      startScanner();
    });
  });
}

function showScreen(screenId) {
  $$(".screen").forEach((screen) => screen.classList.toggle("active", screen.id === screenId));
  $$(".bottom-nav [data-screen]").forEach((button) => button.classList.toggle("active", button.dataset.screen === screenId));
  const titles = {
    "orders-screen": "Orders",
    "pick-screen": "Order Picking",
    "dispatch-screen": "Dispatch",
    "stock-screen": "Stock In",
    "move-screen": "Move Stock",
  };
  $("#screen-title").textContent = titles[screenId] || "Picker";
  if (screenId !== "pick-screen") stopScanner();
}

async function initializeSession() {
  if (!store.user) {
    lockApp();
    return;
  }

  unlockApp();
  try {
    const data = await apiFetch("/me");
    store.user = data.user;
    localStorage.setItem("warehouseMobileUser", JSON.stringify(store.user));
    await refreshAll();
  } catch {
    logout(false);
  }
}

async function login(event) {
  event.preventDefault();
  store.apiBase = normalizeApiBase($("#api-base").value);
  localStorage.setItem("warehouseMobileApi", store.apiBase);
  try {
    const data = await apiFetch("/login", {
      method: "POST",
      body: {
        email: $("#login-email").value.trim(),
        password: $("#login-password").value,
      },
      auth: false,
    });
    store.user = data.user;
    store.token = data.token || "";
    localStorage.setItem("warehouseMobileUser", JSON.stringify(store.user));
    if (store.token) localStorage.setItem("warehouseMobileToken", store.token);
    unlockApp();
    toast(`Welcome ${store.user.name}`);
    await refreshAll();
  } catch (error) {
    lockApp();
    toast(error.message);
  }
}

async function testApiConnection() {
  store.apiBase = normalizeApiBase($("#api-base").value);
  localStorage.setItem("warehouseMobileApi", store.apiBase);
  setApiStatus("Checking API...", false);
  try {
    const response = await fetch(`${store.apiBase}/health`, { credentials: "include" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok !== true) throw new Error(`API health failed (${response.status})`);
    setApiStatus("API connected.", true);
    toast("API connected.");
  } catch (error) {
    setApiStatus(`API not connected: ${error.message}`, false);
    toast("API not connected.");
  }
}

async function logout(callApi = true) {
  if (callApi) await apiFetch("/logout", { method: "POST", auth: false }).catch(() => {});
  store.user = null;
  store.token = "";
  store.activeOrderId = 0;
  localStorage.removeItem("warehouseMobileUser");
  localStorage.removeItem("warehouseMobileToken");
  localStorage.removeItem("warehouseActiveOrderId");
  stopScanner();
  lockApp();
  toast("Logged out.");
}

function lockApp() {
  $("#auth-gate").classList.add("active");
  $(".mobile-shell").setAttribute("aria-hidden", "true");
}

function unlockApp() {
  $("#auth-gate").classList.remove("active");
  $(".mobile-shell").removeAttribute("aria-hidden");
}

async function refreshAll() {
  await Promise.all([loadDashboard(), loadOrders()]);
}

async function loadDashboard() {
  try {
    const data = await apiFetch("/dashboard");
    $("#m-pending").textContent = data.pending_orders;
  } catch (error) {
    toast(error.message);
  }
}

async function loadOrders() {
  try {
    const data = await apiFetch("/pick-list");
    store.orders = data.orders || [];
    const pending = store.orders.filter((order) => order.status === "pending").length;
    const picking = store.orders.filter((order) => order.status === "picking").length;
    const packed = store.orders.filter((order) => order.status === "packed").length;
    $("#m-pending").textContent = pending;
    $("#m-picking").textContent = picking;
    $("#m-packed").textContent = packed;
    renderOrderQueue();
    renderDispatchQueue();
    renderActiveOrder();
  } catch (error) {
    toast(error.message);
  }
}

function renderOrderQueue() {
  const orders = store.orders.filter((order) => ["pending", "picking"].includes(order.status));
  const target = $("#order-queue");
  if (!orders.length) {
    target.innerHTML = `<div class="empty-state">No pick orders right now.</div>`;
    return;
  }

  target.innerHTML = orders.map(orderCardHtml).join("");
  target.querySelectorAll("[data-start-order]").forEach((card) => {
    card.addEventListener("click", () => startOrder(Number(card.dataset.startOrder)));
  });
}

function orderCardHtml(order) {
  const totalQty = order.items.reduce((sum, item) => sum + item.quantity, 0);
  const pickedQty = order.items.reduce((sum, item) => sum + item.picked_quantity, 0);
  const progress = totalQty ? Math.round((pickedQty / totalQty) * 100) : 0;
  return `
    <article class="order-card tappable" data-start-order="${order.id}">
      <div class="order-top">
        <div>
          <strong>${escapeHtml(order.order_number)}</strong>
          <span>${escapeHtml(order.customer_name)}</span>
        </div>
        <span class="badge ${order.priority === "urgent" ? "warn" : ""}">${escapeHtml(order.priority)}</span>
      </div>
      <div class="progress-line"><span style="width:${progress}%"></span></div>
      <div class="order-meta">
        <span>${order.items.length} SKUs</span>
        <span>${pickedQty}/${totalQty} picked</span>
        <span>${escapeHtml(order.status)}</span>
      </div>
      <div class="order-cta">${order.status === "pending" ? "Tap to start picking" : "Tap to continue"}</div>
    </article>
  `;
}

async function startOrder(orderId) {
  store.activeOrderId = orderId;
  localStorage.setItem("warehouseActiveOrderId", String(orderId));
  const order = activeOrder();
  if (order && order.status === "pending") {
    await apiFetch(`/orders/${order.id}/status`, { method: "POST", body: { status: "picking" } });
    await loadOrders();
  }
  showScreen("pick-screen");
  renderActiveOrder();
}

function activeOrder() {
  return store.orders.find((order) => order.id === store.activeOrderId) || store.orders.find((order) => order.status === "picking") || null;
}

function renderActiveOrder() {
  const order = activeOrder();
  if (!order) {
    $("#active-order-card").innerHTML = `<div class="empty-state">Select an order from the queue.</div>`;
    $("#pick-items").innerHTML = "";
    $("#mark-packed").disabled = true;
    return;
  }

  store.activeOrderId = order.id;
  localStorage.setItem("warehouseActiveOrderId", String(order.id));
  const totalQty = order.items.reduce((sum, item) => sum + item.quantity, 0);
  const pickedQty = order.items.reduce((sum, item) => sum + item.picked_quantity, 0);
  $("#active-order-card").innerHTML = `
    <article class="order-card active">
      <div class="order-top">
        <div>
          <strong>${escapeHtml(order.order_number)}</strong>
          <span>${escapeHtml(order.customer_name)}</span>
        </div>
        <span class="badge">${pickedQty}/${totalQty}</span>
      </div>
    </article>
  `;
  $("#pick-items").innerHTML = order.items.map(pickItemHtml).join("");
  $("#pick-items").querySelectorAll("[data-pick-item]").forEach((button) => {
    button.addEventListener("click", () => updatePickedQuantity(Number(button.dataset.pickItem), Number(button.dataset.quantity)));
  });
  $("#mark-packed").disabled = !order.items.every((item) => item.picked_quantity >= item.quantity);
}

function pickItemHtml(item) {
  const done = item.picked_quantity >= item.quantity;
  return `
    <article class="pick-item ${done ? "done" : ""}" data-product-sku="${escapeHtml(item.product.sku)}" data-item-id="${item.id}">
      <div>
        <strong>${escapeHtml(item.product.sku)}</strong>
        <span>${escapeHtml(item.product.name)}</span>
      </div>
      <div class="qty-control">
        <button type="button" data-pick-item="${item.id}" data-quantity="${Math.max(item.picked_quantity - 1, 0)}">-</button>
        <strong>${item.picked_quantity}/${item.quantity}</strong>
        <button type="button" data-pick-item="${item.id}" data-quantity="${Math.min(item.picked_quantity + 1, item.quantity)}">+</button>
      </div>
    </article>
  `;
}

async function updatePickedQuantity(itemId, quantity) {
  const order = activeOrder();
  if (!order) return;
  try {
    const data = await apiFetch(`/orders/${order.id}/items/${itemId}/pick`, { method: "POST", body: { quantity } });
    replaceOrder(data.order);
    renderActiveOrder();
  } catch (error) {
    toast(error.message);
  }
}

async function markActiveOrderPacked() {
  const order = activeOrder();
  if (!order) return;
  try {
    for (const item of order.items) {
      await apiFetch(`/orders/${order.id}/items/${item.id}/pack`, { method: "POST", body: { quantity: item.quantity } });
    }
    const data = await apiFetch(`/orders/${order.id}/status`, { method: "POST", body: { status: "packed" } });
    replaceOrder(data.order);
    toast("Order packed.");
    await loadOrders();
    showScreen("dispatch-screen");
  } catch (error) {
    toast(error.message);
  }
}

function renderDispatchQueue() {
  const orders = store.orders.filter((order) => ["packed", "dispatched"].includes(order.status));
  const target = $("#dispatch-list");
  if (!orders.length) {
    target.innerHTML = `<div class="empty-state">No packed orders waiting.</div>`;
    return;
  }

  target.innerHTML = orders
    .map((order) => `
      <article class="order-card">
        <div class="order-top">
          <div>
            <strong>${escapeHtml(order.order_number)}</strong>
            <span>${escapeHtml(order.customer_name)}</span>
          </div>
          <span class="badge">${escapeHtml(order.status)}</span>
        </div>
        <div class="order-actions">
          <button type="button" data-order-status="${order.id}:dispatched">Dispatch</button>
          <button class="primary" type="button" data-order-status="${order.id}:completed">Complete</button>
        </div>
      </article>
    `)
    .join("");

  target.querySelectorAll("[data-order-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      const [orderId, status] = button.dataset.orderStatus.split(":");
      await updateOrderStatus(orderId, status);
    });
  });
}

async function updateOrderStatus(orderId, status) {
  try {
    const data = await apiFetch(`/orders/${orderId}/status`, { method: "POST", body: { status } });
    replaceOrder(data.order);
    toast(`Order ${status}.`);
    await loadOrders();
  } catch (error) {
    toast(error.message);
  }
}

async function startScanner() {
  if (!("BarcodeDetector" in window)) {
    toast("Camera barcode detector not supported. Manual entry use karein.");
    return;
  }

  try {
    videoStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    const video = $("#scanner-video");
    video.srcObject = videoStream;
    await video.play();
    const detector = new BarcodeDetector({ formats: ["qr_code", "ean_13", "code_128", "code_39"] });
    scanTimer = window.setInterval(async () => {
      const codes = await detector.detect(video).catch(() => []);
      if (codes.length) {
        const code = codes[0].rawValue;
        stopScanner();
        $("#manual-code").value = code;
        scanCode(code);
      }
    }, 600);
  } catch {
    toast("Camera permission nahi mila.");
  }
}

function stopScanner() {
  if (scanTimer) window.clearInterval(scanTimer);
  scanTimer = null;
  if (videoStream) videoStream.getTracks().forEach((track) => track.stop());
  videoStream = null;
  $("#scanner-video").srcObject = null;
}

async function scanCode(code) {
  if (!code) {
    toast("Code enter karein.");
    return;
  }
  try {
    const data = await apiFetch(`/scan/${encodeURIComponent(code)}`);
    if (scanFillTarget) {
      fillScanTarget(data.type === "location" ? data.location.barcode || data.location.id : data.product.sku);
      return;
    }
    if (data.type === "product") {
      await matchPickedProduct(data.product);
    } else if (data.type === "location") {
      $("#scan-result").innerHTML = `<strong>${escapeHtml(data.location.full_code)}</strong><br><code>${escapeHtml(data.location.barcode)}</code>`;
    }
  } catch (error) {
    $("#scan-result").textContent = error.message;
    toast(error.message);
  }
}

async function matchPickedProduct(product) {
  const order = activeOrder();
  if (!order) {
    toast("Select an order first.");
    return;
  }
  const item = order.items.find((orderItem) => orderItem.product.id === product.id || orderItem.product.sku === product.sku);
  if (!item) {
    $("#scan-result").innerHTML = `<strong>${escapeHtml(product.sku)}</strong><br>Not in active order.`;
    toast("Item not in this order.");
    return;
  }
  const nextQuantity = Math.min(item.picked_quantity + 1, item.quantity);
  await updatePickedQuantity(item.id, nextQuantity);
  $("#scan-result").innerHTML = `<strong>${escapeHtml(product.sku)}</strong><br>Picked ${nextQuantity}/${item.quantity}`;
}

function fillScanTarget(value) {
  const input = $(scanFillTarget);
  if (input) {
    input.value = value;
    input.focus();
  }
  if (scanFillTarget === '#stock-in-form [name=\'product\']') {
    loadStockProductPreview(value);
  }
  const returnScreen = scanReturnScreen;
  scanFillTarget = null;
  scanReturnScreen = null;
  if (returnScreen) showScreen(returnScreen);
  toast("Field filled.");
}

async function submitStock(event, endpoint) {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.quantity = Number(payload.quantity);

  try {
    await apiFetch(`/${endpoint}`, { method: "POST", body: payload });
    form.reset();
    resetStockProductPreview();
    toast("Stock in saved.");
    await refreshAll();
  } catch (error) {
    toast(error.message);
  }
}

async function loadStockProductPreview(code) {
  if (!code) {
    resetStockProductPreview();
    return;
  }
  try {
    const data = await apiFetch(`/scan/${encodeURIComponent(code)}`);
    if (data.type !== "product") {
      resetStockProductPreview("Scan a product SKU or barcode first.");
      return;
    }
    const product = data.product;
    const imageSrc = productImageSrc(product);
    const preview = $("#stock-product-preview");
    preview.classList.remove("hidden", "product-preview--message");
    preview.innerHTML = `
      <div class="product-preview-thumb ${imageSrc ? "" : "empty"}">
        ${imageSrc ? `<img src="${escapeHtml(imageSrc)}" alt="${escapeHtml(product.name)}">` : "<span>No image</span>"}
      </div>
      <div class="product-preview-info">
        <strong>${escapeHtml(product.sku)} / ${escapeHtml(product.name)}</strong>
        <span>Available: ${product.available_quantity}</span>
        <span>${product.image_url ? "Product image loaded" : "No product image saved"}</span>
      </div>
    `;
    preview.querySelector("img")?.addEventListener("error", (event) => {
      const thumb = event.currentTarget.closest(".product-preview-thumb");
      thumb.classList.add("empty");
      thumb.innerHTML = "<span>Image unavailable</span>";
    });
    $("#stock-details").classList.remove("hidden");
    $('#stock-in-form [name="location"]').disabled = false;
    $('#stock-in-form [name="quantity"]').disabled = false;
  } catch (error) {
    resetStockProductPreview(error.message);
  }
}

function resetStockProductPreview(message = "Scan SKU to load product.") {
  const preview = $("#stock-product-preview");
  preview.classList.toggle("hidden", !message);
  preview.classList.add("product-preview--message");
  preview.textContent = message;
  $("#stock-details").classList.add("hidden");
  $('#stock-in-form [name="location"]').disabled = true;
  $('#stock-in-form [name="quantity"]').disabled = true;
}

function productImageSrc(product) {
  const raw = product?.image_display_url || product?.image_url || "";
  if (!raw || raw.startsWith("gs://")) return "";
  if (/^(https?:|data:|blob:)/i.test(raw)) return raw;

  try {
    const apiUrl = new URL(store.apiBase);
    return new URL(raw, `${apiUrl.protocol}//${apiUrl.host}`).href;
  } catch {
    return raw;
  }
}

async function submitLocationUpdate(event) {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.quantity = Number(payload.quantity);

  try {
    await apiFetch("/location-update", { method: "POST", body: payload });
    form.reset();
    toast("Stock moved.");
    await refreshAll();
  } catch (error) {
    toast(error.message);
  }
}

function replaceOrder(order) {
  const index = store.orders.findIndex((existing) => existing.id === order.id);
  if (index >= 0) store.orders.splice(index, 1, order);
  else store.orders.push(order);
}

async function apiFetch(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const init = {
    method: options.method || "GET",
    credentials: "include",
    headers: {},
  };
  if (!isFormData) init.headers["Content-Type"] = "application/json";
  if (store.token && options.auth !== false) init.headers.Authorization = `Bearer ${store.token}`;
  if (options.body) init.body = isFormData ? options.body : JSON.stringify(options.body);

  const response = await fetch(`${store.apiBase}${path}`, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    if (response.status === 401 && options.auth !== false) logout(false);
    throw new Error(data.message || `API error ${response.status}`);
  }
  return data;
}

function initialApiBase() {
  const fallback = "http://127.0.0.1:5000/api";
  const remotePage = location.hostname && !["localhost", "127.0.0.1"].includes(location.hostname);
  if (configuredApiBase && (!savedApiBase || (remotePage && isLocalApiBase(savedApiBase)))) {
    localStorage.setItem("warehouseMobileApi", configuredApiBase);
    return configuredApiBase;
  }
  return savedApiBase || configuredApiBase || fallback;
}

function normalizeApiBase(value) {
  return String(value || "").trim().replace(/\/$/, "");
}

function isLocalApiBase(value) {
  try {
    const url = new URL(value);
    return ["localhost", "127.0.0.1"].includes(url.hostname);
  } catch {
    return false;
  }
}

function setApiStatus(message, ok) {
  const node = $("#api-status");
  node.textContent = message;
  node.classList.toggle("ok", ok);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove("show"), 2600);
}
