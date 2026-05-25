const configuredApiBase = normalizeApiBase(window.WAREHOUSE_API_BASE || "");
const savedApiBase = normalizeApiBase(localStorage.getItem("warehouseMobileApi") || "");
const configuredApiCandidates = Array.isArray(window.WAREHOUSE_API_CANDIDATES) ? window.WAREHOUSE_API_CANDIDATES : [];

const store = {
  apiBase: initialApiBase(),
  user: JSON.parse(localStorage.getItem("warehouseMobileUser") || "null"),
  token: localStorage.getItem("warehouseMobileToken") || "",
  warehouses: JSON.parse(localStorage.getItem("warehouseMobileWarehouses") || "[]"),
  warehouseId: Number(localStorage.getItem("warehouseMobileWarehouseId") || 0),
  orders: [],
  returns: [],
  activeOrderId: Number(localStorage.getItem("warehouseActiveOrderId") || 0),
  activeReturnId: Number(localStorage.getItem("warehouseActiveReturnId") || 0),
  activePickLocation: null,
  activePickInventory: [],
  inventoryView: null,
  moveInventory: [],
  priorityFilter: localStorage.getItem("warehousePriorityFilter") || "all",
  batchMode: localStorage.getItem("warehouseBatchMode") === "true",
  automationSettings: JSON.parse(localStorage.getItem("warehouseAutomationSettings") || "{}"),
  offlineQueue: JSON.parse(localStorage.getItem("warehouseOfflineQueue") || "[]"),
  shiftStartedAt: localStorage.getItem("warehouseShiftStartedAt") || "",
};

let videoStream = null;
let scanTimer = null;
let scanFillTarget = null;
let scanReturnScreen = null;
let refreshTimer = null;
let stockPreviewTimer = null;
let activeReturnConfirmed = false;
let lastSlaAlertAt = 0;
const defaultScreenId = "hub-screen";
const standaloneApp = window.matchMedia?.("(display-mode: standalone)")?.matches || window.navigator.standalone === true;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", async () => {
  $("#api-base").value = store.apiBase;
  bindNavigation();
  bindActions();
  initializeBackNavigation();
  await autoConnectApi();
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
  $("#warehouse-select").addEventListener("change", changeWarehouse);
  $("#sync-btn").addEventListener("click", refreshAll);
  $("#hub-refresh").addEventListener("click", refreshAll);
  $("#shift-toggle").addEventListener("click", toggleShift);
  $("#global-search").addEventListener("input", renderGlobalSearch);
  $("#clear-global-search").addEventListener("click", clearGlobalSearch);
  $("#refresh-orders").addEventListener("click", refreshAll);
  $("#refresh-returns").addEventListener("click", refreshAll);
  $$("[data-screen-jump]").forEach((button) => {
    button.addEventListener("click", () => showScreen(button.dataset.screenJump));
  });
  $("#priority-filter").value = store.priorityFilter;
  $("#priority-filter").addEventListener("change", changePriorityFilter);
  $("#optimize-route").addEventListener("click", optimizeRoute);
  $("#batch-mode-toggle").addEventListener("click", toggleBatchMode);
  $("#run-automation").addEventListener("click", runAutomationCheck);
  $("#auto-start-next").addEventListener("click", startBestOrder);
  $("#retry-offline").addEventListener("click", retryOfflineQueue);
  $("#copy-shift-summary").addEventListener("click", copyShiftSummary);
  $("#copy-route-plan").addEventListener("click", copyRoutePlan);
  $$("[data-automation-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleAutomationSetting(button.dataset.automationToggle));
  });
  $("#return-lookup-form").addEventListener("submit", startReturnFromLookup);
  $("#return-scan-item").addEventListener("click", () => scanReturnCode($("#return-code").value.trim()));
  $("#back-to-returns").addEventListener("click", closeActiveReturn);
  $("#initiate-pv").addEventListener("click", initiateReturnPv);
  $("#pv-back").addEventListener("click", () => showScreen("return-screen"));
  $$("[data-refresh-orders]").forEach((button) => button.addEventListener("click", refreshAll));
  $$("#handoff-bag-check, #handoff-label-check, #handoff-payment-check").forEach((input) => {
    input.addEventListener("change", renderDispatchQueue);
  });
  $("#start-scan").addEventListener("click", startScanner);
  $("#stop-scan").addEventListener("click", stopScanner);
  $("#manual-scan").addEventListener("click", () => scanCode($("#manual-code").value.trim()));
  $("#back-to-orders").addEventListener("click", cancelScanOrBackToOrders);
  $("#mark-packed").addEventListener("click", markActiveOrderPacked);
  $("#stock-in-form").addEventListener("submit", (event) => submitStock(event, "stock-in"));
  $('#stock-in-form [name="product"]').addEventListener("input", scheduleStockProductPreview);
  $('#stock-in-form [name="product"]').addEventListener("change", () => loadStockProductPreview($('#stock-in-form [name="product"]').value.trim()));
  $('#stock-in-form [name="product"]').addEventListener("blur", () => loadStockProductPreview($('#stock-in-form [name="product"]').value.trim()));
  $("#location-form").addEventListener("submit", submitLocationUpdate);
  $("#load-move-bin").addEventListener("click", () => loadMoveBinInventory($('#location-form [name="from_location"]').value.trim()));
  $('#location-form [name="from_location"]').addEventListener("change", () => loadMoveBinInventory($('#location-form [name="from_location"]').value.trim()));
  $('#location-form [name="from_location"]').addEventListener("blur", () => loadMoveBinInventory($('#location-form [name="from_location"]').value.trim()));
  $("#inventory-lookup-form").addEventListener("submit", (event) => {
    event.preventDefault();
    loadInventoryView($('#inventory-lookup-form [name="location"]').value.trim());
  });
  $('#inventory-lookup-form [name="location"]').addEventListener("change", () => loadInventoryView($('#inventory-lookup-form [name="location"]').value.trim()));
  $('#inventory-lookup-form [name="location"]').addEventListener("blur", () => loadInventoryView($('#inventory-lookup-form [name="location"]').value.trim()));
  $$("[data-scan-fill]").forEach((button) => {
    button.addEventListener("click", () => beginScanFill(button.dataset.scanFill));
  });
}

function beginScanFill(target) {
  scanFillTarget = target;
  scanReturnScreen = $(".screen.active")?.id || "orders-screen";
  $("#manual-code").value = "";
  $("#manual-code").placeholder = scanFillTarget.includes("location") ? "Scan bin barcode" : "Scan product barcode";
  $("#scan-result").textContent = scanFillTarget.includes("location") ? "Scan bin barcode." : "Scan product barcode.";
  showScreen("pick-screen");
  startScanner();
}

function initializeBackNavigation() {
  if (!window.history?.replaceState) return;
  const currentScreenId = activeScreenId();
  replaceAppHistory(currentScreenId);
  if (standaloneApp && window.history.pushState) pushAppHistory(currentScreenId);
  window.addEventListener("popstate", restoreFromHistory);
}

function activeScreenId() {
  return $(".screen.active")?.id || defaultScreenId;
}

function appHistoryState(screenId) {
  return {
    warehouseScreen: screenId,
    activeOrderId: store.activeOrderId || 0,
    activeReturnId: store.activeReturnId || 0,
  };
}

function pushAppHistory(screenId) {
  if (!window.history?.pushState) return;
  window.history.pushState(appHistoryState(screenId), "", window.location.href);
}

function replaceAppHistory(screenId) {
  if (!window.history?.replaceState) return;
  window.history.replaceState(appHistoryState(screenId), "", window.location.href);
}

function restoreFromHistory(event) {
  const state = event.state || {};
  const screenId = state.warehouseScreen;
  if (!screenId || !document.getElementById(screenId)) {
    if (standaloneApp) {
      pushAppHistory(activeScreenId());
      toast("App close nahi hoga. Navigation buttons use karein.");
    }
    return;
  }

  if (standaloneApp && screenId === activeScreenId() && screenId === defaultScreenId) {
    pushAppHistory(screenId);
    toast("App close nahi hoga. Navigation buttons use karein.");
    return;
  }

  store.activeOrderId = Number(state.activeOrderId || 0);
  store.activeReturnId = Number(state.activeReturnId || 0);
  if (store.activeOrderId) localStorage.setItem("warehouseActiveOrderId", String(store.activeOrderId));
  else localStorage.removeItem("warehouseActiveOrderId");
  if (store.activeReturnId) localStorage.setItem("warehouseActiveReturnId", String(store.activeReturnId));
  else localStorage.removeItem("warehouseActiveReturnId");

  if (scanFillTarget) clearScanFillTarget();
  showScreen(screenId, { history: false });
  renderActiveOrder();
  renderReturnQueue();
  renderActiveReturn();
  renderReturnPv();
}

