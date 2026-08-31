(() => {
  "use strict";

  const STATE = {
    summary: null,
    selectedId: null,
    currentDocument: null,
    filter: "",
    history: [],
  };

  const CATEGORY_LABELS = {
    governance: "Основное",
    legacy: "Архив",
    technical: "Техническое",
  };

  const ACTOR_STORAGE_KEY = "ntAnalyzerDocsActor";

  const $ = (id) => document.getElementById(id);

  async function apiGet(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `${response.status}`);
    }
    return payload;
  }

  async function apiPost(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `${response.status}`);
    }
    return payload;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setStatus(text, tone = "info") {
    const node = $("docs-status");
    if (!node) return;
    node.textContent = text;
    node.className = `status-pill ${tone}`;
  }

  function savedActor() {
    try {
      return String(window.localStorage.getItem(ACTOR_STORAGE_KEY) || "").trim();
    } catch (_) {
      return "";
    }
  }

  function rememberActor(actor) {
    const value = String(actor || "").trim();
    if (!value) return;
    try {
      window.localStorage.setItem(ACTOR_STORAGE_KEY, value);
    } catch (_) {
      // ignore storage errors
    }
  }

  function documents() {
    const list = (STATE.summary && STATE.summary.documents) || [];
    if (!STATE.filter) return list;
    const needle = STATE.filter.toLowerCase();
    return list.filter((doc) => {
      const hay = [doc.title, doc.label, doc.category, doc.rel_path].join(" ").toLowerCase();
      return hay.includes(needle);
    });
  }

  function formatLawValue(law) {
    if (!law) return "—";
    if (law.kind === "boolean") return law.value ? "Да" : "Нет";
    if (law.kind === "number" && law.unit) {
      const numeric = Number(law.value);
      if (Number.isFinite(numeric)) {
        if (law.unit === "USD") return `${numeric.toFixed(2)} USD`;
        if (law.unit === "%") return `${numeric.toFixed(0)}%`;
        if (Math.abs(numeric - Math.round(numeric)) < 1e-9) return `${Math.round(numeric)} ${law.unit}`;
        return `${numeric.toFixed(2)} ${law.unit}`;
      }
    }
    return law.unit ? `${law.value} ${law.unit}` : String(law.value ?? "—");
  }

  function formatDateTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  }

  function hideEditors() {
    $("docs-law-editor").hidden = true;
    $("docs-markdown-editor").hidden = true;
  }

  function latestEntryForEntity(entityId) {
    return (STATE.history || []).find((entry) => entry.entity_id === entityId) || null;
  }

  function latestEntryForDocument(docId) {
    return (STATE.history || []).find((entry) => {
      const ids = Array.isArray(entry.document_ids) ? entry.document_ids : [];
      return ids.includes(docId) || entry.entity_id === docId;
    }) || null;
  }

  function renderSidebar() {
    const root = $("docs-list");
    if (!root) return;
    const groups = new Map();
    for (const doc of documents()) {
      const category = doc.category || "other";
      if (!groups.has(category)) groups.set(category, []);
      groups.get(category).push(doc);
    }
    const html = [];
    for (const [category, items] of groups.entries()) {
      html.push(`<section class="docs-list-group">`);
      html.push(`<h3>${escapeHtml(CATEGORY_LABELS[category] || category)}</h3>`);
      for (const doc of items) {
        const active = doc.id === STATE.selectedId ? " active" : "";
        html.push(
          `<button type="button" class="docs-list-item${active}" data-doc-id="${escapeHtml(doc.id)}">` +
          `<span class="docs-list-title">${escapeHtml(doc.label || doc.title || doc.id)}</span>` +
          `<span class="docs-list-path">${escapeHtml(doc.rel_path || "")}</span>` +
          `</button>`
        );
      }
      html.push(`</section>`);
    }
    root.innerHTML = html.join("");
    root.querySelectorAll("[data-doc-id]").forEach((button) => {
      button.addEventListener("click", () => openDocument(button.getAttribute("data-doc-id")));
    });
  }

  function renderRuntimeBand() {
    const root = $("docs-runtime-band");
    if (!root || !STATE.summary) return;
    const defaults = STATE.summary.runtime_defaults || {};
    const capital = Number(defaults.starting_capital || 0);
    const maxDdPct = Number(defaults.max_drawdown_pct || 0) * 100;
    const commission = Number(defaults.round_turn_commission || 0);
    root.innerHTML =
      `<div class="docs-chip"><span class="docs-chip-label">Capital</span><strong>${escapeHtml(Number.isFinite(capital) ? capital.toFixed(2) : "—")} USD</strong></div>` +
      `<div class="docs-chip"><span class="docs-chip-label">MaxDD</span><strong>${escapeHtml(Number.isFinite(maxDdPct) ? maxDdPct.toFixed(0) : "—")}%</strong></div>` +
      `<div class="docs-chip"><span class="docs-chip-label">Commission</span><strong>${escapeHtml(Number.isFinite(commission) ? commission.toFixed(2) : "—")} USD</strong></div>` +
      `<div class="docs-chip"><span class="docs-chip-label">Slippage</span><strong>${escapeHtml(String(defaults.slippage_ticks ?? "—"))}</strong></div>` +
      `<div class="docs-chip"><span class="docs-chip-label">Fill</span><strong>${escapeHtml(defaults.order_fill_resolution || "—")}</strong></div>`;
  }

  function renderDocumentHeader() {
    const doc = STATE.currentDocument;
    $("docs-title").textContent = doc ? (doc.label || doc.title || doc.id) : "Документ";
    $("docs-meta").textContent = doc ? `${doc.rel_path || ""} · ${doc.editable_kind || "none"}` : "";
    const editBtn = $("docs-edit-doc-btn");
    if (!editBtn) return;
    editBtn.hidden = !(doc && doc.editable_kind === "markdown");
  }

  function renderChangeList(changes) {
    const items = Array.isArray(changes) ? changes : [];
    if (!items.length) return `<div class="docs-history-empty-row">Без детализированных полей.</div>`;
    return items.map((change) => {
      const label = escapeHtml(change.label || change.field || "Изменение");
      const beforeText = escapeHtml(change.before_text || "—");
      const afterText = escapeHtml(change.after_text || "—");
      const hashes = change.before_hash || change.after_hash
        ? `<div class="docs-history-hash">${escapeHtml(change.before_hash || "—")} -> ${escapeHtml(change.after_hash || "—")}</div>`
        : "";
      return (
        `<div class="docs-history-change">` +
        `<strong>${label}</strong>` +
        `<div class="docs-history-diff"><span>${beforeText}</span><span>${afterText}</span></div>` +
        hashes +
        `</div>`
      );
    }).join("");
  }

  function renderHistoryStamp(entry, compact = false) {
    if (!entry) return "";
    const detail = compact
      ? `${formatDateTime(entry.ts_utc)} · ${entry.actor || "—"} · поправка №${entry.amendment_no || "—"}`
      : `Поправка №${entry.amendment_no || "—"} · ${formatDateTime(entry.ts_utc)} · ${entry.actor || "—"}`;
    return `<div class="docs-last-edit">${escapeHtml(detail)}</div>`;
  }

  function renderLawCards(doc) {
    const items = Array.isArray(doc.laws) ? doc.laws : [];
    if (!items.length) {
      return `<div class="docs-empty">Для этого документа пока нет законов.</div>`;
    }
    return items.map((law) => {
      const sources = (law.source_refs || []).map((row) => `<li>${escapeHtml(row)}</li>`).join("");
      const dynamic = (law.dynamic_targets || []).map((row) => `<li>${escapeHtml(row)}</li>`).join("");
      const review = (law.review_targets || []).map((row) => `<li>${escapeHtml(row)}</li>`).join("");
      const latest = latestEntryForEntity(law.id);
      return (
        `<article class="law-card">` +
        `<div class="law-card-head">` +
        `<div><h3>${escapeHtml(law.id)} — ${escapeHtml(law.title)}</h3>` +
        `<div class="law-card-value">${escapeHtml(formatLawValue(law))}</div>` +
        renderHistoryStamp(latest, true) +
        `</div>` +
        `<button type="button" class="btn" data-edit-law="${escapeHtml(law.id)}">Редактировать</button>` +
        `</div>` +
        `<p>${escapeHtml(law.summary || "")}</p>` +
        (law.warning ? `<div class="law-warning">${escapeHtml(law.warning)}</div>` : "") +
        `<div class="law-grid">` +
        `<section><h4>Источники</h4><ul>${sources || "<li>—</li>"}</ul></section>` +
        `<section><h4>Автосинхронизация</h4><ul>${dynamic || "<li>—</li>"}</ul></section>` +
        `<section><h4>Проверить вручную</h4><ul>${review || "<li>—</li>"}</ul></section>` +
        `</div>` +
        `</article>`
      );
    }).join("");
  }

  function renderMarkdown(doc) {
    const latest = latestEntryForDocument(doc.id);
    return (
      (latest ? renderHistoryStamp(latest, false) : "") +
      `<pre class="docs-raw">${escapeHtml(doc.content || "")}</pre>`
    );
  }

  function renderDocumentContent() {
    const root = $("docs-content");
    const doc = STATE.currentDocument;
    if (!root) return;
    if (!doc) {
      root.innerHTML = `<div class="docs-empty">Документ не выбран.</div>`;
      return;
    }
    root.innerHTML = doc.editable_kind === "laws" ? renderLawCards(doc) : renderMarkdown(doc);
    root.querySelectorAll("[data-edit-law]").forEach((button) => {
      button.addEventListener("click", () => openLawEditor(button.getAttribute("data-edit-law")));
    });
  }

  function renderConsistency() {
    const root = $("docs-consistency-body");
    const report = STATE.summary && STATE.summary.consistency;
    if (!root || !report) return;
    const html = [];
    for (const item of report.items || []) {
      const refs = (item.candidate_hardcoded_refs || []).slice(0, 8);
      html.push(`<article class="docs-check-card">`);
      html.push(`<h4>${escapeHtml(item.law_id)} — ${escapeHtml(item.title)}</h4>`);
      html.push(`<div class="docs-check-value">Текущее значение: <strong>${escapeHtml(String(item.value))}</strong></div>`);
      html.push(`<div class="docs-check-list"><strong>Автоматически:</strong> ${escapeHtml((item.dynamic_targets || []).join(", ") || "—")}</div>`);
      html.push(`<div class="docs-check-list"><strong>Ручная проверка:</strong> ${escapeHtml((item.review_targets || []).join(", ") || "—")}</div>`);
      if (refs.length) {
        html.push(`<div class="docs-check-list"><strong>Кандидаты на хардкод:</strong><ul>`);
        for (const row of refs) {
          html.push(`<li>${escapeHtml(row.path)} · совпадений: ${escapeHtml(row.hits)}</li>`);
        }
        html.push(`</ul></div>`);
      }
      html.push(`</article>`);
    }
    root.innerHTML = html.join("");
  }

  function relevantHistory() {
    const entries = Array.isArray(STATE.history) ? STATE.history : [];
    const doc = STATE.currentDocument;
    if (!doc) return entries;
    if (doc.editable_kind === "laws") {
      const ids = new Set((doc.laws || []).map((law) => law.id));
      const filtered = entries.filter((entry) => ids.has(entry.entity_id));
      return filtered.length ? filtered : entries;
    }
    const filtered = entries.filter((entry) => {
      const ids = Array.isArray(entry.document_ids) ? entry.document_ids : [];
      return ids.includes(doc.id) || entry.entity_id === doc.id;
    });
    return filtered.length ? filtered : entries;
  }

  function renderHistory() {
    const root = $("docs-history-body");
    const doc = STATE.currentDocument;
    if (!root) return;
    const entries = relevantHistory().slice(0, 24);
    if (!entries.length) {
      root.innerHTML = `<div class="docs-empty">Поправок пока нет.</div>`;
      return;
    }
    const scope = doc
      ? `<div class="docs-history-scope">Показаны последние поправки по текущему документу. Если их нет, показаны общие последние изменения.</div>`
      : "";
    root.innerHTML = scope + entries.map((entry) => {
      const meta = [
        `Поправка №${entry.amendment_no || "—"}`,
        formatDateTime(entry.ts_utc),
        entry.actor || "—",
        entry.path || entry.entity_id || "",
      ].filter(Boolean).map(escapeHtml).join(" · ");
      return (
        `<article class="docs-history-card">` +
        `<h4>${escapeHtml(entry.entity_title || entry.entity_id || "Изменение")}</h4>` +
        `<div class="docs-history-meta">${meta}</div>` +
        (entry.reason ? `<div class="docs-history-reason">${escapeHtml(entry.reason)}</div>` : "") +
        renderChangeList(entry.changes) +
        `</article>`
      );
    }).join("");
  }

  function seedActorFields() {
    const actor = savedActor();
    ["docs-law-actor", "docs-markdown-actor"].forEach((id) => {
      const node = $(id);
      if (node && !String(node.value || "").trim()) {
        node.value = actor;
      }
    });
  }

  function openLawEditor(lawId) {
    const doc = STATE.currentDocument;
    if (!doc || !Array.isArray(doc.laws)) return;
    const law = doc.laws.find((row) => row.id === lawId);
    if (!law) return;
    hideEditors();
    $("docs-law-id").value = law.id;
    $("docs-law-value").value = law.value ?? "";
    $("docs-law-summary").value = law.summary || "";
    $("docs-law-warning").value = law.warning || "";
    $("docs-law-actor").value = savedActor();
    $("docs-law-reason").value = "";
    $("docs-law-editor").hidden = false;
    $("docs-law-value").focus();
  }

  function openMarkdownEditor() {
    const doc = STATE.currentDocument;
    if (!doc || doc.editable_kind !== "markdown") return;
    hideEditors();
    $("docs-markdown-id").value = doc.id;
    $("docs-markdown-content").value = doc.content || "";
    $("docs-markdown-actor").value = savedActor();
    $("docs-markdown-reason").value = "";
    $("docs-markdown-editor").hidden = false;
    $("docs-markdown-content").focus();
  }

  async function openDocument(docId) {
    if (!docId) return;
    STATE.selectedId = docId;
    renderSidebar();
    hideEditors();
    setStatus("Загрузка документа…");
    const doc = await apiGet(`/api/governance/documents/${encodeURIComponent(docId)}`);
    STATE.currentDocument = doc;
    renderDocumentHeader();
    renderDocumentContent();
    renderHistory();
    setStatus("Документ загружен", "ok");
  }

  async function reloadSummary(preserveSelection = true) {
    setStatus("Обновление…");
    STATE.summary = await apiGet("/api/governance/summary");
    STATE.history = Array.isArray(STATE.summary.history) ? STATE.summary.history : [];
    renderRuntimeBand();
    renderSidebar();
    renderConsistency();
    seedActorFields();
    const fallbackId = documents()[0] && documents()[0].id;
    const docId = preserveSelection ? (STATE.selectedId || fallbackId) : fallbackId;
    if (docId) {
      await openDocument(docId);
    } else {
      renderHistory();
    }
  }

  async function saveLaw(event) {
    event.preventDefault();
    const lawId = $("docs-law-id").value;
    const actor = String($("docs-law-actor").value || "").trim() || "ui_docs";
    const reason = String($("docs-law-reason").value || "").trim();
    const payload = {
      actor,
      reason,
      value: $("docs-law-value").value,
      summary: $("docs-law-summary").value,
      warning: $("docs-law-warning").value,
    };
    rememberActor(actor);
    setStatus("Сохранение закона…");
    const result = await apiPost(`/api/governance/laws/${encodeURIComponent(lawId)}`, payload);
    hideEditors();
    await reloadSummary(true);
    const amendment = result.history_entry ? ` Поправка №${result.history_entry.amendment_no}.` : "";
    const extra = Array.isArray(result.review_targets) && result.review_targets.length
      ? ` Проверить вручную: ${result.review_targets.join(", ")}`
      : "";
    setStatus(`Закон сохранён.${amendment}${extra}`, "ok");
  }

  async function saveMarkdown(event) {
    event.preventDefault();
    const docId = $("docs-markdown-id").value;
    const actor = String($("docs-markdown-actor").value || "").trim() || "ui_docs";
    const reason = String($("docs-markdown-reason").value || "").trim();
    rememberActor(actor);
    setStatus("Сохранение документа…");
    const result = await apiPost(`/api/governance/documents/${encodeURIComponent(docId)}`, {
      actor,
      reason,
      content: $("docs-markdown-content").value,
    });
    hideEditors();
    await reloadSummary(true);
    const amendment = result.history_entry ? ` Поправка №${result.history_entry.amendment_no}.` : "";
    setStatus(`Документ сохранён.${amendment}`, "ok");
  }

  function wire() {
    $("docs-search")?.addEventListener("input", (event) => {
      STATE.filter = String(event.target.value || "").trim();
      renderSidebar();
    });
    $("docs-edit-doc-btn")?.addEventListener("click", openMarkdownEditor);
    $("docs-law-form")?.addEventListener("submit", (event) => {
      saveLaw(event).catch((error) => setStatus(error.message || String(error), "bad"));
    });
    $("docs-markdown-form")?.addEventListener("submit", (event) => {
      saveMarkdown(event).catch((error) => setStatus(error.message || String(error), "bad"));
    });
    $("docs-law-cancel")?.addEventListener("click", hideEditors);
    $("docs-markdown-cancel")?.addEventListener("click", hideEditors);
    $("docs-refresh-summary")?.addEventListener("click", () => {
      reloadSummary(true).catch((error) => setStatus(error.message || String(error), "bad"));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    wire();
    reloadSummary(true).catch((error) => {
      setStatus(error.message || String(error), "bad");
      $("docs-content").innerHTML = `<div class="docs-empty">Не удалось загрузить документы.</div>`;
    });
  });
})();
