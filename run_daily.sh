#!/usr/bin/env bash
# run_daily.sh — يشغّله cron يوميًا. يكتب السجل في daily.log
set -euo pipefail
cd "$(dirname "$0")"
python3 daily_live.py >> daily.log 2>&1
