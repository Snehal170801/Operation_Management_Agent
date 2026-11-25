const apiBaseInput = document.getElementById("api-base");

function apiBase() {
  return apiBaseInput.value.replace(/\/$/, "");
}

const EYE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"></path>
  <circle cx="12" cy="12" r="3"></circle>
</svg>`;

function viewButton(caseId) {
  return `<button class="view-link" data-case-id="${caseId}" title="View details">${EYE_ICON}</button>`;
}

function wireViewButtons(container) {
  container.querySelectorAll(".view-link").forEach((btn) => {
    btn.addEventListener("click", () => goToLookup(btn.dataset.caseId));
  });
}

// ---------- Formatting helpers ----------
function humanize(str) {
  if (!str) return "—";
  return str
    .toString()
    .replace(/[_.]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDateTime(value) {
  if (!value) return "—";
  // The backend stores UTC (SYSUTCDATETIME()) but sends it with no timezone
  // marker, so the browser would otherwise misread it as local time.
  const isoWithZone = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const d = new Date(isoWithZone);
  if (isNaN(d)) return value;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusBadgeClass(status) {
  if (status === "open") return "badge badge-open";
  if (status === "closed") return "badge badge-closed";
  if (status === "rejected") return "badge badge-rejected";
  return "badge badge-stage";
}

// Renders a list of {label, value, mono} rows into a container, replacing raw JSON.
function renderFields(container, rows) {
  container.innerHTML = rows
    .map(
      (row) => `
      <div class="field-row">
        <div class="field-label">${row.label}</div>
        <div class="field-value${row.mono ? " mono-value" : ""}">${row.value}</div>
      </div>`
    )
    .join("");
}

function caseFieldRows(caseData) {
  return [
    { label: "Case ID", value: caseData.case_id, mono: true },
    { label: "Requester", value: caseData.requester_id },
    { label: "Stage", value: `<span class="badge badge-stage">${humanize(caseData.stage)}</span>` },
    { label: "Status", value: `<span class="${statusBadgeClass(caseData.status)}">${humanize(caseData.status)}</span>` },
    { label: "Created", value: formatDateTime(caseData.created_at) },
    { label: "Updated", value: formatDateTime(caseData.updated_at) },
  ];
}

function purchaseFieldRows(purchaseData) {
  return [
    { label: "Cost Center", value: purchaseData.cost_center || "Not specified" },
    { label: "Original Request", value: `“${purchaseData.raw_request}”` },
    { label: "Created", value: formatDateTime(purchaseData.created_at) },
  ];
}

function renderPurchaseItems(container, items) {
  if (!items || !items.length) {
    container.innerHTML = "";
    return;
  }
  const total = items.reduce((sum, i) => sum + i.quantity, 0);
  const rows = items
    .map((i) => `<tr><td>${i.description}</td><td class="item-qty">${i.quantity}</td></tr>`)
    .join("");
  container.innerHTML = `
    <div class="items-heading">Line Items</div>
    <table class="items-table">
      <tbody>
        ${rows}
        <tr class="items-total-row"><td>Total</td><td class="item-qty">${total}</td></tr>
      </tbody>
    </table>`;
}

function formatPayload(rawPayload) {
  try {
    const obj = JSON.parse(rawPayload);
    const keys = Object.keys(obj);
    if (!keys.length) return "";
    return keys
      .map((k) => `<span class="payload-pair"><strong>${humanize(k)}:</strong> ${obj[k] ?? "—"}</span>`)
      .join("  ·  ");
  } catch {
    return rawPayload || "";
  }
}

// ---------- Sidebar navigation ----------
const navLinks = document.querySelectorAll(".nav-link");
const pages = document.querySelectorAll(".page");

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    if (link.disabled) return;
    navLinks.forEach((l) => l.classList.remove("active"));
    link.classList.add("active");

    const pageId = link.dataset.page;
    const target = document.getElementById(`page-${pageId}`);

    pages.forEach((p) => p.classList.remove("active"));

    if (target) {
      target.classList.add("active");
      if (pageId === "requests") loadRequests();
      if (pageId === "operations-agent") loadOperationsAgentStats();
      if (pageId === "purchase-agent") loadPurchaseAgentStats();
      if (pageId === "procurement-agent") {
        loadProcurementAgentStats();
        loadStock();
      }
      if (pageId === "vendor-agent") {
        loadVendorAgentStats();
        loadVendors();
      }
    } else {
      document.getElementById("placeholder-title").textContent = link.textContent.trim();
      document.getElementById("page-placeholder").classList.add("active");
    }
  });
});

function goToLookup(caseId) {
  document.getElementById("lookup-case-id").value = caseId;
  document.querySelector('.nav-link[data-page="case-lookup"]').click();
  runLookup();
}

// ---------- Requests list ----------
async function loadRequests() {
  const tbody = document.getElementById("requests-table-body");
  const errorEl = document.getElementById("requests-error");
  const countEl = document.getElementById("requests-count");

  errorEl.textContent = "";
  tbody.innerHTML = '<tr><td colspan="8" class="empty-state">Loading...</td></tr>';

  try {
    const res = await fetch(`${apiBase()}/cases`);
    const cases = await res.json();
    if (!res.ok) throw new Error(cases.detail || "Failed to load requests");

    countEl.textContent = `${cases.length} case${cases.length === 1 ? "" : "s"}`;

    if (!cases.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No cases created yet.</td></tr>';
      return;
    }

    tbody.innerHTML = cases
      .map((c) => {
        const shortId = c.case_id.split("-")[0];
        return `<tr>
          <td class="case-id-cell" title="${c.case_id}">${shortId}</td>
          <td>${c.requester_id}</td>
          <td class="items-summary-cell" title="${c.items_summary || ""}">${c.items_summary || "—"}</td>
          <td>${c.total_quantity ?? "—"}</td>
          <td><span class="badge badge-stage">${humanize(c.stage)}</span></td>
          <td><span class="${statusBadgeClass(c.status)}">${humanize(c.status)}</span></td>
          <td>${formatDateTime(c.created_at)}</td>
          <td>${viewButton(c.case_id)}</td>
        </tr>`;
      })
      .join("");

    wireViewButtons(tbody);
  } catch (err) {
    errorEl.textContent = err.message;
    tbody.innerHTML = '<tr><td colspan="8" class="empty-state">Could not load requests.</td></tr>';
  }
}

document.getElementById("btn-refresh-requests").addEventListener("click", loadRequests);

// ---------- Operations Agent live stats ----------
async function loadOperationsAgentStats() {
  const tbody = document.getElementById("ops-recent-cases");
  try {
    const res = await fetch(`${apiBase()}/cases`);
    const cases = await res.json();
    if (!res.ok) throw new Error(cases.detail || "Failed to load");

    document.getElementById("ops-stat-total").textContent = cases.length;
    document.getElementById("ops-stat-open").textContent = cases.filter((c) => c.status === "open").length;
    document.getElementById("ops-stat-closed").textContent = cases.filter((c) => c.status === "closed").length;
    document.getElementById("ops-stat-rejected").textContent = cases.filter((c) => c.status === "rejected").length;

    if (!cases.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No cases yet.</td></tr>';
      return;
    }

    tbody.innerHTML = cases
      .slice(0, 5)
      .map(
        (c) => `<tr>
          <td class="case-id-cell" title="${c.case_id}">${c.case_id.split("-")[0]}</td>
          <td>${c.requester_id}</td>
          <td><span class="badge badge-stage">${humanize(c.stage)}</span></td>
          <td><span class="${statusBadgeClass(c.status)}">${humanize(c.status)}</span></td>
          <td>${formatDateTime(c.created_at)}</td>
          <td>${viewButton(c.case_id)}</td>
        </tr>`
      )
      .join("");
    wireViewButtons(tbody);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">${err.message}</td></tr>`;
  }
}

