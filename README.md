<div align="center">

# 🤖 VisionBot

**وكيل ذكاء اصطناعي يرى شاشتك ويتحكم فيها**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)](https://python.org)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-orange)](https://anthropic.com)
[![GPT-4V](https://img.shields.io/badge/GPT--4o-OpenAI-green)](https://openai.com)
[![Gemini](https://img.shields.io/badge/Gemini-Google-blue)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-white)](LICENSE)

</div>

---

## كيف يعمل؟

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   1. يلتقط لقطة شاشة                                   │
│          ↓                                              │
│   2. يرسلها + المهمة → LLM (Claude/GPT-4o/Gemini)     │
│          ↓                                              │
│   3. LLM يحلل: "أرى زر بحث في (450, 320)، سأنقر عليه"│
│          ↓                                              │
│   4. البوت ينقر بدقة على تلك الإحداثيات               │
│          ↓                                              │
│   5. يكرر حتى اكتمال المهمة                            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## التشغيل السريع

```
انقر مرتين على run.bat
```

أو من سطر الأوامر:
```bash
pip install -r requirements.txt
python vision_bot.py
```

---

## المتطلبات

```bash
# الأساسيات
pip install pyautogui pillow

# اختر مزوداً واحداً:
pip install anthropic          # Claude
pip install openai             # GPT-4o
pip install google-generativeai # Gemini
```

---

## أمثلة على المهام

```
"افتح المتصفح وابحث عن سعر الذهب اليوم"
"افتح Notepad واكتب فيه: مرحبا بالعالم"
"أغلق جميع النوافذ المفتوحة"
"انتقل إلى موقع github.com وسجل الدخول"
"خذ لقطة شاشة واحفظها على سطح المكتب"
```

---

## الفرق عن SmartBot Pro

| SmartBot Pro | VisionBot |
|-------------|-----------|
| يبحث عن صور محددة | يفهم الشاشة بالكامل |
| أنت تبرمج الخطوات | LLM يقرر الخطوات |
| لا يحتاج API | يحتاج مفتاح API |
| يعمل بدون إنترنت | يحتاج اتصال للـ API |
| مجاني تماماً | تكلفة API لكل طلب |

---

## الإيقاف الطارئ

> حرّك الماوس بسرعة لـ **الزاوية العلوية اليسرى** لإيقاف البوت فوراً

---

## الرخصة

MIT License