function showScreen(screenId, options = {}) {
  const previousScreenId = activeScreenId();
  $$(".screen").forEach((screen) => screen.classList.toggle("active", screen.id === screenId));
  $$(".bottom-nav [data-screen]").forEach((button) => button.classList.toggle("active", button.dataset.screen === screenId));
  const titles = {
    "hub-screen": "Command",
    "orders-screen": "Orders",
    "pick-screen": "Order Picking",
    "automation-screen": "Ops Automation",
    "dispatch-screen": "Dispatch",
    "return-screen": "Returns",
    "pv-screen": "Return PV",
    "stock-screen": "Stock In",
    "move-screen": "Move Stock",
    "inventory-screen": "View Inventory",
  };
  $("#screen-title").textContent = titles[screenId] || "Picker";
  if (screenId !== "pick-screen") stopScanner();
  if (options.history !== false) {
    if (previousScreenId === screenId && !options.forceHistory) replaceAppHistory(screenId);
    else pushAppHistory(screenId);
  }
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
    applyUserWarehouses(data.user);
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
    applyUserWarehouses(store.user);
    localStorage.setItem("warehouseMobileUser", JSON.stringify(store.user));
    if (store.token) localStorage.setItem("warehouseMobileToken", store.token);
    unlockApp();
    toast(`Welcome ${store.user.name}`);
    await refreshAll();
  } catch (error) {
    lockApp();
    setApiStatus(error.message, false);
    toast(error.message);
  }
}

async function testApiConnection() {
  store.apiBase = normalizeApiBase($("#api-base").value);
  localStorage.setItem("warehouseMobileApi", store.apiBase);
  setApiStatus("Checking API...", false);
  try {
    await testApiBase(store.apiBase);
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
  store.warehouses = [];
  store.warehouseId = 0;
  store.activeOrderId = 0;
  store.activePickLocation = null;
  store.activePickInventory = [];
  localStorage.removeItem("warehouseMobileUser");
  localStorage.removeItem("warehouseMobileToken");
  localStorage.removeItem("warehouseMobileWarehouses");
  localStorage.removeItem("warehouseMobileWarehouseId");
  localStorage.removeItem("warehouseActiveOrderId");
  localStorage.removeItem("warehouseActivePickLocation");
  stopScanner();
  lockApp();
  toast("Logged out.");
}

function lockApp() {
  $("#auth-gate").classList.add("active");
  $(".mobile-shell").setAttribute("aria-hidden", "true");
  stopAutoRefresh();
}

function unlockApp() {
  $("#auth-gate").classList.remove("active");
  $(".mobile-shell").removeAttribute("aria-hidden");
  applyUserWarehouses(store.user);
  startAutoRefresh();
}

function applyUserWarehouses(user) {
  store.warehouses = Array.isArray(user?.warehouses) ? user.warehouses : store.warehouses;
  const selected = user?.warehouse || store.warehouses.find((warehouse) => warehouse.id === store.warehouseId) || store.warehouses[0] || null;
  store.warehouseId = selected?.id || store.warehouseId || 0;
  localStorage.setItem("warehouseMobileWarehouses", JSON.stringify(store.warehouses));
  if (store.warehouseId) localStorage.setItem("warehouseMobileWarehouseId", String(store.warehouseId));
  renderWarehouseSelect();
}

function renderWarehouseSelect() {
  const select = $("#warehouse-select");
  if (!select) return;
  select.innerHTML = store.warehouses
    .map((warehouse) => `<option value="${warehouse.id}" ${warehouse.id === store.warehouseId ? "selected" : ""}>${escapeHtml(warehouse.code)}</option>`)
    .join("");
  select.disabled = store.warehouses.length <= 1;
}

async function changeWarehouse(event) {
  store.warehouseId = Number(event.target.value || 0);
  localStorage.setItem("warehouseMobileWarehouseId", String(store.warehouseId));
  store.activePickLocation = null;
  store.activePickInventory = [];
  store.inventoryView = null;
  store.moveInventory = [];
  $("#manual-code").value = "";
  toast("Warehouse changed.");
  await refreshAll();
}

async function refreshAll() {
  await Promise.all([loadDashboard(), loadOrders(), loadReturns()]);
  renderHub();
  renderOpsAutomation();
}

function startAutoRefresh() {
  if (refreshTimer) return;
  refreshTimer = window.setInterval(() => {
    if (store.user) refreshAll().catch(() => {});
  }, 15000);
}

function stopAutoRefresh() {
  if (!refreshTimer) return;
  window.clearInterval(refreshTimer);
  refreshTimer = null;
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
    renderQuickOps();
    renderBatchGroups();
    renderOpsAutomation();
    renderHub();
    renderDispatchQueue();
    renderActiveOrder();
  } catch (error) {
    toast(error.message);
  }
}

async function loadReturns() {
  try {
    const data = await apiFetch("/returns/pick-list");
    store.returns = data.returns || [];
    renderReturnQueue();
    renderActiveReturn();
    renderReturnPv();
    renderHub();
  } catch (error) {
    toast(error.message);
  }
}

function renderHub() {
  const pickOrders = store.orders.filter((order) => ["pending", "picking"].includes(order.status));
  const packed = store.orders.filter((order) => order.status === "packed");
  const returnDesk = store.returns.filter((item) => ["approved", "return_picking", "return_picked", "inspection"].includes(item.status));
  const slaRisk = pickOrders.filter((order) => slaMinutesLeft(order) <= 10);
  const pickedQty = pickOrders.reduce((sum, order) => sum + (order.items || []).reduce((itemSum, item) => itemSum + Number(item.picked_quantity || 0), 0), 0);
  const totalItems = pickOrders.reduce((sum, order) => sum + (order.items || []).length, 0);
  const shortageCount = exceptionOrders().filter((item) => item.action === "Substitute").length;
  const name = store.user?.name || store.user?.email || "Picker";
  const warehouse = currentWarehouseName();
  $("#hub-greeting").textContent = `${name}, mission ready`;
  $("#hub-warehouse").textContent = warehouse ? `${warehouse} live floor` : "Warehouse sync pending";
  $("#hub-pick-load").textContent = pickOrders.length;
  $("#hub-sla-heat").textContent = slaRisk.length;
  $("#hub-pack-ready").textContent = packed.length;
  $("#hub-return-desk").textContent = returnDesk.length;
  $("#hub-picked-qty").textContent = pickedQty;
  $("#hub-avg-items").textContent = pickOrders.length ? (totalItems / pickOrders.length).toFixed(1) : "0";
  $("#hub-shortage").textContent = shortageCount;
  $("#hub-shift").textContent = store.shiftStartedAt ? "On" : "Off";
  $("#hub-shift-time").textContent = store.shiftStartedAt ? shiftDurationLabel() : "Not started";
  $("#shift-toggle").textContent = store.shiftStartedAt ? "End Shift" : "Start Shift";
  renderHubMissions(pickOrders, packed, returnDesk);
  renderGlobalSearch();
}

function renderHubMissions(pickOrders, packed, returnDesk) {
  const target = $("#hub-missions");
  if (!target) return;
  const missions = [
    ...filteredPickOrders().slice(0, 3).map((order) => ({
      title: orderShortCode(order),
      detail: `${order.items?.length || 0} SKUs · ${Math.max(slaMinutesLeft(order), 0)} min SLA`,
      tag: order.priority || order.status || "pick",
      screen: "pick",
      id: order.id,
    })),
    ...packed.slice(0, 1).map((order) => ({
      title: `Ship ${orderShortCode(order)}`,
      detail: order.customer_name || "Ready for rider handoff",
      tag: "handoff",
      screen: "dispatch-screen",
    })),
    ...returnDesk.slice(0, 1).map((item) => ({
      title: item.return_number || item.website_order_id || `Return ${item.id}`,
      detail: item.reason || "Return quality check",
      tag: "return",
      screen: "return-screen",
    })),
  ];
  if (!missions.length) {
    target.innerHTML = `<div class="empty-state">No live mission right now. Sync karke latest queue dekhein.</div>`;
    return;
  }
  target.innerHTML = missions.map((mission) => `
    <article class="order-card tappable" data-hub-screen="${mission.screen}" data-hub-order="${mission.id || ""}">
      <div class="order-top">
        <div>
          <strong>${escapeHtml(mission.title)}</strong>
          <span>${escapeHtml(mission.detail)}</span>
        </div>
        <span class="badge ${String(mission.tag).toLowerCase() === "urgent" ? "warn" : ""}">${escapeHtml(mission.tag)}</span>
      </div>
      <div class="order-cta">${mission.screen === "pick" ? "Start picking" : "Open mission"}</div>
    </article>
  `).join("");
  target.querySelectorAll("[data-hub-screen]").forEach((card) => {
    card.addEventListener("click", () => {
      if (card.dataset.hubScreen === "pick" && card.dataset.hubOrder) startOrder(Number(card.dataset.hubOrder));
      else showScreen(card.dataset.hubScreen);
    });
  });
}

