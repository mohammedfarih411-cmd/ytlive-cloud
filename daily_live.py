#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_live.py — النظام الرئيسي للبث المباشر اليومي التلقائي.

الخطوات:
  1) تحديد قناة اليوم بالتناوب (دورة من أربع قنوات).
  2) سحب قائمة فيديوهات القناة عبر yt-dlp ثم اختيار واحد عشوائيًا.
  3) تنزيل الفيديو المختار.
  4) إنشاء بث مباشر جديد بعنوانٍ خاص عبر YouTube Live API (تشغيل/إيقاف تلقائي).
  5) دفع الفيديو عبر FFmpeg إلى عنوان الإدخال (RTMP).
  6) إرسال إشعارات تيليجرام (بدء / انتهاء / خطأ).
"""

import os
import sys
import json
import glob
import datetime
import subprocess

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import notify

BASE = os.path.dirname(os.path.abspath(__file__))
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TITLE = 100


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_config():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def tg_send(cfg, text):
    tg = (cfg or {}).get("telegram", {})
    if not tg.get("enabled"):
        return
    notify.send_telegram(tg.get("bot_token"), tg.get("chat_id"), text)


def pick_today_channel(cfg):
    order = cfg["schedule_order"]
    epoch = datetime.date.fromisoformat(cfg["epoch_date"])
    today = datetime.date.today()
    idx = (today - epoch).days % len(order)
    return order[idx]


def get_credentials(cfg, channel):
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


def _channel_videos_url(url):
    if "/videos" not in url and "playlist" not in url:
        return url.rstrip("/") + "/videos"
    return url


def list_channel_videos(channel_url, cookies_file):
    url = _channel_videos_url(channel_url)
    cmd = [
        "yt-dlp", "--flat-playlist", "--playlist-end", "200",
        "--print", "%(id)s",
        "--cookies", cookies_file, url,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def get_title(video_id, cookies_file):
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = ["yt-dlp", "--skip-download", "--print", "%(title)s",
           "--cookies", cookies_file, url]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def download_video(video_id, cookies_file, work_dir, fmt):
    for f in glob.glob(os.path.join(work_dir, "today.*")):
        os.remove(f)
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp", "-f", fmt, "--cookies", cookies_file,
        "--merge-output-format", "mp4",
        "-o", os.path.join(work_dir, "today.%(ext)s"), url,
    ]
    subprocess.run(cmd, check=True)
    files = glob.glob(os.path.join(work_dir, "today.*"))
    if not files:
        raise RuntimeError("فشل التنزيل: لا يوجد ملف ناتج.")
    files.sort(key=lambda p: (not p.endswith(".mp4"), p))
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
    broadcast_id = broadcast["id"]

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
    stream_id = stream["id"]
    info = stream["cdn"]["ingestionInfo"]
    ingest_url = info["ingestionAddress"] + "/" + info["streamName"]

    youtube.liveBroadcasts().bind(
        id=broadcast_id, part="id,contentDetails", streamId=stream_id
    ).execute()

    return broadcast_id, ingest_url


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
        cmd = ["ffmpeg", "-re", "-i", video_path, "-c", "copy",
               "-f", "flv", ingest_url]
    subprocess.run(cmd, check=True)


def main():
    cfg = load_config()
    channel_name = "?"
    try:
        channel = pick_today_channel(cfg)
        cinfo = cfg["channels"][channel]
        channel_name = cinfo["name"]
        cookies = os.path.join(BASE, cinfo["cookies_file"])
        work = cfg["work_dir"]
        os.makedirs(work, exist_ok=True)

        log(f"قناة اليوم: {channel_name} ({channel})")

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
        ordered_items = [
            ((start_position + offset) % len(ids), ids[(start_position + offset) % len(ids)])
            for offset in range(len(ids))
        ]
        max_attempts = min(10, len(ordered_items))
        last_error = None
        path = None
        video_id = None
        title = None
        next_position = start_position

        for item_position, candidate in ordered_items[:max_attempts]:
            try:
                candidate_title = get_title(candidate, cookies) or "بث مباشر"
                today = datetime.date.today().isoformat()
                candidate_title = cinfo.get("title_template", "{title}").format(
                    title=candidate_title, date=today
                )
                candidate_title = candidate_title[:MAX_TITLE]

                log(
                    f"تجربة الفيديو رقم {item_position + 1} من القائمة: "
                    f"{candidate} — {candidate_title}"
                )
                candidate_path = download_video(
                    candidate, cookies, work, cfg["video_format"]
                )

                video_id = candidate
                title = candidate_title
                path = candidate_path
                next_position = (item_position + 1) % len(ids)
                break
            except subprocess.CalledProcessError as exc:
                last_error = exc
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                log(f"تعذر استخدام الفيديو {candidate}; تجربة الفيديو التالي. {detail[:500]}")
            except Exception as exc:
                last_error = exc
                log(f"تعذر استخدام الفيديو {candidate}; تجربة الفيديو التالي. {exc}")

        if not path:
            raise RuntimeError(
                f"تعذر إيجاد فيديو صالح بعد {max_attempts} محاولات: {last_error}"
            )

        log(f"الفيديو المختار: {video_id} — {title}")
        log(f"تم التنزيل: {path}")

        creds = get_credentials(cfg, channel)
        youtube = build("youtube", "v3", credentials=creds)
        broadcast_id, ingest_url = create_live(
            youtube, title, cinfo.get("description", ""), cinfo.get("privacy", "public")
        )
        watch_url = f"https://www.youtube.com/watch?v={broadcast_id}"
        log(f"تم إنشاء البث: {broadcast_id}")

        tg_send(cfg, f"🔴 بدأ البث المباشر\nالقناة: {channel_name}\nالعنوان: {title}\n{watch_url}")

        log("بدء الدفع عبر FFmpeg... (سيتحول البث إلى مباشر تلقائيًا)")
        stream_ffmpeg(path, ingest_url, cfg.get("reencode", True))

        with open(position_file, "w", encoding="utf-8") as f:
            f.write(str(next_position))
        log(f"انتهى البث. الفيديو التالي في القائمة: {next_position + 1}")

        tg_send(cfg, f"✅ انتهى البث\nالقناة: {channel_name}\nالعنوان: {title}")

    except Exception as e:
        log(f"خطأ: {e}")
        tg_send(cfg, f"⚠️ خطأ في نظام البث\nالقناة: {channel_name}\nالتفاصيل: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
