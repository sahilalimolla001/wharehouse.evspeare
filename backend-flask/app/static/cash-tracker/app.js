const CASH_KEY = "simpleCash.total.v1";
const SETTLED_KEY = "simpleCash.lastSettled.v1";
const SHEET_KEY = "simpleCash.sheetUrl.v1";
const SHEET_COLUMNS_KEY = "simpleCash.sheetColumns.v1";
const SHEET_BASELINE_KEY = "simpleCash.sheetBaseline.v1";
const LAST_SHEET_TOTAL_KEY = "simpleCash.lastSheetTotal.v1";
const PENDING_SETTLEMENT_EXPORTS_KEY = "simpleCash.pendingSettlementExports.v1";
const AUTO_IMPORT_DELAY_MS = 700;
const AUTO_IMPORT_INTERVAL_MS = 60000;
const SHEET_CONFIG = window.CASH_TRACKER_CONFIG || {};
const BACKEND_SUMMARY_URL = String(SHEET_CONFIG.summaryUrl || "").trim();
const BACKEND_SETTLEMENT_URL = String(SHEET_CONFIG.settlementUrl || "").trim();

const els = {
  totalCash: document.querySelector("#totalCash"),
  settleCash: document.querySelector("#settleCash"),
  settleDialog: document.querySelector("#settleDialog"),
  settleDialogAmount: document.querySelector("#settleDialogAmount"),
  settleBank: document.querySelector("#settleBank"),
  noteCounts: document.querySelectorAll(".note-count"),
  otherCash: document.querySelector("#otherCash"),
  settleNowAmount: document.querySelector("#settleNowAmount"),
  remainingDueAmount: document.querySelector("#remainingDueAmount"),
  settleAmountCheck: document.querySelector("#settleAmountCheck"),
  settleWarning: document.querySelector("#settleWarning"),
  cancelSettle: document.querySelector("#cancelSettle"),
  confirmSettle: document.querySelector("#confirmSettle"),
  finalSettleDialog: document.querySelector("#finalSettleDialog"),
  finalBankName: document.querySelector("#finalBankName"),
  finalSettleAmount: document.querySelector("#finalSettleAmount"),
  finalDueAmount: document.querySelector("#finalDueAmount"),
  backToSettle: document.querySelector("#backToSettle"),
  finalConfirmSettle: document.querySelector("#finalConfirmSettle"),
  receiptPanel: document.querySelector("#receiptPanel"),
  receiptDate: document.querySelector("#receiptDate"),
  receiptBank: document.querySelector("#receiptBank"),
  receiptSettled: document.querySelector("#receiptSettled"),
  receiptDue: document.querySelector("#receiptDue"),
  receiptNotes: document.querySelector("#receiptNotes"),
  downloadReceipt: document.querySelector("#downloadReceipt"),
  statusText: document.querySelector("#statusText"),
};

let totalCash = BACKEND_SUMMARY_URL ? 0 : Number(localStorage.getItem(CASH_KEY) || 0);
let isImportingSheet = false;
let pendingSettlement = null;

function formatCurrency(value) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: value % 1 ? 2 : 0,
  }).format(value || 0);
}

function saveTotal() {
  if (BACKEND_SUMMARY_URL) return;
  localStorage.setItem(CASH_KEY, String(totalCash));
}

function render() {
  els.totalCash.textContent = formatCurrency(totalCash);
}

function showStatus(message) {
  els.statusText.textContent = message;
  els.statusText.hidden = false;
}

