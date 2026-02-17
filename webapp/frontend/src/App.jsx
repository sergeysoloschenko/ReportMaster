import { useEffect, useMemo, useState } from "react";
import { attachmentsUrl, createJob, getJob, reportUrl } from "./api";

const ACCEPTED_MAX = 50;

function App() {
  const [files, setFiles] = useState([]);
  const [reportMonth, setReportMonth] = useState("");
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isProcessing = job && !["completed", "failed"].includes(job.status);

  useEffect(() => {
    if (!jobId || !isProcessing) return;
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

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!files.length) {
      setError("Select at least one .msg file");
      return;
    }
    if (files.length > ACCEPTED_MAX) {
      setError(`Maximum ${ACCEPTED_MAX} files`);
      return;
    }
    setSubmitting(true);
    try {
      const created = await createJob(files, reportMonth);
      setJobId(created.job_id);
      const initial = await getJob(created.job_id);
      setJob(initial);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <section className="card hero">
        <p className="eyebrow">Private Deployment</p>
        <h1>ReportMaster Web Console</h1>
        <p className="subtitle">
          Upload Outlook `.msg` emails, monitor AI processing, and download final report packages.
        </p>
      </section>

      <section className="grid">
        <form className="card" onSubmit={onSubmit}>
          <h2>1. Upload</h2>
          <label className="field">
            <span>Email files (.msg, up to 50)</span>
            <input
              type="file"
              accept=".msg"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
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
          <p className="meta">{files.length} file(s) selected</p>
          <button className="btn" disabled={submitting}>
            {submitting ? "Starting..." : "Start Processing"}
          </button>
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
              <p>Total emails: {job.stats.total_messages}</p>
              <p>Threads: {job.stats.total_threads}</p>
              <p>Categories: {job.stats.total_categories}</p>
              <p>Attachments: {job.stats.total_attachments}</p>
              <p>Report size: {job.stats.report_size_kb} KB</p>
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
        </section>
      </section>
    </main>
  );
}

export default App;
