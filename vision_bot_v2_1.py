"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   ██╗   ██╗██╗███████╗██╗ ██████╗ ███╗   ██╗██████╗  ██████╗ ████████╗    ║
║   ██║   ██║██║██╔════╝██║██╔═══██╗████╗  ██║██╔══██╗██╔═══██╗╚══██╔══╝    ║
║   ██║   ██║██║███████╗██║██║   ██║██╔██╗ ██║██████╔╝██║   ██║   ██║       ║
║   ╚██╗ ██╔╝██║╚════██║██║██║   ██║██║╚██╗██║██╔══██╗██║   ██║   ██║       ║
║    ╚████╔╝ ██║███████║██║╚██████╔╝██║ ╚████║██████╔╝╚██████╔╝   ██║       ║
║     ╚═══╝  ╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═════╝  ╚═════╝   ╚═╝       ║
║                                                                              ║
║                    v2.1 — الوكيل الهجين المتكامل                           ║
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐   ║
║  │  التقنيات المدمجة — 11 ميزة احترافية                               │   ║
║  │                                                                     │   ║
║  │  من v2.0:                                                           │   ║
║  │   ① Visual Gridding      — شبكة إحداثيات فوق الشاشة              │   ║
║  │   ② Precision Prompt     — System Prompt هندسي                    │   ║
║  │   ③ Scale Normalizer     — تصحيح فارق الدقة                      │   ║
║  │   ④ Self-Correction      — دورة تحقق ذاتي                        │   ║
║  │   ⑤ Delta Compression    — كشف تغييرات الشاشة                    │   ║
║  │                                                                     │   ║
║  │  جديد في v2.1:                                                      │   ║
║  │   ⑥ ACTION FORMAT        — لغة أوامر موحدة (من UI-TARS)          │   ║
║  │   ⑦ Pre-Click Verify     — تحقق قبل النقر (من UI-TARS)           │   ║
║  │   ⑧ Normalized Coords    — إحداثيات /1000 (من UI-TARS)           │   ║
║  │   ⑨ Memory System        — ذاكرة تراكمية تتعلم                   │   ║
║  │   ⑩ Hierarchical Models  — نماذج هرمية بسيط/متوسط/معقد          │   ║
║  │   ⑪ Silent Watcher       — مراقب صامت في الخلفية                 │   ║
║  └─────────────────────────────────────────────────────────────────────┘   ║
║                                                                              ║
║  المزودون: Claude │ OpenAI │ Gemini │ Groq │ NVIDIA                        ║
║  pip install pyautogui pillow anthropic openai groq numpy                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# الثوابت والمجلدات
# ══════════════════════════════════════════════════════════════════════════════

VERSION      = "2.1.0"
CONFIG_FILE  = Path("vision_config.json")
MEMORY_FILE  = Path("vision_memory.json")
LOG_DIR      = Path("vision_logs")
DEBUG_DIR    = Path("vision_debug")

for d in (LOG_DIR, DEBUG_DIR):
    d.mkdir(exist_ok=True)

_log_file = LOG_DIR / f"v21_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
_logger = logging.getLogger("VisionBot.v21")

Provider = Literal["claude", "openai", "gemini", "groq", "nvidia"]


# ══════════════════════════════════════════════════════════════════════════════
# ① مدير الإعدادات
# ══════════════════════════════════════════════════════════════════════════════

class ConfigManager:
    """يحفظ ويحمّل جميع إعدادات VisionBot v2.1."""

    DEFAULTS: Dict[str, Any] = {
        # المزود والنموذج
        "provider":             "claude",
        "api_key":              "",
        "groq_key":             "",
        "nvidia_key":           "",
        "model":                "",
        # إعدادات التشغيل
        "max_steps":            15,
        "step_delay":           1.0,
        "screenshot_quality":   80,
        "move_duration":        0.25,
        "failsafe":             True,
        # الشبكة
        "grid_step":            100,
        "grid_enabled":         True,
        "save_debug_images":    True,
        # التحقق والتصحيح
        "self_correction":      True,
        "pre_click_verify":     True,   # ⑦ جديد
        "delta_threshold":      0.03,
        "max_retries":          3,
        # الذاكرة
        "memory_enabled":       True,   # ⑨ جديد
        "memory_min_success":   3,      # حد أدنى للنجاح قبل الثقة بالذاكرة
        # النماذج الهرمية
        "auto_model":           True,   # ⑩ اختيار تلقائي للنموذج
        # المراقب الصامت
        "watcher_enabled":      False,  # ⑪ معطل افتراضياً
        "watcher_interval":     30,
        # التعاون مع المستخدم
        "user_collab":          False,
        "collab_countdown":     10,
    }

    DEFAULT_MODELS: Dict[str, str] = {
        "claude": "claude-sonnet-4-5",
        "openai": "gpt-4o",
        "gemini": "gemini-1.5-pro",
        "groq":   "meta-llama/llama-4-scout-17b-16e-instruct",
        "nvidia": "microsoft/phi-3.5-vision-instruct",
    }

    # النماذج الهرمية — بسيط / متوسط / معقد
    TIER_MODELS: Dict[str, Dict[str, str]] = {
        "simple": {
            "provider": "groq",
            "model":    "meta-llama/llama-4-scout-17b-16e-instruct",
        },
        "medium": {
            "provider": "claude",
            "model":    "claude-haiku-4-5-20251001",
        },
        "complex": {
            "provider": "claude",
            "model":    "claude-sonnet-4-5",
        },
    }

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                with CONFIG_FILE.open(encoding="utf-8") as f:
                    self._data = {**self.DEFAULTS, **json.load(f)}
                return
            except Exception:
                pass
        self._data = dict(self.DEFAULTS)
        self.save()

    def save(self) -> None:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def get_model(self) -> str:
        provider = self.get("provider", "claude")
        # أولاً: تحقق من النموذج المخصص للمزود
        key_map = {
            "claude":  "model_api_key",
            "openai":  "model_api_key",
            "gemini":  "model_api_key",
            "groq":    "model_groq_key",
            "nvidia":  "model_nvidia_key",
        }
        custom_key = key_map.get(provider, "model_api_key")
        custom = self.get(custom_key, "").strip()
        if custom:
            return custom
        # ثانياً: النموذج العام
        m = self.get("model", "")
        return m or self.DEFAULT_MODELS.get(provider, "")


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ ACTION FORMAT — لغة أوامر موحدة (من UI-TARS)
# ══════════════════════════════════════════════════════════════════════════════

