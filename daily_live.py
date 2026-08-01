
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""النظام الرئيسي للبث المباشر اليومي التلقائي دون إشعارات خارجية."""
 
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
 
BASE = os.path.dirname(os.path.abspath(__file__))
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TITLE = 100
POT_SERVER_HOME = os.path.join(BASE, "bgutil-ytdlp-pot-provider", "server")


def pot_extractor_args():
    """Use the bgutil PO token provider when it has been set up (e.g. in
    CI), otherwise fall back to plain cookie-based auth (e.g. a local/VM
    run where the provider isn't installed)."""
    if os.path.isdir(POT_SERVER_HOME):
        return [
            "--extractor-args",
            f"youtubepot-bgutilscript:server_home={POT_SERVER_HOME}",
        ]
    return []
 
 
def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)
 
 
def load_config():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f)
 
 
def pick_today_channel(cfg):
    order = cfg["schedule_order"]
    epoch = datetime.date.fromisoformat(cfg["epoch_date"])
    today = datetime.date.today()
    return order[(today - epoch).days % len(order)]
 
 
def get_credentials(channel):
    token_file = os.path.join(BASE, f"token_{channel}.json")
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(f"التفويض غير صالح للقناة {channel}. أعد authorize.py.")
    return creds
 
 
def channel_content_urls(url):
    """Return useful YouTube channel tabs in a stable, de-duplicated order."""
    url = url.rstrip("/")
    if "playlist" in url:
        return [url]
 
    for suffix in ("/videos", "/shorts", "/streams"):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
            break
 
    candidates = [url + "/videos", url + "/shorts", url]
    return list(dict.fromkeys(candidates))
 
 