// ---------- Purchase Agent live stats ----------
async function loadPurchaseAgentStats() {
  const tbody = document.getElementById("purchase-recent-requests");
  try {
    const res = await fetch(`${apiBase()}/cases`);
    const cases = await res.json();
    if (!res.ok) throw new Error(cases.detail || "Failed to load");

    const withRequests = cases.filter((c) => c.item_count);
    const totalItems = withRequests.reduce((sum, c) => sum + c.item_count, 0);
    const totalQty = withRequests.reduce((sum, c) => sum + (c.total_quantity || 0), 0);

    document.getElementById("purchase-stat-requests").textContent = withRequests.length;
    document.getElementById("purchase-stat-items").textContent = totalItems;
    document.getElementById("purchase-stat-qty").textContent = totalQty;

    if (!withRequests.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No purchase requests yet.</td></tr>';
      return;
    }

    tbody.innerHTML = withRequests
      .slice(0, 5)
      .map(
        (c) => `<tr>
          <td class="case-id-cell" title="${c.case_id}">${c.case_id.split("-")[0]}</td>
          <td class="items-summary-cell" title="${c.items_summary || ""}">${c.items_summary || "—"}</td>
          <td>${c.total_quantity ?? "—"}</td>
          <td>${formatDateTime(c.created_at)}</td>
          <td>${viewButton(c.case_id)}</td>
        </tr>`
      )
      .join("");
    wireViewButtons(tbody);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">${err.message}</td></tr>`;
  }
}