class ActionParser:
    """
    يحوّل استجابة LLM إلى إجراء موحد بغض النظر عن المزود.

    لغة ACTION FORMAT الموحدة:
        ACTION: CLICK     COORDS: [x, y]
        ACTION: TYPE      TEXT: "النص"
        ACTION: SCROLL    DIR: down  AMOUNT: 3
        ACTION: HOTKEY    KEYS: ctrl+c
        ACTION: VERIFY    DESC: "وصف العنصر"
        ACTION: DONE
        ACTION: FAIL      REASON: "السبب"

    هذا يجعل VisionBot مستقلاً عن أي نموذج — غيّر المزود بدون تغيير الكود.
    """

    # الـ System Prompt الموحد الذي يجبر أي LLM على ACTION FORMAT
    SYSTEM_PROMPT = """أنت وكيل تحكم في واجهات المستخدم (GUI Control Agent) عالي الدقة.

═══════════════════════════════════════════════════════════
نظام الإحداثيات:
═══════════════════════════════════════════════════════════
• الصورة مقسمة بشبكة فوشيا كل 100 بكسل
• الأرقام الصفراء = قيم الإحداثيات
• أعطِ الإحداثيات كأرقام من 0 إلى 1000 (نظام مُطبَّع)
  مثال: x=500 يعني منتصف الشاشة أفقياً
  النظام يحوّلها تلقائياً للإحداثيات الحقيقية

═══════════════════════════════════════════════════════════
منهجية التفكير (إلزامي قبل كل إجراء):
═══════════════════════════════════════════════════════════
1. ماذا أرى؟ — وصف الشاشة الحالية
2. أين العنصر المستهدف؟ — تحديد الخلية في الشبكة
3. ما الإجراء الصحيح؟ — نقر / كتابة / تمرير
4. ما درجة ثقتي؟ — من 0.0 إلى 1.0

═══════════════════════════════════════════════════════════
صيغة الإجابة الإلزامية — ACTION FORMAT:
═══════════════════════════════════════════════════════════
أجب بـ JSON فقط، لا نص قبله أو بعده:

{
  "thinking": "تفكيرك بالخطوات الأربع أعلاه",
  "action": "CLICK | TYPE | SCROLL | HOTKEY | DONE | FAIL",
  "x": <0-1000>,
  "y": <0-1000>,
  "text": "<للكتابة فقط>",
  "keys": ["ctrl", "c"],
  "direction": "up | down",
  "amount": 3,
  "confidence": <0.0-1.0>,
  "element": "وصف العنصر المستهدف",
  "grid_cell": "X:400-500 Y:200-300",
  "reason": "سبب الإجراء",
  "obstacles": "عوائق محتملة إن وجدت"
}

قواعد صارمة:
• confidence < 0.55 → action: "FAIL" إلزامياً
• المهمة مكتملة → action: "DONE"
• لا تخمّن مطلقاً — الشك = FAIL"""

    @staticmethod
    def parse(raw: str) -> Dict[str, Any]:
        """
        يستخرج ACTION FORMAT من استجابة LLM الخام.

        يدعم:
        - JSON نظيف
        - JSON داخل نص
        - ACTION FORMAT نصي كـ fallback

        Returns:
            dict موحد مع action وبقية الحقول.
        """
        # محاولة 1: JSON نظيف
        start = raw.find('{')
        end   = raw.rfind('}')
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start:end+1])
                if "action" in data:
                    # توحيد حقل action للأحرف الكبيرة
                    data["action"] = data["action"].upper()
                    if data.get("thinking"):
                        _logger.info(f"🧠 CoT: {str(data['thinking'])[:100]}…")
                    if data.get("confidence") is not None:
                        _logger.info(f"🎯 Conf: {float(data['confidence']):.0%} | عنصر: {data.get('element','')}")
                    return data
            except (json.JSONDecodeError, ValueError):
                pass

        # محاولة 2: ACTION FORMAT نصي
        patterns = {
            "action":     r"ACTION:\s*(\w+)",
            "x":          r"COORDS?:\s*\[(\d+)",
            "y":          r"COORDS?:\s*\[\d+[,\s]+(\d+)",
            "text":       r'TEXT:\s*["\']?([^"\'}\n]+)',
            "reason":     r"REASON:\s*(.+)",
            "confidence": r"CONF(?:IDENCE)?:\s*([\d.]+)",
        }
        result: Dict[str, Any] = {}
        for key, pat in patterns.items():
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                result[key] = float(val) if key in ("x","y","confidence") else val

        if result.get("action"):
            result["action"] = result["action"].upper()
            return result

        _logger.warning(f"⚠️ لم يُعثر على ACTION FORMAT:\n{raw[:200]}")
        return {"action": "FAIL", "reason": "استجابة LLM غير قابلة للتحليل"}

    @staticmethod
    def build_user_message(
        task:        str,
        history:     List[str],
        grid_desc:   str,
        screen_size: Tuple[int, int],
        complexity:  str = "medium",
    ) -> str:
        """يبني رسالة المستخدم الكاملة."""
        w, h = screen_size
        hist = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(history[-6:]))
        hist_sec = f"\nالخطوات المنفذة:\n{hist}" if hist else ""
        return (
            f"المهمة: {task}\n"
            f"الشاشة: {w}×{h} | الشبكة: {grid_desc}"
            f"{hist_sec}\n\n"
            "حلّل الشاشة وأعطني الخطوة التالية بـ ACTION FORMAT."
        )


# ══════════════════════════════════════════════════════════════════════════════
# ⑧ Normalized Coordinates — إحداثيات /1000 (من UI-TARS)
# ══════════════════════════════════════════════════════════════════════════════

class CoordNormalizer:
    """
    يحوّل الإحداثيات المُطبَّعة (0-1000) للإحداثيات الفعلية.

    من UI-TARS: بدل حساب نسبة الصورة/الشاشة المعقد،
    نطلب من LLM إحداثيات من 0 إلى 1000 ونحوّلها بسطرين.

    x_real = round((x_norm / 1000) * screen_width)
    y_real = round((y_norm / 1000) * screen_height)
    """

    def __init__(self) -> None:
        self._screen_w: int = 1920
        self._screen_h: int = 1080

    def set_screen(self, w: int, h: int) -> None:
        self._screen_w = w
        self._screen_h = h

    def to_real(self, x_norm: float, y_norm: float) -> Tuple[int, int]:
        """
        يُحوّل إحداثيات 0-1000 للشاشة الفعلية.

        Args:
            x_norm: إحداثي X من LLM (0-1000).
            y_norm: إحداثي Y من LLM (0-1000).

        Returns:
            (x, y) الإحداثيات الفعلية على الشاشة.
        """
        x = round((float(x_norm) / 1000.0) * self._screen_w)
        y = round((float(y_norm) / 1000.0) * self._screen_h)
        x = max(0, min(x, self._screen_w - 1))
        y = max(0, min(y, self._screen_h - 1))
        _logger.debug(f"📐 ({x_norm},{y_norm})/1000 → ({x},{y}) على {self._screen_w}×{self._screen_h}")
        return x, y

    def get_screen_size(self) -> Tuple[int, int]:
        return self._screen_w, self._screen_h


# ══════════════════════════════════════════════════════════════════════════════
# ① Visual Gridding — الشبكة الذكية
# ══════════════════════════════════════════════════════════════════════════════