function toggleShift() {
  if (store.shiftStartedAt) {
    store.shiftStartedAt = "";
    localStorage.removeItem("warehouseShiftStartedAt");
    toast("Shift ended.");
  } else {
    store.shiftStartedAt = new Date().toISOString();
    localStorage.setItem("warehouseShiftStartedAt", store.shiftStartedAt);
    toast("Shift started.");
  }
  renderHub();
  renderOpsAutomation();
}

function shiftDurationLabel() {
  const started = new Date(store.shiftStartedAt);
  if (Number.isNaN(started.getTime())) return "Live";
  const minutes = Math.max(0, Math.floor((Date.now() - started.getTime()) / 60000));
  if (minutes < 60) return `${minutes}m live`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function renderGlobalSearch() {
  const input = $("#global-search");
  const target = $("#global-search-results");
  if (!input || !target) return;
  const query = input.value.trim().toLowerCase();
  target.classList.toggle("hidden", !query);
  if (!query) {
    target.innerHTML = "";
    return;
  }
  const orderResults = store.orders
    .filter((order) => searchTextForOrder(order).includes(query))
    .slice(0, 6)
    .map((order) => ({ type: "order", order }));
  const returnResults = store.returns
    .filter((item) => searchTextForReturn(item).includes(query))
    .slice(0, 3)
    .map((returnOrder) => ({ type: "return", returnOrder }));
  const results = [...orderResults, ...returnResults];
  target.innerHTML = results.length ? results.map(searchResultHtml).join("") : `<div class="empty-state">No match found.</div>`;
  target.querySelectorAll("[data-search-order]").forEach((card) => {
    card.addEventListener("click", () => startOrder(Number(card.dataset.searchOrder)));
  });
  target.querySelectorAll("[data-search-return]").forEach((card) => {
    card.addEventListener("click", () => startReturn(Number(card.dataset.searchReturn)));
  });
}

function clearGlobalSearch() {
  $("#global-search").value = "";
  renderGlobalSearch();
}

function searchResultHtml(result) {
  if (result.type === "return") {
    const item = result.returnOrder;
    return `
      <article class="order-card tappable" data-search-return="${item.id}">
        <div class="order-top">
          <div><strong>${escapeHtml(item.return_number || item.website_order_id || item.id)}</strong><span>${escapeHtml(item.reason || item.status || "return")}</span></div>
          <span class="badge">return</span>
        </div>
      </article>
    `;
  }
  const order = result.order;
  return `
    <article class="order-card tappable" data-search-order="${order.id}">
      <div class="order-top">
        <div><strong>${escapeHtml(orderShortCode(order))}</strong><span>${escapeHtml(order.customer_name || order.status || "order")}</span></div>
        <span class="badge">${escapeHtml(order.status || "order")}</span>
      </div>
    </article>
  `;
}

function searchTextForOrder(order) {
  return [
    order.id,
    order.order_number,
    order.website_order_id,
    order.customer_name,
    order.customer_phone,
    order.pincode,
    order.awb,
    order.tracking_number,
    order.status,
    ...(order.items || []).flatMap((item) => [item.sku, item.product_sku, item.product?.sku, item.product?.name, item.product_name]),
  ].join(" ").toLowerCase();
}

function searchTextForReturn(item) {
  return [item.id, item.return_number, item.website_order_id, item.order_id, item.reason, item.status, item.customer_name].join(" ").toLowerCase();
}

function currentWarehouseName() {
  const selected = store.warehouses.find((warehouse) => Number(warehouse.id) === Number(store.warehouseId));
  return selected?.name || selected?.code || selected?.warehouse_name || "";
}

function renderOrderQueue() {
  const orders = filteredPickOrders();
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

function filteredPickOrders() {
  const filter = store.priorityFilter;
  return store.orders
    .filter((order) => ["pending", "picking"].includes(order.status))
    .filter((order) => {
      if (filter === "all") return true;
      if (filter === "sla") return slaMinutesLeft(order) <= 10;
      if (filter === "pending" || filter === "picking") return order.status === filter;
      return String(order.priority || "").toLowerCase() === filter;
    })
    .sort((a, b) => orderPriorityScore(b) - orderPriorityScore(a) || routeKey(a).localeCompare(routeKey(b)));
}

function changePriorityFilter(event) {
  store.priorityFilter = event.target.value;
  localStorage.setItem("warehousePriorityFilter", store.priorityFilter);
  renderOrderQueue();
  renderBatchGroups();
}

function toggleBatchMode() {
  store.batchMode = !store.batchMode;
  localStorage.setItem("warehouseBatchMode", String(store.batchMode));
  renderBatchGroups();
  toast(store.batchMode ? "Batch picking enabled." : "Batch picking disabled.");
}

function optimizeRoute() {
  store.automationSettings.routeAssist = true;
  saveAutomationSettings();
  renderOrderQueue();
  renderQuickOps();
  renderBatchGroups();
  renderOpsAutomation();
  toast("Route optimized by priority and bin sequence.");
}

function runAutomationCheck() {
  renderQuickOps();
  renderBatchGroups();
  renderOpsAutomation();
  toast("Automation check complete.");
}

function toggleAutomationSetting(key) {
  store.automationSettings[key] = !store.automationSettings[key];
  saveAutomationSettings();
  if (key === "slaAlerts" && store.automationSettings[key]) requestLocalNotifications();
  renderOrderQueue();
  renderOpsAutomation();
  if (key === "routeAssist") renderBatchGroups();
}

function requestLocalNotifications() {
  if (!("Notification" in window) || Notification.permission !== "default") return;
  Notification.requestPermission().catch(() => {});
}

function saveAutomationSettings() {
  localStorage.setItem("warehouseAutomationSettings", JSON.stringify(store.automationSettings));
}

function renderQuickOps() {
  const pickOrders = store.orders.filter((order) => ["pending", "picking"].includes(order.status));
  const next = filteredPickOrders()[0];
  const exceptions = exceptionOrders();
  const slaRisk = pickOrders.filter((order) => slaMinutesLeft(order) <= 10).length;
  $("#m-sla-risk").textContent = slaRisk;
  $("#m-next-pick").textContent = next ? orderShortCode(next) : "--";
  $("#m-route-score").textContent = routeScore(pickOrders);
  $("#m-exceptions").textContent = exceptions.length;
  maybeNotifySlaRisk(slaRisk, next);
}

function maybeNotifySlaRisk(count, nextOrder) {
  if (!store.automationSettings.slaAlerts || !count || !("Notification" in window) || Notification.permission !== "granted") return;
  if (Date.now() - lastSlaAlertAt < 120000) return;
  lastSlaAlertAt = Date.now();
  new Notification("Picker SLA alert", {
    body: `${count} order SLA risk me hai. Next: ${nextOrder ? orderShortCode(nextOrder) : "open queue"}`,
  });
}

function renderBatchGroups() {
  const target = $("#batch-groups");
  $("#batch-mode-toggle").textContent = store.batchMode ? "Batch On" : "Batch Off";
  $("#batch-mode-toggle").classList.toggle("primary", store.batchMode);
  if (!store.batchMode) {
    target.innerHTML = "";
    return;
  }
  const groups = batchGroups();
  if (!groups.length) {
    target.innerHTML = `<div class="empty-state">No batchable SKUs in current queue.</div>`;
    return;
  }
  target.innerHTML = groups
    .slice(0, 3)
    .map((group) => `
      <article class="batch-card">
        <div>
          <strong>${escapeHtml(group.sku)}</strong>
          <span>${group.orders.length} orders · ${group.quantity} qty</span>
        </div>
        <b>${escapeHtml(group.bin || "Bin pending")}</b>
      </article>
    `)
    .join("");
}

function renderOpsAutomation() {
  const best = filteredPickOrders()[0];
  const pickOrders = store.orders.filter((order) => ["pending", "picking"].includes(order.status));
  const totalQty = pickOrders.reduce((sum, order) => sum + (order.items || []).reduce((itemSum, item) => itemSum + Number(item.quantity || 0), 0), 0);
  const pickedQty = pickOrders.reduce((sum, order) => sum + (order.items || []).reduce((itemSum, item) => itemSum + Number(item.picked_quantity || 0), 0), 0);
  const packedOrders = store.orders.filter((order) => order.status === "packed");
  $("#auto-next-order").textContent = best ? orderShortCode(best) : "--";
  $("#auto-sla-count").textContent = pickOrders.filter((order) => slaMinutesLeft(order) <= 10).length;
  $("#auto-offline-count").textContent = store.offlineQueue.length;
  $("#auto-productivity").textContent = totalQty ? `${Math.round((pickedQty / totalQty) * 100)}%` : "--";
  $("#auto-route-stops").textContent = routeStops().length;
  $("#auto-batchable").textContent = batchGroups().length;
  $("#auto-quality").textContent = packedOrders.length ? `${packedOrders.length} ready` : "Clear";
  $("#auto-workload").textContent = pickOrders.length > 15 ? "High" : pickOrders.length > 5 ? "Medium" : "Low";
  Object.entries({ autoAssign: "autoAssign", shortageAlert: "shortageAlert", routeAssist: "routeAssist", slaAlerts: "slaAlerts" }).forEach(([key, id]) => {
    const node = $(`#toggle-${id}`);
    if (node) node.textContent = store.automationSettings[key] ? "On" : "Off";
  });
  renderExceptionQueue();
  renderRouteTimeline();
}

function renderRouteTimeline() {
  const target = $("#route-timeline");
  if (!target) return;
  const stops = routeStops();
  if (!stops.length) {
    target.innerHTML = `<div class="empty-state">No route stops. Queue me bin data aate hi timeline ban jayega.</div>`;
    return;
  }
  target.innerHTML = stops.slice(0, 8).map((stop, index) => `
    <article class="route-stop">
      <b>${index + 1}</b>
      <div>
        <strong>${escapeHtml(stop.bin || "Bin pending")}</strong>
        <span>${stop.orders.length} orders - ${stop.quantity} qty - ${escapeHtml(stop.skus.slice(0, 3).join(", "))}</span>
      </div>
    </article>
  `).join("");
}

function renderExceptionQueue() {
  const target = $("#exception-list");
  if (!target) return;
  const exceptions = exceptionOrders();
  if (!exceptions.length) {
    target.innerHTML = `<div class="empty-state">No exceptions. Picker flow healthy.</div>`;
    return;
  }
  target.innerHTML = exceptions.map((item) => `
    <article class="exception-card">
      <div>
        <strong>${escapeHtml(orderShortCode(item.order))}</strong>
        <span>${escapeHtml(item.reason)}</span>
      </div>
      <b>${escapeHtml(item.action)}</b>
    </article>
  `).join("");
}

function exceptionOrders() {
  return store.orders.flatMap((order) => {
    const rows = [];
    if (["pending", "picking"].includes(order.status) && slaMinutesLeft(order) <= 10) {
      rows.push({ order, reason: "SLA risk: pick fast", action: "Priority" });
    }
    if (!Array.isArray(order.items) || !order.items.length) {
      rows.push({ order, reason: "Items missing in order payload", action: "Check" });
    }
    (order.items || []).forEach((item) => {
      const available = Number(item.available_quantity ?? item.stock_quantity ?? item.inventory_quantity ?? 0);
      const needed = Number(item.quantity || 0) - Number(item.picked_quantity || 0);
      if (needed > 0 && available < needed && store.automationSettings.shortageAlert) {
        rows.push({ order, reason: `${itemLabel(item)} stock short by ${needed - available}`, action: "Substitute" });
      }
    });
    return rows;
  });
}

function batchGroups() {
  const groups = new Map();
  filteredPickOrders().forEach((order) => {
    (order.items || []).forEach((item) => {
      const remaining = Number(item.quantity || 0) - Number(item.picked_quantity || 0);
      if (remaining <= 0) return;
      const sku = itemLabel(item);
      const bin = item.location_barcode || item.location_name || item.bin || item.location || "";
      const key = `${sku}|${bin}`;
      if (!groups.has(key)) groups.set(key, { sku, bin, quantity: 0, orders: [] });
      const group = groups.get(key);
      group.quantity += remaining;
      group.orders.push(order.id);
    });
  });
  return Array.from(groups.values())
    .filter((group) => group.orders.length > 1 || group.quantity > 1)
    .sort((a, b) => b.orders.length - a.orders.length || a.sku.localeCompare(b.sku));
}

function routeStops() {
  const stops = new Map();
  filteredPickOrders().forEach((order) => {
    (order.items || []).forEach((item) => {
      const remaining = Number(item.quantity || 0) - Number(item.picked_quantity || 0);
      if (remaining <= 0) return;
      const bin = item.location_barcode || item.location_name || item.bin || item.location || routeKey(order) || "";
      if (!bin) return;
      if (!stops.has(bin)) stops.set(bin, { bin, orders: [], quantity: 0, skus: [] });
      const stop = stops.get(bin);
      stop.quantity += remaining;
      if (!stop.orders.includes(order.id)) stop.orders.push(order.id);
      const sku = itemLabel(item);
      if (!stop.skus.includes(sku)) stop.skus.push(sku);
    });
  });
  return Array.from(stops.values()).sort((a, b) => a.bin.localeCompare(b.bin));
}

function startBestOrder() {
  const best = filteredPickOrders()[0];
  if (!best) {
    toast("No best order available.");
    return;
  }
  startOrder(best.id);
}

async function retryOfflineQueue() {
  if (!store.offlineQueue.length) {
    toast("Offline queue empty.");
    return;
  }
  const pending = [...store.offlineQueue];
  const failed = [];
  store.offlineQueue = [];
  localStorage.setItem("warehouseOfflineQueue", JSON.stringify(store.offlineQueue));
  for (const item of pending) {
    try {
      await apiFetch(item.path, { method: item.method, body: item.body });
    } catch {
      failed.push(item);
    }
  }
  store.offlineQueue = failed.slice(-25);
  localStorage.setItem("warehouseOfflineQueue", JSON.stringify(store.offlineQueue));
  await refreshAll();
  toast(failed.length ? `${failed.length} offline action pending.` : "Offline sync complete.");
}

function copyShiftSummary() {
  const pickOrders = store.orders.filter((order) => ["pending", "picking"].includes(order.status));
  const packed = store.orders.filter((order) => order.status === "packed").length;
  const summary = [
    `Picker: ${store.user?.name || store.user?.email || "Picker"}`,
    `Warehouse: ${currentWarehouseName() || store.warehouseId || "NA"}`,
    `Shift: ${store.shiftStartedAt ? shiftDurationLabel() : "Off"}`,
    `Pick load: ${pickOrders.length}`,
    `Packed: ${packed}`,
    `SLA risk: ${pickOrders.filter((order) => slaMinutesLeft(order) <= 10).length}`,
    `Exceptions: ${exceptionOrders().length}`,
  ].join("\n");
  copyText(summary, "Shift summary copied.");
}

function copyRoutePlan() {
  const plan = routeStops().map((stop, index) => `${index + 1}. ${stop.bin} - ${stop.quantity} qty - ${stop.skus.join(", ")}`).join("\n");
  copyText(plan || "No route stops.", "Route plan copied.");
}

function copyText(value, message) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(value).then(() => toast(message)).catch(() => toast(value));
  } else {
    toast(value);
  }
}