// ---------- Procurement Agent live stats ----------
async function loadProcurementAgentStats() {
  try {
    const res = await fetch(`${apiBase()}/cases`);
    const cases = await res.json();
    if (!res.ok) throw new Error(cases.detail || "Failed to load");

    const fulfilled = cases.filter((c) => c.stage === "fulfilled_from_stock").length;
    const sourcing = cases.filter((c) => c.stage === "sourcing_needed").length;

    document.getElementById("procurement-stat-checked").textContent = fulfilled + sourcing;
    document.getElementById("procurement-stat-fulfilled").textContent = fulfilled;
    document.getElementById("procurement-stat-sourcing").textContent = sourcing;
  } catch {
    // stat boxes just stay at "—"
  }
}

// ---------- Stock management ----------
async function loadStock() {
  const tbody = document.getElementById("stock-table-body");
  try {
    const res = await fetch(`${apiBase()}/stock`);
    const stock = await res.json();
    if (!res.ok) throw new Error(stock.detail || "Failed to load stock");

    if (!stock.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty-state">No stock added yet.</td></tr>';
      return;
    }

    tbody.innerHTML = stock
      .map(
        (s) => `<tr>
          <td>${s.item_description}</td>
          <td>${s.quantity_available}</td>
          <td>${formatDateTime(s.updated_at)}</td>
        </tr>`
      )
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="3" class="empty-state">${err.message}</td></tr>`;
  }
}

document.getElementById("btn-save-stock").addEventListener("click", async () => {
  const description = document.getElementById("stock-description").value.trim();
  const quantityRaw = document.getElementById("stock-quantity").value.trim();
  const errorEl = document.getElementById("stock-error");

  errorEl.textContent = "";

  const quantity = Number(quantityRaw);
  if (!description || quantityRaw === "" || !Number.isInteger(quantity) || quantity < 0) {
    errorEl.textContent = "Enter an item description and a whole number quantity.";
    return;
  }

  try {
    const res = await fetch(`${apiBase()}/stock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_description: description, quantity_available: quantity }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Failed to save stock");
    }
    document.getElementById("stock-description").value = "";
    document.getElementById("stock-quantity").value = "";
    loadStock();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// ---------- Vendor Agent live stats ----------
async function loadVendorAgentStats() {
  try {
    const [vendorsRes, casesRes] = await Promise.all([
      fetch(`${apiBase()}/vendors`),
      fetch(`${apiBase()}/cases`),
    ]);
    const vendors = await vendorsRes.json();
    const cases = await casesRes.json();

    document.getElementById("vendor-stat-count").textContent = vendorsRes.ok ? vendors.length : "—";
    if (casesRes.ok) {
      document.getElementById("vendor-stat-quotes").textContent =
        cases.filter((c) => c.stage === "sourcing_needed").length;
      document.getElementById("vendor-stat-selected").textContent =
        cases.filter((c) => c.stage === "vendor_selected").length;
    }
  } catch {
    // stat boxes just stay at "—"
  }
}

