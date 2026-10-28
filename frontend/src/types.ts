export type Me = {
  username: string;
  retention_days: number;
  max_concurrent: number;
  max_filesize_mb: number;
  max_duration_sec: number;
  password_is_weak: boolean;
  ytdlp: string;
  ffmpeg: boolean;
  js_runtime: string | null;
};

export type Job = {
  id: string;
  url: string;
  title: string | null;
  site_key: string | null;
  site_label: string | null;
  format: string;
  quality: string;
  status: string;
  phase: string | null;
  message: string;
  error: string | null;
  error_detail: string | null;
  needs_cookies: boolean;
  file_ready: boolean;
  file_size: number | null;
  percent: number | null;
  speed: string | null;
  eta: number | null;
  duration_sec: number | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  download_url: string | null;
};

export type CookieItem = {
  id: string;
  site_key: string;
  label: string;
  size_bytes: number;
  created_at: string;
  updated_at: string;
};

export type Inspect = {
  ok: boolean;
  error: string | null;
  site_key: string | null;
  site_label: string | null;
  needs_cookies_likely: boolean;
  hint: string | null;
  cookie_ready: boolean;
  cookie_source: string | null;
};
