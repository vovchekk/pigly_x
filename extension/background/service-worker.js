importScripts("../lib/api.js");

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.action) return false;
  handleMessage(msg).then(sendResponse).catch((err) => {
    sendResponse({ ok: false, error: { code: "internal", message: err.message } });
  });
  return true;
});

async function handleMessage(msg) {
  switch (msg.action) {
    case "login":
      return handleGetSession(); // Removed explicit token login
    case "logout":
      return handleLogout();
    case "getSession":
      return handleGetSession();
    case "updateProfile":
      return handleUpdateProfile(msg.payload);
    case "shorten":
      return handleShorten(msg.payload);
    case "reply":
      return handleReply(msg.payload);
    case "translate":
      return handleTranslate(msg.payload);
    case "getHistory":
      return handleGetHistory(msg.payload);
    default:
      return { ok: false, error: { code: "unknown_action", message: `Unknown action: ${msg.action}` } };
  }
}

async function handleLogout() {
  await chrome.storage.local.remove(["pigly_user"]);
  // Note: we can't easily clear the browser's cookies from here without host permissions arrays
  // but if the user wants to logout from extension, they logout from site.
  // Realistically, "logout" just clears local cache until next getSession.
  return { ok: true };
}

async function handleGetSession() {
  // Always fetch fresh session to ensure cookies are still valid and get updated limits
  const result = await apiRequest("/api/auth/session/");
  if (!result.ok) {
    await chrome.storage.local.remove(["pigly_user"]);
    return { ok: false, authenticated: false };
  }

  const userData = {
    email: result.data.user?.email || "",
    plan: result.data.plan?.name || "free",
    plan_label: capitalize(result.data.plan?.name || "free"),
    reply_remaining: result.data.plan?.reply_remaining,
    shorten_remaining: result.data.plan?.shorten_remaining,
    expires_at: result.data.plan?.expires_at,
    defaults: result.data.defaults || {},
  };

  await chrome.storage.local.set({ pigly_user: userData });
  return { ok: true, authenticated: true, user: userData };
}

async function handleUpdateProfile(payload) {
  const result = await apiRequest("/api/auth/profile/update/", {
    method: "POST",
    body: payload
  });
  
  if (!result.ok) {
    return { ok: false, error: result.error };
  }

  // Update cached user data
  const userData = {
    email: result.data.user?.email || "",
    plan: result.data.plan?.name || "free",
    plan_label: capitalize(result.data.plan?.name || "free"),
    reply_remaining: result.data.plan?.reply_remaining,
    shorten_remaining: result.data.plan?.shorten_remaining,
    defaults: result.data.defaults || {},
  };

  await chrome.storage.local.set({ pigly_user: userData });
  return { ok: true, user: userData };
}

async function handleShorten({ text, tone, language, variant_count, target_length }) {
  const body = { text };
  if (tone) body.tone = tone;
  if (language) body.language = language;
  if (variant_count) body.variant_count = variant_count;
  if (target_length) body.target_length = target_length;

  const result = await apiRequest("/api/ai/shorten/", { method: "POST", body });
  if (result.ok) {
    await refreshLimits(result.data); // Assuming response contains limits, or we fetch again
  }
  return result;
}

async function handleReply({ text, context, tone, language, variant_count }) {
  const body = { text };
  if (context) body.context = context;
  if (tone) body.tone = tone;
  if (language) body.language = language;
  if (variant_count) body.variant_count = variant_count;

  const result = await apiRequest("/api/ai/reply/", { method: "POST", body });
  if (result.ok) {
    await refreshLimits(result.data); // Or fetch session
  }
  return result;
}

async function handleTranslate({ text }) {
  const body = { text };
  return apiRequest("/api/ai/translate/", { method: "POST", body });
}

async function handleGetHistory({ kind, limit } = {}) {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (limit) params.set("limit", String(limit));
  const qs = params.toString();
  return apiRequest(`/api/history/${qs ? "?" + qs : ""}`);
}

async function refreshLimits() {
  const result = await apiRequest("/api/auth/session/");
  if (result.ok) {
    const storage = await chrome.storage.local.get(["pigly_user"]);
    const user = storage.pigly_user || {};
    user.reply_remaining = result.data.plan?.reply_remaining;
    user.shorten_remaining = result.data.plan?.shorten_remaining;
    user.plan = result.data.plan?.name || user.plan;
    user.plan_label = capitalize(result.data.plan?.name || user.plan || "free");
    await chrome.storage.local.set({ pigly_user: user });
  }
}

function capitalize(str) {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
}
