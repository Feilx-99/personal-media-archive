import { useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "./api.ts";
import Mark from "./Mark.tsx";
import type { Me } from "./types.ts";

export default function LoginScreen({ onSuccess }: { onSuccess: (me: Me) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const me = await api<Me>("/api/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      onSuccess(me);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="panel login-card" onSubmit={submit}>
        <div className="brand">
          <Mark />
          <div>
            <p className="eyebrow">Personal archive</p>
            <strong>个人媒体存档</strong>
          </div>
        </div>
        <h1 className="login-title">登录后才能下载</h1>
        <p className="lede login-copy">
          这是私人工具。用户名和口令来自服务器的 AUTH_USERNAME / AUTH_PASSWORD。
        </p>
        <label className="field">
          <span>用户名</span>
          <input className="input" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="field">
          <span>口令</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <p className="error" role="alert">{error}</p> : null}
        <button className="btn btn-primary" type="submit" disabled={pending || !password}>
          {pending ? "正在核对…" : "进入"}
        </button>
        <p className="faint">只保存你有权访问的内容。不要把这台服务开放成匿名下载站。</p>
      </form>
    </div>
  );
}