function orderPriorityScore(order) {
  const priority = String(order.priority || "").toLowerCase();
  const statusBoost = order.status === "picking" ? 30 : 0;
  const urgentBoost = priority === "urgent" ? 80 : priority === "high" ? 45 : 0;
  const sla = slaMinutesLeft(order);
  const slaBoost = sla <= 0 ? 100 : sla <= 10 ? 70 : sla <= 20 ? 35 : 0;
  const sizeBoost = Math.min((order.items || []).length * 3, 18);
  const routeBoost = store.automationSettings.routeAssist ? Math.max(0, 20 - routeKey(order).length) : 0;
  return statusBoost + urgentBoost + slaBoost + sizeBoost + routeBoost;
}

function slaMinutesLeft(order) {
  const candidates = [
    order.sla_at,
    order.promised_at,
    order.expected_dispatch_at,
    order.expected_delivery_at,
    order.dispatch_deadline,
  ].filter(Boolean);
  const target = candidates.map((value) => new Date(value)).find((date) => !Number.isNaN(date.getTime()));
  if (target) return Math.round((target.getTime() - Date.now()) / 60000);
  const created = new Date(order.created_at || order.createdAt || order.order_date || order.updated_at || Date.now());
  const base = Number.isNaN(created.getTime()) ? Date.now() : created.getTime();
  const windowMinutes = String(order.priority || "").toLowerCase() === "urgent" ? 15 : 30;
  return Math.round((base + windowMinutes * 60000 - Date.now()) / 60000);
}

function routeKey(order) {
  const firstItem = (order.items || []).find(Boolean) || {};
  return String(firstItem.location_barcode || firstItem.location_name || firstItem.bin || firstItem.location || order.order_number || "");
}

function routeScore(orders) {
  if (!orders.length) return "--";
  const withBins = orders.filter((order) => routeKey(order)).length;
  return `${Math.round((withBins / orders.length) * 100)}%`;
}

function orderShortCode(order) {
  return String(order.order_number || order.website_order_id || order.id || "--").replace(/^ORDER-/i, "#");
}

function itemLabel(item) {
  return String(item.sku || item.product_sku || item.product_name || item.product_id || item.id || "SKU");
}