class VisualGridder:
    """يرسم شبكة إحداثيات مرئية فوق لقطة الشاشة."""

    GRID_COLOR   = (255, 0, 255)
    LABEL_COLOR  = (255, 255, 0)
    LINE_OPACITY = 100

    def __init__(self, step: int = 100, save_debug: bool = True) -> None:
        self.step       = step
        self.save_debug = save_debug

    def draw(self, img_bytes: bytes) -> bytes:
        try:
            from PIL import Image, ImageDraw
            import io as _io

            img  = Image.open(_io.BytesIO(img_bytes)).convert("RGBA")
            w, h = img.size
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw    = ImageDraw.Draw(overlay)
            r, g, b = self.GRID_COLOR
            lf      = (r, g, b, self.LINE_OPACITY)

            for x in range(0, w, self.step):
                draw.line([(x, 0), (x, h)], fill=lf, width=1)
                draw.text((x+3, 3),      str(x), fill=(*self.LABEL_COLOR, 200))
                draw.text((x+3, h-16),   str(x), fill=(*self.LABEL_COLOR, 170))

            for y in range(0, h, self.step):
                draw.line([(0, y), (w, y)], fill=lf, width=1)
                draw.text((3, y+3),      str(y), fill=(*self.LABEL_COLOR, 200))
                draw.text((w-38, y+3),   str(y), fill=(*self.LABEL_COLOR, 170))

            combined = Image.alpha_composite(img, overlay).convert("RGB")

            if self.save_debug:
                p = DEBUG_DIR / f"grid_{int(time.time())}.jpg"
                combined.save(p, "JPEG", quality=70)

            buf = _io.BytesIO()
            combined.save(buf, "JPEG", quality=80)
            return buf.getvalue()

        except Exception as exc:
            _logger.error(f"❌ خطأ الشبكة: {exc}")
            return img_bytes

    def description(self, w: int, h: int) -> str:
        return (
            f"شبكة كل {self.step}px. "
            f"X: 0-{(w//self.step)*self.step} | Y: 0-{(h//self.step)*self.step}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ Delta Detector — كشف تغييرات الشاشة
# ══════════════════════════════════════════════════════════════════════════════

class DeltaDetector:
    """يكشف إذا تغيرت الشاشة بما يكفي بعد تنفيذ إجراء."""

    def __init__(self, threshold: float = 0.03) -> None:
        self.threshold    = threshold
        self._last: Optional[bytes] = None

    def has_changed(self, new_frame: bytes) -> Tuple[bool, float]:
        if self._last is None:
            self._last = new_frame
            return True, 1.0
        try:
            import numpy as np
            from PIL import Image
            import io as _io

            def gray(b):
                img = Image.open(_io.BytesIO(b)).convert("L").resize((320,180))
                return np.array(img, dtype=np.float32)

            diff  = np.abs(gray(new_frame) - gray(self._last))
            ratio = float(np.sum(diff > 15)) / diff.size
            self._last = new_frame
            changed = ratio > self.threshold
            _logger.debug(f"🔄 Delta: {ratio:.1%} {'✅' if changed else '⚠️'}")
            return changed, ratio
        except Exception:
            self._last = new_frame
            return True, 1.0

    def reset(self) -> None:
        self._last = None


# ══════════════════════════════════════════════════════════════════════════════
# ⑨ Memory System — الذاكرة التراكمية
# ══════════════════════════════════════════════════════════════════════════════

class MemorySystem:
    """
    يحفظ نجاحات النقر في memory.json ويستخدمها لتسريع المهام المتكررة.

    المبدأ:
        كل مرة ينجح VisionBot بنقرة → يحفظها مع اسم التطبيق ووصف العنصر.
        المرة التالية لنفس التطبيق والعنصر → يجرب المحفوظ أولاً.
        بعد 3 نجاحات → يثق بالإحداثيات ويتخطى الـ LLM مباشرة.

    هيكل الذاكرة:
        {
          "app_or_url": {
            "وصف_العنصر": {
              "x": 850, "y": 400,
              "success_count": 7,
              "last_used": "2025-03-10"
            }
          }
        }
    """

    def __init__(self, min_success: int = 3) -> None:
        self._min_success = min_success
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if MEMORY_FILE.exists():
            try:
                with MEMORY_FILE.open(encoding="utf-8") as f:
                    self._data = json.load(f)
                _logger.info(f"🧠 ذاكرة محملة: {len(self._data)} تطبيق")
            except Exception:
                self._data = {}

    def _save(self) -> None:
        with MEMORY_FILE.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def lookup(self, app: str, element: str) -> Optional[Tuple[int, int]]:
        """
        يبحث عن إحداثيات محفوظة للعنصر.

        Returns:
            (x, y) إذا وجد وموثوق، None إذا لا.
        """
        entry = self._data.get(app, {}).get(element)
        if not entry:
            return None
        if entry.get("success_count", 0) >= self._min_success:
            _logger.info(f"🧠 ذاكرة: '{element}' في {app} → ({entry['x']},{entry['y']}) [{entry['success_count']} نجاح]")
            return entry["x"], entry["y"]
        return None

    def record_success(self, app: str, element: str, x: int, y: int) -> None:
        """يسجّل نجاح نقرة في الذاكرة."""
        if app not in self._data:
            self._data[app] = {}
        entry = self._data[app].get(element, {"x": x, "y": y, "success_count": 0})
        # تحديث الإحداثيات بمتوسط متحرك للدقة
        entry["x"] = int((entry["x"] * 0.7) + (x * 0.3))
        entry["y"] = int((entry["y"] * 0.7) + (y * 0.3))
        entry["success_count"] = entry.get("success_count", 0) + 1
        entry["last_used"]     = datetime.now().strftime("%Y-%m-%d")
        self._data[app][element] = entry
        self._save()
        _logger.info(f"🧠 حُفظ: '{element}' ({x},{y}) → نجاح #{entry['success_count']}")

    def get_stats(self) -> str:
        total_apps     = len(self._data)
        total_elements = sum(len(v) for v in self._data.values())
        return f"{total_apps} تطبيق | {total_elements} عنصر محفوظ"

    def clear(self) -> None:
        self._data = {}
        self._save()


# ══════════════════════════════════════════════════════════════════════════════
# ⑩ Hierarchical Model Selector — اختيار النموذج الهرمي
# ══════════════════════════════════════════════════════════════════════════════

class ModelSelector:
    """
    يختار النموذج المناسب تلقائياً بناءً على تعقيد المهمة.

    بسيط (< 5 كلمات):   Groq llama-vision — مجاني تقريباً
    متوسط (5-15 كلمة):  Claude Haiku     — سريع ورخيص
    معقد  (> 15 كلمة):  Claude Sonnet    — دقيق للمهام الصعبة
    """

    @staticmethod
    def classify(task: str) -> str:
        words = len(task.split())
        if words <= 5:
            return "simple"
        elif words <= 15:
            return "medium"
        return "complex"

    @staticmethod
    def describe(tier: str) -> str:
        labels = {
            "simple":  "بسيط → Groq (مجاني تقريباً)",
            "medium":  "متوسط → Claude Haiku (سريع)",
            "complex": "معقد → Claude Sonnet (دقيق)",
        }
        return labels.get(tier, tier)


# ══════════════════════════════════════════════════════════════════════════════
# عملاء LLM — جميع المزودين
# ══════════════════════════════════════════════════════════════════════════════

class BaseLLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model   = model

    def analyze(
        self,
        screenshot_b64: str,
        task:           str,
        history:        List[str],
        grid_desc:      str,
        screen_size:    Tuple[int, int],
    ) -> Dict[str, Any]:
        raise NotImplementedError


class ClaudeClient(BaseLLMClient):
    def analyze(self, screenshot_b64, task, history, grid_desc, screen_size):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            msg = ActionParser.build_user_message(task, history, grid_desc, screen_size)
            resp = client.messages.create(
                model=self.model, max_tokens=1500,
                system=ActionParser.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg",
                        "data": screenshot_b64}},
                    {"type": "text", "text": msg},
                ]}],
            )
            return ActionParser.parse(resp.content[0].text)
        except ImportError:
            return {"action": "FAIL", "reason": "pip install anthropic"}
        except Exception as e:
            return {"action": "FAIL", "reason": str(e)}


class OpenAIClient(BaseLLMClient):
    def analyze(self, screenshot_b64, task, history, grid_desc, screen_size):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            msg = ActionParser.build_user_message(task, history, grid_desc, screen_size)
            resp = client.chat.completions.create(
                model=self.model, max_tokens=1500,
                messages=[
                    {"role": "system", "content": ActionParser.SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{screenshot_b64}",
                            "detail": "high"}},
                        {"type": "text", "text": msg},
                    ]},
                ],
            )
            return ActionParser.parse(resp.choices[0].message.content)
        except ImportError:
            return {"action": "FAIL", "reason": "pip install openai"}
        except Exception as e:
            return {"action": "FAIL", "reason": str(e)}


class GroqClient(BaseLLMClient):
    """عميل Groq — نماذج مجانية تقريباً وسريعة جداً."""
    def analyze(self, screenshot_b64, task, history, grid_desc, screen_size):
        try:
            from groq import Groq
            client = Groq(api_key=self.api_key)
            msg = ActionParser.build_user_message(task, history, grid_desc, screen_size)
            resp = client.chat.completions.create(
                model=self.model, max_tokens=1500,
                messages=[
                    {"role": "system", "content": ActionParser.SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{screenshot_b64}"}},
                        {"type": "text", "text": msg},
                    ]},
                ],
            )
            return ActionParser.parse(resp.choices[0].message.content)
        except ImportError:
            return {"action": "FAIL", "reason": "pip install groq"}
        except Exception as e:
            return {"action": "FAIL", "reason": str(e)}


class NvidiaClient(BaseLLMClient):
    """عميل NVIDIA API — نماذج phi-3.5-vision وغيرها."""
    def analyze(self, screenshot_b64, task, history, grid_desc, screen_size):
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=self.api_key,
                base_url="https://integrate.api.nvidia.com/v1"
            )
            msg = ActionParser.build_user_message(task, history, grid_desc, screen_size)
            resp = client.chat.completions.create(
                model=self.model, max_tokens=1500,
                messages=[
                    {"role": "system", "content": ActionParser.SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{screenshot_b64}"}},
                        {"type": "text", "text": msg},
                    ]},
                ],
            )
            return ActionParser.parse(resp.choices[0].message.content)
        except ImportError:
            return {"action": "FAIL", "reason": "pip install openai"}
        except Exception as e:
            return {"action": "FAIL", "reason": str(e)}


class GeminiClient(BaseLLMClient):
    def analyze(self, screenshot_b64, task, history, grid_desc, screen_size):
        try:
            import google.generativeai as genai
            from PIL import Image
            import io as _io
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                self.model, system_instruction=ActionParser.SYSTEM_PROMPT)
            img = Image.open(_io.BytesIO(base64.b64decode(screenshot_b64)))
            msg = ActionParser.build_user_message(task, history, grid_desc, screen_size)
            resp = model.generate_content([img, msg])
            return ActionParser.parse(resp.text)
        except ImportError:
            return {"action": "FAIL", "reason": "pip install google-generativeai"}
        except Exception as e:
            return {"action": "FAIL", "reason": str(e)}


def build_client(config: ConfigManager, tier: str = "medium") -> BaseLLMClient:
    """
    مصنع العملاء — يختار المزود والنموذج المناسب.

    إذا auto_model مفعّل → يستخدم النموذج الهرمي حسب التعقيد.
    وإلا → يستخدم المزود المحدد في الإعدادات.
    """
    if config.get("auto_model", True) and tier in ConfigManager.TIER_MODELS:
        tier_cfg  = ConfigManager.TIER_MODELS[tier]
        provider  = tier_cfg["provider"]
        model     = tier_cfg["model"]
        # الـ API key من الإعدادات
        if provider == "groq":
            api_key = config.get("groq_key", "") or config.get("api_key", "")
        else:
            api_key = config.get("api_key", "")
    else:
        provider = config.get("provider", "claude")
        model    = config.get_model()
        api_key  = config.get("api_key", "")
        if provider in ("groq",):
            api_key = config.get("groq_key", "") or api_key
        elif provider == "nvidia":
            api_key = config.get("nvidia_key", "") or api_key

    cls_map = {
        "claude": ClaudeClient,
        "openai": OpenAIClient,
        "groq":   GroqClient,
        "nvidia": NvidiaClient,
        "gemini": GeminiClient,
    }
    cls = cls_map.get(provider, ClaudeClient)
    _logger.info(f"🤖 نموذج [{tier}]: {provider}/{model}")
    return cls(api_key=api_key, model=model)


