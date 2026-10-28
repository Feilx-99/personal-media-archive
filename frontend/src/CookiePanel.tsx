import { useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "./api.ts";
import { formatBytes, formatWhen } from "./format.ts";
import type { CookieItem } from "./types.ts";

const PRESETS = [
  { key: "global", label: "全局", note: "匹配不到具体站点时使用" },
  { key: "youtube", label: "YouTube", note: "人机验证或会员内容" },
  { key: "bilibili", label: "哔哩哔哩", note: "大会员清晰度" },
  { key: "twitter", label: "X / Twitter", note: "受限帖子" },
  { key: "douyin", label: "抖音", note: "通常必填" },
  { key: "xiaohongshu", label: "小红书", note: "通常必填" },
  { key: "wechat", label: "视频号", note: "通常必填，仍可能失败" },
];

export default function CookiePanel({
  cookies,
  loading,
  error,
  onChange,
}: {
  cookies: CookieItem[];
  loading: boolean;
  error: string;
  onChange: () => Promise<void>;
}) {
  const [pasteSite, setPasteSite] = useState("douyin");
  const [customLabel, setCustomLabel] = useState("");
  const [content, setContent] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmId, setConfirmId] = useState("");
  const bySite = new Map(cookies.filter((item) => item.site_key !== "custom").map((item) => [item.site_key, item]));
  const custom = cookies.filter((item) => item.site_key === "custom");

  async function send(siteKey: string, file: File | null, pasted: string, label?: string) {
    setPending(true);
    setMessage("");
    try {
      const form = new FormData();
      form.set("site_key", siteKey);
      if (label) form.set("label", label);
      if (file) form.set("file", file);
      if (pasted.trim()) form.set("content", pasted);
      await api("/api/cookies", { method: "POST", body: form });
      setContent("");
      setCustomLabel("");
      await onChange();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "上传失败");
    } finally {
      setPending(false);
    }
  }

  async function remove(id: string) {
    if (confirmId !== id) {
      setConfirmId(id);
      return;
    }
    setMessage("");
    try {
      await api(`/api/cookies/${id}`, { method: "DELETE" });
      setConfirmId("");
      await onChange();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  async function paste(event: FormEvent) {
    event.preventDefault();
    await send(pasteSite, null, content, pasteSite === "custom" ? customLabel : undefined);
  }

  return (
    <section className="panel" id="cookies">
      <div className="section-head">
        <h2>站点 Cookie</h2>
      </div>
      <p className="faint">抖音、小红书、视频号通常要你自己的浏览器 Cookie。文件只保存在这台服务器上。</p>
      {loading ? <p className="muted">正在读取 Cookie…</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <div className="list">
        {PRESETS.map((preset) => {
          const item = bySite.get(preset.key);
          return (
            <div className="cookie-row" key={preset.key}>
              <div className="job-main">
                <strong>{preset.label}</strong>
                <div className="faint">{item ? `${formatBytes(item.size_bytes)} · ${formatWhen(item.updated_at)}` : preset.note}</div>
              </div>
              <div className="cookie-actions">
                <label className="btn-small">
                  {item ? "替换" : "上传"}
                  <input
                    hidden
                    type="file"
                    accept=".txt,text/plain"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void send(preset.key, file, "");
                      event.target.value = "";
                    }}
                  />
                </label>
                {item ? (
                  <button className="btn-small btn-danger" type="button" onClick={() => void remove(item.id)}>
                    {confirmId === item.id ? "确认删除" : "删除"}
                  </button>
                ) : (
                  <span className="pill">未上传</span>
                )}
              </div>
            </div>
          );
        })}
        {custom.map((item) => (
          <div className="cookie-row" key={item.id}>
            <div className="job-main">
              <strong>{item.label}</strong>
              <div className="faint">自定义 · {formatBytes(item.size_bytes)}</div>
            </div>
            <button className="btn-small btn-danger" type="button" onClick={() => void remove(item.id)}>
              {confirmId === item.id ? "确认删除" : "删除"}
            </button>
          </div>
        ))}
      </div>
      <form className="form" onSubmit={paste} style={{ marginTop: 14 }}>
        <div className="cookie-line">
          <label className="field">
            <span>粘贴到</span>
            <select className="select" value={pasteSite} onChange={(event) => setPasteSite(event.target.value)}>
              {PRESETS.map((preset) => (
                <option key={preset.key} value={preset.key}>{preset.label}</option>
              ))}
              <option value="custom">自定义</option>
            </select>
          </label>
          {pasteSite === "custom" ? (
            <label className="field">
              <span>名称</span>
              <input className="input" value={customLabel} onChange={(event) => setCustomLabel(event.target.value)} placeholder="例如 Instagram" />
            </label>
          ) : null}
        </div>
        <label className="field">
          <span>Netscape cookies.txt</span>
          <textarea
            className="textarea"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="# Netscape HTTP Cookie File"
          />
        </label>
        <button className="btn btn-ghost" type="submit" disabled={pending || !content.trim()}>
          {pending ? "正在保存…" : "保存粘贴的 Cookie"}
        </button>
      </form>
      {message ? <p className="error" role="alert">{message}</p> : null}
      <details style={{ marginTop: 14 }}>
        <summary>如何导出 cookies.txt</summary>
        <ol>
          <li>在电脑浏览器安装扩展 “Get cookies.txt LOCALLY”，或任何能导出 Netscape 格式的工具。</li>
          <li>用你自己的账号登录抖音、小红书或微信网页版，并打开要保存的视频页。</li>
          <li>导出 cookies.txt。不要导出 JSON，也不要把 Cookie 发给别人，它等于登录态。</li>
          <li>在上面选择对应站点，上传或粘贴。视频号即使有 Cookie 也可能失败。</li>
        </ol>
      </details>
    </section>
  );
}
