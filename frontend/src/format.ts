const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export function isTerminal(status: string): boolean {
  return TERMINAL.has(status);
}

export function formatBytes(size: number | null | undefined): string {
  if (size == null) return "—";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`;
}

export function formatEta(seconds: number | null): string {
  if (seconds == null) return "剩余时间计算中";
  if (seconds < 5) return "即将完成";
  if (seconds < 60) return `剩余 ${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `剩余 ${minutes} 分 ${rest} 秒`;
  const hours = Math.floor(minutes / 60);
  return `剩余 ${hours} 小时 ${minutes % 60} 分`;
}

export function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatLimit(mb: number): string | null {
  if (mb <= 0) return null;
  if (mb % 1024 === 0) return `单文件上限 ${mb / 1024} GB`;
  return `单文件上限 ${mb} MB`;
}

export function formatQuality(quality: string): string {
  return quality === "best" ? "最佳" : `${quality}p`;
}

export function formatChoice(format: string): string {
  return (
    {
      mp4: "视频 MP4",
      mp3: "音频 MP3",
      m4a: "音频 M4A",
      best: "最佳可用",
    } as Record<string, string>
  )[format] ?? format;
}

const STARTED = "archive-started";
const SAVED = "archive-saved";

function readSet(key: string): Set<string> {
  return new Set((sessionStorage.getItem(key) || "").split(",").filter(Boolean));
}

function writeSet(key: string, values: Set<string>) {
  sessionStorage.setItem(key, [...values].join(","));
}

export function markStarted(id: string) {
  const values = readSet(STARTED);
  values.add(id);
  writeSet(STARTED, values);
}

export function wasStarted(id: string): boolean {
  return readSet(STARTED).has(id);
}

export function markSaved(id: string): boolean {
  const values = readSet(SAVED);
  if (values.has(id)) return false;
  values.add(id);
  writeSet(SAVED, values);
  return true;
}

export function newerJob<T extends { id: string; updated_at: string }>(prev: T | null, next: T): T {
  // A late event from the job we just left must not replace the one on screen.
  if (prev && prev.id !== next.id) return prev;
  if (prev && prev.updated_at > next.updated_at) return prev;
  return next;
}