# ══════════════════════════════════════════════════════════════════════════════
# ⑦ Pre-Click Verifier — التحقق قبل النقر (من UI-TARS)
# ══════════════════════════════════════════════════════════════════════════════

class PreClickVerifier:
    """
    يلتقط لقطة صغيرة حول مؤشر الماوس قبل النقر ويتحقق من صحة الموقع.

    المبدأ من UI-TARS:
        بدل النقر مباشرة → تحرك → التقط 200×200 حول المؤشر →
        اسأل LLM "هل هذا هو العنصر الصحيح؟" → إذا نعم انقر.

    يمنع الأخطاء الفادحة مثل إغلاق ملف بدل حفظه.
    """

    VERIFY_SIZE = 200  # حجم منطقة التحقق بالبكسل

    def __init__(self, llm_client: BaseLLMClient) -> None:
        self._llm = llm_client

    def verify(
        self,
        x: int, y: int,
        element_desc: str,
        capture_fn: Callable[[], Optional[bytes]],
    ) -> bool:
        """
        يتحقق أن المؤشر فوق العنصر الصحيح.

        Args:
            x, y:         الإحداثيات المستهدفة.
            element_desc: وصف العنصر المتوقع.
            capture_fn:   دالة التقاط الشاشة.

        Returns:
            True إذا العنصر صحيح، False إذا خطأ.
        """
        try:
            from PIL import Image, ImageGrab
            import io as _io

            # التقاط منطقة صغيرة حول المؤشر
            half = self.VERIFY_SIZE // 2
            region = (
                max(0, x - half),
                max(0, y - half),
                x + half,
                y + half,
            )
            try:
                mini = ImageGrab.grab(bbox=region)
            except Exception:
                return True  # إذا فشل الالتقاط → افترض الصحة

            buf = _io.BytesIO()
            mini.convert("RGB").save(buf, "JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode()

            # سؤال مبسط للـ LLM (رخيص جداً — صورة صغيرة)
            verify_task = f"هل ترى في مركز الصورة عنصراً يشبه: {element_desc}؟ أجب بـ JSON: {{\"match\": true}} أو {{\"match\": false}}"
            result = self._llm.analyze(b64, verify_task, [], "", (self.VERIFY_SIZE, self.VERIFY_SIZE))

            match = result.get("match", True)  # افتراضي: True لتجنب الإيقاف الزائد
            if not match:
                _logger.warning(f"⚠️ تحقق فاشل — المؤشر ليس فوق: {element_desc}")
            else:
                _logger.info(f"✅ تحقق نجح — المؤشر فوق: {element_desc}")
            return bool(match)

        except Exception as exc:
            _logger.debug(f"Pre-click verify error (non-fatal): {exc}")
            return True  # عند الخطأ → افترض الصحة


# ══════════════════════════════════════════════════════════════════════════════
# ④ Self-Correction Engine — التصحيح الذاتي
# ══════════════════════════════════════════════════════════════════════════════

class SelfCorrectionEngine:
    """ينفّذ النقر مع إعادة المحاولة بإزاحات تدريجية عند الفشل."""

    OFFSETS: List[Tuple[int,int]] = [(0,0), (5,0), (-5,5), (0,-5), (8,8)]

    def __init__(
        self,
        delta:        DeltaDetector,
        log_cb:       Callable[[str,str], None],
        wait_secs:    float = 1.0,
        max_retries:  int   = 3,
    ) -> None:
        self._delta      = delta
        self._log        = log_cb
        self._wait       = wait_secs
        self._max_tries  = max_retries

    def execute(
        self,
        pag:         Any,
        x:           int,
        y:           int,
        capture_fn:  Callable[[], Optional[bytes]],
        action_type: str = "CLICK",
    ) -> bool:
        for attempt, (dx, dy) in enumerate(self.OFFSETS[:self._max_tries+1]):
            cx, cy = x + dx, y + dy
            if attempt > 0:
                self._log(f"🔁 محاولة {attempt} — إزاحة ({dx:+},{dy:+}) → ({cx},{cy})", "WARNING")
            try:
                if action_type == "CLICK":
                    pag.click(cx, cy)
                elif action_type == "DOUBLE_CLICK":
                    pag.doubleClick(cx, cy)
            except Exception as e:
                self._log(f"❌ خطأ: {e}", "ERROR")
                continue

            time.sleep(self._wait)
            frame = capture_fn()
            if frame:
                changed, ratio = self._delta.has_changed(frame)
                if changed:
                    self._log(f"✅ نجح — تغيير: {ratio:.1%}", "INFO")
                    return True
                self._log(f"⚠️ لم تتغير الشاشة ({ratio:.1%})", "WARNING")
            else:
                return True

        self._log(f"❌ فشلت {self._max_tries+1} محاولات", "ERROR")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ⑪ Silent Watcher — المراقب الصامت
# ══════════════════════════════════════════════════════════════════════════════

class SilentWatcher:
    """
    يراقب الشاشة في الخلفية وينفّذ إجراءات عند تحقق شروط معينة.

    أمثلة:
        "إذا ظهر إعلان → أغلقه تلقائياً"
        "إذا انتهى التحميل → أخبرني"
        "إذا وصل إشعار → اقرأه"
    """

    def __init__(
        self,
        capture_fn:  Callable[[], Optional[bytes]],
        llm_client:  BaseLLMClient,
        rules:       List[Dict[str, Any]],
        interval:    int = 30,
        log_cb:      Optional[Callable[[str,str], None]] = None,
    ) -> None:
        self._capture  = capture_fn
        self._llm      = llm_client
        self._rules    = rules
        self._interval = interval
        self._log      = log_cb or (lambda m,l: None)
        self._thread: Optional[threading.Thread] = None
        self._stop    = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._log("👁 المراقب الصامت يعمل في الخلفية", "INFO")

    def stop(self) -> None:
        self._stop.set()
        self._log("👁 المراقب الصامت توقف", "INFO")

    def _loop(self) -> None:
        while not self._stop.is_set():
            frame = self._capture()
            if frame:
                b64 = base64.b64encode(frame).decode()
                for rule in self._rules:
                    condition = rule.get("condition", "")
                    action_fn = rule.get("action")
                    result = self._llm.analyze(b64, condition, [], "", (1280, 720))
                    if result.get("action") not in ("FAIL", "DONE") and result.get("confidence", 0) > 0.7:
                        self._log(f"👁 شرط تحقق: {condition}", "SUCCESS")
                        if action_fn:
                            action_fn()
            self._stop.wait(self._interval)


# ══════════════════════════════════════════════════════════════════════════════
# محرك الوكيل v2.1
# ══════════════════════════════════════════════════════════════════════════════

class VisionAgentV21:
    """
    الوكيل الكامل — يدمج كل التقنيات الإحدى عشرة.

    تدفق التنفيذ:
        1. تصنيف تعقيد المهمة (بسيط/متوسط/معقد)
        2. البحث في الذاكرة أولاً
        3. التقاط شاشة + رسم شبكة
        4. إرسال للـ LLM المناسب
        5. تحويل إحداثيات /1000
        6. Pre-Click Verify
        7. تنفيذ + Self-Correction
        8. Delta Check
        9. حفظ النجاح في الذاكرة
    """

    def __init__(
        self,
        config:   ConfigManager,
        log_cb:   Optional[Callable[[str,str], None]] = None,
    ) -> None:
        self._config  = config
        self._log_cb  = log_cb
        self.is_running = False

        self._gridder   = VisualGridder(
            step=config.get("grid_step", 100),
            save_debug=config.get("save_debug_images", True),
        )
        self._coords    = CoordNormalizer()
        self._delta     = DeltaDetector(config.get("delta_threshold", 0.03))
        self._memory    = MemorySystem(config.get("memory_min_success", 3))
        self._history:  List[str] = []
        self._pag       = None
        self._PIL       = None
        self._watcher:  Optional[SilentWatcher] = None
        self._init_libs()

    def _init_libs(self) -> None:
        try:
            import pyautogui as pag
            pag.FAILSAFE = self._config.get("failsafe", True)
            pag.PAUSE    = 0.1
            self._pag    = pag
            self._log("✅ PyAutoGUI", "INFO")
        except ImportError:
            self._log("❌ pip install pyautogui", "ERROR")
        try:
            from PIL import ImageGrab, Image
            self._PIL = {"ImageGrab": ImageGrab, "Image": Image}
            self._log("✅ Pillow", "INFO")
        except ImportError:
            self._log("❌ pip install pillow", "ERROR")

    # ── التقاط الشاشة ────────────────────────────────────────────────

    def _capture_raw(self) -> Optional[bytes]:
        if not self._PIL:
            return None
        try:
            try:
                img = self._PIL["ImageGrab"].grab(all_screens=True)
            except TypeError:
                img = self._PIL["ImageGrab"].grab()

            sw, sh = img.size
            self._coords.set_screen(sw, sh)

            max_w = 1280
            if sw > max_w:
                img = img.resize((max_w, int(sh * max_w / sw)), self._PIL["Image"].LANCZOS)

            import io as _io
            buf = _io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=self._config.get("screenshot_quality", 80))
            return buf.getvalue()
        except Exception as exc:
            self._log(f"❌ خطأ التقاط: {exc}", "ERROR")
            return None

    def capture_for_api(self, grid: bool = True) -> Optional[Tuple[str, bytes]]:
        raw = self._capture_raw()
        if not raw:
            return None
        processed = self._gridder.draw(raw) if grid and self._config.get("grid_enabled") else raw
        b64 = base64.b64encode(processed).decode()
        self._log(f"📸 لقطة {len(processed)//1024}KB {'+ شبكة' if grid else ''}", "INFO")
        return b64, raw

    # ── تنفيذ الإجراءات ───────────────────────────────────────────────

    def execute_action(
        self,
        action:  Dict[str, Any],
        llm:     BaseLLMClient,
        app_ctx: str = "unknown",
    ) -> bool:
        if not self._pag:
            return False

        act  = action.get("action", "FAIL").upper()
        elem = action.get("element", "")
        conf = float(action.get("confidence", 1.0))

        self._log(f"▶ {act} | conf={conf:.0%} | {elem}", "INFO")

        if conf < 0.55 and act in ("CLICK","DOUBLE_CLICK","RIGHT_CLICK"):
            self._log(f"⚠️ ثقة منخفضة ({conf:.0%}) — تخطي", "WARNING")
            return False

        try:
            dur = float(self._config.get("move_duration", 0.25))

            if act in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                # تحويل إحداثيات /1000
                x_n = float(action.get("x", 0))
                y_n = float(action.get("y", 0))
                x, y = self._coords.to_real(x_n, y_n)

                # ⑨ تحقق من الذاكرة أولاً
                if self._config.get("memory_enabled") and elem:
                    cached = self._memory.lookup(app_ctx, elem)
                    if cached:
                        x, y = cached
                        self._log(f"🧠 استخدام الذاكرة: ({x},{y})", "INFO")

                self._pag.moveTo(x, y, duration=dur)

                # ⑦ Pre-Click Verify
                if self._config.get("pre_click_verify") and elem:
                    verifier = PreClickVerifier(llm)
                    ok = verifier.verify(x, y, elem, self._capture_raw)
                    if not ok:
                        self._log(f"⚠️ فشل التحقق — إعادة الحساب", "WARNING")
                        return False

                # ④ Self-Correction
                corrector = SelfCorrectionEngine(
                    delta=self._delta,
                    log_cb=self._log,
                    max_retries=self._config.get("max_retries", 3),
                )
                success = corrector.execute(self._pag, x, y, self._capture_raw, act)

                # ⑨ حفظ في الذاكرة إذا نجح
                if success and elem and self._config.get("memory_enabled"):
                    self._memory.record_success(app_ctx, elem, x, y)

                return success

            elif act == "TYPE":
                text = action.get("text", "")
                self._pag.write(str(text), interval=0.04)
                self._log(f"⌨ كتابة: {str(text)[:40]}", "INFO")
                return True

            elif act == "HOTKEY":
                keys = action.get("keys", [])
                if isinstance(keys, list) and keys:
                    self._pag.hotkey(*keys)
                elif isinstance(keys, str):
                    self._pag.hotkey(*keys.split("+"))
                self._log(f"⌨ اختصار: {keys}", "INFO")
                return True

            elif act == "SCROLL":
                x_n = float(action.get("x", 500))
                y_n = float(action.get("y", 500))
                x, y = self._coords.to_real(x_n, y_n)
                d     = action.get("direction", "down")
                amt   = int(action.get("amount", 3))
                self._pag.scroll(-amt if d == "down" else amt, x=x, y=y)
                self._log(f"🖱 تمرير {d} ×{amt}", "INFO")
                return True

            elif act in ("DONE", "FAIL"):
                return True

            else:
                self._log(f"⚠️ إجراء غير معروف: {act}", "WARNING")
                return False

        except Exception as exc:
            self._log(f"❌ خطأ تنفيذ {act}: {exc}", "ERROR")
            return False

    # ── حلقة الوكيل الرئيسية ─────────────────────────────────────────

    def run_task(
        self,
        task:       str,
        stop_event: threading.Event,
        done_cb:    Optional[Callable[[bool,str], None]] = None,
        app_ctx:    str = "desktop",
    ) -> None:
        self.is_running = True
        self._history   = []
        self._delta.reset()

        # ⑩ تصنيف التعقيد
        tier    = ModelSelector.classify(task)
        tier_lbl = ModelSelector.describe(tier)
        self._log(f"🚀 v2.1 | مهمة: {task}", "SUCCESS")
        self._log(f"🎯 تعقيد: {tier_lbl}", "INFO")
        self._log(f"🧠 ذاكرة: {self._memory.get_stats()}", "INFO")

        llm        = build_client(self._config, tier)
        max_steps  = int(self._config.get("max_steps", 15))
        step_delay = float(self._config.get("step_delay", 1.0))
        sw, sh     = self._coords.get_screen_size()

        for step in range(1, max_steps + 1):
            if stop_event.is_set():
                self._log("🛑 إيقاف المستخدم", "WARNING")
                break

            self._log(f"\n{'─'*55}\n الخطوة {step}/{max_steps}", "INFO")

            # التقاط + شبكة
            result = self.capture_for_api(grid=True)
            if not result:
                self._log("❌ فشل التقاط", "ERROR")
                break
            b64, _ = result

            grid_desc = self._gridder.description(sw, sh)

            # إرسال للـ LLM
            self._log("🧠 تحليل…", "INFO")
            action = llm.analyze(b64, task, self._history, grid_desc, (sw, sh))
            self._log(f"📋 ACTION: {action.get('action')} | {action.get('reason','')}", "INFO")

            act = action.get("action", "FAIL").upper()

            if act == "DONE":
                msg = f"✅ مكتملة! {action.get('reason','')}"
                self._log(msg, "SUCCESS")
                if done_cb:
                    done_cb(True, msg)
                self.is_running = False
                return

            if act == "FAIL":
                msg = f"❌ فشل: {action.get('reason','')}"
                self._log(msg, "ERROR")
                if done_cb:
                    done_cb(False, msg)
                self.is_running = False
                return

            success = self.execute_action(action, llm, app_ctx)

            status = "✅" if success else "⚠️"
            self._history.append(
                f"{status} {act} على '{action.get('element',act)}' "
                f"[conf={action.get('confidence',0):.0%}]"
            )

            time.sleep(step_delay)

        msg = f"⚠️ انتهت {max_steps} خطوة"
        self._log(msg, "WARNING")
        if done_cb:
            done_cb(False, msg)
        self.is_running = False

    # ── المراقب الصامت ────────────────────────────────────────────────

    def start_watcher(self, rules: List[Dict[str, Any]]) -> None:
        if self._watcher:
            self._watcher.stop()
        llm = build_client(self._config, "simple")
        self._watcher = SilentWatcher(
            capture_fn=self._capture_raw,
            llm_client=llm,
            rules=rules,
            interval=self._config.get("watcher_interval", 30),
            log_cb=self._log,
        )
        self._watcher.start()

    def stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()

    def _log(self, msg: str, level: str = "INFO") -> None:
        getattr(_logger, level.lower(), _logger.info)(msg)
        if self._log_cb:
            self._log_cb(msg, level)


