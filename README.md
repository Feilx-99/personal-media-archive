# 个人媒体存档

自用的视频下载小站。把一条视频链接交给 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，在你自己的服务器上保存成文件。界面以中文为主。

它不是公开的下载站。所有下载接口都要先登录，口令来自环境变量 `AUTH_PASSWORD`。

适合保存你有权访问的内容：自己的投稿、已经获授权的素材、权利人允许下载的公开视频。

## 功能

- 粘贴链接后选择格式：合并后的视频 MP4、仅音频 MP3、仅音频 M4A，或最佳可用（不强制转成 MP4）
- 可选清晰度：1080p、720p、480p、最佳
- 通过 Server-Sent Events 显示进度、速度和剩余时间；代理把 SSE 缓冲掉时，页面仍会每 2 秒轮询
- 上传或粘贴 Netscape `cookies.txt`，按站点保存，下载时传给 yt-dlp `--cookies`
- 最近任务、失败原因、文件还在磁盘上时可以再次下载
- 超过 `RETENTION_DAYS`（默认 3 天）的文件自动删除，历史记录保留
- 最多同时下载 `MAX_CONCURRENT` 个（默认 2），多出来的排队
- 拒绝非 http(s) 链接，以及指向本机、内网和云元数据地址的链接
- `GET /healthz` 给平台做健康检查，不需要登录

YouTube、哔哩哔哩、X 是优先支持的站点。抖音、小红书、视频号和其他 yt-dlp 能识别的站点是尽力而为：很多时候必须有你自己的 Cookie，而且站点一改版就可能失败。失败时页面会直接说明是不是要 Cookie。

## 用 Docker 本地运行

需要 Docker，以及镜像里会装好的 ffmpeg、Deno 和 yt-dlp。

```bash
docker compose up --build
```

浏览器打开 <http://127.0.0.1:8787>。

默认登录：

- 用户名 `admin`
- 口令 `changeme`

这个口令只适合本机试试。页面上会一直提示它太简单。准备放到公网之前，先在项目目录写一个 `.env`：

```bash
cp .env.example .env
```

把 `AUTH_PASSWORD` 改成至少 12 位的随机口令，然后重新 `docker compose up --build`。

数据在三个卷里：

| 卷 | 容器路径 | 内容 |
| --- | --- | --- |
| `archive_downloads` | `/data/downloads` | 下好的视频和音频 |
| `archive_cookies` | `/data/cookies` | cookies.txt |
| `archive_db` | `/data/db` | SQLite 任务记录 |

想在当前目录直接看到文件，可以把 `docker-compose.yml` 里的卷改成绑定挂载：`./data/downloads:/data/downloads`，cookies 和 db 同理。

## 不用 Docker 开发

本机需要 Python 3.12、Node.js 22、ffmpeg。YouTube 还需要 Deno，或至少 Node.js 20 以上（程序会自动启用 PATH 里的 `deno` 或 `node`）。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cd frontend
npm install
npm run build
cd ..

export AUTH_PASSWORD='please-change-this-password'
export DATA_DIR=./data
export COOKIE_SECURE=0
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

打开 <http://127.0.0.1:8787>。

改界面时可以另开一个终端：

```bash
cd frontend
npm run dev
```

Vite 在 <http://127.0.0.1:5197>，并把 `/api` 代理到 8787。

测试：

```bash
pytest
```

## 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `AUTH_USERNAME` | `admin` | 登录用户名 |
| `AUTH_PASSWORD` | 空，拒绝启动 | 登录口令。公网部署必填，至少 12 位 |
| `AUTH_PASSWORD_FILE` | 空 | 从文件读口令，适合 Docker secret。设置后优先于 `AUTH_PASSWORD` |
| `AUTH_SECRET` | 由口令派生 | 签发会话 cookie 的密钥。换口令会让旧会话失效；固定这个值可以分开轮换 |
| `DATA_DIR` | `./data` | 下载、Cookie、数据库的根目录。容器里是 `/data` |
| `RETENTION_DAYS` | `3` | 保留完成文件的天数。`0` 表示不自动删 |
| `MAX_CONCURRENT` | `2` | 同时进行的下载数 |
| `MAX_FILESIZE_MB` | `2048` | 单文件上限，兆字节。`0` 表示不限制 |
| `MAX_DURATION_SEC` | `0` | 最长时长，秒。`0` 表示不限制 |
| `SESSION_DAYS` | `14` | 登录保持天数 |
| `COOKIE_SECURE` | `0` | 设为 `1` 时会话 cookie 带 Secure。HTTPS 公网部署要开；本机 http 必须关，否则登录态存不住 |
| `PORT` | `8787` | 监听端口。Railway、Render 会注入自己的 `PORT` |
| `PROXY_HEADERS` | 镜像里为 `1`，compose 里为 `0` | 为 `1` 时信任 `X-Forwarded-*`。平台反代后面要开 |
| `STATIC_DIR` | 自动找 `frontend/dist` 或 `/app/static` | 前端构建结果 |