function renderReturnQueue() {
  const returns = store.returns.filter((item) => ["approved", "return_picking", "return_picked", "inspection"].includes(item.status));
  const target = $("#return-queue");
  if (!target) return;
  const listHidden = Boolean(store.activeReturnId);
  $("#return-lookup-form").classList.toggle("hidden", listHidden);
  $("#return-list-head").classList.toggle("hidden", listHidden);
  target.classList.toggle("hidden", listHidden);
  if (listHidden) {
    target.innerHTML = "";
    return;
  }
  if (!returns.length) {
    target.innerHTML = `<div class="empty-state">No approved returns right now.</div>`;
    return;
  }
  target.innerHTML = returns.map(returnCardHtml).join("");
  target.querySelectorAll("[data-start-return]").forEach((card) => {
    card.addEventListener("click", () => startReturn(Number(card.dataset.startReturn)));
  });
}

function returnCardHtml(returnOrder) {
  const totalQty = returnOrder.items.reduce((sum, item) => sum + item.expected_quantity, 0);
  const pickedQty = returnOrder.items.reduce((sum, item) => sum + item.picked_quantity, 0);
  const progress = totalQty ? Math.round((pickedQty / totalQty) * 100) : 0;
  return `
    <article class="order-card tappable" data-start-return="${returnOrder.id}">
      <div class="order-top">
        <div>
          <strong>${escapeHtml(returnOrder.return_number)}</strong>
          <span>${escapeHtml(returnOrder.website_order_id || returnOrder.customer_name)}</span>
        </div>
        <span class="badge">${escapeHtml(returnOrder.status)}</span>
      </div>
      <div class="progress-line"><span style="width:${progress}%"></span></div>
      <div class="order-meta">
        <span>${returnOrder.items.length} SKUs</span>
        <span>${pickedQty}/${totalQty} picked</span>
        <span>${escapeHtml(returnOrder.reason || "return")}</span>
      </div>
      <div class="order-cta">${returnOrder.status === "inspection" ? "Open PV" : "Tap to receive return"}</div>
    </article>
  `;
}

async function startReturnFromLookup(event) {
  event.preventDefault();
  const lookup = $("#return-order-lookup").value.trim().toLowerCase();
  if (!lookup) {
    toast("Return or order ID enter karein.");
    return;
  }
  const returnOrder = store.returns.find((item) =>
    String(item.id) === lookup ||
    String(item.return_number || "").toLowerCase() === lookup ||
    String(item.website_order_id || "").toLowerCase() === lookup ||
    String(item.order_id || "") === lookup
  );
  if (!returnOrder) {
    toast("Approved return nahi mila.");
    return;
  }
  startReturn(returnOrder.id);
}

function startReturn(returnId) {
  store.activeReturnId = returnId;
  activeReturnConfirmed = false;
  localStorage.setItem("warehouseActiveReturnId", String(returnId));
  const returnOrder = activeReturn();
  if (returnOrder?.status === "inspection") showScreen("pv-screen");
  else showScreen("return-screen", { forceHistory: true });
  renderReturnQueue();
  renderActiveReturn();
  renderReturnPv();
}

function activeReturn() {
  return store.returns.find((item) => item.id === store.activeReturnId) || null;
}

function closeActiveReturn() {
  store.activeReturnId = 0;
  activeReturnConfirmed = false;
  localStorage.removeItem("warehouseActiveReturnId");
  $("#return-code").value = "";
  showScreen("return-screen");
  renderReturnQueue();
  renderActiveReturn();
}

function returnIdentifierMatches(returnOrder, code) {
  const cleaned = String(code || "").trim().toLowerCase();
  if (!cleaned) return false;
  return [
    returnOrder.id,
    returnOrder.return_number,
    returnOrder.website_order_id,
    returnOrder.order_id,
  ].some((value) => String(value || "").trim().toLowerCase() === cleaned);
}

function renderActiveReturn() {
  const returnOrder = activeReturn();
  const card = $("#active-return-card");
  if (!card) return;
  if (!returnOrder) {
    card.innerHTML = `<div class="empty-state">Return/order ID type karein ya approved return select karein.</div>`;
    $("#return-items").innerHTML = "";
    $("#return-result").textContent = "Admin approve ke baad return list me dikhega.";
    $("#return-code").placeholder = "Return / website order ID";
    $("#initiate-pv").disabled = true;
    return;
  }
  const totalQty = returnOrder.items.reduce((sum, item) => sum + item.expected_quantity, 0);
  const pickedQty = returnOrder.items.reduce((sum, item) => sum + item.picked_quantity, 0);
  const currentItem = nextReturnPickItem(returnOrder);
  card.innerHTML = `
    <article class="order-card active">
      <div class="order-top">
        <div>
          <strong>${escapeHtml(returnOrder.return_number)}</strong>
          <span>${escapeHtml(returnOrder.customer_name)} / ${escapeHtml(returnOrder.website_order_id || "-")}</span>
        </div>
        <span class="badge">${pickedQty}/${totalQty}</span>
      </div>
    </article>
  `;
  if (!activeReturnConfirmed) {
    $("#return-code").placeholder = returnOrder.website_order_id || returnOrder.return_number;
    $("#return-items").innerHTML = `<div class="empty-state">Step 1: Return/order ID scan ya type karein.</div>`;
    $("#return-result").textContent = "Return ID confirm hone ke baad product scan open hoga.";
    $("#initiate-pv").disabled = true;
    return;
  }
  $("#return-code").placeholder = currentItem ? currentItem.product.sku : "PV ready";
  $("#return-items").innerHTML = currentItem
    ? returnItemHtml(currentItem)
    : `<div class="empty-state">Return pick complete. Ab Initiate PV karein.</div>`;
  $("#return-items").querySelectorAll("[data-return-pick]").forEach((button) => {
    button.addEventListener("click", () => updateReturnPickedQuantity(Number(button.dataset.returnPick), Number(button.dataset.quantity)));
  });
  $("#return-result").textContent = currentItem ? `${currentItem.product.sku} scan karein.` : "All items picked. PV start karein.";
  $("#initiate-pv").disabled = !returnOrder.items.every((item) => item.picked_quantity >= item.expected_quantity);
}

function nextReturnPickItem(returnOrder) {
  return returnOrder.items.find((item) => item.picked_quantity < item.expected_quantity) || null;
}

function returnItemHtml(item) {
  const done = item.picked_quantity >= item.expected_quantity;
  return `
    <article class="pick-item ${done ? "done" : ""}">
      <div>
        <strong>${escapeHtml(item.product.sku)}</strong>
        <span>${escapeHtml(item.product.name)}</span>
      </div>
      <div class="qty-control">
        <button type="button" data-return-pick="${item.id}" data-quantity="${Math.max(item.picked_quantity - 1, 0)}">-</button>
        <strong>${item.picked_quantity}/${item.expected_quantity}</strong>
        <button type="button" data-return-pick="${item.id}" data-quantity="${Math.min(item.picked_quantity + 1, item.expected_quantity)}" ${done ? "disabled" : ""}>+</button>
      </div>
    </article>
  `;
}

async function scanReturnCode(code) {
  const returnOrder = activeReturn();
  if (!returnOrder) {
    toast("Return select karein.");
    return;
  }
  if (!code) {
    toast(activeReturnConfirmed ? "Product SKU/barcode enter karein." : "Return/order ID enter karein.");
    return;
  }
  if (!activeReturnConfirmed) {
    if (!returnIdentifierMatches(returnOrder, code)) {
      $("#return-result").textContent = "Return/order ID match nahi hua.";
      toast("Sahi return/order ID scan karein.");
      return;
    }
    activeReturnConfirmed = true;
    $("#return-code").value = "";
    renderActiveReturn();
    toast("Return confirmed. Product scan karein.");
    return;
  }
  try {
    const data = await apiFetch(`/scan/${encodeURIComponent(code)}`);
    if (data.type !== "product") {
      $("#return-result").textContent = "Product SKU/barcode scan karein.";
      return;
    }
    const item = nextReturnPickItem(returnOrder);
    if (!item) {
      $("#return-result").textContent = "All return items picked. PV start karein.";
      toast("PV start karein.");
      return;
    }
    if (item.product.id !== data.product.id && item.product.sku !== data.product.sku) {
      $("#return-result").innerHTML = `<strong>${escapeHtml(data.product.sku)}</strong><br>Abhi ${escapeHtml(item.product.sku)} scan karna hai.`;
      toast("Next return item match nahi hua.");
      return;
    }
    const nextQuantity = Math.min(item.picked_quantity + 1, item.expected_quantity);
    await updateReturnPickedQuantity(item.id, nextQuantity);
    $("#return-code").value = "";
    $("#return-result").innerHTML = `<strong>${escapeHtml(data.product.sku)}</strong><br>Return picked ${nextQuantity}/${item.expected_quantity}`;
  } catch (error) {
    $("#return-result").textContent = error.message;
    toast(error.message);
  }
}

