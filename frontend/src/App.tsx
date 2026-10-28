import { useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api.ts";
import Board from "./Board.tsx";
import LoginScreen from "./LoginScreen.tsx";
import type { Me } from "./types.ts";

export default function App() {
  const [session, setSession] = useState<"loading" | "in" | "out">("loading");
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setMe(null);
      setSession("out");
    });
    void api<Me>("/api/me")
      .then((profile) => {
        setMe(profile);
        setSession("in");
      })
      .catch(() => setSession("out"));
  }, []);

  async function logout() {
    try {
      await api("/api/logout", { method: "POST" });
    } catch {
      /* the session is already gone */
    }
    setMe(null);
    setSession("out");
  }

  if (session === "loading") return <div className="boot">正在确认登录状态…</div>;
  if (session === "out" || !me) return <LoginScreen onSuccess={(profile) => { setMe(profile); setSession("in"); }} />;
  return <Board me={me} onLogout={() => void logout()} />;
}
