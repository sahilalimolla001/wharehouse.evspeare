const SHEET_NAME = "Settlements";

function doPost(e) {
  const data = JSON.parse(e.postData.contents || "{}");
  const sheet = getSettlementSheet();
  sheet.appendRow([
    data.receiptId || "",
    data.date || "",
    data.bank || "",
    data.settledAmount || 0,
    data.remainingDue || 0,
    data.notesText || "",
    JSON.stringify(data.noteBreakdown || []),
  ]);

  return ContentService.createTextOutput(JSON.stringify({ ok: true })).setMimeType(ContentService.MimeType.JSON);
}

function getSettlementSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(SHEET_NAME);
  }

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Receipt ID", "Date", "Bank", "Settled Amount", "Remaining Due", "Notes", "Raw Breakdown"]);
  }

  return sheet;
}