async function updateReturnPickedQuantity(itemId, quantity) {
  const returnOrder = activeReturn();
  if (!returnOrder) return;
  try {
    const data = await apiFetch(`/returns/${returnOrder.id}/items/${itemId}/pick`, { method: "POST", body: { quantity } });
    replaceReturn(data.return_order);
    renderReturnQueue();
    renderActiveReturn();
  } catch (error) {
    toast(error.message);
  }
}

async function initiateReturnPv() {
  const returnOrder = activeReturn();
  if (!returnOrder) return;
  try {
    const data = await apiFetch(`/returns/${returnOrder.id}/initiate-pv`, { method: "POST", body: {} });
    replaceReturn(data.return_order);
    renderReturnQueue();
    renderReturnPv();
    showScreen("pv-screen");
    toast("PV initiated.");
  } catch (error) {
    toast(error.message);
  }
}

function renderReturnPv() {
  const returnOrder = activeReturn();
  const target = $("#pv-items");
  if (!target) return;
  if (!returnOrder) {
    $("#pv-return-card").innerHTML = `<div class="empty-state">Return select karein.</div>`;
    target.innerHTML = "";
    return;
  }
  $("#pv-return-card").innerHTML = `
    <article class="order-card active">
      <div class="order-top">
        <div>
          <strong>${escapeHtml(returnOrder.return_number)}</strong>
          <span>${escapeHtml(returnOrder.status)} / issue items RC-DA-01 me jayenge</span>
        </div>
      </div>
    </article>
  `;
  target.innerHTML = returnOrder.items.map(returnPvItemHtml).join("");
  target.querySelectorAll("[data-return-stock-form]").forEach((form) => {
    form.addEventListener("submit", submitReturnStockIn);
  });
  target.querySelectorAll("[data-scan-fill]").forEach((button) => {
    button.addEventListener("click", () => beginScanFill(button.dataset.scanFill));
  });
}

function returnPvItemHtml(item) {
  const pending = item.remaining_stock_in_quantity;
  return `
    <form class="form-card return-pv-card" data-return-stock-form="${item.id}">
      <h2>${escapeHtml(item.product.sku)}</h2>
      <div class="result-card">${escapeHtml(item.product.name)}<br>Pending PV: ${pending}</div>
      <label>Product Condition
        <select name="condition">
          <option value="no_issue">No Issue</option>
          <option value="issue">Product Issue</option>
        </select>
      </label>
      <label>Normal Bin For No Issue
        <span class="scan-input"><input name="location" placeholder="LOC:A-2-4-08"><button type="button" data-scan-fill="[data-return-stock-form='${item.id}'] [name='location']">Scan</button></span>
      </label>
      <label>Quantity
        <input name="quantity" type="number" min="1" max="${pending}" value="${pending || 1}" required>
      </label>
      <button class="primary" type="submit" ${pending <= 0 ? "disabled" : ""}>Stock In Return</button>
    </form>
  `;
}

async function submitReturnStockIn(event) {
  event.preventDefault();
  const form = event.target;
  const returnOrder = activeReturn();
  if (!returnOrder) return;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.quantity = Number(payload.quantity);
  try {
    const data = await apiFetch(`/returns/${returnOrder.id}/items/${form.dataset.returnStockForm}/stock-in`, { method: "POST", body: payload });
    replaceReturn(data.return_order);
    renderReturnQueue();
    renderActiveReturn();
    renderReturnPv();
    toast("Return stock in saved.");
  } catch (error) {
    toast(error.message);
  }
}

function orderCardHtml(order) {
  const items = order.items || [];
  const totalQty = items.reduce((sum, item) => sum + item.quantity, 0);
  const pickedQty = items.reduce((sum, item) => sum + item.picked_quantity, 0);
  const progress = totalQty ? Math.round((pickedQty / totalQty) * 100) : 0;
  const sla = slaMinutesLeft(order);
  return `
    <article class="order-card tappable" data-start-order="${order.id}">
      <div class="order-top">
        <div>
          <strong>${escapeHtml(order.order_number)}</strong>
          <span>${escapeHtml(order.customer_name)} · ${escapeHtml(routeKey(order) || "bin pending")}</span>
        </div>
        <span class="badge ${order.priority === "urgent" ? "warn" : ""}">${escapeHtml(order.priority)}</span>
      </div>
      <div class="progress-line"><span style="width:${progress}%"></span></div>
      <div class="order-meta">
        <span>${items.length} SKUs</span>
        <span>${pickedQty}/${totalQty} picked</span>
        <span>${sla <= 0 ? "SLA due" : `${sla} min left`}</span>
      </div>
      <div class="order-cta">${order.status === "pending" ? "Tap to start picking" : "Tap to continue"}</div>
    </article>
  `;
}

async function startOrder(orderId) {
  store.activeOrderId = orderId;
  localStorage.setItem("warehouseActiveOrderId", String(orderId));
  resetActivePickBin();
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
    $("#pick-bin-card").innerHTML = `Scan bin barcode first.`;
    $("#pick-items").innerHTML = "";
    $("#scan-result").textContent = "Select an order first.";
    $("#pick-manual-label").textContent = "Manual Bin / Product Barcode";
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

  renderPickBinCard(order);
  const itemsForBin = pickItemsForActiveBin(order);
  if (!store.activePickLocation) {
    $("#pick-manual-label").textContent = "Manual Bin Barcode";
    $("#manual-code").placeholder = "LOC:A-2-4-08";
    $("#scan-result").textContent = "Scan bin first. Product scan will open after bin is selected.";
    $("#pick-items").innerHTML = `<div class="empty-state">Bin scan ke baad product list dikhegi.</div>`;
  } else {
    $("#pick-manual-label").textContent = "Manual SKU Number / Barcode";
    $("#manual-code").placeholder = "1001 or barcode";
    $("#scan-result").textContent = "Scan product barcode from this bin.";
    $("#pick-items").innerHTML = itemsForBin.length
      ? itemsForBin.map((item) => pickItemHtml(item, binInventoryForProduct(item.product.id))).join("")
      : `<div class="empty-state">Is bin me active order ka item nahi mila. Dusra bin scan karein.</div>`;
  }
  $("#pick-items").querySelectorAll("[data-pick-item]").forEach((button) => {
    button.addEventListener("click", () => updatePickedQuantity(Number(button.dataset.pickItem), Number(button.dataset.quantity)));
  });
  $("#pick-bin-card").querySelector("[data-change-bin]")?.addEventListener("click", () => {
    resetActivePickBin();
    renderActiveOrder();
    toast("Scan another bin.");
  });
  $("#mark-packed").disabled = !order.items.every((item) => item.picked_quantity >= item.quantity);
}

function renderPickBinCard(order) {
  if (!store.activePickLocation) {
    const binHints = order.items
      .flatMap((item) => item.product.locations || [])
      .filter((row) => Number(row.available_quantity || 0) > 0)
      .slice(0, 4);
    $("#pick-bin-card").innerHTML = `
      <strong>Step 1: Scan bin</strong><br>
      <span>Order item pick karne se pehle bin barcode scan karein.</span>
      ${
        binHints.length
          ? `<div class="bin-hints">${binHints.map((row) => `<code>${escapeHtml(row.location.barcode || row.location.id)}</code>`).join("")}</div>`
          : ""
      }
    `;
    return;
  }

  const matchingItems = pickItemsForActiveBin(order);
  $("#pick-bin-card").innerHTML = `
    <div class="bin-card-top">
      <div>
        <strong>${escapeHtml(store.activePickLocation.full_code)}</strong>
        <span><code>${escapeHtml(store.activePickLocation.barcode || store.activePickLocation.id)}</code> / ${matchingItems.length} order item(s)</span>
      </div>
      <button type="button" data-change-bin>Change Bin</button>
    </div>
  `;
}

function pickItemsForActiveBin(order) {
  if (!store.activePickLocation) return [];
  return order.items.filter((item) => {
    const inventory = binInventoryForProduct(item.product.id);
    return item.picked_quantity > 0 || (inventory && Number(inventory.available_quantity || 0) > 0);
  });
}

function binInventoryForProduct(productId) {
  return store.activePickInventory.find((item) => item.product.id === productId);
}

function pickItemHtml(item, inventory = null) {
  const done = item.picked_quantity >= item.quantity;
  const binAvailable = Number(inventory?.available_quantity || 0);
  return `
    <article class="pick-item ${done ? "done" : ""}" data-product-sku="${escapeHtml(item.product.sku)}" data-item-id="${item.id}">
      <div>
        <strong>${escapeHtml(item.product.sku)}</strong>
        <span>${escapeHtml(item.product.name)}</span>
        ${inventory ? `<span>Bin available: ${binAvailable}</span>` : ""}
      </div>
      <div class="qty-control">
        <button type="button" data-pick-item="${item.id}" data-quantity="${Math.max(item.picked_quantity - 1, 0)}">-</button>
        <strong>${item.picked_quantity}/${item.quantity}</strong>
        <button type="button" data-pick-item="${item.id}" data-quantity="${Math.min(item.picked_quantity + 1, item.quantity)}" ${done || binAvailable <= 0 ? "disabled" : ""}>+</button>
      </div>
    </article>
  `;
}

