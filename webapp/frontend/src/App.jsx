import { useEffect, useMemo, useRef, useState } from "react";
import { attachmentsUrl, createJob, getAuthStatus, getJob, login, logout, reportUrl } from "./api";

const ACCEPTED_TYPES = ".msg,.txt,.csv,.md,.docx,.pdf,.xlsx,.xlsm";
const MONTHLY_MODE = "monthly_msg_report";
const CUSTOM_MODE = "custom_analysis";

function App() {
  const [mode, setMode] = useState(MONTHLY_MODE);
  const [files, setFiles] = useState([]);
  const [reportMonth, setReportMonth] = useState("");
  const [userPrompt, setUserPrompt] = useState("");
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [authChecked, setAuthChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const logEndRef = useRef(null);

  const isProcessing = job && !["completed", "failed"].includes(job.status);

  useEffect(() => {
    let mounted = true;
    getAuthStatus()
      .then((state) => {
        if (!mounted) return;
        setAuthenticated(state.authenticated);
      })
      .catch(() => {
        if (!mounted) return;
        setAuthError("Failed to check session");
      })
      .finally(() => {
        if (!mounted) return;
        setAuthChecked(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!authenticated || !jobId || !isProcessing) return;
    const timer = setInterval(async () => {
      try {
        const state = await getJob(jobId);
        setJob(state);
      } catch {
        setError("Failed to refresh job status");
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [jobId, isProcessing]);

  const progressLabel = useMemo(() => {
    if (!job) return "Ready";
    if (job.status === "completed") return "Completed";
    if (job.status === "failed") return "Failed";
    return `${job.step} (${job.progress}%)`;
  }, [job]);

  const logs = job?.logs || [];

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: "end" });
  }, [logs.length]);

  function mergeFiles(nextFiles) {
    setFiles((prev) => {
      const byKey = new Map(prev.map((f) => [`${f.name}:${f.size}:${f.lastModified}`, f]));
      nextFiles.forEach((file) => {
        byKey.set(`${file.name}:${file.size}:${file.lastModified}`, file);
      });
      return Array.from(byKey.values());
    });
  }

  function onFilesSelected(event) {
    const nextFiles = Array.from(event.target.files || []);
    if (nextFiles.length) {
      mergeFiles(nextFiles);
    }
    event.target.value = "";
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!files.length) {
      setError("Select at least one supported email or document file");
      return;
    }
    if (mode === CUSTOM_MODE && !userPrompt.trim()) {
      setError("Enter analysis prompt for custom mode");
      return;
    }
    setSubmitting(true);
    setUploadProgress(0);
    try {
      const created = await createJob(files, reportMonth, mode, userPrompt, setUploadProgress);
      setJobId(created.job_id);
      const initial = await getJob(created.job_id);
      setJob(initial);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function onLogin(event) {
    event.preventDefault();
    setAuthError("");
    try {
      await login(password);
      setAuthenticated(true);
      setPassword("");
    } catch (e) {
      setAuthError(e.message);
    }
  }

  async function onLogout() {
    await logout();
    setAuthenticated(false);
    setJobId(null);
    setJob(null);
  }

  if (!authChecked) {
    return (
      <main className="page authPage">
        <section className="card authCard">
          <p className="eyebrow">Private Deployment</p>
          <h1>ReportMaster</h1>
          <p className="subtitle">Checking session...</p>
        </section>
      </main>
    );
  }

  if (!authenticated) {
    return (
      <main className="page authPage">
        <form className="card authCard" onSubmit={onLogin}>
          <p className="eyebrow">Private Deployment</p>
          <h1>ReportMaster</h1>
          <p className="subtitle">Enter the application password.</p>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="btn" disabled={!password}>
            Sign in
          </button>
          {authError && <p className="error">{authError}</p>}
        </form>
      </main>
    );
  }

  return (
    <main className="page">
      <section className="card hero">
        <div className="heroTop">
          <p className="eyebrow">Private Deployment</p>
          <button className="btn ghost small" type="button" onClick={onLogout}>
            Sign out
          </button>
        </div>
        <h1>ReportMaster Web Console</h1>
        <p className="subtitle">
          Upload monthly Outlook emails or run prompt-based analysis on mixed source files.
        </p>
      </section>

      <section className="grid">
        <form className="card" onSubmit={onSubmit}>
          <h2>1. Upload</h2>
          <div className="modeSwitch" role="group" aria-label="Processing mode">
            <button
              type="button"
              className={mode === MONTHLY_MODE ? "modeButton active" : "modeButton"}
              onClick={() => {
                setMode(MONTHLY_MODE);
                setFiles([]);
              }}
            >
              Monthly .msg report
            </button>
            <button
              type="button"
              className={mode === CUSTOM_MODE ? "modeButton active" : "modeButton"}
              onClick={() => {
                setMode(CUSTOM_MODE);
                setFiles([]);
              }}
            >
              Custom analysis
            </button>
          </div>
          <label className="field">
            <span>{mode === MONTHLY_MODE ? "Monthly Outlook email files" : "Source files"}</span>
            <input
              type="file"
              accept={mode === MONTHLY_MODE ? ".msg" : ACCEPTED_TYPES}
              multiple
              onChange={onFilesSelected}
            />
          </label>
          <label className="field">
            <span>Report month (optional)</span>
            <input
              type="text"
              placeholder="e.g. February 2026"
              value={reportMonth}
              onChange={(e) => setReportMonth(e.target.value)}
            />
          </label>
          {mode === CUSTOM_MODE && (
            <label className="field">
              <span>Analysis prompt</span>
              <textarea
                rows="7"
                placeholder="Describe the analysis or report you need from these files"
                value={userPrompt}
                onChange={(e) => setUserPrompt(e.target.value)}
              />
            </label>
          )}
          <p className="meta">{files.length} file(s) selected</p>
          {!!files.length && <p className="meta">You can open picker again to add files from another folder.</p>}
          <button className="btn" disabled={submitting}>
            {submitting ? `Uploading... ${uploadProgress || 0}%` : "Start Processing"}
          </button>
          {submitting && (
            <p className="meta">
              Uploading files and creating the processing job. Progress details appear after the job is accepted.
            </p>
          )}
          {error && <p className="error">{error}</p>}
        </form>

        <section className="card">
          <h2>2. Progress</h2>
          <div className="meter">
            <div className="meterFill" style={{ width: `${job?.progress || 0}%` }} />
          </div>
          <p className="meta">{progressLabel}</p>
          {job?.error && <p className="error">{job.error}</p>}
          {job?.stats && (
            <div className="stats">
              <p>Mode: {job.stats.mode}</p>
              <p>Total emails: {job.stats.total_messages}</p>
              <p>Uploaded files: {job.stats.uploaded_files}</p>
              <p>Unique files: {job.stats.unique_uploaded_files}</p>
              <p>Duplicate files: {job.stats.duplicate_uploaded_files}</p>
              <p>Parsed emails: {job.stats.parsed_emails}</p>
              <p>Parsed documents: {job.stats.parsed_documents}</p>
              <p>Duplicate messages: {job.stats.duplicate_messages}</p>
              <p>Threads: {job.stats.total_threads}</p>
              <p>Thread insights: {job.stats.total_insights ?? 0}</p>
              <p>Categories: {job.stats.total_categories}</p>
              <p>Attachments: {job.stats.total_attachments}</p>
              <p>Duplicate attachments: {job.stats.duplicate_attachments}</p>
              <p>Report size: {job.stats.report_size_kb} KB</p>
              <p>Input tokens: {job.stats.input_tokens ?? 0}</p>
              <p>Output tokens: {job.stats.output_tokens ?? 0}</p>
              <p>Total tokens: {job.stats.total_tokens ?? 0}</p>
              <p>LLM cache hits: {job.stats.llm_cache_hits ?? 0}</p>
              <p>Codex runs: {job.stats.codex_runs ?? 0}</p>
              <p>Prompt chars: {job.stats.prompt_chars ?? 0}</p>
              <p>Output chars: {job.stats.output_chars ?? 0}</p>
            </div>
          )}
          {job?.status === "completed" && (
            <div className="actions">
              <a className="btn secondary" href={reportUrl(jobId)}>
                Download Report
              </a>
              <a className="btn ghost" href={attachmentsUrl(jobId)}>
                Download Attachments ZIP
              </a>
            </div>
          )}
          <div className="logPanel">
            <div className="logHeader">
              <h3>Live log</h3>
              <span>{logs.length} event(s)</span>
            </div>
            <div className="logStream">
              {logs.length ? (
                logs.map((item, index) => (
                  <div className={`logLine ${item.source || "system"}`} key={`${item.time}-${index}`}>
                    <span className="logSource">{item.source || "system"}</span>
                    <span className="logMessage">{item.message}</span>
                  </div>
                ))
              ) : (
                <p className="meta">No processing events yet.</p>
              )}
              <div ref={logEndRef} />
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

export default App;
