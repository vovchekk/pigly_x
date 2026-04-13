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
  const freeProgressBlock = document.getElementById("free-progress-block");
  const freeGenerationsText = document.getElementById("free-generations-text");
  const freeProgressFill = document.getElementById("free-progress-fill");

  const toggleReplies = document.getElementById("toggle-replies");
  const toggleShorten = document.getElementById("toggle-shorten");

  const selTranslate = document.getElementById("sel-translate");
  const selDash = document.getElementById("sel-dash");
  const selLength = document.getElementById("sel-length");
  const selEmoji = document.getElementById("sel-emoji");
  const selCaps = document.getElementById("sel-caps");
  const selPunct = document.getElementById("sel-punct");
  const variantCountPills = document.querySelectorAll(".variant-count-pill");
  const settingsOpen = document.getElementById("settings-open");
  const settingsBack = document.getElementById("settings-back");
  const pageMain = document.getElementById("page-main");
  const pageSettings = document.getElementById("page-settings");
  const pillsStyles = document.querySelectorAll("#pills-styles .style-pill");
  const settingsStatus = document.getElementById("settings-status");

  let saveTimeout = null;
  let currentVariantCount = 3;

  function showState(name) {
    stateLoading.style.display = name === "loading" ? "" : "none";
    stateLogin.style.display = name === "login" ? "" : "none";
    stateUser.style.display = name === "user" ? "" : "none";
  }

  function openSettingsPage() {
    if (!pageMain || !pageSettings) return;
    pageMain.classList.add("is-leaving-left");
    pageMain.classList.remove("is-active");
    pageSettings.classList.add("is-active");
  }

  function closeSettingsPage() {
    if (!pageMain || !pageSettings) return;
    pageSettings.classList.remove("is-active");
    pageMain.classList.add("is-active");
    pageMain.classList.remove("is-leaving-left");
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

    if (plan === "free") {
      userPlan.style.display = "none";
      if (freeUpgradeBlock) freeUpgradeBlock.style.display = "flex";
      if (freeProgressBlock) {
        freeProgressBlock.style.display = "";
        const maxTokens = 5;
        const remaining = Math.min(typeof user.reply_remaining === "number" ? user.reply_remaining : maxTokens, maxTokens);
        const percent = Math.max((remaining / maxTokens) * 100, 0);

        if (freeGenerationsText) freeGenerationsText.textContent = remaining;
        if (freeProgressFill) freeProgressFill.style.width = `${percent}%`;
      }
    } else {
      userPlan.style.display = "";
      if (freeUpgradeBlock) freeUpgradeBlock.style.display = "none";
      if (freeProgressBlock) freeProgressBlock.style.display = "none";
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
      currentVariantCount = [1, 2, 3].includes(Number(user.defaults.variant_count)) ? Number(user.defaults.variant_count) : 3;
      variantCountPills.forEach((pill) => {
        pill.classList.toggle("active", Number(pill.dataset.count) === currentVariantCount);
      });
      if (selTranslate) selTranslate.value = user.defaults.translate_to_language || "";
      if (selLength) selLength.value = user.defaults.comment_length || "mix";
      if (selEmoji) selEmoji.value = user.defaults.emoji_mode || "moderate";
      if (selDash) selDash.value = user.defaults.dash_style || "ndash";
      if (selCaps) selCaps.value = user.defaults.capitalization || "upper";
      if (selPunct) selPunct.value = user.defaults.terminal_punctuation || "none";

      const activeStyles = user.defaults.comment_styles || ["supportive"];
      pillsStyles.forEach((pill) => {
        pill.classList.toggle("active", activeStyles.includes(pill.dataset.val));
      });
    }
  }

  function gatherSettings() {
    const activeStyles = Array.from(pillsStyles)
      .filter((pill) => pill.classList.contains("active"))
      .map((pill) => pill.dataset.val);

    if (activeStyles.length === 0) {
      activeStyles.push("supportive");
      pillsStyles.forEach((pill) => {
        if (pill.dataset.val === "supportive") pill.classList.add("active");
      });
    }

    return {
      comment_styles: activeStyles,
      variant_count: currentVariantCount,
      translate_to_language: selTranslate ? selTranslate.value : "",
      comment_length: selLength.value,
      emoji_mode: selEmoji.value,
      dash_style: selDash ? selDash.value : "ndash",
      capitalization: selCaps.value,
      terminal_punctuation: selPunct.value
    };
  }

  function triggerSaveSettings() {
    clearTimeout(saveTimeout);
    settingsStatus.textContent = "Saving...";
    settingsStatus.classList.add("show");

    saveTimeout = setTimeout(async () => {
      const payload = gatherSettings();

      try {
        const res = await chrome.runtime.sendMessage({
          action: "updateProfile",
          payload
        });

        if (res && res.ok) {
          settingsStatus.textContent = "Saved";
          setTimeout(() => {
            if (settingsStatus.textContent === "Saved") {
              settingsStatus.classList.remove("show");
            }
          }, 2000);
        } else {
          settingsStatus.textContent = "Failed to save";
          setTimeout(() => settingsStatus.classList.remove("show"), 2000);
        }
      } catch {
        settingsStatus.textContent = "Error saving";
        setTimeout(() => settingsStatus.classList.remove("show"), 2000);
      }
    }, 500);
  }

  [selTranslate, selDash, selLength, selEmoji, selCaps, selPunct].forEach((sel) => {
    if (sel) sel.addEventListener("change", triggerSaveSettings);
  });

  if (settingsOpen) settingsOpen.addEventListener("click", openSettingsPage);
  if (settingsBack) settingsBack.addEventListener("click", closeSettingsPage);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && pageSettings && pageSettings.classList.contains("is-active")) {
      closeSettingsPage();
    }
  });

  pillsStyles.forEach((pill) => {
    pill.addEventListener("click", () => {
      pill.classList.toggle("active");

      const activeCount = Array.from(pillsStyles).filter((item) => item.classList.contains("active")).length;
      if (activeCount === 0) {
        pill.classList.add("active");
        return;
      }

      triggerSaveSettings();
    });
  });

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
      const features = res.pigly_features || { replies: true, shorten: true };
      if (toggleReplies) toggleReplies.checked = features.replies !== false;
      if (toggleShorten) toggleShorten.checked = features.shorten !== false;
    });

    const saveFeatures = () => {
      chrome.storage.local.set({
        pigly_features: {
          replies: toggleReplies ? toggleReplies.checked : true,
          shorten: toggleShorten ? toggleShorten.checked : true
        }
      });
    };

    if (toggleReplies) toggleReplies.addEventListener("change", saveFeatures);
    if (toggleShorten) toggleShorten.addEventListener("change", saveFeatures);

    showState("loading");

    try {
      const res = await chrome.runtime.sendMessage({ action: "getSession" });
      if (res && res.ok && res.authenticated) {
        renderUser(res.user);
        showState("user");
      } else {
        showState("login");
      }
    } catch {
      showState("login");
    }
  }

  btnLogin.addEventListener("click", () => {
    chrome.tabs.create({ url: "http://127.0.0.1:8000/users/login/" });
  });

  init();
});
