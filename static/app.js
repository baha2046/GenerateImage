// static/app.js
// Fully extracted client-side logic for the MFLUX Image Generator (Phase B)

(function () {
  const config = window.APP_CONFIG || {};
  const modelDefaults = config.modelDefaults || {};
  const icons = config.icons || {};

  // === DOM References (populated early so top-level listeners can use them) ===
  let modelSelect, promptInput, widthInput, heightInput, stepsInput, filenamePrefixInput,
      upscaleResolutionInput, form, formErrors, resultSlot, button,
      historyButton, historyModal, historyClose, historyList,
      templatesButton, templatesModal, templatesClose, templatesList, templatesSearch, saveTemplateBtn,
      outputsButton, outputsModal, outputsClose, outputsList,
      settingsButton, settingsModal, settingsClose, settingsSave,
      compareModal, compareClose, compareSwap, compareReset,
      compareSliderContainer, compareImageA, compareImageBWrapper, compareImageB, compareHandle,
      compareLabelA, compareLabelB;

  function initDOMReferences() {
    modelSelect = document.getElementById("model");
    promptInput = document.getElementById("prompt");
    widthInput = document.getElementById("width");
    heightInput = document.getElementById("height");
    stepsInput = document.getElementById("steps");
    filenamePrefixInput = document.getElementById("filename_prefix");
    upscaleResolutionInput = document.getElementById("upscale_resolution");
    form = document.getElementById("generator-form");
    formErrors = document.getElementById("form-errors");
    resultSlot = document.getElementById("result-slot");
    button = document.getElementById("generate-button");

    historyButton = document.getElementById("history-button");
    historyModal = document.getElementById("history-modal");
    historyClose = document.getElementById("history-close");
    historyList = document.getElementById("history-list");

    templatesButton = document.getElementById("templates-button");
    templatesModal = document.getElementById("templates-modal");
    templatesClose = document.getElementById("templates-close");
    templatesList = document.getElementById("templates-list");
    templatesSearch = document.getElementById("templates-search");
    saveTemplateBtn = document.getElementById("save-template-btn");

    outputsButton = document.getElementById("outputs-button");
    outputsModal = document.getElementById("outputs-modal");
    outputsClose = document.getElementById("outputs-close");
    outputsList = document.getElementById("outputs-list");

    settingsButton = document.getElementById("settings-button");
    settingsModal = document.getElementById("settings-modal");
    settingsClose = document.getElementById("settings-close");
    settingsSave = document.getElementById("settings-save");

    compareModal = document.getElementById("compare-modal");
    compareClose = document.getElementById("compare-close");
    compareSwap = document.getElementById("compare-swap");
    compareReset = document.getElementById("compare-reset");
    compareSliderContainer = document.getElementById("compare-slider-container");
    compareImageA = document.getElementById("compare-image-a");
    compareImageBWrapper = document.getElementById("compare-image-b-wrapper");
    compareImageB = document.getElementById("compare-image-b");
    compareHandle = document.getElementById("compare-handle");
    compareLabelA = document.getElementById("compare-label-a");
    compareLabelB = document.getElementById("compare-label-b");
  }

  function addClickOnce(element, key, handler) {
    if (!element || element.dataset[key] === "1") return;
    element.dataset[key] = "1";
    element.addEventListener("click", handler);
  }

  function bindModalControls() {
    addClickOnce(historyButton, "boundOpen", openHistoryModal);
    addClickOnce(templatesButton, "boundOpen", openTemplatesModal);
    addClickOnce(outputsButton, "boundOpen", openOutputsModal);
    addClickOnce(settingsButton, "boundOpen", openSettingsModal);

    addClickOnce(historyClose, "boundClose", closeHistoryModal);
    addClickOnce(historyModal, "boundBackdrop", (e) => {
      if (e.target === historyModal) closeHistoryModal();
    });

    addClickOnce(templatesClose, "boundClose", closeTemplatesModal);
    addClickOnce(templatesModal, "boundBackdrop", (e) => {
      if (e.target === templatesModal) closeTemplatesModal();
    });

    addClickOnce(outputsClose, "boundClose", closeOutputsModal);
    addClickOnce(outputsModal, "boundBackdrop", (e) => {
      if (e.target === outputsModal) closeOutputsModal();
    });

    addClickOnce(settingsClose, "boundClose", closeSettingsModal);
    addClickOnce(settingsModal, "boundBackdrop", (e) => {
      if (e.target === settingsModal) closeSettingsModal();
    });

    addClickOnce(compareClose, "boundClose", closeCompareModal);
    addClickOnce(compareModal, "boundBackdrop", (e) => {
      if (e.target === compareModal) closeCompareModal();
    });
  }

  function setIconButton(buttonElement, iconName, label) {
    buttonElement.classList.add("icon-button");
    buttonElement.setAttribute("aria-label", label);
    buttonElement.setAttribute("title", label);
    buttonElement.innerHTML = icons[iconName] || "";
  }

  // === Toast ===
  function showToast(message) {
    const toast = document.createElement("div");
    toast.style.cssText = "position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:10px 16px;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:9999;";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = "opacity .2s";
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 200);
    }, 1600);
  }

  // === Modal Helpers ===
  function openHistoryModal() {
    if (historyModal) historyModal.setAttribute("aria-hidden", "false");
    loadPromptHistory();
  }
  function closeHistoryModal() {
    if (historyModal) historyModal.setAttribute("aria-hidden", "true");
  }

  function openTemplatesModal() {
    if (templatesModal) templatesModal.setAttribute("aria-hidden", "false");
    if (templatesSearch) templatesSearch.value = _currentTemplateSearch || "";
    loadPromptTemplates();
  }
  function closeTemplatesModal() {
    if (templatesModal) templatesModal.setAttribute("aria-hidden", "true");
  }

  function openOutputsModal() {
    if (outputsModal) outputsModal.setAttribute("aria-hidden", "false");
    loadOutputImages();
  }
  function closeOutputsModal() {
    if (outputsModal) outputsModal.setAttribute("aria-hidden", "true");
  }

  function openSettingsModal() {
    if (settingsModal) settingsModal.setAttribute("aria-hidden", "false");
    loadSettingsIntoUI();
  }
  function closeSettingsModal() {
    if (settingsModal) settingsModal.setAttribute("aria-hidden", "true");
  }

  function closeCompareModal() {
    if (compareModal) compareModal.setAttribute("aria-hidden", "true");
  }

  // === Result Actions ===
  function handleResultAction(event) {
    const buttonEl = event.target.closest("[data-action]");
    if (!buttonEl) return;

    const resultSection = buttonEl.closest(".result");
    if (!resultSection || !resultSection.dataset.result) return;

    let data;
    try {
      data = JSON.parse(resultSection.dataset.result);
    } catch (e) { return; }

    const action = buttonEl.dataset.action;

    if (action === "remix" || action === "remix-new-seed") {
      if (data.model && modelSelect) modelSelect.value = data.model;
      if (promptInput) promptInput.value = data.prompt || "";
      if (widthInput) widthInput.value = data.width ?? 512;
      if (heightInput) heightInput.value = data.height ?? 512;
      if (stepsInput) stepsInput.value = data.steps ?? 9;
      if (filenamePrefixInput) filenamePrefixInput.value = data.filename_prefix || "";

      const seedInput = document.getElementById("seed");
      if (seedInput) {
        seedInput.value = (action === "remix-new-seed")
          ? Math.floor(Math.random() * 4294967295)
          : (data.seed ?? 42);
      }

      const randomCb = document.querySelector('input[name="random_seed"]');
      if (randomCb) randomCb.checked = !!data.random_seed;

      const upscaleCb = document.getElementById("upscale_enabled");
      if (upscaleCb) upscaleCb.checked = !!data.upscale_enabled;

      const upscaleRes = document.getElementById("upscale_resolution");
      if (upscaleRes) upscaleRes.value = data.upscale_resolution || "";

      if (modelSelect) modelSelect.dispatchEvent(new Event("change", { bubbles: true }));
      if (typeof updateUpscalePlaceholder === "function") updateUpscalePlaceholder();
      if (typeof updateAdvancedFieldsVisibility === "function") updateAdvancedFieldsVisibility();

      if (historyModal) historyModal.setAttribute("aria-hidden", "true");
      if (outputsModal) outputsModal.setAttribute("aria-hidden", "true");
      if (promptInput) { promptInput.focus(); promptInput.select(); }

      showToast("Form updated — ready to generate");
    }

    if (action === "copy-prompt") {
      navigator.clipboard.writeText(data.prompt || "").then(() => showToast("Prompt copied"));
    }
    if (action === "copy-seed") {
      const seedStr = String(data.seed ?? "");
      navigator.clipboard.writeText(seedStr).then(() => showToast("Seed copied"));
    }
    if (action === "compare") {
      if (data.image_url && data.upscaled_image_url && typeof openCompareModal === "function") {
        openCompareModal(data.image_url, data.upscaled_image_url, "Original", "Upscaled");
      }
    }
  }
  document.addEventListener("click", handleResultAction);

  // === Gallery Logic (Search + Filters + Multi-select + Bulk Delete + Upscale) ===
  let _allGalleryImages = [];
  let _currentGalleryFilter = "all";
  let _currentGallerySearch = "";
  let _selectedFilenames = new Set();

  // === Templates state ===
  let _allTemplates = [];
  let _currentTemplateSearch = "";

  // Current running job (for cancellation)
  let _currentJobId = null;

  function updateBulkDeleteUI() {
    const bulkBtn = document.getElementById("gallery-bulk-delete");
    const compareBtn = document.getElementById("gallery-compare");

    const count = _selectedFilenames.size;

    // Bulk Delete
    if (bulkBtn) {
      if (count > 0) {
        bulkBtn.textContent = `Delete Selected (${count})`;
        bulkBtn.disabled = false;
      } else {
        bulkBtn.textContent = "Delete Selected";
        bulkBtn.disabled = true;
      }
    }

    // Compare (only when exactly 2 selected)
    if (compareBtn) {
      if (count === 2) {
        compareBtn.disabled = false;
      } else {
        compareBtn.disabled = true;
      }
    }
  }

  function applyGalleryFilters() {
    let filtered = _allGalleryImages;

    if (_currentGalleryFilter === "upscaled") {
      filtered = filtered.filter(img => img.is_upscaled);
    } else if (_currentGalleryFilter !== "all") {
      filtered = filtered.filter(img => (img.prefix || "").toLowerCase() === _currentGalleryFilter);
    }

    const q = _currentGallerySearch.trim().toLowerCase();
    if (q) {
      filtered = filtered.filter(img =>
        img.filename.toLowerCase().includes(q) ||
        (img.prefix || "").toLowerCase().includes(q)
      );
    }

    renderGalleryGrid(filtered);
    const statsEl = document.getElementById("gallery-stats");
    if (statsEl) {
      const totalSize = _allGalleryImages.reduce((sum, i) => sum + (i.size || 0), 0);
      statsEl.textContent = `${filtered.length} / ${_allGalleryImages.length} images • ${(totalSize / (1024*1024)).toFixed(1)} MB`;
    }
    updateBulkDeleteUI();
  }

  function renderGalleryGrid(images) {
    if (!outputsList) return;
    outputsList.textContent = "";

    if (!images.length) {
      const empty = document.createElement("p");
      empty.className = "empty-history";
      empty.textContent = "No images match the current filter.";
      outputsList.appendChild(empty);
      return;
    }

    images.forEach(image => {
      const item = document.createElement("article");
      item.className = "image-item";
      item.dataset.filename = image.filename;

      if (_selectedFilenames.has(image.filename)) item.classList.add("selected");

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "select-checkbox";
      checkbox.checked = _selectedFilenames.has(image.filename);
      checkbox.addEventListener("change", (e) => {
        e.stopImmediatePropagation();
        if (checkbox.checked) _selectedFilenames.add(image.filename);
        else _selectedFilenames.delete(image.filename);
        item.classList.toggle("selected", checkbox.checked);
        updateBulkDeleteUI();
      });
      item.appendChild(checkbox);

      item.addEventListener("click", (e) => {
        if (e.target.closest("button") || e.target.closest("input")) return;
        const selected = !_selectedFilenames.has(image.filename);
        if (selected) _selectedFilenames.add(image.filename);
        else _selectedFilenames.delete(image.filename);
        checkbox.checked = selected;
        item.classList.toggle("selected", selected);
        updateBulkDeleteUI();
      });

      const thumbnail = document.createElement("img");
      thumbnail.src = image.url;
      thumbnail.loading = "lazy";
      item.appendChild(thumbnail);

      const name = document.createElement("p");
      name.className = "image-name";
      name.textContent = image.filename;
      item.appendChild(name);

      const meta = document.createElement("p");
      meta.className = "image-meta";
      meta.textContent = `${image.size_label || ""} ${image.is_upscaled ? "• upscaled" : ""}`;
      item.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "image-actions";

      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      setIconButton(viewBtn, "external", "View");
      viewBtn.addEventListener("click", (e) => { e.stopImmediatePropagation(); window.open(image.url, "_blank"); });

      const upscaleBtn = document.createElement("button");
      upscaleBtn.type = "button";
      setIconButton(upscaleBtn, "upscale", "Upscale image");
      upscaleBtn.addEventListener("click", async (e) => {
        e.stopImmediatePropagation();
        closeOutputsModal();
        createProgressPanel();
        const fd = new FormData();
        fd.append("filename", image.filename);
        const resp = await fetch("/output-images/upscale", { method: "POST", body: fd });
        const data = await resp.json();
        if (resp.ok && data.job_id) {
          connectJobStream(data.job_id);
        }
      });

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "danger";
      setIconButton(delBtn, "trash", "Delete");
      delBtn.addEventListener("click", async (e) => {
        e.stopImmediatePropagation();
        const fd = new FormData();
        fd.append("filename", image.filename);
        await fetch("/output-images/delete", { method: "POST", body: fd });
        _selectedFilenames.delete(image.filename);
        await loadOutputImages(true);
      });

      actions.append(viewBtn, upscaleBtn, delBtn);
      item.appendChild(actions);
      outputsList.appendChild(item);
    });
  }

  async function loadOutputImages(forceReload = false) {
    if (forceReload || !_allGalleryImages.length) {
      const resp = await fetch("/output-images");
      const data = await resp.json();
      _allGalleryImages = data.images || [];
    }
    applyGalleryFilters();
  }

  // === Settings ===
  function applyTheme(theme) {
    const html = document.documentElement;
    if (theme === "light") html.setAttribute("data-theme", "light");
    else if (theme === "dark") html.setAttribute("data-theme", "dark");
    else html.removeAttribute("data-theme");
    localStorage.setItem("imagegen-theme", theme);
  }

  async function loadSettingsIntoUI() {
    try {
      const resp = await fetch("/settings");
      const data = await resp.json();

      document.querySelectorAll(".theme-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.theme === (data.theme || "system"));
        btn.onclick = () => {
          document.querySelectorAll(".theme-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          applyTheme(btn.dataset.theme);
        };
      });

      const modelSel = document.getElementById("default-model");
      if (modelSel) {
        modelSel.innerHTML = "";
        Object.keys(modelDefaults).forEach(m => {
          const opt = document.createElement("option");
          opt.value = m; opt.textContent = m;
          if (m === (data.default_model || "zimage")) opt.selected = true;
          modelSel.appendChild(opt);
        });
      }

      const autoOpen = document.getElementById("auto-open-gallery");
      if (autoOpen) autoOpen.checked = !!data.auto_open_gallery_on_success;
    } catch (e) {}
  }

  async function saveSettingsFromUI() {
    const themeBtn = document.querySelector(".theme-btn.active");
    const theme = themeBtn ? themeBtn.dataset.theme : "system";
    const modelSel = document.getElementById("default-model");
    const defaultModel = modelSel ? modelSel.value : "zimage";
    const autoOpen = document.getElementById("auto-open-gallery");
    const autoOpenVal = autoOpen ? autoOpen.checked : false;

    try {
      const fd = new FormData();
      fd.append("theme", theme);
      fd.append("default_model", defaultModel);
      fd.append("auto_open_gallery_on_success", autoOpenVal ? "1" : "0");
      await fetch("/settings", { method: "POST", body: fd });
    } catch (e) {}

    localStorage.setItem("autoOpenGalleryOnSuccess", autoOpenVal ? "true" : "false");
    applyTheme(theme);
    closeSettingsModal();
  }

  // === Keyboard Shortcuts ===
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (historyModal) historyModal.setAttribute("aria-hidden", "true");
      if (outputsModal) outputsModal.setAttribute("aria-hidden", "true");
      if (settingsModal) settingsModal.setAttribute("aria-hidden", "true");
      if (compareModal) compareModal.setAttribute("aria-hidden", "true");
    }

    const active = document.activeElement;
    const isTyping = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");

    if (!isTyping) {
      const key = event.key.toLowerCase();
      if (key === "g" && promptInput) { event.preventDefault(); promptInput.focus(); promptInput.select(); }
      if (key === "/") { event.preventDefault(); openOutputsModal(); }
      if (key === "h") { event.preventDefault(); openHistoryModal(); }
    }
  });

  // === Core Missing Functions (restored for feature parity) ===

  function createProgressPanel(infoHtml = "") {
    resultSlot.innerHTML = `
      <section class="progress-panel">
        <h2>Progress</h2>
        ${infoHtml ? `<div class="progress-info">${infoHtml}</div>` : ""}
        <div id="progress-result" class="progress-result"></div>
        <p id="progress-status" class="progress-status">Queued...</p>
        <div id="progress-log" class="progress-log" role="log" aria-live="polite"></div>
        <div style="margin-top:12px;">
          <button id="progress-cancel" class="danger" type="button" style="font-size:13px; display:none;">Cancel</button>
        </div>
      </section>
    `;
  }

  function appendProgressLine(message) {
    const log = document.getElementById("progress-log");
    if (!log) return;
    log.textContent += `${message}\n`;
    log.scrollTop = log.scrollHeight;
  }

  function setProgressStatus(message) {
    const status = document.getElementById("progress-status");
    if (status) status.textContent = message;
  }

  function connectJobStream(jobId) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/jobs/${jobId}/stream`);

    socket.addEventListener("message", (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "status") {
        setProgressStatus(data.message || data.status || "Working...");
      } 
      else if (data.type === "log") {
        const phase = data.phase ? `[${data.phase}] ` : "";
        if (data.stream === "command") {
          appendProgressLine(`${phase}command started`);
          return;
        }
        const stream = data.stream ? `${data.stream}: ` : "";
        appendProgressLine(`${phase}${stream}${data.message || ""}`);
      } 
      else if (data.type === "done" || data.type === "error") {
        const target = document.getElementById("progress-result");
        if (target) {
          target.innerHTML = data.result_html || "";
        } else {
          resultSlot.innerHTML = data.result_html || "";
        }
        if (data.status === "cancelled") {
          setProgressStatus("Cancelled.");
        } else {
          setProgressStatus(data.type === "done" ? "Finished." : "Finished with errors.");
        }
        _currentJobId = null;
        const cancelBtn = document.getElementById("progress-cancel");
        if (cancelBtn) cancelBtn.style.display = "none";
        resetGenerateButton();
        socket.close();
      }
    });

    socket.addEventListener("close", () => {
      if (button && button.disabled) {
        appendProgressLine("Progress connection closed.");
        _currentJobId = null;
        const cancelBtn = document.getElementById("progress-cancel");
        if (cancelBtn) cancelBtn.style.display = "none";
        resetGenerateButton();
      }
    });

    socket.addEventListener("error", () => {
      appendProgressLine("Progress connection error.");
      _currentJobId = null;
      const cancelBtn = document.getElementById("progress-cancel");
      if (cancelBtn) cancelBtn.style.display = "none";
      resetGenerateButton();
    });
  }

  function resetGenerateButton() {
    if (button) {
      button.disabled = false;
      button.textContent = "Generate Image";
    }
  }

  function wireProgressCancelButton() {
    const cancelBtn = document.getElementById("progress-cancel");
    if (!cancelBtn || !_currentJobId) return;

    cancelBtn.style.display = ""; // show it
    cancelBtn.disabled = false;
    cancelBtn.textContent = "Cancel";

    // Use onclick to avoid duplicate listeners
    cancelBtn.onclick = async () => {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "Cancelling...";
      try {
        await fetch(`/jobs/${_currentJobId}/cancel`, { method: "POST" });
      } catch (e) {}
    };
  }



  // === Dimension & Model Helpers (restored) ===
  function updateUpscalePlaceholder() {
    if (!widthInput || !heightInput || !upscaleResolutionInput) return;
    const width = Number.parseInt(widthInput.value || "512", 10);
    const height = Number.parseInt(heightInput.value || "512", 10);
    const shortSide = Math.min(
      Number.isFinite(width) ? width : 512,
      Number.isFinite(height) ? height : 512
    );
    upscaleResolutionInput.placeholder = String(shortSide * 2);
  }

  function updateAdvancedFieldsVisibility() {
    if (!modelSelect) return;
    const selectedModel = modelSelect.value;
    document.querySelectorAll(".advanced-field").forEach(field => {
      const models = (field.dataset.forModels || "").split(",").map(s => s.trim());
      const shouldShow = models.length === 0 || models.includes(selectedModel);
      field.style.display = shouldShow ? "" : "none";
    });
  }

  function clampDimension(value) {
    const parsed = Number.parseInt(value || "512", 10);
    if (!Number.isFinite(parsed)) return 512;
    return Math.max(64, Math.min(2048, parsed));
  }

  // === Initial Setup ===
  function setupInitialListeners() {
    if (modelSelect) {
      modelSelect.addEventListener("change", () => {
        const defaults = modelDefaults[modelSelect.value] || modelDefaults.zimage || {};
        if (stepsInput) stepsInput.value = defaults.steps;
        if (filenamePrefixInput) filenamePrefixInput.value = defaults.filenamePrefix;
        if (typeof updateAdvancedFieldsVisibility === "function") updateAdvancedFieldsVisibility();
      });
    }

    if (widthInput) widthInput.addEventListener("input", () => {
      if (typeof updateUpscalePlaceholder === "function") updateUpscalePlaceholder();
    });
    if (heightInput) heightInput.addEventListener("input", () => {
      if (typeof updateUpscalePlaceholder === "function") updateUpscalePlaceholder();
    });

    // Dimension x2 / /2 buttons
    document.querySelectorAll(".dimension-action").forEach(btn => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.dimension === "height" ? heightInput : widthInput;
        if (!target) return;
        const factor = Number.parseFloat(btn.dataset.factor || "1");
        const current = clampDimension(target.value);
        target.value = String(clampDimension(Math.round(current * factor)));
        if (typeof updateUpscalePlaceholder === "function") updateUpscalePlaceholder();
      });
    });

    if (typeof updateUpscalePlaceholder === "function") updateUpscalePlaceholder();
    if (typeof updateAdvancedFieldsVisibility === "function") updateAdvancedFieldsVisibility();

    // Auto-apply saved theme
    const savedTheme = localStorage.getItem("imagegen-theme");
    if (savedTheme) {
      const html = document.documentElement;
      if (savedTheme === "light") html.setAttribute("data-theme", "light");
      else if (savedTheme === "dark") html.setAttribute("data-theme", "dark");
    }
  }

  // === History (interactive) ===
  async function loadPromptHistory() {
    if (!historyList) return;
    try {
      const resp = await fetch("/prompt-history");
      const data = await resp.json();
      historyList.innerHTML = "";

      if (!data.prompts || data.prompts.length === 0) {
        const empty = document.createElement("p");
        empty.className = "empty-history";
        empty.textContent = "No prompts saved yet.";
        historyList.appendChild(empty);
        return;
      }

      data.prompts.forEach(prompt => {
        const item = document.createElement("article");
        item.className = "history-item";

        const text = document.createElement("p");
        text.className = "history-text";
        text.textContent = prompt;

        const actions = document.createElement("div");
        actions.className = "history-actions";

        const useBtn = document.createElement("button");
        useBtn.type = "button";
        setIconButton(useBtn, "check", "Use prompt");
        useBtn.addEventListener("click", () => {
          if (promptInput) {
            promptInput.value = prompt;
            promptInput.focus();
          }
          closeHistoryModal();
        });

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "danger";
        setIconButton(delBtn, "trash", "Delete prompt");
        delBtn.addEventListener("click", async () => {
          delBtn.disabled = true;
          const fd = new FormData();
          fd.append("prompt", prompt);
          await fetch("/prompt-history/delete", { method: "POST", body: fd });
          loadPromptHistory(); // refresh
        });

        actions.append(useBtn, delBtn);
        item.append(text, actions);
        historyList.appendChild(item);
      });
    } catch (e) {
      historyList.innerHTML = '<p class="empty-history">Failed to load history.</p>';
    }
  }

  // === Prompt Templates ===
  async function loadPromptTemplates(forceReload = false) {
    if (!templatesList) return;

    if (forceReload || _allTemplates.length === 0) {
      try {
        const resp = await fetch("/prompt-templates");
        const data = await resp.json();
        _allTemplates = data.templates || [];
      } catch (e) {
        _allTemplates = [];
      }
    }

    applyTemplateFilters();
  }

  function applyTemplateFilters() {
    if (!templatesList) return;

    const q = (_currentTemplateSearch || "").trim().toLowerCase();

    let filtered = _allTemplates;
    if (q) {
      filtered = _allTemplates.filter(t =>
        (t.name || "").toLowerCase().includes(q) ||
        (t.prompt || "").toLowerCase().includes(q)
      );
    }

    templatesList.innerHTML = "";

    if (!filtered.length) {
      const empty = document.createElement("p");
      empty.className = "empty-history";
      empty.textContent = q
        ? "No templates match your search."
        : "No templates saved yet. Use the button above to save current settings.";
      templatesList.appendChild(empty);
      return;
    }

    filtered.forEach(tpl => {
      const item = document.createElement("article");
      item.className = "history-item";

      const text = document.createElement("div");
      text.className = "history-text";
      text.innerHTML = `<strong>${tpl.name}</strong><br><small style="color:var(--muted)">${(tpl.model || "")} • ${tpl.width}×${tpl.height}</small>`;

      const actions = document.createElement("div");
      actions.className = "history-actions";

      const useBtn = document.createElement("button");
      useBtn.type = "button";
      setIconButton(useBtn, "check", "Use template");
      useBtn.addEventListener("click", () => {
        applyTemplateToForm(tpl);
        closeTemplatesModal();
      });

      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      setIconButton(renameBtn, "rename", "Rename template");
      renameBtn.addEventListener("click", () => {
        // Inline rename mode
        item.innerHTML = "";

        const input = document.createElement("input");
        input.type = "text";
        input.value = tpl.name;
        input.style.flex = "1";
        input.style.marginRight = "8px";

        const saveBtn = document.createElement("button");
        saveBtn.textContent = "Save";
        saveBtn.style.width = "100px";
        saveBtn.style.fontSize = "12px";
        saveBtn.style.marginRight = "8px";
        saveBtn.style.marginTop = "-2px";

        const cancelBtn = document.createElement("button");
        cancelBtn.textContent = "Cancel";
        cancelBtn.style.width = "100px";
        cancelBtn.style.fontSize = "12px";
        cancelBtn.style.marginTop = "-2px";

        const editRow = document.createElement("div");
        editRow.style.display = "flex";
        editRow.style.alignItems = "center";
        editRow.style.width = "100%";
        editRow.append(input, saveBtn, cancelBtn);

        item.appendChild(editRow);

        const doRename = async () => {
          const newName = input.value.trim();
          if (!newName || newName === tpl.name) {
            loadPromptTemplates(true);
            return;
          }

          saveBtn.disabled = true;
          const fd = new FormData();
          fd.append("old_name", tpl.name);
          fd.append("new_name", newName);
          await fetch("/prompt-templates/rename", { method: "POST", body: fd });
          loadPromptTemplates(true);
        };

        saveBtn.addEventListener("click", doRename);
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") doRename();
          if (e.key === "Escape") loadPromptTemplates(true);
        });

        cancelBtn.addEventListener("click", () => loadPromptTemplates(true));
        input.focus();
        input.select();
      });

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "danger";
      setIconButton(delBtn, "trash", "Delete template");
      delBtn.addEventListener("click", async () => {
        delBtn.disabled = true;
        const fd = new FormData();
        fd.append("name", tpl.name);
        await fetch("/prompt-templates/delete", { method: "POST", body: fd });
        loadPromptTemplates(true);
      });

      actions.append(useBtn, renameBtn, delBtn);
      item.append(text, actions);
      templatesList.appendChild(item);
    });
  }

  function setupTemplatesSearch() {
    if (!templatesSearch) return;

    templatesSearch.addEventListener("input", () => {
      _currentTemplateSearch = templatesSearch.value;
      applyTemplateFilters();
    });
  }

  function applyTemplateToForm(tpl) {
    if (!tpl) return;

    if (modelSelect) modelSelect.value = tpl.model || modelSelect.value;
    if (promptInput) promptInput.value = tpl.prompt || "";
    if (widthInput) widthInput.value = tpl.width || 512;
    if (heightInput) heightInput.value = tpl.height || 512;
    if (stepsInput) stepsInput.value = tpl.steps || 9;

    const seedInput = document.getElementById("seed");
    if (seedInput) seedInput.value = tpl.seed ?? 42;

    const randomCb = document.querySelector('input[name="random_seed"]');
    if (randomCb) randomCb.checked = !!tpl.random_seed;

    const guidance = document.getElementById("guidance");
    if (guidance) guidance.value = tpl.guidance || "";

    const lora = document.getElementById("lora_scale");
    if (lora) lora.value = tpl.lora_scale || "";

    const neg = document.getElementById("negative_prompt");
    if (neg) neg.value = tpl.negative_prompt || "";

    const upscaleCb = document.getElementById("upscale_enabled");
    if (upscaleCb) upscaleCb.checked = !!tpl.upscale_enabled;

    const upscaleRes = document.getElementById("upscale_resolution");
    if (upscaleRes) upscaleRes.value = tpl.upscale_resolution || "";

    const prefix = document.getElementById("filename_prefix");
    if (prefix) prefix.value = tpl.filename_prefix || "";

    if (modelSelect) modelSelect.dispatchEvent(new Event("change", { bubbles: true }));
    if (typeof updateUpscalePlaceholder === "function") updateUpscalePlaceholder();
    if (typeof updateAdvancedFieldsVisibility === "function") updateAdvancedFieldsVisibility();

    showToast("Template loaded");
  }

  async function saveCurrentAsTemplate() {
    const name = prompt("Template name:");
    if (!name || !name.trim()) return;

    const fd = new FormData();
    fd.append("name", name.trim());
    fd.append("prompt", promptInput ? promptInput.value : "");
    fd.append("model", modelSelect ? modelSelect.value : "");
    fd.append("width", widthInput ? widthInput.value : "");
    fd.append("height", heightInput ? heightInput.value : "");
    fd.append("steps", stepsInput ? stepsInput.value : "");
    fd.append("seed", document.getElementById("seed")?.value || "");
    fd.append("random_seed", document.querySelector('input[name="random_seed"]')?.checked ? "1" : "0");
    fd.append("guidance", document.getElementById("guidance")?.value || "");
    fd.append("lora_scale", document.getElementById("lora_scale")?.value || "");
    fd.append("negative_prompt", document.getElementById("negative_prompt")?.value || "");
    fd.append("upscale_enabled", document.getElementById("upscale_enabled")?.checked ? "1" : "0");
    fd.append("upscale_resolution", document.getElementById("upscale_resolution")?.value || "");
    fd.append("filename_prefix", document.getElementById("filename_prefix")?.value || "");

    try {
      await fetch("/prompt-templates", { method: "POST", body: fd });
      showToast("Template saved");

      // Force refresh so the new template appears without needing to reopen the modal
      _currentTemplateSearch = "";
      if (templatesSearch) templatesSearch.value = "";

      if (templatesModal && templatesModal.getAttribute("aria-hidden") === "false") {
        loadPromptTemplates(true);   // force refetch
      }
    } catch (e) {
      alert("Failed to save template");
    }
  }

  // === Settings (improved) ===
  async function loadSettingsIntoUI() {
    try {
      const resp = await fetch("/settings");
      const data = await resp.json();

      document.querySelectorAll(".theme-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.theme === (data.theme || "system"));
        btn.onclick = () => {
          document.querySelectorAll(".theme-btn").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          const html = document.documentElement;
          const t = btn.dataset.theme;
          if (t === "light") html.setAttribute("data-theme", "light");
          else if (t === "dark") html.setAttribute("data-theme", "dark");
          else html.removeAttribute("data-theme");
          localStorage.setItem("imagegen-theme", t);
        };
      });

      const modelSel = document.getElementById("default-model");
      if (modelSel) {
        modelSel.innerHTML = "";
        Object.keys(modelDefaults).forEach(m => {
          const opt = document.createElement("option");
          opt.value = m;
          opt.textContent = m;
          if (m === (data.default_model || "zimage")) opt.selected = true;
          modelSel.appendChild(opt);
        });
      }

      const autoOpen = document.getElementById("auto-open-gallery");
      if (autoOpen) autoOpen.checked = !!data.auto_open_gallery_on_success;
    } catch (e) {}
  }

  // === Compare with draggable slider ===
  let _compareDragging = false;

  function openCompareModal(urlA, urlB, labelA = "Original", labelB = "Upscaled") {
    if (!compareModal || !urlA || !urlB) return;
    compareImageA.src = urlA;
    compareImageB.src = urlB;
    compareLabelA.textContent = labelA;
    compareLabelB.textContent = labelB;
    compareModal.setAttribute("aria-hidden", "false");

    // Reset slider position
    if (compareImageBWrapper) {
      compareImageBWrapper.style.width = "100%";
      compareImageBWrapper.style.clipPath = "inset(0 50% 0 0)";
    }
    if (compareHandle) compareHandle.style.left = "50%";

    initCompareSlider();
  }

  function initCompareSlider() {
    if (!compareSliderContainer || !compareHandle) return;

    const updateSlider = (clientX) => {
      const rect = compareSliderContainer.getBoundingClientRect();
      let percent = ((clientX - rect.left) / rect.width) * 100;
      percent = Math.max(5, Math.min(95, percent));
      if (compareImageBWrapper) {
        compareImageBWrapper.style.width = "100%";
        compareImageBWrapper.style.clipPath = `inset(0 ${100 - percent}% 0 0)`;
      }
      if (compareHandle) compareHandle.style.left = `${percent}%`;
    };

    const onMouseMove = (e) => {
      if (!_compareDragging) return;
      updateSlider(e.clientX);
    };

    const onMouseUp = () => {
      _compareDragging = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    const startDrag = (e) => {
      _compareDragging = true;
      updateSlider(e.clientX);
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    };

    // Mouse drag
    compareHandle.addEventListener("mousedown", startDrag);
    compareSliderContainer.addEventListener("click", (e) => {
      updateSlider(e.clientX);
    });

    // Touch support
    compareHandle.addEventListener("touchstart", (e) => {
      _compareDragging = true;
      updateSlider(e.touches[0].clientX);
    });

    document.addEventListener("touchend", () => {
      _compareDragging = false;
    });

    document.addEventListener("touchmove", (e) => {
      if (!_compareDragging) return;
      updateSlider(e.touches[0].clientX);
    });
  }

  function bindCompareControls() {
    addClickOnce(compareSwap, "boundCompareSwap", () => {
      if (!compareImageA || !compareImageB) return;
      const tempSrc = compareImageA.src;
      compareImageA.src = compareImageB.src;
      compareImageB.src = tempSrc;

      const tempLabel = compareLabelA.textContent;
      compareLabelA.textContent = compareLabelB.textContent;
      compareLabelB.textContent = tempLabel;
    });

    addClickOnce(compareReset, "boundCompareReset", () => {
      if (compareImageBWrapper) {
        compareImageBWrapper.style.width = "100%";
        compareImageBWrapper.style.clipPath = "inset(0 50% 0 0)";
      }
      if (compareHandle) compareHandle.style.left = "50%";
    });
  }

  // === Main Initialization ===
  function initApp() {
    // DOM references already initialized early at the top of the IIFE.
    // Re-query anyway in case of any dynamic content (harmless).
    initDOMReferences();
    bindModalControls();
    bindCompareControls();

    // === Form submit (moved here for maximum reliability across browsers) ===
    if (form) {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (typeof renderFormErrors === "function") renderFormErrors([]);
        if (button) {
          button.disabled = true;
          button.textContent = "Generating...";
        }

        const modelName = modelSelect ? modelSelect.value : "";
        const w = widthInput ? widthInput.value : "";
        const h = heightInput ? heightInput.value : "";
        const info = modelName ? `<strong>${modelName}</strong> — ${w}×${h}` : "";
        if (typeof createProgressPanel === "function") createProgressPanel(info);

        const response = await fetch("/generate", {
          method: "POST",
          body: new FormData(form),
        });
        const data = await response.json();
        if (!response.ok || data.errors) {
          if (typeof renderFormErrors === "function") renderFormErrors(data.errors || ["Generation could not start."]);
          resultSlot.innerHTML = `<section class="result"><h2>Result</h2><p class="meta">Generated images will appear here after the command finishes.</p></section>`;
          resetGenerateButton();
          return;
        }

        _currentJobId = data.job_id;
      if (typeof wireProgressCancelButton === "function") {
        wireProgressCancelButton();
      }
      if (typeof connectJobStream === "function") connectJobStream(data.job_id);
      });
    }

    // Full initial listeners (dimensions x2/2, model change, etc.)
    if (typeof setupInitialListeners === "function") {
      setupInitialListeners();
    }

    // Gallery filter setup (runs when gallery modal is opened)
    const setupGallery = () => {
      const search = document.getElementById("gallery-search");
      if (search) search.addEventListener("input", () => { _currentGallerySearch = search.value; applyGalleryFilters(); });
      document.querySelectorAll(".gallery-filter").forEach(btn => {
        btn.addEventListener("click", () => {
          _currentGalleryFilter = btn.dataset.filter;
          document.querySelectorAll(".gallery-filter").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          applyGalleryFilters();
        });
      });

      // Wire Refresh button (static in modal)
      const refreshBtn = document.getElementById("gallery-refresh");
      if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
          if (typeof loadOutputImages === "function") loadOutputImages(true);
        });
      }

      // Basic bulk delete wiring (if the button exists)
      const bulkBtn = document.getElementById("gallery-bulk-delete");
      if (bulkBtn) {
        bulkBtn.addEventListener("click", async () => {
          if (_selectedFilenames.size === 0) return;
          if (!confirm(`Delete ${_selectedFilenames.size} selected image(s)?`)) return;

          bulkBtn.disabled = true;
          for (const fname of Array.from(_selectedFilenames)) {
            try {
              const fd = new FormData();
              fd.append("filename", fname);
              await fetch("/output-images/delete", { method: "POST", body: fd });
              _selectedFilenames.delete(fname);
            } catch (e) {}
          }
          if (typeof loadOutputImages === "function") loadOutputImages(true);
          bulkBtn.disabled = false;
        });
      }

      // Compare two selected images (uses the existing draggable compare modal)
      const compareBtn = document.getElementById("gallery-compare");
      if (compareBtn) {
        compareBtn.addEventListener("click", () => {
          if (_selectedFilenames.size !== 2) return;

          const selected = Array.from(_selectedFilenames);
          const imgs = selected
            .map(fname => _allGalleryImages.find(i => i.filename === fname))
            .filter(Boolean);

          if (imgs.length === 2) {
            // Sort by filename for consistent left/right order
            const [a, b] = imgs.sort((x, y) => x.filename.localeCompare(y.filename));
            openCompareModal(a.url, b.url, a.filename, b.filename);
            // Clear selection after opening compare (optional but clean)
            //_selectedFilenames.clear();
            updateBulkDeleteUI();
          }
        });
      }
    };

    if (outputsButton) {
      outputsButton.addEventListener("click", () => setTimeout(setupGallery, 60));
    }

    if (settingsSave) settingsSave.addEventListener("click", saveSettingsFromUI);

    if (saveTemplateBtn) {
      saveTemplateBtn.addEventListener("click", saveCurrentAsTemplate);
    }

    // Setup search for templates when opening the modal
    if (templatesButton) {
      templatesButton.addEventListener("click", () => {
        setTimeout(() => {
          if (typeof setupTemplatesSearch === "function") {
            setupTemplatesSearch();
          }
        }, 50);
      });
    }

    // Initial theme
    const savedTheme = localStorage.getItem("imagegen-theme");
    if (savedTheme) applyTheme(savedTheme);

    console.log("MFLUX Image Generator - Phase B extracted JS loaded");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }

})();
