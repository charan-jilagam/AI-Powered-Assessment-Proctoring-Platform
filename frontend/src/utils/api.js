const API_URL = "http://localhost:8000";

// Helper to get the stored token
export function getToken() {
  return localStorage.getItem("token");
}

// Helper to save the token after login
export function setToken(token) {
  localStorage.setItem("token", token);
}

// Helper to remove the token on logout
export function removeToken() {
  localStorage.removeItem("token");
}

// Generic API call function - handles auth headers automatically
export async function apiCall(endpoint, method = "GET", body = null) {
  const headers = {
    "Content-Type": "application/json",
  };

  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const config = {
    method,
    headers,
  };

  if (body) {
    config.body = JSON.stringify(body);
  }

  const response = await fetch(`${API_URL}${endpoint}`, config);
  const data = await response.json();

  if (!response.ok) {
    let message = "Something went wrong";
    if (typeof data.detail === "string") {
        message = data.detail;
    } else if (Array.isArray(data.detail)) {
        // FastAPI validation errors: extract readable messages
        message = data.detail.map((e) => {
            const field = e.loc ? e.loc[e.loc.length - 1] : "field";
            return `${field}: ${e.msg}`;
        }).join(", ");
    }
    throw new Error(message);
}
  return data;
}