#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify.py — إرسال إشعارات عبر تيليجرام باستخدام مكتبات بايثون القياسية فقط."""

import urllib.parse
import urllib.request


def send_telegram(token, chat_id, text):
    """يرسل رسالة إلى محادثة/قناة تيليجرام. يتجاهل الإرسال إن نقصت البيانات."""
    if not token or not chat_id:
        return

    # يدعم chat_id واحدًا أو قائمة من المعرّفات
    targets = chat_id if isinstance(chat_id, list) else [chat_id]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for target in targets:
        data = urllib.parse.urlencode({
            "chat_id": str(target),
            "text": text,
            "disable_web_page_preview": "false",
        }).encode("utf-8")
        try:
            with urllib.request.urlopen(url, data=data, timeout=20) as resp:
                resp.read()
        except Exception as e:  # لا نوقف البث بسبب فشل الإشعار
            print("تعذّر إرسال إشعار تيليجرام:", e, flush=True)
