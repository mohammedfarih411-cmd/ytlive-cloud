# YTLIVE — ملف تعريف المشروع

## الغرض
هذا الملف يُستخدم لتعريف مشروع **YTLIVE** عند فتح محادثة جديدة في أي حساب ChatGPT.
ارفع هذا الملف في المحادثة الجديدة واطلب: **"تابع مشروع YTLIVE من هذا الملف"**.

## هوية المشروع
- اسم المشروع: `ytlive`
- مستودع GitHub: `mohammedfarih411-cmd/ytlive-cloud`
- رابط المستودع:
  `https://github.com/mohammedfarih411-cmd/ytlive-cloud`
- النظام: بث يومي تلقائي إلى قنوات YouTube باستخدام Python وFFmpeg وyt-dlp وGitHub Actions.

## ملفات المشروع الأساسية
- `daily_live.py`
- `config.json`
- `requirements.txt`
- `.github/workflows/daily_live.yml`
- `.gitignore`
- `authorize.py`
- `notify.py`

## الملفات السرية المحلية
هذه الملفات لا تُرفع إلى GitHub:
- `cookies.txt`
- `client_secret.json`
- `token_channel11.json`
- `token_channel12.json`
- `token_channel13.json`
- `token_channel14.json`
- مجلد `work/`

## GitHub Actions Secrets
الأسرار الموجودة في المستودع:
- `COOKIES_B64`
- `TOKEN_CHANNEL11_B64`
- `TOKEN_CHANNEL12_B64`
- `TOKEN_CHANNEL13_B64`
- `TOKEN_CHANNEL14_B64`

مهم: لا تُكتب قيم هذه الأسرار في أي محادثة أو ملف عام.

## القنوات
يستخدم المشروع أسماء داخلية:
- `channel11`
- `channel12`
- `channel13`
- `channel14`

ويتم اختيار قناة اليوم حسب:
```json
"schedule_order": ["channel11", "channel12", "channel13", "channel14"]
```

## الجدولة
ملف GitHub Actions:
`.github/workflows/daily_live.yml`

الهدف:
- التشغيل يوميًا في المساء.
- التوقيت المطلوب: الساعة 20:00 بتوقيت إيطاليا.
- التشغيل من GitHub حتى عندما يكون الكمبيوتر مغلقًا.
- الحد الأقصى التقريبي للمهمة أقل من 6 ساعات.

## حالة الخصوصية
آخر إعداد معروف في `config.json`:
```json
"privacy": "private"
```

هذا يعني أن البث يُنشأ كخاص.
قبل جعله عامًا يجب تعديل الكود أو الإعداد بوضوح وعدم الافتراض أن التحويل إلى `public` يحدث تلقائيًا.

## إيقاف البث
### إذا كان محليًا
داخل Terminal:
```text
Ctrl + C
```

### إذا كان من GitHub Actions
- افتح المستودع.
- افتح `Actions`.
- افتح التشغيل الجاري.
- اختر `Cancel workflow`.

## نقاط أمان مهمة
1. لا ترفع ملفات `token_channel*.json`.
2. لا ترفع `cookies.txt`.
3. لا ترفع `client_secret.json`.
4. لا تنشر قيم GitHub Secrets.
5. افحص `git status` قبل كل `git push`.
6. شغّل البث أولًا بوضع `private` عند الاختبار.
7. لا تفترض أن البث انتهى لمجرد اختفاء النافذة؛ تحقق من YouTube Studio أو GitHub Actions.

## صيغة الطلب في محادثة ChatGPT جديدة
بعد رفع هذا الملف، اكتب:
> تابع مشروع YTLIVE من ملف التعريف المرفق. لا تغيّر أي إعداد قبل التأكد من الحالة الحالية للمستودع وملفات المشروع.

## ملاحظة مهمة
هذا الملف لا يسمح لـChatGPT بمعرفة حسابك تلقائيًا، ولا يربط بين حسابات ChatGPT.
هو فقط ملف تسليم آمن يحمل سياق المشروع، بحيث يمكن لأي محادثة جديدة فهم المشروع دون إعادة شرح كل الخطوات.