def list_channel_videos(channel_url, cookies_file):
    """List videos without aborting on a broken or empty YouTube tab."""
    collected = []
    diagnostics = []
 
    for content_url in channel_content_urls(channel_url):
        cmd = [
            sys.executable, "-m", "yt_dlp", "--flat-playlist", "--playlist-end", "200",
            "--ignore-errors", "--print", "%(id)s", "--cookies", cookies_file,
            "--no-warnings",
            *pot_extractor_args(),
            content_url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        collected.extend(ids)

        if result.returncode != 0:
            detail = (
                f"[exit={result.returncode}] "
                f"stdout={result.stdout.strip()[:200]!r} "
                f"stderr={result.stderr.strip()[:200]!r}"
            )
            diagnostics.append(f"{content_url}: {detail[:400]}")
 
    ids = list(dict.fromkeys(collected))
    if ids:
        return ids
 
    detail = " | ".join(diagnostics) or "no videos were returned"
    raise RuntimeError(f"تعذر قراءة فيديوهات القناة: {detail}")
 
 
def get_title(video_id, cookies_file):
    cmd = [
        sys.executable, "-m", "yt_dlp", "--skip-download", "--print", "%(title)s",
        "--cookies", cookies_file,
        "--no-warnings",
        *pot_extractor_args(),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        detail = (
            f"[exit={result.returncode}] "
            f"stdout={result.stdout.strip()[:200]!r} "
            f"stderr={result.stderr.strip()[:200]!r}"
        )
        raise RuntimeError(f"get_title فشل لهذا الفيديو {video_id}: {detail[:500]}")
    return result.stdout.strip()
 
 
def download_video(video_id, cookies_file, work_dir, fmt):
    for path in glob.glob(os.path.join(work_dir, "today.*")):
        os.remove(path)
 
    cmd = [
        sys.executable, "-m", "yt_dlp", "-f", fmt, "--cookies", cookies_file,
        "--merge-output-format", "mp4",
        "--no-warnings",
        *pot_extractor_args(),
        "-o", os.path.join(work_dir, "today.%(ext)s"),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        detail = (
            f"[exit={result.returncode}] "
            f"stdout={result.stdout.strip()[:200]!r} "
            f"stderr={result.stderr.strip()[:200]!r}"
        )
        raise RuntimeError(f"download_video فشل لهذا الفيديو {video_id}: {detail[:500]}")
 
    files = glob.glob(os.path.join(work_dir, "today.*"))
    if not files:
        raise RuntimeError("فشل التنزيل: لا يوجد ملف ناتج.")
    files.sort(key=lambda path: (not path.endswith(".mp4"), path))
    return files[0]
 
 
def create_live(youtube, title, description, privacy):
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    broadcast = youtube.liveBroadcasts().insert(
        part="snippet,status,contentDetails",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "scheduledStartTime": now,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
            "contentDetails": {
                "enableAutoStart": True,
                "enableAutoStop": True,
            },
        },
    ).execute()
 
    stream = youtube.liveStreams().insert(
        part="snippet,cdn,contentDetails",
        body={
            "snippet": {"title": title},
            "cdn": {
                "ingestionType": "rtmp",
                "resolution": "1080p",
                "frameRate": "30fps",
            },
            "contentDetails": {"isReusable": False},
        },
    ).execute()
 
    info = stream["cdn"]["ingestionInfo"]
    ingest_url = info["ingestionAddress"] + "/" + info["streamName"]
    youtube.liveBroadcasts().bind(
        id=broadcast["id"],
        part="id,contentDetails",
        streamId=stream["id"],
    ).execute()
    return broadcast["id"], ingest_url
 
 
def stream_ffmpeg(video_path, ingest_url, reencode):
    if reencode:
        cmd = [
            "ffmpeg", "-re", "-i", video_path,
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", "4500k", "-maxrate", "4500k", "-bufsize", "9000k",
            "-pix_fmt", "yuv420p", "-g", "60", "-r", "30",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-f", "flv", ingest_url,
        ]
    else:
        cmd = [
            "ffmpeg", "-re", "-i", video_path,
            "-c", "copy", "-f", "flv", ingest_url,
        ]
    subprocess.run(cmd, check=True)
 
 
def select_video(cfg, channel, cinfo, cookies, work):
    ids = list_channel_videos(cinfo["youtube_channel_url"], cookies)
    if not ids:
        raise RuntimeError("لا توجد فيديوهات في القناة.")
 
    position_file = os.path.join(work, f"playlist_position_{channel}.txt")
    try:
        with open(position_file, encoding="utf-8") as f:
            start_position = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        start_position = 0
 
    start_position %= len(ids)
    max_attempts = min(10, len(ids))
    last_detail = "unknown error"
 
    for offset in range(max_attempts):
        position = (start_position + offset) % len(ids)
        candidate = ids[position]
        try:
            title = "بث مباشر"
            title = cinfo.get("title_template", "{title}").format(
                title=title,
                date=datetime.date.today().isoformat(),
            )[:MAX_TITLE]
            log(f"تجربة الفيديو رقم {position + 1}: {candidate} — {title}")
            path = download_video(candidate, cookies, work, cfg["video_format"])
            return candidate, title, path, position_file, (position + 1) % len(ids)
        except Exception as exc:
            last_detail = str(exc)
            log(f"تعذر استخدام الفيديو {candidate}. تجربة التالي. {last_detail[:500]}")
 
    raise RuntimeError(
        f"تعذر إيجاد فيديو صالح بعد {max_attempts} محاولات: {last_detail[:800]}"
    )
 
 
def candidate_channels(cfg):
    """Try today's channel first, then the remaining configured channels."""
    order = cfg["schedule_order"]
    first = pick_today_channel(cfg)
    start = order.index(first)
    return order[start:] + order[:start]
 
 
def main():
    log(f"yt-dlp resolved to: {shutil.which('yt-dlp')}")
    log(f"ffmpeg resolved to: {shutil.which('ffmpeg')}")
    cfg = load_config()
    try:
        work = cfg["work_dir"]
        os.makedirs(work, exist_ok=True)
        selected = None
        failures = []
 
        for channel in candidate_channels(cfg):
            cinfo = cfg["channels"][channel]
            cookies = os.path.join(BASE, cinfo["cookies_file"])
            log(f"تجربة القناة: {cinfo['name']} ({channel})")
            try:
                if not os.path.isfile(cookies) or os.path.getsize(cookies) == 0:
                    raise RuntimeError(
                        f"ملف Cookies غير متاح لهذه القناة: {cinfo['cookies_file']}"
                    )
 
                # Validate OAuth before listing or downloading any video. This avoids
                # spending time and bandwidth on a channel that cannot go live.
                credentials = get_credentials(channel)
                video = select_video(cfg, channel, cinfo, cookies, work)
                selected = (channel, cinfo, cookies, credentials, video)
                break
            except Exception as exc:
                failures.append(f"{channel}: {exc}")
                log(f"تخطي القناة {channel}: {exc}")
 
        if selected is None:
            raise RuntimeError(
                "تعذر العثور على قناة جاهزة وفيديو صالح: "
                + " | ".join(failures)
            )
 
        channel, cinfo, cookies, credentials, video = selected
        video_id, title, path, position_file, next_position = video
        log(f"الفيديو المختار: {video_id} — {title}")
        log(f"تم التنزيل: {path}")
 
        youtube = build("youtube", "v3", credentials=credentials)
        broadcast_id, ingest_url = create_live(
            youtube,
            title,
            cinfo.get("description", ""),
            cinfo.get("privacy", "public"),
        )
        log(f"تم إنشاء البث: https://www.youtube.com/watch?v={broadcast_id}")
        log("بدء الدفع عبر FFmpeg...")
        stream_ffmpeg(path, ingest_url, cfg.get("reencode", True))
 
        with open(position_file, "w", encoding="utf-8") as f:
            f.write(str(next_position))
        log(f"انتهى البث. الفيديو التالي في القائمة: {next_position + 1}")
    except Exception as exc:
        log(f"خطأ: {exc}")
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
 
