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
      referenceImagePanel, referenceImagePreview, referenceImageName, referenceImageStatus,
      referenceImageUpload, referenceImageUploadButton, referenceImagePath, referenceImagePathButton,
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

    referenceImagePanel = document.getElementById("reference-image-panel");
    referenceImagePreview = document.getElementById("reference-image-preview");
    referenceImageName = document.getElementById("reference-image-name");
    referenceImageStatus = document.getElementById("reference-image-status");
    referenceImageUpload = document.getElementById("reference-image-upload");
    referenceImageUploadButton = document.getElementById("reference-image-upload-button");
    referenceImagePath = document.getElementById("reference-image-path");
    referenceImagePathButton = document.getElementById("reference-image-path-button");

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

  function canRemixFromMetadata(metadata) {
    if (!metadata || typeof metadata !== "object") return false;
    const size = metadata.size || {};
    const width = metadata.width ?? size.width;
    const height = metadata.height ?? size.height;
    return !!metadata.prompt && !!metadata.model && metadata.seed != null && metadata.steps != null && width != null && height != null;
  }

  function remixDataFromMetadata(image) {
    const metadata = image.metadata || {};
    const size = metadata.size || {};
    const upscale = metadata.upscale || {};
    return {
      model: metadata.model || "",
      prompt: metadata.prompt || "",
      width: metadata.width ?? size.width,
      height: metadata.height ?? size.height,
      steps: metadata.steps,
      seed: metadata.seed,
      random_seed: !!metadata.random_seed,
      filename_prefix: metadata.filename_prefix || image.prefix || "",
      upscale_enabled: !!(metadata.upscale_enabled || upscale.enabled),
      upscale_resolution: metadata.upscale_resolution || upscale.resolution || "",
      guidance: metadata.guidance ?? "",
      lora_scale: metadata.lora_scale ?? "",
      negative_prompt: metadata.negative_prompt || "",
      image_url: image.url || metadata.image_url || "",
    };
  }

  function hydrateGeneratorForm(data, useNewSeed = false) {
    if (data.model && modelSelect) modelSelect.value = data.model;
    if (promptInput) promptInput.value = data.prompt || "";
    if (widthInput) widthInput.value = data.width ?? 512;
    if (heightInput) heightInput.value = data.height ?? 512;
    if (stepsInput) stepsInput.value = data.steps ?? 9;
    if (filenamePrefixInput) filenamePrefixInput.value = data.filename_prefix || "";

    const seedInput = document.getElementById("seed");
    if (seedInput) {
      seedInput.value = useNewSeed
        ? Math.floor(Math.random() * 4294967295)
        : (data.seed ?? 42);
    }

    const randomCb = document.querySelector('input[name="random_seed"]');
    if (randomCb) randomCb.checked = !!data.random_seed;

    const upscaleCb = document.getElementById("upscale_enabled");
    if (upscaleCb) upscaleCb.checked = !!data.upscale_enabled;

    const upscaleRes = document.getElementById("upscale_resolution");
    if (upscaleRes) upscaleRes.value = data.upscale_resolution || "";

    const guidance = document.getElementById("guidance");
    if (guidance) guidance.value = data.guidance ?? "";

    const lora = document.getElementById("lora_scale");
    if (lora) lora.value = data.lora_scale ?? "";

    const negativePrompt = document.getElementById("negative_prompt");
    if (negativePrompt) negativePrompt.value = data.negative_prompt || "";

    if (modelSelect) modelSelect.dispatchEvent(new Event("change", { bubbles: true }));
    if (typeof updateUpscalePlaceholder === "function") updateUpscalePlaceholder();
    if (typeof updateAdvancedFieldsVisibility === "function") updateAdvancedFieldsVisibility();

    if (historyModal) historyModal.setAttribute("aria-hidden", "true");
    if (outputsModal) outputsModal.setAttribute("aria-hidden", "true");
    if (promptInput) { promptInput.focus(); promptInput.select(); }

    showToast("Form updated - ready to generate");
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

  // === Form error display (was missing — called on async submit errors) ===
  function renderFormErrors(errors) {
    if (!formErrors) return;
    formErrors.innerHTML = "";
    if (!errors || !errors.length) return;
    const div = document.createElement("div");
    div.className = "alert error";
    const strong = document.createElement("strong");
    strong.textContent = "Fix these fields:";
    div.appendChild(strong);
    const ul = document.createElement("ul");
    for (const err of errors) {
      const li = document.createElement("li");
      li.textContent = err;
      ul.appendChild(li);
    }
    div.appendChild(ul);
    formErrors.appendChild(div);
  }

  function setReferenceStatus(message, isError = false) {
    if (!referenceImageStatus) return;
    referenceImageStatus.textContent = message || "";
    referenceImageStatus.style.color = isError ? "var(--error-text)" : "";
  }

  function renderReferenceImage(reference) {
    if (!reference) {
      if (referenceImageName) referenceImageName.textContent = "No active reference";
      if (referenceImagePreview) referenceImagePreview.removeAttribute("src");
      return;
    }

    if (referenceImageName) referenceImageName.textContent = reference.display_name || reference.path || "Active reference";
    if (referenceImagePath) referenceImagePath.value = reference.path || "";
    if (referenceImagePreview) {
      const separator = (reference.preview_url || "").includes("?") ? "&" : "?";
      referenceImagePreview.src = `${reference.preview_url || "/reference-image/preview"}${separator}t=${Date.now()}`;
    }
  }

  function updateReferencePanelVisibility() {
    if (!referenceImagePanel || !modelSelect) return;
    const shouldShow = modelSelect.value === "flux2-9B-face";
    referenceImagePanel.hidden = !shouldShow;
    referenceImagePanel.classList.toggle("hidden", !shouldShow);
    if (shouldShow) loadActiveReferenceImage();
  }

  async function loadActiveReferenceImage() {
    if (!referenceImagePanel) return;
    try {
      setReferenceStatus("Loading reference...");
      const resp = await fetch("/reference-image");
      const data = await resp.json();
      if (!resp.ok || data.error) {
        renderReferenceImage(null);
        setReferenceStatus(data.error || "Reference image could not be loaded.", true);
        return;
      }
      renderReferenceImage(data.reference);
      setReferenceStatus("Active reference is ready.");
    } catch (e) {
      renderReferenceImage(null);
      setReferenceStatus("Reference image could not be loaded.", true);
    }
  }

  async function submitReferencePath() {
    if (!referenceImagePath || !referenceImagePathButton) return;
    const rawPath = referenceImagePath.value.trim();
    if (!rawPath) {
      renderFormErrors(["Reference image path is required."]);
      setReferenceStatus("Reference image path is required.", true);
      return;
    }

    referenceImagePathButton.disabled = true;
    setReferenceStatus("Saving reference path...");
    try {
      const fd = new FormData();
      fd.append("path", rawPath);
      const resp = await fetch("/reference-image/path", { method: "POST", body: fd });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        const message = data.error || "Reference image path could not be saved.";
        renderFormErrors([message]);
        setReferenceStatus(message, true);
        return;
      }
      renderFormErrors([]);
      renderReferenceImage(data.reference);
      setReferenceStatus("Reference path saved.");
      showToast("Reference image updated");
    } catch (e) {
      renderFormErrors(["Reference image path could not be saved."]);
      setReferenceStatus("Reference image path could not be saved.", true);
    } finally {
      referenceImagePathButton.disabled = false;
    }
  }

  async function uploadReferenceImage() {
    if (!referenceImageUpload || !referenceImageUploadButton) return;
    const file = referenceImageUpload.files && referenceImageUpload.files[0];
    if (!file) {
      renderFormErrors(["Choose a reference image to upload."]);
      setReferenceStatus("Choose a reference image to upload.", true);
      return;
    }

    referenceImageUploadButton.disabled = true;
    setReferenceStatus("Uploading reference image...");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const resp = await fetch("/reference-image/upload", { method: "POST", body: fd });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        const message = data.error || "Reference image could not be uploaded.";
        renderFormErrors([message]);
        setReferenceStatus(message, true);
        return;
      }
      renderFormErrors([]);
      renderReferenceImage(data.reference);
      referenceImageUpload.value = "";
      setReferenceStatus("Uploaded reference is active.");
      showToast("Reference image uploaded");
    } catch (e) {
      renderFormErrors(["Reference image could not be uploaded."]);
      setReferenceStatus("Reference image could not be uploaded.", true);
    } finally {
      referenceImageUploadButton.disabled = false;
    }
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

    // Look for the container that carries the result data (more robust than relying on .result class)
    const resultSection = buttonEl.closest("[data-result]");
    if (!resultSection) return;

    let data;
    try {
      data = JSON.parse(resultSection.dataset.result);
    } catch (e) { return; }

    const action = buttonEl.dataset.action;

    if (action === "remix" || action === "remix-new-seed") {
      hydrateGeneratorForm(data, action === "remix-new-seed");
    }

    if (action === "copy-prompt") {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(data.prompt).then(() => showToast("Prompt copied"));
      } else {
        const ta = document.createElement("textarea");
        ta.value = data.prompt;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        showToast("Prompt copied");
      }
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
      item.className = "image-item group bg-white dark:bg-[#1a201f] border border-[#d9dedb] dark:border-[#33413d] rounded-2xl transition-all hover:shadow-md hover:border-[#0f766e]/40 dark:hover:border-[#2dd4bf]/40";
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
      thumbnail.className = "w-full aspect-[4/3] object-cover bg-[#f7f7f4] dark:bg-[#111514] group-hover:scale-[1.02] transition-transform duration-200";
      item.appendChild(thumbnail);

      const name = document.createElement("p");
      name.className = "image-name px-3 pt-2.5 text-[13px] font-medium truncate";
      name.textContent = image.filename;
      item.appendChild(name);

      const meta = document.createElement("p");
      meta.className = "image-meta px-3 pb-2 text-xs text-[#626b73] dark:text-[#a7b1ad]";
      meta.textContent = `${image.size_label || ""} ${image.is_upscaled ? "• upscaled" : ""}`;
      item.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "image-actions flex flex-wrap gap-1.5 px-2.5 pb-2.5";

      const remixable = canRemixFromMetadata(image.metadata);

      const remixBtn = document.createElement("button");
      remixBtn.type = "button";
      remixBtn.className = "flex-1 h-8 rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514] text-xs flex items-center justify-center gap-1";
      setIconButton(remixBtn, "remix", "Remix from stored metadata");
      remixBtn.addEventListener("click", (e) => {
        e.stopImmediatePropagation();
        hydrateGeneratorForm(remixDataFromMetadata(image), false);
      });

      const remixNewSeedBtn = document.createElement("button");
      remixNewSeedBtn.type = "button";
      remixNewSeedBtn.className = "flex-1 h-8 rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514] text-xs flex items-center justify-center gap-1";
      setIconButton(remixNewSeedBtn, "new_seed", "Remix from stored metadata with a new seed");
      remixNewSeedBtn.addEventListener("click", (e) => {
        e.stopImmediatePropagation();
        hydrateGeneratorForm(remixDataFromMetadata(image), true);
      });

      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "flex-1 h-8 rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514] text-xs flex items-center justify-center gap-1";
      setIconButton(viewBtn, "external", "View");
      viewBtn.addEventListener("click", (e) => { e.stopImmediatePropagation(); window.open(image.url, "_blank"); });

      const upscaleBtn = document.createElement("button");
      upscaleBtn.type = "button";
      upscaleBtn.className = "flex-1 h-8 rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514] text-xs flex items-center justify-center gap-1";
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
      delBtn.className = "flex-1 h-8 rounded-xl border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 text-xs flex items-center justify-center gap-1";
      setIconButton(delBtn, "trash", "Delete");
      delBtn.addEventListener("click", async (e) => {
        e.stopImmediatePropagation();
        const fd = new FormData();
        fd.append("filename", image.filename);
        await fetch("/output-images/delete", { method: "POST", body: fd });
        _selectedFilenames.delete(image.filename);
        await loadOutputImages(true);
      });

      if (remixable) actions.append(remixBtn, remixNewSeedBtn);
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
    // Support both the legacy data-theme system (for old CSS vars) and
    // the `dark` class that Tailwind's dark: variants expect.
    const prefersDark = !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const effectiveDark = theme === "dark" || (theme === "system" && prefersDark);

    if (effectiveDark) {
      html.setAttribute("data-theme", "dark");
      html.classList.add("dark");
    } else {
      html.setAttribute("data-theme", "light");
      html.classList.remove("dark");
    }

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

      // Wire the previously dormant setting (Phase C renewal)
      const adv = document.querySelector("details.advanced-section");
      if (adv) {
        if (data.show_advanced_by_default) {
          adv.setAttribute("open", "");
        } else {
          adv.removeAttribute("open");
        }
      }
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
    // Renewed Tailwind progress panel (matches new form aesthetic + good dark mode)
    resultSlot.innerHTML = `
      <section class="bg-white dark:bg-[#1a201f] border border-[#d9dedb] dark:border-[#33413d] rounded-2xl p-6 shadow-sm">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-xl font-semibold tracking-tight">Generating</h2>
          ${infoHtml ? `<div class="text-sm px-3 py-1 rounded-full bg-[#f7f7f4] dark:bg-[#111514] text-[#626b73] dark:text-[#a7b1ad]">${infoHtml}</div>` : ""}
        </div>

        <div id="progress-result" class="progress-result mb-4"></div>

        <div class="flex items-center gap-3 mb-3">
          <div class="w-2 h-2 rounded-full bg-[#0f766e] animate-pulse"></div>
          <p id="progress-status" class="progress-status text-base font-medium text-[#1e2428] dark:text-[#edf3f1]">Queued...</p>
        </div>

        <div id="progress-log"
             class="progress-log h-72 overflow-auto rounded-2xl border border-[#d9dedb] dark:border-[#33413d] bg-[#f7f7f4] dark:bg-[#111514] p-4 font-mono text-sm leading-relaxed text-[#1e2428] dark:text-[#c3c9c6]"
             role="log" aria-live="polite"></div>

        <div class="mt-4 flex justify-end">
          <button id="progress-cancel"
                  class="px-5 py-2 rounded-2xl border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 text-sm font-semibold transition-colors"
                  type="button" style="display:none;">
            Cancel generation
          </button>
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
        if (typeof updateReferencePanelVisibility === "function") updateReferencePanelVisibility();
      });
    }

    if (referenceImageUploadButton) {
      referenceImageUploadButton.addEventListener("click", uploadReferenceImage);
    }
    if (referenceImagePathButton) {
      referenceImagePathButton.addEventListener("click", submitReferencePath);
    }
    if (referenceImagePath) {
      referenceImagePath.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          submitReferencePath();
        }
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
    if (typeof updateReferencePanelVisibility === "function") updateReferencePanelVisibility();

    // Auto-apply saved theme (now also handles Tailwind dark class)
    const savedTheme = localStorage.getItem("imagegen-theme");
    if (savedTheme && typeof applyTheme === "function") {
      applyTheme(savedTheme);
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

  // (duplicate loadSettingsIntoUI removed during renewal — canonical version lives above)

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

    // Apply advanced-section default state on boot (fixes previously dormant setting)
    if (typeof loadSettingsIntoUI === "function") {
      loadSettingsIntoUI(); // fire-and-forget; it will set the <details open> if needed
    }

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

    // Initial theme (also handles "system" → correct Tailwind dark class on first load)
    const savedTheme = localStorage.getItem("imagegen-theme");
    if (savedTheme) {
      applyTheme(savedTheme);
    } else {
      applyTheme("system");
    }

    // Keep Tailwind + legacy theme in sync when OS preference changes and user chose "system"
    if (window.matchMedia) {
      const media = window.matchMedia("(prefers-color-scheme: dark)");
      media.addEventListener?.("change", () => {
        const current = localStorage.getItem("imagegen-theme");
        if (current === "system" && typeof applyTheme === "function") {
          applyTheme("system");
        }
      });
    }

    console.log("MFLUX Image Generator - Phase B extracted JS loaded");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }

})();
