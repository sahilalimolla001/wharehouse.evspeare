document.addEventListener("submit", (event) => {
  const form = event.target;
  const archiveButton = event.submitter;
  if (archiveButton && archiveButton.textContent.trim().toLowerCase() === "archive") {
    const confirmed = window.confirm("Archive this item?");
    if (!confirmed) event.preventDefault();
  }
});
