document.addEventListener("DOMContentLoaded", () => {
  const stateLoading = document.getElementById("state-loading");
  const stateLogin = document.getElementById("state-login");
  const stateUser = document.getElementById("state-user");
  const btnLogin = document.getElementById("btn-login");
  const userEmail = document.getElementById("user-email");
  const userPlan = document.getElementById("user-plan");
  const userExpires = document.getElementById("user-expires");
  const userCardBanner = document.getElementById("user-card-banner");

  const freeUpgradeBlock = document.getElementById("free-upgrade-block");
  const proSupportBlock = document.getElementById("pro-support-block");
  const freeProgressBlock = document.getElementById("free-progress-block");
  const freeGenerationsLabel = document.getElementById("free-generations-label");
  const freeGenerationsText = document.getElementById("free-generations-text");
  const freeProgressFill = document.getElementById("free-progress-fill");

  const toggleReplies = document.getElementById("toggle-replies");
  const toggleShorten = document.getElementById("toggle-shorten");
  const toggleTranslate = document.getElementById("toggle-translate");

  const selTranslate = document.getElementById("sel-translate");
  const shortenTriggerLengthInput = document.getElementById("inp-shorten-trigger-length");
  const selDash = document.getElementById("sel-dash");
  const selLength = document.getElementById("sel-length");
  const selEmoji = document.getElementById("sel-emoji");
  const selCaps = document.getElementById("sel-caps");
  const selPunct = document.getElementById("sel-punct");
  const variantCountPills = document.querySelectorAll(".variant-count-pill");
  const commentSettingsOpen = document.getElementById("comment-settings-open");
  const shortenerSettingsOpen = document.getElementById("shortener-settings-open");
  const commentSettingsBack = document.getElementById("comment-settings-back");
  const shortenerSettingsBack = document.getElementById("shortener-settings-back");
  const pageMain = document.getElementById("page-main");
  const pageCommentSettings = document.getElementById("page-comment-settings");
  const pageShortenerSettings = document.getElementById("page-shortener-settings");
  const pillsStylesContainer = document.getElementById("pills-styles");
  const addStyleLink = pillsStylesContainer ? pillsStylesContainer.querySelector(".style-pill-add") : null;
  const settingsStatusEls = document.querySelectorAll("#settings-status, .settings-status-panel");

  let saveTimeout = null;
  let currentVariantCount = 3;
  let activeSubpage = null;
  let refreshInFlight = null;
  const DEFAULT_SHORTEN_TRIGGER_LENGTH = 200;

  function normalizeShortenTriggerLength(value) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) return DEFAULT_SHORTEN_TRIGGER_LENGTH;
    return Math.max(1, Math.min(10000, parsed));
  }

  function getStyleButtons() {
    return pillsStylesContainer ? Array.from(pillsStylesContainer.querySelectorAll(".style-pill")) : [];
  }

  function renderCustomStylePills(customStyles = []) {
    if (!pillsStylesContainer || !addStyleLink) return;

    pillsStylesContainer.querySelectorAll(".style-pill-custom").forEach((node) => node.remove());

    customStyles.forEach((style) => {
      if (!style || !style.id || !style.label) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "style-pill style-pill-custom";
      button.dataset.val = style.id;
      button.title = style.label;
      button.textContent = style.label;
      pillsStylesContainer.insertBefore(button, addStyleLink);
    });
  }

  function showState(name) {
    stateLoading.style.display = name === "loading" ? "" : "none";
    stateLogin.style.display = name === "login" ? "" : "none";
    stateUser.style.display = name === "user" ? "" : "none";
  }

  function setSettingsStatus(message, visible = true) {
    settingsStatusEls.forEach((node) => {
      if (!node) return;
      node.textContent = message;
      node.classList.toggle("show", visible);
    });
  }

  function openSettingsPage(targetPage) {
    if (!pageMain || !targetPage) return;
    [pageCommentSettings, pageShortenerSettings].forEach((page) => {
      if (page && page !== targetPage) page.classList.remove("is-active");
    });
    pageMain.classList.add("is-leaving-left");
    pageMain.classList.remove("is-active");
    targetPage.classList.add("is-active");
    activeSubpage = targetPage;
  }

  function closeSettingsPage() {
    if (!pageMain || !activeSubpage) return;
    activeSubpage.classList.remove("is-active");
    pageMain.classList.add("is-active");
    pageMain.classList.remove("is-leaving-left");
    activeSubpage = null;
  }

  function renderUser(user) {
    userEmail.textContent = user.email || "—";

    const plan = (user.plan || "free").toLowerCase();
    userPlan.textContent = user.plan_label || "Free";
    userPlan.className = "plan-badge";

    if (plan === "pro") userPlan.classList.add("pro");
    else if (plan === "supporter") userPlan.classList.add("supporter");

    let bgUrl = "../images/svinka2.png";
    if (plan === "supporter" || plan === "free") bgUrl = "../images/svinka-supporter-banner.png";
    else if (plan === "pro") bgUrl = "../images/svinka_wide.png";

    if (userCardBanner) {
      userCardBanner.style.backgroundImage = `url('${bgUrl}')`;
    }

    if (freeProgressBlock) {
      freeProgressBlock.style.display = "";
    }

    if (plan === "free") {
      userPlan.style.display = "none";
      if (freeUpgradeBlock) freeUpgradeBlock.style.display = "flex";
      if (proSupportBlock) proSupportBlock.style.display = "none";
      if (freeProgressBlock) {
        const maxTokens = 5;
        const remaining = Math.min(typeof user.reply_remaining === "number" ? user.reply_remaining : maxTokens, maxTokens);
        const percent = Math.max((remaining / maxTokens) * 100, 0);

        if (freeGenerationsLabel) freeGenerationsLabel.textContent = "Generations left";
        if (freeGenerationsText) freeGenerationsText.textContent = remaining;
        if (freeProgressFill) freeProgressFill.style.width = `${percent}%`;
      }
    } else {
      userPlan.style.display = "";
      if (freeUpgradeBlock) freeUpgradeBlock.style.display = "none";
      if (proSupportBlock) proSupportBlock.style.display = plan === "pro" ? "flex" : "none";
      if (freeProgressBlock) freeProgressBlock.style.display = "none";
      if (freeProgressBlock) {
        freeProgressBlock.style.display = "";
        if (freeGenerationsLabel) freeGenerationsLabel.textContent = "Generations";
        if (freeGenerationsText) freeGenerationsText.textContent = "Unlimited";
        if (freeProgressFill) freeProgressFill.style.width = "100%";
      }
    }

    if (user.expires_at && userExpires) {
      const expDate = new Date(user.expires_at);
      const formatted = expDate.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric" });
      userExpires.textContent = `Expires: ${formatted}`;
      userExpires.style.display = "";
    } else if (userExpires) {
      userExpires.style.display = "none";
    }

    if (user.defaults) {
      if (toggleTranslate) toggleTranslate.checked = !!user.defaults.translate_enabled;
      chrome.storage.local.get(["pigly_features"], (res) => {
        const features = res.pigly_features || {};
        chrome.storage.local.set({
          pigly_features: {
            replies: features.replies !== false,
            shorten: features.shorten !== false,
            translate: !!user.defaults.translate_enabled
          }
        });
      });
      currentVariantCount = [1, 2, 3].includes(Number(user.defaults.variant_count)) ? Number(user.defaults.variant_count) : 3;
      variantCountPills.forEach((pill) => {
        pill.classList.toggle("active", Number(pill.dataset.count) === currentVariantCount);
      });
      if (selTranslate) selTranslate.value = user.defaults.translate_to_language || "en";
      if (shortenTriggerLengthInput) {
        shortenTriggerLengthInput.value = String(
          normalizeShortenTriggerLength(user.defaults.shorten_trigger_length || DEFAULT_SHORTEN_TRIGGER_LENGTH)
        );
      }
      if (selLength) selLength.value = user.defaults.comment_length || "mix";
      if (selEmoji) selEmoji.value = user.defaults.emoji_mode || "moderate";
      if (selDash) selDash.value = user.defaults.dash_style || "ndash";
      if (selCaps) selCaps.value = user.defaults.capitalization || "upper";
      if (selPunct) selPunct.value = user.defaults.terminal_punctuation || "none";

      renderCustomStylePills(user.defaults.custom_comment_styles || []);

      const activeStyles = user.defaults.comment_styles || ["supportive"];
      getStyleButtons().forEach((pill) => {
        pill.classList.toggle("active", activeStyles.includes(pill.dataset.val));
      });
    }
  }

  async function refreshSession({ withLoading = false } = {}) {
    if (refreshInFlight) return refreshInFlight;

    refreshInFlight = (async () => {
      if (withLoading) {
        showState("loading");
      }

      try {
        const res = await chrome.runtime.sendMessage({ action: "getSession" });
        if (res && res.ok && res.authenticated) {
          renderUser(res.user);
          showState("user");
          return res;
        }

        showState("login");
        return res;
      } catch {
        showState("login");
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();

    return refreshInFlight;
  }

  function gatherSettings() {
    const activeStyles = getStyleButtons()
      .filter((pill) => pill.classList.contains("active"))
      .map((pill) => pill.dataset.val);

    if (activeStyles.length === 0) {
      activeStyles.push("supportive");
      getStyleButtons().forEach((pill) => {
        if (pill.dataset.val === "supportive") pill.classList.add("active");
      });
    }

    return {
      comment_styles: activeStyles,
      variant_count: currentVariantCount,
      translate_to_language: selTranslate ? selTranslate.value : "",
      shorten_trigger_length: shortenTriggerLengthInput ? normalizeShortenTriggerLength(shortenTriggerLengthInput.value) : DEFAULT_SHORTEN_TRIGGER_LENGTH,
      comment_length: selLength.value,
      emoji_mode: selEmoji.value,
      dash_style: selDash ? selDash.value : "ndash",
      capitalization: selCaps.value,
      terminal_punctuation: selPunct.value
    };
  }

  function triggerSaveSettings() {
    clearTimeout(saveTimeout);
    setSettingsStatus("Saving...");

    saveTimeout = setTimeout(async () => {
      const payload = gatherSettings();

      try {
        const res = await chrome.runtime.sendMessage({
          action: "updateProfile",
          payload
        });

        if (res && res.ok) {
          setSettingsStatus("Saved");
          setTimeout(() => {
            const allSaved = Array.from(settingsStatusEls).every((node) => !node || node.textContent === "Saved");
            if (allSaved) setSettingsStatus("", false);
          }, 2000);
        } else {
          setSettingsStatus("Failed to save");
          setTimeout(() => setSettingsStatus("", false), 2000);
        }
      } catch {
        setSettingsStatus("Error saving");
        setTimeout(() => setSettingsStatus("", false), 2000);
      }
    }, 500);
  }

  [selTranslate, shortenTriggerLengthInput, selDash, selLength, selEmoji, selCaps, selPunct].forEach((sel) => {
    if (sel) sel.addEventListener("change", triggerSaveSettings);
  });

  if (shortenTriggerLengthInput) {
    shortenTriggerLengthInput.addEventListener("blur", () => {
      shortenTriggerLengthInput.value = String(normalizeShortenTriggerLength(shortenTriggerLengthInput.value));
    });
  }

  if (commentSettingsOpen) commentSettingsOpen.addEventListener("click", () => openSettingsPage(pageCommentSettings));
  if (shortenerSettingsOpen) shortenerSettingsOpen.addEventListener("click", () => openSettingsPage(pageShortenerSettings));
  if (commentSettingsBack) commentSettingsBack.addEventListener("click", closeSettingsPage);
  if (shortenerSettingsBack) shortenerSettingsBack.addEventListener("click", closeSettingsPage);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && activeSubpage && activeSubpage.classList.contains("is-active")) {
      closeSettingsPage();
    }
  });

  if (pillsStylesContainer) {
    pillsStylesContainer.addEventListener("click", (event) => {
      const pill = event.target.closest(".style-pill");
      if (!pill || !pillsStylesContainer.contains(pill)) return;

      pill.classList.toggle("active");

      const activeCount = getStyleButtons().filter((item) => item.classList.contains("active")).length;
      if (activeCount === 0) {
        pill.classList.add("active");
        return;
      }

      triggerSaveSettings();
    });
  }

  variantCountPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      currentVariantCount = Number(pill.dataset.count) || 3;
      variantCountPills.forEach((item) => {
        item.classList.toggle("active", item === pill);
      });
      triggerSaveSettings();
    });
  });

  async function init() {
    chrome.storage.local.get(["pigly_features"], (res) => {
      const features = res.pigly_features || { replies: true, shorten: true, translate: false };
      if (toggleReplies) toggleReplies.checked = features.replies !== false;
      if (toggleShorten) toggleShorten.checked = features.shorten !== false;
      if (toggleTranslate && typeof features.translate === "boolean") {
        toggleTranslate.checked = features.translate;
      }
    });

    const saveFeatures = () => {
      chrome.storage.local.set({
        pigly_features: {
          replies: toggleReplies ? toggleReplies.checked : true,
          shorten: toggleShorten ? toggleShorten.checked : true,
          translate: toggleTranslate ? toggleTranslate.checked : false
        }
      });
    };

    const handleTranslateToggle = async () => {
      saveFeatures();
      try {
        await chrome.runtime.sendMessage({
          action: "updateProfile",
          payload: {
            translate_enabled: toggleTranslate ? toggleTranslate.checked : false
          }
        });
      } catch (_error) {
        // Leave the local toggle as-is; session refresh will reconcile later if needed.
      }
    };

    if (toggleReplies) toggleReplies.addEventListener("change", saveFeatures);
    if (toggleShorten) toggleShorten.addEventListener("change", saveFeatures);
    if (toggleTranslate) toggleTranslate.addEventListener("change", handleTranslateToggle);

    await refreshSession({ withLoading: true });
  }

  btnLogin.addEventListener("click", () => {
    chrome.tabs.create({ url: "http://127.0.0.1:8000/users/login/" });
  });

  window.addEventListener("focus", () => {
    refreshSession();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshSession();
    }
  });

  init();
});
