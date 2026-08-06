#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""النظام الرئيسي لرفع فيديو يومي تلقائي (رفع عادي، وليس بثًا مباشرًا) دون إشعارات خارجية."""

import datetime
import glob
import json
import os
import random
import shutil
import subprocess
import sys
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

BASE = os.path.dirname(os.path.abspath(__file__))
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TITLE = 100
SHORT_MAX_SECONDS = 60
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


def video_duration_seconds(video_path):
    """Probe a local video file's duration with ffprobe. Returns None if it
    can't be determined (never fails the whole run over a missing duration)."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return float(result.stdout.strip())
    except (ValueError, OSError):
        return None


def upload_video(youtube, video_path, title, description, category_id, privacy, tags=None):
    """Upload a regular (non-live) video with resumable upload + retry on
    transient server errors, per Google's documented upload pattern."""
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if tags:
        body["snippet"]["tags"] = tags

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retries = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                log(f"رفع الفيديو: {int(status.progress() * 100)}%")
        except HttpError as exc:
            if exc.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                wait = min(60, 2 ** retries) + random.uniform(0, 1)
                log(f"خطأ خادم مؤقت أثناء الرفع ({exc.resp.status})، إعادة محاولة خلال {wait:.0f} ثانية...")
                time.sleep(wait)
                continue
            raise

    return response["id"]


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
            source_title = get_title(candidate, cookies)
            title = cinfo.get("title_template", "{title}").format(
                title=source_title,
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
                # spending time and bandwidth on a channel that cannot upload.
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

        duration = video_duration_seconds(path)
        is_short = duration is not None and duration <= SHORT_MAX_SECONDS
        description = cinfo.get("description", "")
        if is_short:
            if "#Shorts" not in description:
                description = (description + "\n\n#Shorts").strip()
            if "#Shorts" not in title:
                title = (title + " #Shorts")[:MAX_TITLE]
        duration_label = f"{duration:.0f}ث" if duration is not None else "غير معروفة"
        log(f"مدة الفيديو: {duration_label} — {'Shorts' if is_short else 'فيديو عادي'}")

        youtube = build("youtube", "v3", credentials=credentials)
        uploaded_id = upload_video(
            youtube,
            path,
            title,
            description,
            cinfo.get("category_id", "20"),
            cinfo.get("privacy", "public"),
        )
        log(f"تم رفع الفيديو: https://www.youtube.com/watch?v={uploaded_id}")

        with open(position_file, "w", encoding="utf-8") as f:
            f.write(str(next_position))
        log(f"انتهى الرفع. الفيديو التالي في القائمة: {next_position + 1}")
    except Exception as exc:
        log(f"خطأ: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
