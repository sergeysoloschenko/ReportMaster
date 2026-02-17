const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function createJob(files, reportMonth) {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  if (reportMonth) form.append("report_month", reportMonth);

  const response = await fetch(`${API_BASE}/api/jobs`, {
    method: "POST",
    body: form
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Failed to start job");
  }
  return response.json();
}

export async function getJob(jobId) {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
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