// ---------- Vendor management ----------
async function loadVendors() {
  const tbody = document.getElementById("vendor-table-body");
  const select = document.getElementById("quote-vendor-select");
  try {
    const res = await fetch(`${apiBase()}/vendors`);
    const vendors = await res.json();
    if (!res.ok) throw new Error(vendors.detail || "Failed to load vendors");

    if (!vendors.length) {
      tbody.innerHTML = '<tr><td colspan="2" class="empty-state">No vendors added yet.</td></tr>';
      select.innerHTML = '<option value="">No vendors yet</option>';
      return;
    }

    tbody.innerHTML = vendors
      .map((v) => `<tr><td>${v.name}</td><td>${v.reliability_score}</td></tr>`)
      .join("");

    select.innerHTML = vendors
      .map((v) => `<option value="${v.vendor_id}">${v.name}</option>`)
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="2" class="empty-state">${err.message}</td></tr>`;
  }
}

document.getElementById("btn-save-vendor").addEventListener("click", async () => {
  const name = document.getElementById("vendor-name").value.trim();
  const reliabilityRaw = document.getElementById("vendor-reliability").value.trim();
  const errorEl = document.getElementById("vendor-error");
  errorEl.textContent = "";

  const reliability = Number(reliabilityRaw);
  if (!name || reliabilityRaw === "" || isNaN(reliability) || reliability < 1 || reliability > 5) {
    errorEl.textContent = "Enter a vendor name and a reliability score between 1 and 5.";
    return;
  }

  try {
    const res = await fetch(`${apiBase()}/vendors`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, reliability_score: reliability }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Failed to save vendor");
    }
    document.getElementById("vendor-name").value = "";
    document.getElementById("vendor-reliability").value = "";
    loadVendors();
    loadVendorAgentStats();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// ---------- Quotes ----------
async function loadQuotes(caseId) {
  const tbody = document.getElementById("quotes-table-body");
  const resultBox = document.getElementById("vendor-selection-result");
  resultBox.classList.add("hidden");

  try {
    const res = await fetch(`${apiBase()}/cases/${caseId}/quotes`);
    const quotes = await res.json();
    if (!res.ok) throw new Error(quotes.detail || "Failed to load quotes");

    if (!quotes.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No quotes submitted for this case yet.</td></tr>';
    } else {
      tbody.innerHTML = quotes
        .map(
          (q) => `<tr>
            <td>${q.vendor_name}</td>
            <td>${q.price != null ? "₹" + q.price : "—"}</td>
            <td>${q.lead_time_days != null ? q.lead_time_days + " days" : "—"}</td>
            <td>${q.terms || "—"}</td>
          </tr>`
        )
        .join("");
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-state">${err.message}</td></tr>`;
  }

  try {
    const selRes = await fetch(`${apiBase()}/cases/${caseId}/vendor-selection`);
    if (selRes.ok) {
      const sel = await selRes.json();
      renderFields(document.getElementById("vendor-selection-details"), [
        { label: "Recommended", value: sel.vendor_name },
        { label: "Rationale", value: sel.rationale || "—" },
      ]);
      resultBox.classList.remove("hidden");
    }
  } catch {
    // no selection yet -- leave hidden
  }
}

