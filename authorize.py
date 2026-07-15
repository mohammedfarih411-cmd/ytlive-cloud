#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
authorize.py — تفويض قناة واحدة والحصول على مفتاح تحديث (Refresh Token).

يُشغَّل مرة واحدة لكل قناة (أربع مرات) على جهازك الشخصي الذي فيه متصفح.
بعدها انسخ ملفات token_channelX.json إلى الخادم.

الاستخدام:
    python authorize.py client_secret.json token_channel1.json

عند التشغيل سيفتح المتصفح: سجّل الدخول بالحساب الذي يملك القناة،
واختر القناة الصحيحة (أو الحساب ذي العلامة التجارية) عند السؤال.
"""

import sys
from google_auth_oauthlib.flow import InstalledAppFlow

# صلاحية إدارة البث المباشر على القناة
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def main():
    if len(sys.argv) != 3:
        print("الاستخدام: python authorize.py <client_secret.json> <token_out.json>")
        sys.exit(1)

    client_secret = sys.argv[1]
    token_out = sys.argv[2]

    flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
    # access_type=offline + prompt=consent مطلوبان للحصول على refresh token
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )

    with open(token_out, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print("تم الحفظ بنجاح في:", token_out)


if __name__ == "__main__":
    main()
