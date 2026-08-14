const holdingsBody = document.getElementById("holdingsBody");
const addForm = document.getElementById("addForm");
const refreshBtn = document.getElementById("refreshBtn");
const analyzePortfolioBtn = document.getElementById("analyzePortfolioBtn");
const promptModal = document.getElementById("promptModal");
const promptModalTitle = document.getElementById("promptModalTitle");
const promptText = document.getElementById("promptText");
const closeModalBtn = document.getElementById("closeModalBtn");
const copyPromptBtn = document.getElementById("copyPromptBtn");
const copyStatus = document.getElementById("copyStatus");

function fmtMoney(v) {
  if (v === null || v === undefined) return "—";
  return "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function fmtPct(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(2) + "%";
}

function plClass(v) {
  if (v === null || v === undefined) return "";
  return v >= 0 ? "pl-positive" : "pl-negative";
}

async function loadHoldings() {
  const res = await fetch("/api/holdings");
  const data = await res.json();
  renderHoldings(data.holdings);
  renderSummary(data.summary);
}

function renderSummary(summary) {
  document.getElementById("sumInvested").textContent = fmtMoney(summary.total_invested);
  document.getElementById("sumCurrent").textContent = fmtMoney(summary.total_current_value);
  const plEl = document.getElementById("sumPL");
  plEl.textContent = fmtMoney(summary.total_pl);
  plEl.className = "card-value " + plClass(summary.total_pl);
  const plPctEl = document.getElementById("sumPLPct");
  plPctEl.textContent = fmtPct(summary.total_pl_pct);
  plPctEl.className = "card-value " + plClass(summary.total_pl_pct);
}

function renderHoldings(holdings) {
  if (!holdings.length) {
    holdingsBody.innerHTML = '<tr><td colspan="12" class="empty-row">No holdings yet — add your first stock above.</td></tr>';
    return;
  }

  holdingsBody.innerHTML = holdings.map(h => `
    <tr data-id="${h.id}">
      <td>${h.symbol}</td>
      <td>${h.name}</td>
      <td>${h.exchange}</td>
      <td>${h.quantity}</td>
      <td>${fmtMoney(h.buy_price)}</td>
      <td>${fmtMoney(h.current_price)}</td>
      <td>${fmtMoney(h.invested)}</td>
      <td>${fmtMoney(h.current_value)}</td>
      <td class="${plClass(h.pl)}">${fmtMoney(h.pl)}</td>
      <td class="${plClass(h.pl_pct)}">${fmtPct(h.pl_pct)}</td>
      <td>${fmtPct(h.weight_pct)}</td>
      <td class="row-actions">
        <button class="analyze-btn" data-id="${h.id}">Analyze</button>
        <button class="delete-btn" data-id="${h.id}">Delete</button>
      </td>
    </tr>
  `).join("");

  holdingsBody.querySelectorAll(".analyze-btn").forEach(btn => {
    btn.addEventListener("click", () => openStockPrompt(btn.dataset.id));
  });
  holdingsBody.querySelectorAll(".delete-btn").forEach(btn => {
    btn.addEventListener("click", () => deleteHolding(btn.dataset.id));
  });
}

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    symbol: document.getElementById("symbol").value,
    name: document.getElementById("name").value,
    exchange: document.getElementById("exchange").value,
    quantity: document.getElementById("quantity").value,
    buy_price: document.getElementById("buyPrice").value,
    buy_date: document.getElementById("buyDate").value,
  };
  const res = await fetch("/api/holdings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    addForm.reset();
    document.getElementById("exchange").value = "NSE";
    await loadHoldings();
  } else {
    const err = await res.json();
    alert(err.error || "Failed to add holding");
  }
});

async function deleteHolding(id) {
  if (!confirm("Remove this holding?")) return;
  await fetch(`/api/holdings/${id}`, { method: "DELETE" });
  await loadHoldings();
}

refreshBtn.addEventListener("click", async () => {
  refreshBtn.textContent = "Refreshing…";
  refreshBtn.disabled = true;
  try {
    const res = await fetch("/api/refresh", { method: "POST" });
    const data = await res.json();
    renderHoldings(data.holdings);
    renderSummary(data.summary);
  } finally {
    refreshBtn.textContent = "Refresh Prices";
    refreshBtn.disabled = false;
  }
});

function openModal(title, text) {
  promptModalTitle.textContent = title;
  promptText.value = text;
  copyStatus.textContent = "";
  promptModal.classList.remove("hidden");
}

closeModalBtn.addEventListener("click", () => promptModal.classList.add("hidden"));
promptModal.addEventListener("click", (e) => {
  if (e.target === promptModal) promptModal.classList.add("hidden");
});

copyPromptBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(promptText.value);
    copyStatus.textContent = "Copied!";
  } catch {
    promptText.select();
    document.execCommand("copy");
    copyStatus.textContent = "Copied!";
  }
  setTimeout(() => (copyStatus.textContent = ""), 2000);
});

analyzePortfolioBtn.addEventListener("click", async () => {
  const res = await fetch("/api/prompts/portfolio");
  const data = await res.json();
  openModal("Full Portfolio Analysis Prompt", data.prompt);
});

async function openStockPrompt(id) {
  const res = await fetch(`/api/prompts/holding/${id}`);
  const data = await res.json();
  if (data.prompt) {
    openModal("Stock Analysis Prompt", data.prompt);
  } else {
    alert(data.error || "Could not generate prompt");
  }
}

loadHoldings();