document.getElementById("btn-submit-quote").addEventListener("click", async () => {
  const caseId = document.getElementById("quote-case-id").value.trim();
  const vendorId = document.getElementById("quote-vendor-select").value;
  const rawText = document.getElementById("quote-raw-text").value.trim();
  const errorEl = document.getElementById("quote-error");
  errorEl.textContent = "";

  if (!caseId || !vendorId || !rawText) {
    errorEl.textContent = "Case ID, vendor, and quote text are all required.";
    return;
  }

  try {
    const res = await fetch(`${apiBase()}/cases/${caseId}/quotes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vendor_id: vendorId, raw_quote_text: rawText }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to submit quote");

    document.getElementById("quote-raw-text").value = "";
    loadQuotes(caseId);
    loadVendorAgentStats();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById("btn-rank-vendors").addEventListener("click", async () => {
  const caseId = document.getElementById("quote-case-id").value.trim();
  const errorEl = document.getElementById("quote-error");
  errorEl.textContent = "";

  if (!caseId) {
    errorEl.textContent = "Enter a case ID first.";
    return;
  }

  try {
    const res = await fetch(`${apiBase()}/cases/${caseId}/rank-vendors`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to rank vendors");

    loadQuotes(caseId);
    loadVendorAgentStats();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById("quote-case-id").addEventListener("change", (e) => {
  const caseId = e.target.value.trim();
  if (caseId) loadQuotes(caseId);
});

// ---------- API status check ----------
async function checkApiStatus() {
  const dot = document.getElementById("api-status-dot");
  const text = document.getElementById("api-status-text");
  try {
    const res = await fetch(`${apiBase()}/health`);
    if (res.ok) {
      dot.className = "status-dot online";
      text.textContent = "API online";
    } else {
      throw new Error("not ok");
    }
  } catch {
    dot.className = "status-dot offline";
    text.textContent = "API unreachable";
  }
}
checkApiStatus();
setInterval(checkApiStatus, 8000);

// ---------- Create Case ----------
document.getElementById("btn-create-case").addEventListener("click", async () => {
  const requesterId = document.getElementById("requester-id").value.trim();
  const rawRequest = document.getElementById("raw-request").value.trim();
  const errorEl = document.getElementById("create-case-error");
  const resultCard = document.getElementById("create-case-result");
  const detailsEl = document.getElementById("create-case-details");

  errorEl.textContent = "";
  resultCard.classList.add("hidden");

  if (!requesterId || !rawRequest) {
    errorEl.textContent = "Both fields are required.";
    return;
  }

  try {
    const res = await fetch(`${apiBase()}/cases`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requester_id: requesterId, raw_request: rawRequest }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");

    renderFields(detailsEl, [
      { label: "Case ID", value: data.case_id, mono: true },
      { label: "Status", value: `<span class="badge badge-open">Created</span>` },
    ]);
    resultCard.classList.remove("hidden");

    // Pre-fill the lookup page so you can jump straight there
    document.getElementById("lookup-case-id").value = data.case_id;
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// ---------- Case Lookup ----------
document.getElementById("btn-lookup").addEventListener("click", runLookup);

async function runLookup() {
  const caseId = document.getElementById("lookup-case-id").value.trim();
  const errorEl = document.getElementById("lookup-error");
  const caseDetails = document.getElementById("lookup-case-details");
  const purchaseDetails = document.getElementById("lookup-purchase-details");
  const eventsList = document.getElementById("lookup-events-list");

  errorEl.textContent = "";

  if (!caseId) {
    errorEl.textContent = "Enter a case_id first.";
    return;
  }

  try {
    const caseRes = await fetch(`${apiBase()}/cases/${caseId}`);
    const caseData = await caseRes.json();
    if (!caseRes.ok) throw new Error(caseData.detail || "Case lookup failed");
    renderFields(caseDetails, caseFieldRows(caseData));
  } catch (err) {
    caseDetails.innerHTML = `<p class="empty-state">${err.message}</p>`;
    errorEl.textContent = err.message;
    return;
  }

  try {
    const purchaseRes = await fetch(`${apiBase()}/purchase-requests/${caseId}`);
    const purchaseData = await purchaseRes.json();
    const itemsEl = document.getElementById("lookup-purchase-items");
    if (purchaseRes.ok) {
      renderFields(purchaseDetails, purchaseFieldRows(purchaseData));
      renderPurchaseItems(itemsEl, purchaseData.items);
    } else {
      purchaseDetails.innerHTML = `<p class="empty-state">Not created yet — ${purchaseData.detail}</p>`;
      itemsEl.innerHTML = "";
    }
  } catch {
    purchaseDetails.innerHTML = `<p class="empty-state">Could not load.</p>`;
  }

  try {
    const eventsRes = await fetch(`${apiBase()}/cases/${caseId}/events`);
    const events = await eventsRes.json();
    if (!eventsRes.ok || !events.length) {
      eventsList.innerHTML = '<li class="timeline-empty">No events found.</li>';
      return;
    }
    eventsList.innerHTML = events
      .map((e) => {
        const payload = formatPayload(e.payload);
        return `<li>
          <div class="timeline-type">${humanize(e.event_type)}</div>
          <div class="timeline-meta">${e.agent_name || "System"} · ${formatDateTime(e.created_at)}</div>
          ${payload ? `<div class="timeline-payload">${payload}</div>` : ""}
        </li>`;
      })
      .join("");
  } catch {
    eventsList.innerHTML = '<li class="timeline-empty">Could not load events.</li>';
  }
}
