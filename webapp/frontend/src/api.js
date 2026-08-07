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

export async function createJob(files, reportMonth, mode, userPrompt, onUploadProgress) {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  if (reportMonth) form.append("report_month", reportMonth);
  form.append("mode", mode);
  if (userPrompt) form.append("user_prompt", userPrompt);

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE}/api/jobs`);
    request.withCredentials = true;

    request.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onUploadProgress) return;
      onUploadProgress(Math.round((event.loaded / event.total) * 100));
    };

    request.onload = () => {
      const contentType = request.getResponseHeader("content-type") || "";
      const payload = contentType.includes("application/json")
        ? safeJsonParse(request.responseText)
        : {};

      if (request.status >= 200 && request.status < 300) {
        resolve(payload);
        return;
      }

      const text = payload.detail || request.statusText || "Failed to start job";
      if (request.status === 413) {
        reject(new Error("Upload is too large for the current server/proxy limit"));
        return;
      }
      reject(new Error(text));
    };

    request.onerror = () => reject(new Error("Network error while uploading files"));
    request.send(form);
  });
}

function safeJsonParse(text) {
  try {
    return JSON.parse(text || "{}");
  } catch {
    return {};
  }
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