async function syncBackendCash(options = {}) {
  if (!BACKEND_SUMMARY_URL) return false;
  const { automatic = false } = options;
  try {
    const response = await fetch(BACKEND_SUMMARY_URL, {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    totalCash = roundMoney(data.availableCash || 0);
    render();
    showStatus(
      `${formatCurrency(data.collectedCash || 0)} COD cash collected, ${formatCurrency(data.settledCash || 0)} settled.`
    );
    return true;
  } catch {
    if (!automatic) showStatus("Unable to load warehouse COD cash. Please refresh after login.");
    return false;
  }
}

async function saveBackendSettlement(settlement) {
  if (!BACKEND_SETTLEMENT_URL) return false;
  const response = await fetch(BACKEND_SETTLEMENT_URL, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      amount: settlement.amount,
      bank: settlement.bank,
      remainingDue: settlement.due,
      breakdown: settlement.breakdown,
      receiptId: settlement.id,
      date: settlement.date,
    }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.message || "Settlement failed");
  }
  return true;
}

function readJson(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}

function getSheetBaseline(urlValue, columnSpec) {
  const baseline = readJson(SHEET_BASELINE_KEY);
  return baseline?.url === urlValue && baseline?.columns === columnSpec ? Number(baseline.total || 0) : 0;
}

function setSheetBaseline(urlValue, columnSpec, total) {
  localStorage.setItem(SHEET_BASELINE_KEY, JSON.stringify({ url: urlValue, columns: columnSpec, total }));
}

function saveLastSheetTotal(urlValue, columnSpec, total) {
  localStorage.setItem(LAST_SHEET_TOTAL_KEY, JSON.stringify({ url: urlValue, columns: columnSpec, total }));
}

function getSettlementWebhookUrl() {
  return String(SHEET_CONFIG.settlementWebhookUrl || "").trim();
}

function getPendingSettlementExports() {
  const pending = readJson(PENDING_SETTLEMENT_EXPORTS_KEY);
  return Array.isArray(pending) ? pending : [];
}

function savePendingSettlementExports(exports) {
  localStorage.setItem(PENDING_SETTLEMENT_EXPORTS_KEY, JSON.stringify(exports));
}

function queueSettlementExport(settlement) {
  savePendingSettlementExports([...getPendingSettlementExports(), settlement]);
}

function settlementExportPayload(settlement) {
  return {
    receiptId: settlement.id,
    date: settlement.date,
    bank: settlement.bank,
    settledAmount: settlement.amount,
    remainingDue: settlement.due,
    noteBreakdown: settlement.breakdown,
    notesText: settlement.breakdown.map((row) => `${row.label} x ${row.count} = ${row.amount}`).join(", "),
  };
}

async function exportSettlementToSheet(settlement) {
  const webhookUrl = getSettlementWebhookUrl();
  if (!webhookUrl) {
    queueSettlementExport(settlement);
    return false;
  }

  await fetch(webhookUrl, {
    method: "POST",
    mode: "no-cors",
    headers: { "Content-Type": "text/plain;charset=utf-8" },
    body: JSON.stringify(settlementExportPayload(settlement)),
  });
  return true;
}

async function retryPendingSettlementExports() {
  const pending = getPendingSettlementExports();
  if (!pending.length || !getSettlementWebhookUrl()) return;

  const failed = [];
  for (const settlement of pending) {
    try {
      await exportSettlementToSheet(settlement);
    } catch {
      failed.push(settlement);
    }
  }
  savePendingSettlementExports(failed);
}

