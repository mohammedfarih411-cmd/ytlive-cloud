#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""النظام الرئيسي للبث المباشر اليومي التلقائي دون إشعارات خارجية."""

import datetime
import glob
import json
import os
import subprocess
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BASE = os.path.dirname(os.path.abspath(__file__))
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TITLE = 100


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


def channel_videos_url(url):
    if "/videos" not in url and "playlist" not in url:
        return url.rstrip("/") + "/videos"
    return url


def list_channel_videos(channel_url, cookies_file):
    cmd = [
        "yt-dlp", "--flat-playlist", "--playlist-end", "200",
        "--print", "%(id)s", "--cookies", cookies_file,
        channel_videos_url(channel_url),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_title(video_id, cookies_file):
    cmd = [
        "yt-dlp", "--skip-download", "--print", "%(title)s",
        "--cookies", cookies_file,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def download_video(video_id, cookies_file, work_dir, fmt):
    for path in glob.glob(os.path.join(work_dir, "today.*")):
        os.remove(path)

    cmd = [
        "yt-dlp", "-f", fmt, "--cookies", cookies_file,
        "--merge-output-format", "mp4",
        "-o", os.path.join(work_dir, "today.%(ext)s"),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    subprocess.run(cmd, check=True)

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
    last_error = None

    for offset in range(max_attempts):
        position = (start_position + offset) % len(ids)
        candidate = ids[position]
        try:
            title = get_title(candidate, cookies) or "بث مباشر"
            title = cinfo.get("title_template", "{title}").format(
                title=title,
                date=datetime.date.today().isoformat(),
            )[:MAX_TITLE]
            log(f"تجربة الفيديو رقم {position + 1}: {candidate} — {title}")
            path = download_video(candidate, cookies, work, cfg["video_format"])
            return candidate, title, path, position_file, (position + 1) % len(ids)
        except subprocess.CalledProcessError as exc:
            last_error = exc
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            log(f"تعذر استخدام الفيديو {candidate}. تجربة التالي. {detail[:500]}")
        except Exception as exc:
            last_error = exc
            log(f"تعذر استخدام الفيديو {candidate}. تجربة التالي. {exc}")

    raise RuntimeError(
        f"تعذر إيجاد فيديو صالح بعد {max_attempts} محاولات: {last_error}"
    )


def main():
    cfg = load_config()
    try:
        channel = pick_today_channel(cfg)
        cinfo = cfg["channels"][channel]
        cookies = os.path.join(BASE, cinfo["cookies_file"])
        work = cfg["work_dir"]
        os.makedirs(work, exist_ok=True)

        log(f"قناة اليوم: {cinfo['name']} ({channel})")
        video_id, title, path, position_file, next_position = select_video(
            cfg, channel, cinfo, cookies, work
        )
        log(f"الفيديو المختار: {video_id} — {title}")
        log(f"تم التنزيل: {path}")

        youtube = build("youtube", "v3", credentials=get_credentials(channel))
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
