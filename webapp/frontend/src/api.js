const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function getAuthStatus() {
  const response = await fetch(`${API_BASE}/api/auth/status`, {
    credentials: "include"
  });
  if (!response.ok) {
    throw new Error("Failed to check authentication");
  }
  return response.json();
}

export async function login(password) {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ password })
  });
  if (!response.ok) {
    throw new Error("Invalid password");
  }
  return response.json();
}

export async function logout() {
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: "POST",
    credentials: "include"
  });
}

export async function createJob(files, reportMonth, mode, userPrompt) {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  if (reportMonth) form.append("report_month", reportMonth);
  form.append("mode", mode);
  if (userPrompt) form.append("user_prompt", userPrompt);

  const response = await fetch(`${API_BASE}/api/jobs`, {
    method: "POST",
    credentials: "include",
    body: form
  });
  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => ({}))
      : {};
    const text = payload.detail || response.statusText || "Failed to start job";
    if (response.status === 413) {
      throw new Error("Upload is too large for the current server/proxy limit");
    }
    throw new Error(text);
  }
  return response.json();
}

export async function getJob(jobId) {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
    credentials: "include"
  });
  if (!response.ok) {
    throw new Error("Failed to fetch job state");
  }
  return response.json();
}

export function reportUrl(jobId) {
  return `${API_BASE}/api/jobs/${jobId}/report`;
}

export function attachmentsUrl(jobId) {
  return `${API_BASE}/api/jobs/${jobId}/attachments.zip`;
}