function clampAmount(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function roundMoney(value) {
  return Math.round(Number(value || 0) * 100) / 100;
}

function getConfiguredSheetUrl() {
  return String(SHEET_CONFIG.sheetUrl || localStorage.getItem(SHEET_KEY) || "").trim();
}

function getConfiguredColumns() {
  return String(SHEET_CONFIG.importColumns || localStorage.getItem(SHEET_COLUMNS_KEY) || "").trim();
}

function parseSheetLink(value) {
  try {
    const url = new URL(value);
    if (!url.hostname.includes("docs.google.com")) {
      return value.toLowerCase().endsWith(".csv") ? { kind: "csv", url: value } : null;
    }

    const idMatch = url.pathname.match(/\/spreadsheets\/d\/([^/]+)/);
    if (!idMatch) return null;

    const gidFromQuery = url.searchParams.get("gid");
    const gidFromHash = new URLSearchParams(url.hash.replace(/^#/, "")).get("gid");
    return {
      kind: "google",
      id: idMatch[1],
      gid: gidFromQuery || gidFromHash || "0",
    };
  } catch {
    return null;
  }
}

async function loadCsvRows(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return parseCsv(await response.text());
}

function loadGoogleSheetRows({ id, gid }) {
  return new Promise((resolve, reject) => {
    const callbackName = `cashSheet_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const script = document.createElement("script");
    const timeoutId = window.setTimeout(() => {
      cleanup();
      reject(new Error("Sheet request timed out"));
    }, 15000);

    function cleanup() {
      window.clearTimeout(timeoutId);
      delete window[callbackName];
      script.remove();
    }

    window[callbackName] = (response) => {
      cleanup();
      if (!response || response.status !== "ok") {
        reject(new Error("Sheet is not public"));
        return;
      }
      resolve(googleTableToRows(response.table));
    };

    const params = new URLSearchParams({
      gid,
      headers: "1",
      cacheBust: String(Date.now()),
      tqx: `responseHandler:${callbackName}`,
    });
    script.src = `https://docs.google.com/spreadsheets/d/${encodeURIComponent(id)}/gviz/tq?${params}`;
    script.onerror = () => {
      cleanup();
      reject(new Error("Sheet script failed"));
    };
    document.head.appendChild(script);
  });
}

function googleTableToRows(table) {
  const headers = table.cols.map((col, index) => String(col.label || col.id || `column_${index + 1}`).trim());
  const rows = table.rows.map((row) =>
    table.cols.map((_, index) => {
      const cell = row.c[index];
      return String(cell?.f ?? cell?.v ?? "").trim();
    })
  );
  return [headers, ...rows];
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (char === '"' && quoted && next === '"') {
      cell += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      quoted = !quoted;
      continue;
    }

    if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
      continue;
    }

    cell += char;
  }

  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function normalizeHeader(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function splitColumnSpec(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function columnLetterToIndex(value) {
  const clean = String(value || "").trim().toUpperCase();
  if (!/^[A-Z]+$/.test(clean)) return -1;

  return clean.split("").reduce((index, char) => index * 26 + char.charCodeAt(0) - 64, 0) - 1;
}

function resolveSelectedColumnIndexes(headers, columnSpec) {
  const specs = splitColumnSpec(columnSpec);
  const normalizedHeaders = headers.map(normalizeHeader);
  const indexes = specs
    .map((spec) => {
      const letterIndex = columnLetterToIndex(spec);
      if (letterIndex >= 0 && letterIndex < headers.length) return letterIndex;

      const headerIndex = normalizedHeaders.indexOf(normalizeHeader(spec));
      return headerIndex >= 0 ? headerIndex : -1;
    })
    .filter((index) => index >= 0);

  return [...new Set(indexes)];
}

function indexToColumnLetter(index) {
  let value = index + 1;
  let label = "";
  while (value > 0) {
    value -= 1;
    label = String.fromCharCode(65 + (value % 26)) + label;
    value = Math.floor(value / 26);
  }
  return label;
}

function parseAmount(value) {
  const clean = String(value || "").replace(/[^\d.-]/g, "");
  if (!clean) return NaN;
  return Number(clean);
}

function firstValue(record, keys) {
  for (const key of keys) {
    if (record[key] !== undefined && String(record[key]).trim() !== "") return record[key];
  }
  return "";
}

function hasNonCashMode(record) {
  const mode = String(firstValue(record, ["payment", "mode", "payment_mode", "method", "payment_method"])).toLowerCase();
  return mode && !mode.includes("cash");
}

function signedCashAmount(record, selectedCells) {
  if (hasNonCashMode(record)) return NaN;

  const amount = selectedCells.reduce((sum, value) => {
    const parsed = parseAmount(value);
    return Number.isFinite(parsed) ? sum + parsed : sum;
  }, 0);

  if (!Number.isFinite(amount) || amount === 0) return NaN;

  const type = String(firstValue(record, ["type", "transaction_type", "kind", "status"])).toLowerCase();
  const isCashOut = ["expense", "debit", "withdraw", "payment", "paid", "out"].some((word) => type.includes(word));

  if (amount > 0 && isCashOut) return -amount;
  return amount;
}

function calculateCashTotal(rows, columnSpec) {
  if (!rows.length) return { total: 0, count: 0, matchedColumns: [] };

  const headerRow = rows.shift();
  const headers = headerRow.map(normalizeHeader);
  const selectedIndexes = resolveSelectedColumnIndexes(headerRow, columnSpec);
  const matchedColumns = selectedIndexes.map((index) => {
    const letter = indexToColumnLetter(index);
    const label = headerRow[index] ? ` - ${headerRow[index]}` : "";
    return `${letter}${label}`;
  });
  if (!selectedIndexes.length) return { total: 0, count: 0, matchedColumns };

  let count = 0;
  const total = rows.reduce((sum, cells) => {
    const record = Object.fromEntries(headers.map((header, index) => [header, cells[index] || ""]));
    const selectedCells = selectedIndexes.map((index) => cells[index] || "");
    const amount = signedCashAmount(record, selectedCells);
    if (!Number.isFinite(amount)) return sum;
    count += 1;
    return sum + amount;
  }, 0);

  return { total: Math.max(0, total), count, matchedColumns };
}

async function importSheetCash(urlValue, options = {}) {
  const { automatic = false } = options;
  const columnSpec = getConfiguredColumns();
  const sheetInfo = parseSheetLink(urlValue);
  if (!sheetInfo) {
    showStatus("Save the sheet link in config.js.");
    return false;
  }
  if (!columnSpec) {
    showStatus("Save the import columns in config.js, for example Cash or C.");
    return false;
  }

  if (isImportingSheet) return false;

  isImportingSheet = true;
  try {
    showStatus(automatic ? "Auto import is running..." : "Importing cash from Google Sheet...");
    const rows = sheetInfo.kind === "google" ? await loadGoogleSheetRows(sheetInfo) : await loadCsvRows(sheetInfo.url);
    const result = calculateCashTotal(rows, columnSpec);
    if (!result.matchedColumns.length) {
      showStatus("Selected columns were not found in the sheet. Check the column name or letter.");
      return false;
    }
    const baseline = getSheetBaseline(urlValue, columnSpec);

    totalCash = Math.max(0, result.total - baseline);
    saveTotal();
    localStorage.setItem(SHEET_KEY, urlValue);
    localStorage.setItem(SHEET_COLUMNS_KEY, columnSpec);
    saveLastSheetTotal(urlValue, columnSpec, result.total);
    render();
    if (result.count === 0) {
      showStatus(`No amount was found in ${result.matchedColumns.join(", ")}.`);
    } else if (totalCash === 0 && result.total > 0) {
      showStatus(`No new cash after the last settlement. Sheet total ${formatCurrency(result.total)} is already settled.`);
    } else {
      showStatus(`${result.count} cash sales synced from ${result.matchedColumns.join(", ")}: ${formatCurrency(totalCash)}.`);
    }
    return true;
  } finally {
    isImportingSheet = false;
  }
}

async function syncSheetCash(options = {}) {
  if (BACKEND_SUMMARY_URL) {
    await syncBackendCash(options);
    return;
  }
  const urlValue = getConfiguredSheetUrl();
  if (!urlValue) {
    showStatus("Save the sheet link in config.js.");
    return;
  }

  try {
    await importSheetCash(urlValue, options);
  } catch {
    showStatus("The sheet must be public: Anyone with the link can view.");
  }
}

function getNoteSettlementAmount() {
  const notesTotal = [...els.noteCounts].reduce((sum, input) => {
    const count = Math.max(0, Math.floor(Number(input.value || 0)));
    return sum + count * Number(input.dataset.value || 0);
  }, 0);
  const otherTotal = Math.max(0, Number(els.otherCash.value || 0));
  return roundMoney(notesTotal + otherTotal);
}

function getSettlementBreakdown() {
  const noteRows = [...els.noteCounts]
    .map((input) => {
      const note = Number(input.dataset.value || 0);
      const count = Math.max(0, Math.floor(Number(input.value || 0)));
      return { label: `Rs ${note}`, count, amount: roundMoney(note * count) };
    })
    .filter((row) => row.count > 0);
  const otherAmount = roundMoney(els.otherCash.value);
  if (otherAmount > 0) {
    noteRows.push({ label: "Coins / other", count: "-", amount: otherAmount });
  }
  return noteRows;
}

function updateSettlePreview() {
  const settlingAmount = getNoteSettlementAmount();
  const remainingAmount = totalCash - settlingAmount;
  const selectedBank = els.settleBank.value.trim();
  const typedAmount = roundMoney(els.settleAmountCheck.value);

  els.settleNowAmount.textContent = formatCurrency(settlingAmount);
  els.remainingDueAmount.textContent = formatCurrency(clampAmount(remainingAmount, 0, totalCash));

  if (!selectedBank) {
    els.settleWarning.textContent = "Select a bank first.";
    els.confirmSettle.disabled = true;
    return;
  }

  if (settlingAmount <= 0) {
    els.settleWarning.textContent = "Enter note counts to settle cash.";
    els.confirmSettle.disabled = true;
    return;
  }

  if (settlingAmount > totalCash) {
    els.settleWarning.textContent = "The settlement amount is greater than the available cash.";
    els.confirmSettle.disabled = true;
    return;
  }

  if (typedAmount !== settlingAmount) {
    els.settleWarning.textContent = `Type exactly ${formatCurrency(settlingAmount)} to cross-check.`;
    els.confirmSettle.disabled = true;
    return;
  }

  els.settleWarning.textContent =
    remainingAmount > 0
      ? `${formatCurrency(remainingAmount)} will remain due.`
      : "The full cash balance will be settled.";
  els.confirmSettle.disabled = false;
}

function resetSettleInputs() {
  els.settleBank.value = "";
  els.noteCounts.forEach((input) => {
    input.value = "0";
  });
  els.otherCash.value = "0";
  els.settleAmountCheck.value = "";
  updateSettlePreview();
}

function renderReceipt(settlement) {
  els.receiptDate.textContent = new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(settlement.date));
  els.receiptBank.textContent = settlement.bank;
  els.receiptSettled.textContent = formatCurrency(settlement.amount);
  els.receiptDue.textContent = formatCurrency(settlement.due);
  els.receiptNotes.innerHTML = "";

  settlement.breakdown.forEach((row) => {
    const tr = document.createElement("tr");
    const noteCell = document.createElement("td");
    const countCell = document.createElement("td");
    const amountCell = document.createElement("td");
    noteCell.textContent = row.label;
    countCell.textContent = String(row.count);
    amountCell.textContent = formatCurrency(row.amount);
    tr.append(noteCell, countCell, amountCell);
    els.receiptNotes.appendChild(tr);
  });

  els.receiptPanel.hidden = false;
}

async function performSettleCash(settledAmount, bankName, breakdown) {
  const nextCashTotal = clampAmount(totalCash - settledAmount, 0, totalCash);
  const settlement = {
    id: `SET-${Date.now()}`,
    amount: settledAmount,
    bank: bankName,
    breakdown,
    due: nextCashTotal,
    date: new Date().toISOString(),
  };

  if (BACKEND_SETTLEMENT_URL) {
    try {
      await saveBackendSettlement(settlement);
    } catch (error) {
      showStatus(error.message || "Settlement failed.");
      return;
    }
  } else {
    const sheetUrl = getConfiguredSheetUrl();
    const columnSpec = getConfiguredColumns();
    const lastSheetTotal = readJson(LAST_SHEET_TOTAL_KEY);
    if (sheetUrl && columnSpec) {
      const currentBaseline = getSheetBaseline(sheetUrl, columnSpec);
      const hasMatchingSheetTotal = lastSheetTotal?.url === sheetUrl && lastSheetTotal?.columns === columnSpec;
      const nextBaseline = hasMatchingSheetTotal
        ? Math.min(Number(lastSheetTotal.total || 0), currentBaseline + settledAmount)
        : currentBaseline + settledAmount;
      setSheetBaseline(sheetUrl, columnSpec, nextBaseline);
    }
  }

  totalCash = nextCashTotal;
  saveTotal();
  localStorage.setItem(SETTLED_KEY, JSON.stringify(settlement));
  render();
  renderReceipt(settlement);
  if (!BACKEND_SUMMARY_URL) exportSettlementToSheet(settlement).catch(() => queueSettlementExport(settlement));
  showStatus(`${formatCurrency(settledAmount)} settled to ${bankName}. ${formatCurrency(totalCash)} due.`);
  window.setTimeout(() => syncSheetCash({ automatic: true }), AUTO_IMPORT_DELAY_MS);
  window.setTimeout(retryPendingSettlementExports, 1200);
}

function openSettleDialog() {
  if (totalCash <= 0) {
    showStatus("Cash must be greater than zero to settle.");
    return;
  }

  els.settleDialogAmount.textContent = formatCurrency(totalCash);
  resetSettleInputs();
  els.settleDialog.showModal();
}

function closeSettleDialog() {
  els.settleDialog.close();
}

function openFinalSettleDialog(settledAmount, bankName, breakdown) {
  pendingSettlement = { amount: settledAmount, bank: bankName, breakdown };
  els.finalBankName.textContent = bankName;
  els.finalSettleAmount.textContent = formatCurrency(settledAmount);
  els.finalDueAmount.textContent = formatCurrency(clampAmount(totalCash - settledAmount, 0, totalCash));
  closeSettleDialog();
  els.finalSettleDialog.showModal();
}

function closeFinalSettleDialog() {
  els.finalSettleDialog.close();
}

els.settleCash.addEventListener("click", openSettleDialog);

els.cancelSettle.addEventListener("click", closeSettleDialog);

els.confirmSettle.addEventListener("click", () => {
  const settledAmount = getNoteSettlementAmount();
  const bankName = els.settleBank.value.trim();
  const typedAmount = roundMoney(els.settleAmountCheck.value);
  if (!bankName || settledAmount <= 0 || settledAmount > totalCash || typedAmount !== settledAmount) {
    updateSettlePreview();
    return;
  }

  openFinalSettleDialog(settledAmount, bankName, getSettlementBreakdown());
});

els.settleDialog.addEventListener("click", (event) => {
  if (event.target === els.settleDialog) closeSettleDialog();
});

els.noteCounts.forEach((input) => {
  input.addEventListener("input", updateSettlePreview);
});

els.otherCash.addEventListener("input", updateSettlePreview);

els.settleBank.addEventListener("change", updateSettlePreview);

els.settleAmountCheck.addEventListener("input", updateSettlePreview);

els.backToSettle.addEventListener("click", () => {
  closeFinalSettleDialog();
  els.settleDialog.showModal();
});

els.finalConfirmSettle.addEventListener("click", () => {
  if (!pendingSettlement) return;

  const { amount, bank, breakdown } = pendingSettlement;
  pendingSettlement = null;
  closeFinalSettleDialog();
  performSettleCash(amount, bank, breakdown);
});

els.finalSettleDialog.addEventListener("click", (event) => {
  if (event.target === els.finalSettleDialog) closeFinalSettleDialog();
});

els.downloadReceipt.addEventListener("click", () => {
  window.print();
});

render();
syncSheetCash({ automatic: true });
if (!BACKEND_SUMMARY_URL) retryPendingSettlementExports();

window.setInterval(() => {
  if (document.hidden) return;
  syncSheetCash({ automatic: true });
}, AUTO_IMPORT_INTERVAL_MS);