也可以用项目根目录的 `.env`。已经存在于环境里的变量不会被 `.env` 覆盖。

## 公开部署

三件事要同时满足，否则不要暴露到公网：

1. `AUTH_PASSWORD` 是长随机口令，不要用 `changeme`
2. 平台提供 HTTPS，并设置 `COOKIE_SECURE=1`
3. 有一块持久磁盘挂在 `/data`。没有磁盘的话，每次重新部署都会丢掉视频、Cookie 和历史

下载和 ffmpeg 合并比较吃内存，建议至少 1 GB。机器休眠或缩到 0 会把正在进行的下载打断，所以不要开启“空闲自动关机”。

应用监听 `PORT`（默认 8787），健康检查路径是 `/healthz`。

### Railway

1. 用这个仓库创建服务，构建方式选 Dockerfile（已写在 `railway.toml`）。
2. 在服务里加一块 Volume，挂载路径填 `/data`。
3. 设置变量：`AUTH_PASSWORD`、`AUTH_SECRET`（随机长字符串）、`AUTH_USERNAME`、`COOKIE_SECURE=1`、`DATA_DIR=/data`。`PORT` 让 Railway 自己注入。
4. 部署后打开 Railway 给的 HTTPS 地址，用你设置的口令登录。

### Fly.io

```bash
# 把 fly.toml 里的 app 改成你的应用名
fly launch --no-deploy --copy-config
fly volumes create archive_data --size 10 --region hkg
fly secrets set AUTH_PASSWORD='一段足够长的口令' AUTH_SECRET='另一段随机字符串'
fly deploy
```

`fly.toml` 把卷挂到 `/data`，`auto_stop_machines` 是 `off`，避免下载做到一半机器被关掉。区域 `hkg` 可以改成离你更近的。

### Render

`render.yaml` 是一个 Docker Web Service，磁盘 `archive-data` 挂在 `/data`，容量 10 GB。Render 的免费实例没有持久磁盘，需要能挂磁盘的套餐。

用 Blueprint 创建时，`AUTH_PASSWORD` 留空是故意的，要在面板里填上。`AUTH_SECRET` 会自动生成。

## Cookie：抖音、小红书、视频号

Cookie 等于你的登录态。只放在你自己的服务器上，不要提交到 git，不要发给别人。

1. 在电脑浏览器安装能导出 Netscape 格式的扩展，例如 “Get cookies.txt LOCALLY”。
2. 用你自己的账号打开对应网站，并停在视频页上。
   - 抖音：`douyin.com`
   - 小红书：`xiaohongshu.com`
   - 视频号：已登录的微信网页里打开视频页。视频号经常改接口，即使 Cookie 正确也可能失败
   - 哔哩哔哩：只有要大会员清晰度或受限视频时才需要
   - YouTube：公开视频通常不用。如果提示人机验证，再导出 YouTube 的 Cookie
3. 导出 `cookies.txt`。文件开头一般是 `# Netscape HTTP Cookie File`，中间是制表符分隔的列。JSON 或请求头不能用。
4. 在页面的「站点 Cookie」里选择对应站点，上传或粘贴。同一站点再次上传会替换旧文件。全局 Cookie 只在没有站点专用文件时使用。
5. 回到上面重新下载。也可以在表单里把 Cookie 从「自动匹配」改成某一份。

## 更新 yt-dlp

YouTube 和其他站点会经常改页面。镜像构建时会再执行一次 `pip install -U "yt-dlp[default,curl-cffi]"`，所以重新构建就会拿到当时的最新版：

```bash
docker compose build --pull --no-cache
docker compose up -d
```

临时在正在运行的容器里升级（容器一重建就没了，持久做法还是重新构建）：

```bash
docker compose exec app pip install -U "yt-dlp[default,curl-cffi]"
docker compose restart app
```

YouTube 还依赖镜像里的 Deno。要换 Deno，修改 `Dockerfile` 的 `DENO_VERSION` 后再构建。本机如果没有 Deno，程序会改用 Node.js。

页面页脚会显示当前 yt-dlp 版本。`/healthz` 也会返回 `ytdlp`、`ffmpeg` 和运行时信息。

## 法律说明

这个仓库是个人归档工具，下载能力来自 yt-dlp，没有额外的爬虫。请只用它保存你有权访问的内容，并遵守来源站点的条款和你所在地的法律。不要用它再分发别人的作品，也不要把它做成没有登录、谁都能用的公开下载服务。作者和部署者各自对自己的使用方式负责。
