import { useEffect, useMemo, useState } from "react";
import { attachmentsUrl, createJob, getJob, reportUrl } from "./api";

const ACCEPTED_TYPES = ".msg,.txt,.csv,.md,.docx,.pdf,.xlsx,.xlsm";

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
          Upload Outlook `.msg` emails and documents, monitor AI processing, and download final report packages.
        </p>
      </section>

      <section className="grid">
        <form className="card" onSubmit={onSubmit}>
          <h2>1. Upload</h2>
          <label className="field">
            <span>Email and document files</span>
            <input
              type="file"
              accept={ACCEPTED_TYPES}
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
          <p className="meta">{files.length} file(s) selected</p>
          {!!files.length && <p className="meta">You can open picker again to add files from another folder.</p>}
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
              <p>Uploaded files: {job.stats.uploaded_files}</p>
              <p>Unique files: {job.stats.unique_uploaded_files}</p>
              <p>Duplicate files: {job.stats.duplicate_uploaded_files}</p>
              <p>Parsed emails: {job.stats.parsed_emails}</p>
              <p>Parsed documents: {job.stats.parsed_documents}</p>
              <p>Duplicate messages: {job.stats.duplicate_messages}</p>
              <p>Threads: {job.stats.total_threads}</p>
              <p>Categories: {job.stats.total_categories}</p>
              <p>Attachments: {job.stats.total_attachments}</p>
              <p>Duplicate attachments: {job.stats.duplicate_attachments}</p>
              <p>Report size: {job.stats.report_size_kb} KB</p>
              <p>Input tokens: {job.stats.input_tokens ?? 0}</p>
              <p>Output tokens: {job.stats.output_tokens ?? 0}</p>
              <p>Total tokens: {job.stats.total_tokens ?? 0}</p>
              <p>LLM cache hits: {job.stats.llm_cache_hits ?? 0}</p>
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
