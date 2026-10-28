import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "./api.ts";
import CookiePanel from "./CookiePanel.tsx";
import {
  formatBytes,
  formatChoice,
  formatEta,
  formatLimit,
  formatQuality,
  formatWhen,
  isTerminal,
  markSaved,
  markStarted,
  newerJob,
  wasStarted,
} from "./format.ts";
import Mark from "./Mark.tsx";
import type { CookieItem, Inspect, Job, Me } from "./types.ts";

const FORMATS = [
  { id: "mp4", label: "视频 MP4", note: "合并音视频" },
  { id: "mp3", label: "音频 MP3", note: "仅声音" },
  { id: "m4a", label: "音频 M4A", note: "仅声音" },
  { id: "best", label: "最佳可用", note: "不强制 MP4" },
] as const;

const QUALITIES = [
  { id: "1080", label: "1080p" },
  { id: "720", label: "720p" },
  { id: "480", label: "480p" },
  { id: "best", label: "最佳" },
] as const;

function pillClass(status: string): string {
  if (status === "completed") return "pill pill-ok";
  if (status === "failed") return "pill pill-bad";
  if (status === "cancelled") return "pill";
  return "pill pill-run";
}

export default function Board({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const [url, setUrl] = useState("");
  const [format, setFormat] = useState<(typeof FORMATS)[number]["id"]>("mp4");
  const [quality, setQuality] = useState<(typeof QUALITIES)[number]["id"]>("1080");
  const [cookieId, setCookieId] = useState("");
  const [autoSave, setAutoSave] = useState(() => localStorage.getItem("archive-autosave") !== "0");
  const [hint, setHint] = useState<Inspect | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState("");
  const [cookies, setCookies] = useState<CookieItem[]>([]);
  const [cookiesLoading, setCookiesLoading] = useState(true);
  const [cookiesError, setCookiesError] = useState("");
  const [active, setActive] = useState<Job | null>(null);
  const [confirmDelete, setConfirmDelete] = useState("");
  const audio = format === "mp3" || format === "m4a";

  const loadJobs = useCallback(async () => {
    try {
      const data = await api<{ jobs: Job[] }>("/api/jobs");
      setJobs(data.jobs);
      setJobsError("");
    } catch (err) {
      setJobsError(err instanceof ApiError ? err.message : "记录加载失败");
    } finally {
      setJobsLoading(false);
    }
  }, []);

  const loadCookies = useCallback(async () => {
    try {
      const data = await api<{ cookies: CookieItem[] }>("/api/cookies");
      setCookies(data.cookies);
      setCookiesError("");
    } catch (err) {
      setCookiesError(err instanceof ApiError ? err.message : "Cookie 加载失败");
    } finally {
      setCookiesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
    void loadCookies();
  }, [loadJobs, loadCookies]);

  useEffect(() => {
    const trimmed = url.trim();
    if (!/^https?:\/\//i.test(trimmed)) {
      setHint(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void api<Inspect>(`/api/inspect?url=${encodeURIComponent(trimmed)}`)
        .then(setHint)
        .catch(() => setHint(null));
    }, 350);
    return () => window.clearTimeout(timer);
  }, [url]);

  useEffect(() => {
    if (!active) return;
    const source = new EventSource(`/api/jobs/${active.id}/events`);
    const apply = (event: MessageEvent) => {
      const next = JSON.parse(event.data) as Job;
      setActive((prev) => newerJob(prev, next));
      if (isTerminal(next.status)) {
        source.close();
        void loadJobs();
      }
    };
    source.addEventListener("snapshot", apply);
    source.addEventListener("progress", apply);
    source.addEventListener("done", apply);
    return () => source.close();
  }, [active?.id, loadJobs]);

  useEffect(() => {
    if (!active || isTerminal(active.status)) return;
    const timer = window.setInterval(() => {
      void api<Job>(`/api/jobs/${active.id}`)
        .then((next) => {
          setActive((prev) => newerJob(prev, next));
          if (isTerminal(next.status)) void loadJobs();
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [active?.id, active?.status, loadJobs]);

  useEffect(() => {
    if (!autoSave || !active || active.status !== "completed" || !active.download_url) return;
    if (!wasStarted(active.id) || !markSaved(active.id)) return;
    const link = document.createElement("a");
    link.href = active.download_url;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, [autoSave, active]);

  useEffect(() => {
    const busy = jobs.some((job) => !isTerminal(job.status));
    if (!busy) return;
    const timer = window.setInterval(() => void loadJobs(), 8000);
    return () => window.clearInterval(timer);
  }, [jobs, loadJobs]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      const job = await api<Job>("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          url: url.trim(),
          format,
          quality: audio ? "best" : quality,
          cookie_id: cookieId || null,
        }),
      });
      markStarted(job.id);
      setActive(job);
      await loadJobs();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "无法开始下载");
    } finally {
      setSubmitting(false);
    }
  }

  async function mutate(path: string, method: string) {
    const job = await api<Job>(path, { method });
    if (job && typeof job === "object" && "id" in job) {
      if (method === "POST" && path.endsWith("/retry")) markStarted(job.id);
      setActive(job);
    }
    await loadJobs();
  }

  async function remove(id: string) {
    if (confirmDelete !== id) {
      setConfirmDelete(id);
      return;
    }
    await api(`/api/jobs/${id}`, { method: "DELETE" });
    if (active?.id === id) setActive(null);
    setConfirmDelete("");
    await loadJobs();
  }

  const limit = formatLimit(me.max_filesize_mb);
  const running = jobs.filter((job) => !isTerminal(job.status)).length;

  return (
    <div className="page">
      <header className="top">
        <div className="brand">
          <Mark />
          <div>
            <p className="eyebrow">Personal archive</p>
            <strong>个人媒体存档</strong>
          </div>
        </div>
        <div className="top-actions">
          <span>{me.username}</span>
          {running > 0 ? <span className="pill pill-run">{running} 个进行中</span> : null}
          <button className="btn-small" type="button" onClick={onLogout}>退出</button>
        </div>
      </header>

      <section className="hero">
        <h1>粘贴链接，存成文件</h1>
        <p className="lede">支持 YouTube、哔哩哔哩和 X。抖音、小红书、视频号通常要先上传你自己的 Cookie。</p>
      </section>

      <div className="stack">
        {me.password_is_weak ? (
          <div className="banner" role="status">当前口令太简单。如果这台机器能从公网访问，请立刻更换 AUTH_PASSWORD。</div>
        ) : null}
        {!me.ffmpeg ? <div className="banner banner-bad">服务器没有找到 ffmpeg，合并音视频和转码会失败。</div> : null}
        {!me.js_runtime ? (
          <div className="banner">没有 Deno 或 Node。YouTube 可能下不了完整画质。Docker 镜像里已经带了 Deno。</div>
        ) : null}

        <form className="panel panel-top form" onSubmit={submit}>
          <div className="url-row">
            <label className="field" style={{ flex: 1 }}>
              <span>视频链接</span>
              <input
                className="input"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://www.bilibili.com/video/..."
                autoComplete="off"
                inputMode="url"
                aria-label="视频链接"
              />
            </label>
            <button className="btn btn-primary" type="submit" disabled={submitting || !url.trim()}>
              {submitting ? "正在提交…" : "开始下载"}
            </button>
          </div>
          <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="legend">格式</legend>
            <div className="chips" role="radiogroup" aria-label="格式">
              {FORMATS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="chip"
                  aria-pressed={format === item.id}
                  onClick={() => setFormat(item.id)}
                >
                  {item.label}
                  <small>{item.note}</small>
                </button>
              ))}
            </div>
          </fieldset>
          <div className="options">
            <label className="field">
              <span>清晰度</span>
              <select
                className="select"
                value={audio ? "best" : quality}
                disabled={audio}
                onChange={(event) => setQuality(event.target.value as typeof quality)}
              >
                {QUALITIES.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="field" style={{ flex: 1 }}>
              <span>Cookie</span>
              <select className="select" value={cookieId} onChange={(event) => setCookieId(event.target.value)}>
                <option value="">自动匹配</option>
                {cookies.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={autoSave}
                onChange={(event) => {
                  setAutoSave(event.target.checked);
                  localStorage.setItem("archive-autosave", event.target.checked ? "1" : "0");
                }}
              />
              完成后自动保存
            </label>
          </div>
          {hint?.ok ? (
            <div className={hint.needs_cookies_likely && !hint.cookie_ready ? "hint hint-bad" : "hint"}>
              <strong>{hint.site_label}</strong>
              <div>{hint.hint}</div>
              {hint.needs_cookies_likely && !hint.cookie_ready ? <div>还没有可用 Cookie。</div> : null}
              {hint.cookie_ready ? <div>将使用{hint.cookie_source === "global" ? "全局" : "该站点"} Cookie。</div> : null}
            </div>
          ) : null}
          {hint && !hint.ok ? <p className="error">{hint.error}</p> : null}
          {formError ? <p className="error" role="alert">{formError}</p> : null}
        </form>

        {active ? (
          <ProgressCard
            job={active}
            onCancel={() => void mutate(`/api/jobs/${active.id}/cancel`, "POST").catch((err: unknown) => setFormError(err instanceof Error ? err.message : "取消失败"))}
            onRetry={() => void mutate(`/api/jobs/${active.id}/retry`, "POST").catch((err: unknown) => setFormError(err instanceof Error ? err.message : "重试失败"))}
            onDelete={() => void remove(active.id).catch((err: unknown) => setFormError(err instanceof Error ? err.message : "删除失败"))}
            confirmDelete={confirmDelete === active.id}
          />
        ) : null}

        <div className="split">
          <section className="panel">
            <div className="section-head">
              <h2>最近的任务</h2>
              <button className="btn-small" type="button" onClick={() => void loadJobs()}>刷新</button>
            </div>
            {jobsLoading ? <p className="muted">正在读取记录…</p> : null}
            {jobsError ? <p className="error">{jobsError}</p> : null}
            {!jobsLoading && !jobsError && jobs.length === 0 ? (
              <p className="empty">还没有任务。上面粘贴一个视频链接即可。</p>
            ) : null}
            <div className="list">
              {jobs.map((job) => (
                <article className={active?.id === job.id ? "job active" : "job"} key={job.id}>
                  <div className="job-main">
                    <button className="link" type="button" onClick={() => setActive(job)}>
                      {job.title || "未命名视频"}
                    </button>
                    <div className="faint">
                      {job.site_label || "未知站点"} · {formatChoice(job.format)} · {formatQuality(job.quality)} · {formatWhen(job.created_at)}
                      {job.file_ready ? ` · ${formatBytes(job.file_size)}` : ""}
                    </div>
                  </div>
                  <span className={pillClass(job.status)}>{job.message}</span>
                </article>
              ))}
            </div>
          </section>
          <CookiePanel cookies={cookies} loading={cookiesLoading} error={cookiesError} onChange={loadCookies} />
        </div>
      </div>

      <footer className="footer">
        <p>
          {me.retention_days > 0 ? `完成的文件保留 ${me.retention_days} 天，然后自动清理。` : "不会自动清理文件。"}
          {limit ? ` ${limit}。` : ""} 同时下载 {me.max_concurrent} 个。yt-dlp {me.ytdlp}
          {me.js_runtime ? ` · ${me.js_runtime}` : ""}。
        </p>
        <p>只保存你有权访问的内容：自己的投稿、已获授权的素材、明确允许下载的公开视频。请遵守平台条款和当地法律。</p>
      </footer>
    </div>
  );
}

function ProgressCard({
  job,
  onCancel,
  onRetry,
  onDelete,
  confirmDelete,
}: {
  job: Job;
  onCancel: () => void;
  onRetry: () => void;
  onDelete: () => void;
  confirmDelete: boolean;
}) {
  const running = !isTerminal(job.status);
  const indeterminate = running && (job.percent == null || job.status === "preparing" || job.status === "queued");
  return (
    <section className="panel" aria-live="polite">
      <div className="progress-head">
        <div style={{ minWidth: 0 }}>
          <div className="site">{job.site_label || "正在识别站点"}</div>
          <h2 className="title clamp">{job.title || "正在解析标题"}</h2>
          <p className="url" title={job.url}>{job.url}</p>
        </div>
        <span className={pillClass(job.status)}>{job.message}</span>
      </div>
      <div className="track" aria-hidden="true">
        <div className={indeterminate ? "bar bar-indet" : "bar"} style={indeterminate ? undefined : { width: `${job.status === "completed" ? 100 : job.percent ?? 0}%` }} />
      </div>
      <div className="stats">
        <span>{job.percent == null ? (running ? "进度计算中" : job.status === "completed" ? "100%" : "—") : `${job.percent.toFixed(0)}%`}</span>
        <span>{job.speed || (running ? "速度计算中" : "—")}</span>
        <span>{running ? formatEta(job.eta) : formatBytes(job.file_size)}</span>
      </div>
      {job.error ? <p className="error">{job.error}</p> : null}
      {job.needs_cookies ? (
        <p className="hint hint-bad">
          需要登录 Cookie。
          <a href="#cookies"> 去上传</a>
        </p>
      ) : null}
      {job.error_detail && job.status === "failed" ? (
        <details>
          <summary>技术详情</summary>
          <p className="faint">{job.error_detail}</p>
        </details>
      ) : null}
      <div className="actions">
        {job.file_ready && job.download_url ? (
          <a className="btn btn-primary" href={job.download_url}>保存到本地</a>
        ) : null}
        {running ? <button className="btn btn-ghost" type="button" onClick={onCancel}>取消</button> : null}
        {job.status === "failed" || job.status === "cancelled" ? (
          <button className="btn btn-ghost" type="button" onClick={onRetry}>重试</button>
        ) : null}
        {!running ? (
          <button className="btn btn-danger" type="button" onClick={onDelete}>{confirmDelete ? "确认删除" : "删除记录"}</button>
        ) : null}
      </div>
    </section>
  );
}