# ══════════════════════════════════════════════════════════════════════════════
# الواجهة الرسومية v2.1
# ══════════════════════════════════════════════════════════════════════════════

class VisionBotGUI21:
    """واجهة VisionBot v2.1 — تعرض حالة كل التقنيات الإحدى عشرة."""

    C = {
        "bg":     "#06090d",
        "panel":  "#0b1219",
        "border": "#182530",
        "accent": "#00e5ff",
        "green":  "#00ff7f",
        "yellow": "#ffc107",
        "red":    "#ff3d57",
        "cyan":   "#40c4ff",
        "purple": "#ce93d8",
        "text":   "#cce8f4",
        "muted":  "#456070",
        "btn":    "#0f1e2b",
        "inp":    "#091420",
    }

    def __init__(self) -> None:
        self._config     = ConfigManager()
        self._stop_event = threading.Event()

        self._root = tk.Tk()
        self._root.title(f"🤖 VisionBot v{VERSION} — الوكيل الهجين المتكامل")
        self._root.geometry("1280x780")
        self._root.configure(bg=self.C["bg"])
        self._root.resizable(True, True)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._agent = VisionAgentV21(self._config, self._safe_log)

    # ── بناء الواجهة ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_header()

        body = tk.Frame(self._root, bg=self.C["bg"])
        body.pack(fill="both", expand=True, padx=8, pady=5)

        # اللوحة اليسرى مع Scrollbar
        left_outer = tk.Frame(body, bg=self.C["panel"],
                              highlightthickness=1,
                              highlightbackground=self.C["border"],
                              width=420)
        left_outer.pack(side="left", fill="y", padx=(0,5))
        left_outer.pack_propagate(False)

        left_canvas = tk.Canvas(left_outer, bg=self.C["panel"],
                                highlightthickness=0, width=400)
        left_scrollbar = tk.Scrollbar(left_outer, orient="vertical",
                                      command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)

        left_scrollbar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)

        left = tk.Frame(left_canvas, bg=self.C["panel"])
        left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_frame_configure(e):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        left.bind("<Configure>", _on_frame_configure)

        def _on_mousewheel(e):
            left_canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        left_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self._build_left(left)

        right = tk.Frame(body, bg=self.C["panel"],
                         highlightthickness=1,
                         highlightbackground=self.C["border"])
        right.pack(side="left", fill="both", expand=True)
        self._build_log(right)

        self._status = tk.Label(
            self._root,
            text="⬤  VisionBot v2.1 جاهز — 11 تقنية مفعّلة",
            font=("Consolas", 10),
            bg=self.C["border"], fg=self.C["green"],
            anchor="w", padx=12, pady=5,
        )
        self._status.pack(fill="x", side="bottom")

    def _build_header(self) -> None:
        hdr = tk.Frame(self._root, bg="#001520", height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(
            hdr,
            text=f"◈  VisionBot  v{VERSION}  ·  الوكيل الهجين المتكامل",
            font=("Consolas", 13, "bold"),
            bg="#001520", fg=self.C["accent"],
        ).pack(side="left", padx=16, pady=10)

        # مؤشرات 11 تقنية
        techs = [
            ("①Grid",    True),
            ("②Prompt",  True),
            ("③Coords",  True),
            ("④Correct", True),
            ("⑤Delta",   True),
            ("⑥Action",  True),
            ("⑦Verify",  True),
            ("⑧Norm",    True),
            ("⑨Memory",  True),
            ("⑩Tier",    True),
            ("⑪Watch",   False),
        ]
        for name, active in reversed(techs):
            c = self.C["green"] if active else self.C["muted"]
            tk.Label(hdr, text=f"● {name}",
                     font=("Consolas", 7, "bold"),
                     bg="#001520", fg=c, padx=4,
                     ).pack(side="right", pady=16)

    def _build_left(self, p: tk.Frame) -> None:
        # المزود
        self._sec(p, "◈  المزود الرئيسي")
        row = tk.Frame(p, bg=self.C["panel"])
        row.pack(fill="x", padx=10, pady=(2,0))
        self._prov_var = tk.StringVar(value=self._config.get("provider","claude"))
        for val, lbl in [("claude","Claude"),("openai","GPT"),("groq","Groq"),("nvidia","NVIDIA"),("gemini","Gemini")]:
            tk.Radiobutton(row, text=lbl, variable=self._prov_var, value=val,
                           bg=self.C["panel"], fg=self.C["text"],
                           selectcolor=self.C["btn"],
                           activebackground=self.C["panel"],
                           font=("Consolas",8)).pack(side="left", padx=3)

        # مفاتيح API مع قوائم منسدلة للنماذج
        self._sec(p, "◈  مفاتيح API والنماذج")
        self._api_vars: Dict[str, tk.StringVar] = {}
        self._model_vars: Dict[str, tk.StringVar] = {}

        # النماذج لكل مزود مع تقييمها
        _models_map = {
            "api_key": [
                ("claude-sonnet-4-6 [95] 👁",          "claude-sonnet-4-6"),
                ("claude-opus-4-6 [98] 👁",            "claude-opus-4-6"),
                ("claude-haiku-4-5-20251001 [80] 👁",  "claude-haiku-4-5-20251001"),
                ("gpt-4o [95] 👁",                     "gpt-4o"),
                ("gpt-4o-mini [80] 👁",                "gpt-4o-mini"),
                ("gemini-2.5-pro-latest [97] 👁",      "gemini-2.5-pro-latest"),
                ("gemini-2.0-flash [88] 👁",           "gemini-2.0-flash"),
                ("gemini-1.5-pro [92] 👁",             "gemini-1.5-pro"),
                ("gemini-1.5-flash [80] 👁",           "gemini-1.5-flash"),
            ],
            "groq_key": [
                ("llama-4-maverick [95] 👁",   "meta-llama/llama-4-maverick-17b-128e-instruct"),
                ("llama-4-scout [90] 👁",      "meta-llama/llama-4-scout-17b-16e-instruct"),
                ("llama-3.3-70b [75] 📝",      "llama-3.3-70b-versatile"),
                ("llama-3.1-70b [70] 📝",      "llama-3.1-70b-versatile"),
                ("llama-3.1-8b [55] ⚡",       "llama-3.1-8b-instant"),
                ("deepseek-r1-70b [72] 🧠",    "deepseek-r1-distill-llama-70b"),
            ],
            "nvidia_key": [
                ("phi-3.5-vision [85] 👁",       "microsoft/phi-3.5-vision-instruct"),
                ("llama-3.2-90b-vision [92] 👁", "meta/llama-3.2-90b-vision-instruct"),
                ("nemotron-70b [88] 📝",         "nvidia/llama-3.1-nemotron-70b-instruct"),
            ],
        }
        _labels_map = {
            "api_key":    "Claude / OpenAI / Gemini:",
            "groq_key":   "Groq API Key:",
            "nvidia_key": "NVIDIA API Key:",
        }

        for key in ["api_key", "groq_key", "nvidia_key"]:
            lbl = _labels_map[key]
            models_list = _models_map[key]

            # عنوان المزود
            tk.Label(p, text=lbl, bg=self.C["panel"], fg=self.C["muted"],
                     font=("Consolas",8)).pack(anchor="w", padx=10)
            # مربع المفتاح
            v = tk.StringVar(value=self._config.get(key,""))
            self._api_vars[key] = v
            tk.Entry(p, textvariable=v, show="•",
                     bg=self.C["inp"], fg=self.C["accent"],
                     font=("Consolas",9), bd=0,
                     insertbackground=self.C["accent"]
                     ).pack(fill="x", padx=10, ipady=4, pady=(0,2))

            # عنوان القائمة
            tk.Label(p, text="اختر النموذج:",
                     bg=self.C["panel"], fg=self.C["muted"],
                     font=("Consolas",7)).pack(anchor="w", padx=10)

            # القائمة المنسدلة
            mv = tk.StringVar(value=self._config.get(f"model_{key}", ""))
            self._model_vars[key] = mv

            # إطار القائمة + زر إضافة
            combo_frame = tk.Frame(p, bg=self.C["panel"])
            combo_frame.pack(fill="x", padx=10, pady=(0,2))

            # Combobox
            from tkinter import ttk
            display_names = [m[0] for m in models_list]
            cb = ttk.Combobox(combo_frame, textvariable=mv,
                              values=display_names,
                              font=("Consolas",8), state="normal",
                              width=28)
            cb.pack(side="left", fill="x", expand=True, ipady=3)

            # تحويل الاختيار من اسم العرض للقيمة الحقيقية
            def _on_select(event, cb=cb, models=models_list, var=mv):
                selected = cb.get()
                for display, real in models:
                    if display == selected:
                        var.set(real)
                        cb.set(display)
                        return
            cb.bind("<<ComboboxSelected>>", _on_select)

            # ضبط القيمة الحالية
            current_val = self._config.get(f"model_{key}", "")
            for display, real in models_list:
                if real == current_val:
                    cb.set(display)
                    break

            # زر + لإضافة نموذج مخصص
            def _add_custom(key=key, cb=cb, models=models_list, var=mv):
                import tkinter.simpledialog as sd
                custom = sd.askstring("نموذج مخصص", "اكتب اسم النموذج:")
                if custom and custom.strip():
                    custom = custom.strip()
                    new_entry = (f"{custom} [?] ✏", custom)
                    models.append(new_entry)
                    cb["values"] = [m[0] for m in models]
                    cb.set(new_entry[0])
                    var.set(custom)

            tk.Button(combo_frame, text="+",
                      command=_add_custom,
                      bg=self.C["accent"], fg="#000",
                      font=("Consolas",9,"bold"),
                      bd=0, padx=6, cursor="hand2"
                      ).pack(side="left", padx=(4,0))

            tk.Frame(p, bg=self.C["border"], height=1).pack(fill="x", padx=10, pady=(4,6))

        # التقنيات
        self._sec(p, "◈  التقنيات الـ 11")
        tf = tk.Frame(p, bg=self.C["panel"])
        tf.pack(fill="x", padx=10, pady=3)

        self._t_vars: Dict[str, tk.BooleanVar] = {}
        toggles = [
            ("⑥ ACTION FORMAT موحد",       None,              self.C["cyan"]),
            ("⑦ Pre-Click Verify",          "pre_click_verify",self.C["green"]),
            ("⑧ إحداثيات /1000",            None,              self.C["cyan"]),
            ("⑨ الذاكرة التراكمية",         "memory_enabled",  self.C["green"]),
            ("⑩ نماذج هرمية تلقائية",       "auto_model",      self.C["green"]),
            ("⑪ المراقب الصامت",            "watcher_enabled", self.C["yellow"]),
            ("① شبكة الإحداثيات",          "grid_enabled",    self.C["green"]),
            ("④ التصحيح الذاتي",           "self_correction", self.C["green"]),
            ("🤝 التعاون مع المستخدم",      "user_collab",     self.C["purple"]),
        ]
        for lbl, key, color in toggles:
            if key:
                v = tk.BooleanVar(value=self._config.get(key, True))
                self._t_vars[key] = v
                tk.Checkbutton(tf, text=lbl, variable=v,
                               bg=self.C["panel"], fg=color,
                               selectcolor=self.C["btn"],
                               activebackground=self.C["panel"],
                               font=("Consolas",8)
                               ).pack(anchor="w", pady=1)
            else:
                tk.Label(tf, text=f"✅ {lbl}",
                         bg=self.C["panel"], fg=color,
                         font=("Consolas",8)
                         ).pack(anchor="w", pady=1)

        # المهمة
        self._sec(p, "◈  المهمة")
        self._task_txt = tk.Text(
            p, height=4, wrap="word",
            bg=self.C["inp"], fg=self.C["text"],
            font=("Consolas",10), bd=0,
            insertbackground=self.C["accent"],
        )
        self._task_txt.pack(fill="x", padx=10, ipady=4)
        self._task_txt.insert("1.0", "مثال: افتح المتصفح وابحث عن أحدث أخبار الذكاء الاصطناعي")

        # العد التنازلي للتعاون
        cd_frame = tk.Frame(p, bg=self.C["panel"])
        cd_frame.pack(fill="x", padx=10, pady=(6,2))
        tk.Label(cd_frame, text="⏱ عد تنازلي (ثوانٍ):",
                 bg=self.C["panel"], fg=self.C["purple"],
                 font=("Consolas",8)).pack(side="left")
        self._countdown_var = tk.IntVar(value=self._config.get("collab_countdown", 10))
        for sec in [5, 10, 15, 20, 30]:
            tk.Radiobutton(cd_frame, text=str(sec),
                           variable=self._countdown_var, value=sec,
                           bg=self.C["panel"], fg=self.C["text"],
                           selectcolor=self.C["btn"],
                           activebackground=self.C["panel"],
                           font=("Consolas",8)
                           ).pack(side="left", padx=3)

        # سياق التطبيق
        tk.Label(p, text="سياق التطبيق (للذاكرة):",
                 bg=self.C["panel"], fg=self.C["muted"],
                 font=("Consolas",8)).pack(anchor="w", padx=10, pady=(6,0))
        self._ctx_var = tk.StringVar(value="desktop")
        tk.Entry(p, textvariable=self._ctx_var,
                 bg=self.C["inp"], fg=self.C["text"],
                 font=("Consolas",9), bd=0
                 ).pack(fill="x", padx=10, ipady=3)

        # الإعدادات
        self._sec(p, "◈  إعدادات")
        gf = tk.Frame(p, bg=self.C["panel"])
        gf.pack(fill="x", padx=10, pady=3)
        params = [
            ("أقصى خطوات:", "max_steps","15"),
            ("تأخير (s):",   "step_delay","1.0"),
            ("عتبة Delta:", "delta_threshold","0.03"),
            ("حد الذاكرة:", "memory_min_success","3"),
            ("فترة المراقب (s):","watcher_interval","30"),
        ]
        self._svars: Dict[str, tk.StringVar] = {}
        for i, (lbl, key, default) in enumerate(params):
            tk.Label(gf, text=lbl, bg=self.C["panel"], fg=self.C["muted"],
                     font=("Consolas",8)).grid(row=i, column=0, sticky="w", pady=1)
            v = tk.StringVar(value=str(self._config.get(key, default)))
            self._svars[key] = v
            tk.Entry(gf, textvariable=v, width=8,
                     bg=self.C["inp"], fg=self.C["text"],
                     font=("Consolas",9), bd=0
                     ).grid(row=i, column=1, padx=6, pady=1)

        # الأزرار
        bf = tk.Frame(p, bg=self.C["panel"])
        bf.pack(fill="x", padx=10, pady=8)
        self._btn(bf,"▶  تشغيل v2.1",self._run,"green",11).pack(fill="x",pady=2)
        self._btn(bf,"■  إيقاف",      self._stop,"red",11).pack(fill="x",pady=2)
        self._btn(bf,"💾 حفظ الإعدادات",self._save).pack(fill="x",pady=2)
        self._btn(bf,"📸 اختبار شبكة", self._test_grid,font_size=9).pack(fill="x",pady=2)
        self._btn(bf,"🧠 عرض الذاكرة", self._show_memory,font_size=9).pack(fill="x",pady=2)
        self._btn(bf,"🗑 مسح الذاكرة", self._clear_memory,font_size=9).pack(fill="x",pady=2)

    def _build_log(self, p: tk.Frame) -> None:
        top = tk.Frame(p, bg=self.C["panel"])
        top.pack(fill="x", padx=8, pady=5)
        tk.Label(top, text="◈  سجل الوكيل v2.1 — مباشر",
                 font=("Consolas",11,"bold"),
                 bg=self.C["panel"], fg=self.C["accent"]).pack(side="left")
        self._btn(top,"مسح",self._clear_log,font_size=9).pack(side="right",padx=4)

        # إطار السجل مع سكرول رأسي وأفقي
        log_frame = tk.Frame(p, bg=self.C["bg"])
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0,8))

        # سكرول رأسي
        v_scroll = tk.Scrollbar(log_frame, orient="vertical")
        v_scroll.pack(side="right", fill="y")

        # سكرول أفقي
        h_scroll = tk.Scrollbar(log_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")

        # منطقة النص
        self._log_txt = tk.Text(
            log_frame,
            bg=self.C["bg"], fg=self.C["text"],
            font=("Consolas",10), bd=0,
            wrap="none",
            state="disabled",
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
        )
        self._log_txt.pack(fill="both", expand=True)

        v_scroll.config(command=self._log_txt.yview)
        h_scroll.config(command=self._log_txt.xview)

        for tag, color, bold in [
            ("SUCCESS", self.C["green"],  True),
            ("INFO",    self.C["text"],   False),
            ("WARNING", self.C["yellow"], False),
            ("ERROR",   self.C["red"],    True),
            ("DEBUG",   self.C["muted"],  False),
        ]:
            kw: Dict[str,Any] = {"foreground": color}
            if bold:
                kw["font"] = ("Consolas", 10, "bold")
            self._log_txt.tag_configure(tag, **kw)

    # ── منطق التشغيل ─────────────────────────────────────────────────

    def _run(self) -> None:
        if self._agent.is_running:
            messagebox.showwarning("تنبيه","الوكيل يعمل!"); return

        # وضع التعاون مع المستخدم
        if self._t_vars.get("user_collab") and self._t_vars["user_collab"].get():
            task = self._task_txt.get("1.0","end").strip()
            if not task:
                messagebox.showerror("خطأ","أدخل وصف المهمة"); return
            seconds = self._countdown_var.get()
            self._safe_log(f"🤝 وضع التعاون — لديك {seconds} ثانية للذهاب للمكان المطلوب!", "WARNING")
            self._safe_log(f"📝 المهمة: {task}", "INFO")
            self._set_status(f"⏱ اذهب للمكان... {seconds}s", self.C["purple"])

            def _collab_worker():
                # أولاً: توليد النص من النموذج (بدون رؤية)
                try:
                    from groq import Groq
                    api_key = self._api_vars["groq_key"].get().strip()
                    if not api_key:
                        # جرب المفتاح العام
                        api_key = self._api_vars["api_key"].get().strip()

                    if api_key:
                        client = Groq(api_key=api_key)
                        self._root.after(0, lambda: self._safe_log("🧠 النموذج يولّد النص...", "INFO"))
                        response = client.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=[
                                {"role": "system", "content": "أنت مساعد كتابة. أجب بالنص المطلوب فقط بدون أي مقدمة أو شرح. فقط النص الجاهز للكتابة."},
                                {"role": "user", "content": task}
                            ],
                            max_tokens=2000,
                            temperature=0.7,
                        )
                        generated_text = response.choices[0].message.content.strip()
                        self._root.after(0, lambda: self._safe_log(f"✅ النص جاهز ({len(generated_text)} حرف)", "SUCCESS"))
                    else:
                        generated_text = task
                        self._root.after(0, lambda: self._safe_log("⚠️ لا يوجد مفتاح Groq — سيكتب المهمة مباشرة", "WARNING"))

                except Exception as ex:
                    generated_text = task
                    self._root.after(0, lambda: self._safe_log(f"⚠️ خطأ في توليد النص: {ex} — سيكتب المهمة مباشرة", "WARNING"))

                # ثانياً: العد التنازلي
                for i in range(seconds, 0, -1):
                    self._root.after(0, lambda i=i: self._set_status(
                        f"⏱ اذهب للمكان وانقر... {i}s", self.C["purple"]))
                    if i <= 5:
                        self._root.after(0, lambda i=i: self._safe_log(f"⏱ {i}...", "WARNING"))
                    time.sleep(1)

                # ثالثاً: الكتابة بعد انتهاء العد
                self._root.after(0, lambda: self._safe_log("✍️ يكتب الآن...", "SUCCESS"))
                self._root.after(0, lambda: self._set_status("✍️ يكتب...", self.C["green"]))

                try:
                    import pyperclip
                    import pyautogui

                    # ضع النص في الحافظة
                    pyperclip.copy(generated_text)
                    time.sleep(0.1)

                    # الصق مباشرة — التركيز عند المستخدم وليس عند البرنامج
                    pyautogui.hotkey("ctrl", "v")

                    self._root.after(0, lambda: self._safe_log(f"✅ تم: {generated_text[:80]}", "SUCCESS"))

                except Exception as ex:
                    self._root.after(0, lambda: self._safe_log(f"❌ خطأ: {ex}", "ERROR"))

                self._root.after(0, lambda: self._set_status("✅ مكتمل", self.C["green"]))

            threading.Thread(target=_collab_worker, daemon=True).start()
            return

        self._run_agent_now()

    def _run_agent_now(self) -> None:
        if not any(self._api_vars[k].get().strip() for k in self._api_vars):
            messagebox.showerror("خطأ","أدخل مفتاح API واحداً على الأقل"); return
        task = self._task_txt.get("1.0","end").strip()
        if not task:
            messagebox.showerror("خطأ","أدخل وصف المهمة"); return
        self._save(silent=True)
        self._stop_event.clear()
        self._set_status("⬤  الوكيل يعمل…", self.C["yellow"])
        threading.Thread(
            target=self._agent.run_task,
            args=(task, self._stop_event, self._on_done, self._ctx_var.get()),
            daemon=True,
        ).start()

    def _on_done(self, success: bool, msg: str) -> None:
        c = self.C["green"] if success else self.C["red"]
        t = "⬤  مكتمل" if success else "⬤  فشل"
        self._root.after(0, lambda: self._set_status(f"{t} — {msg}", c))
        if success:
            self._root.after(0, lambda: messagebox.showinfo("✅ مكتمل", msg))

    def _stop(self) -> None:
        self._stop_event.set()
        self._set_status("⬤  جاري الإيقاف…", self.C["red"])

    def _test_grid(self) -> None:
        self._safe_log("📸 اختبار الشبكة…", "INFO")
        result = self._agent.capture_for_api(grid=True)
        if result:
            b64, _ = result
            kb = len(base64.b64decode(b64)) // 1024
            self._safe_log(f"✅ {kb}KB — vision_debug/ ✓", "SUCCESS")
        else:
            self._safe_log("❌ فشل الالتقاط", "ERROR")

    def _show_memory(self) -> None:
        stats = self._agent._memory.get_stats()
        self._safe_log(f"🧠 الذاكرة: {stats}", "INFO")
        messagebox.showinfo("🧠 الذاكرة التراكمية", f"المحفوظ حالياً:\n{stats}")

    def _clear_memory(self) -> None:
        if messagebox.askyesno("تأكيد","مسح كل الذاكرة؟"):
            self._agent._memory.clear()
            self._safe_log("🗑 تم مسح الذاكرة", "WARNING")

    def _save(self, silent: bool = False) -> None:
        self._config.set("provider", self._prov_var.get())
        for key, var in self._api_vars.items():
            self._config.set(key, var.get().strip())
        # حفظ النماذج المخصصة لكل مزود
        for key, var in self._model_vars.items():
            val = var.get().strip()
            # إذا كان اسم العرض (يحتوي [رقم]) نحوله للقيمة الحقيقية
            import re as _re
            real_match = _re.search(r'\[[\d?]+\].*$', val)
            if real_match:
                # ابحث عن القيمة الحقيقية في القوائم
                pass  # القيمة الحقيقية محفوظة مباشرة في StringVar
            self._config.set(f"model_{key}", val)

        # حفظ إعدادات التعاون
        self._config.set("user_collab", self._t_vars.get("user_collab", tk.BooleanVar()).get() if "user_collab" in self._t_vars else False)
        if hasattr(self, "_countdown_var"):
            self._config.set("collab_countdown", self._countdown_var.get())
        for key, var in self._t_vars.items():
            self._config.set(key, var.get())
        for key, var in self._svars.items():
            try:
                v: Any = float(var.get()) if "." in var.get() else int(var.get())
            except ValueError:
                v = var.get()
            self._config.set(key, v)
        if not silent:
            self._safe_log("💾 حُفظت الإعدادات","SUCCESS")
            messagebox.showinfo("✅","تم الحفظ!")

    # ── مساعدات الواجهة ──────────────────────────────────────────────

    def _sec(self, p: tk.Widget, text: str) -> None:
        tk.Frame(p, bg=self.C["border"], height=1).pack(fill="x", padx=6, pady=(10,0))
        tk.Label(p, text=text, font=("Consolas",9,"bold"),
                 bg=self.C["panel"], fg=self.C["accent"], pady=3
                 ).pack(anchor="w", padx=10)

    def _btn(self, p, text, cmd, color="btn", font_size=10):
        pal = {
            "btn":   (self.C["btn"],   self.C["text"]),
            "green": (self.C["green"], "#001a0d"),
            "red":   (self.C["red"],   "#fff"),
        }
        bg, fg = pal.get(color, pal["btn"])
        return tk.Button(p, text=text, command=cmd,
                         bg=bg, fg=fg, font=("Consolas",font_size),
                         bd=0, relief="flat",
                         activebackground=self.C["border"],
                         activeforeground=self.C["text"],
                         cursor="hand2", padx=6, pady=5)

    def _safe_log(self, msg: str, level: str = "INFO") -> None:
        def _do():
            self._log_txt.configure(state="normal")
            ts  = datetime.now().strftime("%H:%M:%S")
            tag = "INFO" if level not in ("SUCCESS","WARNING","ERROR","DEBUG") else level
            if "─" in msg or "خطوة" in msg:
                tag = "DEBUG"
            self._log_txt.insert("end", f"[{ts}]  {msg}\n", tag)
            self._log_txt.see("end")
            self._log_txt.configure(state="disabled")
        if hasattr(self, "_root") and hasattr(self, "_log_txt"):
            self._root.after(0, _do)

    def _clear_log(self) -> None:
        self._log_txt.configure(state="normal")
        self._log_txt.delete(1.0,"end")
        self._log_txt.configure(state="disabled")

    def _set_status(self, text: str, color: str) -> None:
        self._status.configure(text=text, fg=color)

    def _on_close(self) -> None:
        if self._agent.is_running:
            if not messagebox.askyesno("تأكيد","الوكيل يعمل. خروج؟"):
                return
            self._stop_event.set()
        self._agent.stop_watcher()
        self._root.destroy()

    def run(self) -> None:
        self._safe_log(f"🚀 VisionBot v{VERSION} — 11 تقنية مفعّلة", "SUCCESS")
        techs = [
            "① Visual Gridding — شبكة إحداثيات",
            "② Precision Prompt — Chain of Thought",
            "③ Scale Normalizer — تصحيح الدقة",
            "④ Self-Correction — تصحيح ذاتي",
            "⑤ Delta Detector — كشف التغيير",
            "⑥ ACTION FORMAT — لغة موحدة",
            "⑦ Pre-Click Verify — تحقق قبل النقر",
            "⑧ Coords /1000 — إحداثيات مُطبَّعة",
            "⑨ Memory System — ذاكرة تراكمية",
            "⑩ Hierarchical Models — نماذج هرمية",
            "⑪ Silent Watcher — مراقب صامت",
        ]
        for t in techs:
            self._safe_log(f"  ✅ {t}", "INFO")
        self._safe_log("⚠️ الزاوية العلوية اليسرى للإيقاف الطارئ", "WARNING")
        self._root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# نقطة التشغيل
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = VisionBotGUI21()
    app.run()
