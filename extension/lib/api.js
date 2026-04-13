const API_BASE = "http://127.0.0.1:8000";

let cachedCsrfToken = null;

async function apiRequest(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    "Accept": "application/json",
  };

  if (options.body && typeof options.body === "object") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }

  // Inject CSRF token for mutating requests
  if (options.method && options.method !== "GET" && options.method !== "HEAD") {
    if (cachedCsrfToken) {
      headers["X-CSRFToken"] = cachedCsrfToken;
    } else {
      // We don't have a cached CSRF token. The API request might fail with 403.
      // We can optionally try to fetch it first, but let's assume getSession populates it.
    }
  }

  try {
    const response = await fetch(url, {
      method: options.method || "GET",
      headers,
      body: options.body || undefined,
      credentials: "include", // Send session cookies
    });

    const data = await response.json();
    
    // Auto-update CSRF token if returned by the endpoint
    if (data && data.csrf_token) {
      cachedCsrfToken = data.csrf_token;
    }

    if (response.status === 401 || response.status === 403) {
      cachedCsrfToken = null;
      await chrome.storage.local.remove(["pigly_user"]);
      return { ok: false, status: response.status, error: data.error || { code: "unauthorized", message: "Not logged in." } };
    }

    if (!response.ok) {
      return { ok: false, status: response.status, error: data.error || { code: "api_error", message: "Request failed." } };
    }

    return { ok: true, status: response.status, data };
  } catch (err) {
    return { ok: false, status: 0, error: { code: "network_error", message: err.message || "Network error." } };
  }
}