async function updatePickedQuantity(itemId, quantity) {
  const order = activeOrder();
  if (!order) return;
  const item = order.items.find((orderItem) => orderItem.id === itemId);
  if (!item) return;
  const increasing = quantity > item.picked_quantity;
  if (increasing && !store.activePickLocation) {
    toast("Product pick karne se pehle bin scan karein.");
    return;
  }
  try {
    const body = { quantity };
    if (store.activePickLocation) body.location = store.activePickLocation.barcode || store.activePickLocation.id;
    const data = await apiFetch(`/orders/${order.id}/items/${itemId}/pick`, { method: "POST", body });
    replaceOrder(data.order);
    if (store.activePickLocation) await loadActivePickInventory(store.activePickLocation.barcode || store.activePickLocation.id);
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
  const orders = store.orders.filter((order) => order.status === "packed");
  const target = $("#dispatch-list");
  const handoffReady = handoffChecklistReady();
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
            <span>${escapeHtml(order.customer_name)} - ${escapeHtml(order.awb || order.tracking_number || "AWB pending")}</span>
          </div>
          <span class="badge">${escapeHtml(order.status)}</span>
        </div>
        <div class="order-meta">
          <span>${escapeHtml(order.pincode || "PIN NA")}</span>
          <span>${escapeHtml(order.payment_method || order.payment_status || "payment")}</span>
          <span>${handoffReady ? "Checklist ok" : "Checklist pending"}</span>
        </div>
        <div class="order-actions">
          <button class="primary" type="button" data-manual-dispatch="${order.id}" ${handoffReady ? "" : "disabled"}>Dispatch</button>
        </div>
      </article>
    `)
    .join("");

  target.querySelectorAll("[data-manual-dispatch]").forEach((button) => {
    button.addEventListener("click", () => dispatchOrderManually(button.dataset.manualDispatch));
  });
}

function handoffChecklistReady() {
  return ["#handoff-bag-check", "#handoff-label-check", "#handoff-payment-check"].every((selector) => $(selector)?.checked);
}

function numberInput(value) {
  const number = Number(value || 0);
  return number > 0 ? String(number) : "";
}

async function dispatchOrderManually(orderId) {
  try {
    const data = await apiFetch(`/orders/${orderId}/dispatch`, { method: "POST", body: { manual_dispatch: true } });
    replaceOrder(data.order);
    toast("Order dispatched. Pickup location dashboard se add karein.");
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

function cancelScanOrBackToOrders() {
  if (scanFillTarget && scanReturnScreen) {
    const returnScreen = scanReturnScreen;
    clearScanFillTarget();
    showScreen(returnScreen);
    toast("Scan cancelled.");
    return;
  }
  showScreen("orders-screen");
}

async function scanCode(code) {
  if (!code) {
    toast("Code enter karein.");
    return;
  }
  try {
    const data = await apiFetch(`/scan/${encodeURIComponent(code)}`);
    if (scanFillTarget) {
      const targetNeedsLocation = scanFillTarget.includes("location");
      const targetNeedsProduct = scanFillTarget.includes("product");
      if (targetNeedsLocation && data.type !== "location") {
        reportScanFillError("Location/bin barcode scan karein.");
        return;
      }
      if (targetNeedsProduct && data.type !== "product") {
        reportScanFillError("Product SKU/barcode scan karein.");
        return;
      }
      fillScanTarget(data.type === "location" ? data.location.barcode || data.location.id : data.product.sku);
      return;
    }
    if ($(".screen.active")?.id === "pick-screen" && activeOrder() && !store.activePickLocation) {
      if (data.type !== "location") {
        $("#scan-result").textContent = "Pehle bin barcode scan karein.";
        toast("First scan bin.");
        return;
      }
      await activatePickBin(data.location.barcode || data.location.id);
      return;
    }
    if (data.type === "product") {
      await matchPickedProduct(data.product);
    } else if (data.type === "location") {
      if ($(".screen.active")?.id === "pick-screen" && activeOrder()) {
        await activatePickBin(data.location.barcode || data.location.id);
      } else {
        $("#scan-result").innerHTML = `<strong>${escapeHtml(data.location.full_code)}</strong><br><code>${escapeHtml(data.location.barcode)}</code>`;
      }
    }
  } catch (error) {
    if (scanFillTarget) {
      reportScanFillError(error.message);
      return;
    }
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
  if (!store.activePickLocation) {
    $("#scan-result").textContent = "Scan bin first, then scan product.";
    toast("First scan bin.");
    return;
  }
  const item = order.items.find((orderItem) => orderItem.product.id === product.id || orderItem.product.sku === product.sku);
  if (!item) {
    $("#scan-result").innerHTML = `<strong>${escapeHtml(product.sku)}</strong><br>Not in active order.`;
    toast("Item not in this order.");
    return;
  }
  const inventory = binInventoryForProduct(product.id);
  if (!inventory || Number(inventory.available_quantity || 0) <= 0) {
    $("#scan-result").innerHTML = `<strong>${escapeHtml(product.sku)}</strong><br>Not available in scanned bin.`;
    toast("Item scanned bin me available nahi hai.");
    return;
  }
  const nextQuantity = Math.min(item.picked_quantity + 1, item.quantity);
  await updatePickedQuantity(item.id, nextQuantity);
  $("#scan-result").innerHTML = `<strong>${escapeHtml(product.sku)}</strong><br>Picked ${nextQuantity}/${item.quantity} from scanned bin`;
}

async function activatePickBin(identifier) {
  try {
    await loadActivePickInventory(identifier);
    $("#manual-code").value = "";
    $("#scan-result").textContent = "Bin selected. Now scan product barcode.";
    renderActiveOrder();
    toast("Bin selected. Product scan karein.");
  } catch (error) {
    resetActivePickBin();
    $("#scan-result").textContent = error.message;
    toast(error.message);
  }
}

async function loadActivePickInventory(identifier) {
  const data = await apiFetch(`/location-inventory/${encodeURIComponent(identifier)}`);
  store.activePickLocation = data.location;
  store.activePickInventory = data.items || [];
  return data;
}

function resetActivePickBin() {
  store.activePickLocation = null;
  store.activePickInventory = [];
  localStorage.removeItem("warehouseActivePickLocation");
}

function fillScanTarget(value) {
  const target = scanFillTarget;
  const returnScreen = scanReturnScreen;
  const input = $(target);
  if (input) {
    input.value = value;
    input.focus();
  }
  clearScanFillTarget();
  if (returnScreen) showScreen(returnScreen);
  if (target === '#stock-in-form [name=\'product\']') {
    loadStockProductPreview(value);
  }
  if (target === '#inventory-lookup-form [name=\'location\']') {
    loadInventoryView(value);
  }
  if (target === '#location-form [name=\'from_location\']') {
    loadMoveBinInventory(value);
  }
  toast("Field filled.");
}

function reportScanFillError(message) {
  const target = scanFillTarget;
  const returnScreen = scanReturnScreen;
  clearScanFillTarget();
  if (returnScreen) showScreen(returnScreen);
  if (target === '#inventory-lookup-form [name=\'location\']') {
    $("#inventory-bin-card").textContent = message;
  } else if (target === '#location-form [name=\'from_location\']') {
    $("#move-bin-preview").textContent = message;
    $("#move-bin-items").innerHTML = "";
    resetMoveSelection();
  } else {
    $("#scan-result").textContent = message;
  }
  toast(message);
}

function clearScanFillTarget() {
  scanFillTarget = null;
  scanReturnScreen = null;
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

function scheduleStockProductPreview() {
  window.clearTimeout(stockPreviewTimer);
  stockPreviewTimer = window.setTimeout(() => {
    loadStockProductPreview($('#stock-in-form [name="product"]').value.trim());
  }, 350);
}

async function loadStockProductPreview(code) {
  if (!code) {
    resetStockProductPreview();
    return;
  }
  try {
    const data = await apiFetch(`/scan/${encodeURIComponent(code)}`);
    if (data.type !== "product") {
      resetStockProductPreview("Scan a product SKU number or barcode first.");
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

function resetStockProductPreview(message = "Scan SKU number to load product.") {
  const preview = $("#stock-product-preview");
  preview.classList.toggle("hidden", !message);
  preview.classList.add("product-preview--message");
  preview.textContent = message;
  $("#stock-details").classList.add("hidden");
  $('#stock-in-form [name="location"]').disabled = true;
  $('#stock-in-form [name="quantity"]').disabled = true;
}

async function loadInventoryView(identifier) {
  if (!identifier) {
    $("#inventory-bin-card").textContent = "Scan bin to see what items are inside.";
    $("#inventory-items").innerHTML = "";
    return;
  }
  try {
    const data = await apiFetch(`/location-inventory/${encodeURIComponent(identifier)}`);
    store.inventoryView = data;
    $("#inventory-bin-card").innerHTML = `
      <strong>${escapeHtml(data.location.full_code)}</strong><br>
      <code>${escapeHtml(data.location.barcode || data.location.id)}</code> / ${data.items.length} item(s)
    `;
    $("#inventory-items").innerHTML = inventoryItemsHtml(data.items, "inventory");
  } catch (error) {
    $("#inventory-bin-card").textContent = error.message;
    $("#inventory-items").innerHTML = "";
    toast(error.message);
  }
}

async function loadMoveBinInventory(identifier) {
  if (!identifier) {
    store.moveInventory = [];
    $("#move-bin-preview").textContent = "Scan from bin to show available items.";
    $("#move-bin-items").innerHTML = "";
    resetMoveSelection();
    return;
  }
  try {
    const data = await apiFetch(`/location-inventory/${encodeURIComponent(identifier)}`);
    store.moveInventory = data.items || [];
    $("#move-bin-preview").classList.remove("hidden");
    $("#move-bin-preview").innerHTML = `
      <div class="product-preview-info">
        <strong>${escapeHtml(data.location.full_code)}</strong>
        <span><code>${escapeHtml(data.location.barcode || data.location.id)}</code> / ${store.moveInventory.length} item(s)</span>
      </div>
    `;
    $("#move-bin-items").innerHTML = inventoryItemsHtml(store.moveInventory, "move");
    $("#move-bin-items").querySelectorAll("[data-select-move-product]").forEach((button) => {
      button.addEventListener("click", () => selectMoveItem(button.dataset.selectMoveProduct));
    });
    resetMoveSelection();
  } catch (error) {
    store.moveInventory = [];
    $("#move-bin-preview").textContent = error.message;
    $("#move-bin-items").innerHTML = "";
    resetMoveSelection();
    toast(error.message);
  }
}

function inventoryItemsHtml(items, mode) {
  if (!items.length) {
    return `<div class="empty-state">Is bin me available item nahi hai.</div>`;
  }
  return items
    .map((item) => {
      const product = item.product;
      const imageSrc = productImageSrc(product);
      const action = mode === "move" ? `<button type="button" data-select-move-product="${escapeHtml(product.sku)}">Select</button>` : "";
      return `
        <article class="inventory-item">
          <div class="product-preview-thumb ${imageSrc ? "" : "empty"}">
            ${imageSrc ? `<img src="${escapeHtml(imageSrc)}" alt="${escapeHtml(product.name)}">` : "<span>No image</span>"}
          </div>
          <div class="inventory-item-info">
            <strong>${escapeHtml(product.sku)} / ${escapeHtml(product.name)}</strong>
            <span>Available: ${item.available_quantity} / Total: ${item.quantity}</span>
            <span>${escapeHtml(product.unit || "pcs")}</span>
          </div>
          ${action}
        </article>
      `;
    })
    .join("");
}

function selectMoveItem(sku) {
  const item = store.moveInventory.find((row) => row.product.sku === sku);
  if (!item) return;
  const form = $("#location-form");
  form.elements.product.value = item.product.sku;
  form.elements.quantity.value = 1;
  form.elements.quantity.max = item.available_quantity;
  form.elements.quantity.disabled = false;
  form.elements.to_location.disabled = false;
  $("#move-details").classList.remove("hidden");
  $("#move-selected-item").innerHTML = `
    <strong>${escapeHtml(item.product.sku)} / ${escapeHtml(item.product.name)}</strong><br>
    Available to move: ${item.available_quantity}
  `;
  toast("Item selected. To bin scan karein.");
}

function resetMoveSelection() {
  const form = $("#location-form");
  if (!form) return;
  form.elements.product.value = "";
  form.elements.to_location.value = "";
  form.elements.quantity.value = "";
  form.elements.quantity.removeAttribute("max");
  form.elements.to_location.disabled = true;
  form.elements.quantity.disabled = true;
  $("#move-details").classList.add("hidden");
  $("#move-selected-item").textContent = "Select an item from the scanned bin.";
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
  if (!payload.product) {
    toast("From bin se item select karein.");
    return;
  }

  try {
    await apiFetch("/location-update", { method: "POST", body: payload });
    const fromLocation = payload.from_location;
    form.reset();
    form.elements.from_location.value = fromLocation;
    store.moveInventory = [];
    $("#move-bin-items").innerHTML = "";
    resetMoveSelection();
    if (fromLocation) await loadMoveBinInventory(fromLocation);
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

function replaceReturn(returnOrder) {
  const index = store.returns.findIndex((existing) => existing.id === returnOrder.id);
  if (index >= 0) store.returns.splice(index, 1, returnOrder);
  else store.returns.push(returnOrder);
}

async function apiFetch(path, options = {}) {
  if (!store.apiBase) throw new Error("API URL not set. Open API Settings.");
  const isFormData = options.body instanceof FormData;
  const init = {
    method: options.method || "GET",
    credentials: "include",
    headers: {},
  };
  if (!isFormData) init.headers["Content-Type"] = "application/json";
  if (store.token && options.auth !== false) init.headers.Authorization = `Bearer ${store.token}`;
  if (store.warehouseId && options.auth !== false) init.headers["X-Warehouse-Id"] = String(store.warehouseId);
  if (options.body) init.body = isFormData ? options.body : JSON.stringify(options.body);

  let response;
  try {
    response = await fetch(`${store.apiBase}${path}`, init);
  } catch {
    if (init.method !== "GET" && options.auth !== false) queueOfflineMutation(path, options);
    throw new Error(`API connection failed. Check API URL: ${store.apiBase}`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    if (response.status === 401 && options.auth !== false) logout(false);
    throw new Error(data.message || `API error ${response.status}`);
  }
  return data;
}

function queueOfflineMutation(path, options) {
  store.offlineQueue.push({
    path,
    method: options.method || "GET",
    body: options.body || null,
    queued_at: new Date().toISOString(),
  });
  store.offlineQueue = store.offlineQueue.slice(-25);
  localStorage.setItem("warehouseOfflineQueue", JSON.stringify(store.offlineQueue));
  renderOpsAutomation();
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

async function autoConnectApi() {
  const candidates = apiBaseCandidates();
  if (!candidates.length) return;
  setApiStatus("Connecting to warehouse...", false);
  for (const candidate of candidates) {
    try {
      await testApiBase(candidate);
      store.apiBase = candidate;
      $("#api-base").value = candidate;
      localStorage.setItem("warehouseMobileApi", candidate);
      setApiStatus("API connected automatically.", true);
      return;
    } catch {
      // Try the next candidate.
    }
  }
  setApiStatus("API not connected. Paste backend /api URL and press Test API.", false);
}

function apiBaseCandidates() {
  const queryApi = new URLSearchParams(location.search).get("api");
  const candidates = [
    queryApi,
    configuredApiBase,
    ...configuredApiCandidates,
    savedApiBase,
    ...inferredApiBases(),
    "http://127.0.0.1:5000/api",
  ];
  return Array.from(new Set(candidates.map(normalizeApiBase).filter(Boolean)));
}

function inferredApiBases() {
  if (!location.hostname || ["localhost", "127.0.0.1"].includes(location.hostname)) return [];

  const bases = [`${location.origin}/api`];
  const replacements = [
    ["mobile", "backend"],
    ["picker", "backend"],
    ["staff", "backend"],
  ];
  for (const [from, to] of replacements) {
    if (location.hostname.includes(from)) {
      bases.push(`${location.protocol}//${location.hostname.replace(from, to)}${location.port ? `:${location.port}` : ""}/api`);
    }
  }
  return bases;
}

async function testApiBase(apiBase) {
  if (!apiBase) throw new Error("API URL not set");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(`${apiBase}/health`, {
      cache: "no-store",
      credentials: "omit",
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok !== true) throw new Error(`API health failed (${response.status})`);
    return data;
  } finally {
    window.clearTimeout(timeout);
  }
}

function normalizeApiBase(value) {
  const cleaned = String(value || "").trim().replace(/\/+$/, "");
  if (!cleaned) return "";
  try {
    const url = new URL(cleaned);
    if (!url.pathname || url.pathname === "/") return `${url.origin}/api`;
  } catch {
    return cleaned;
  }
  return cleaned;
}

function clearSavedApi() {
  localStorage.removeItem("warehouseMobileApi");
  store.apiBase = configuredApiBase || "";
  $("#api-base").value = store.apiBase;
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
