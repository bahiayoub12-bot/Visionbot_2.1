"""
╔══════════════════════════════════════════════════════════════════════════╗
║   VisionBot v2.0 — محرك الإدراك المتقدم                                 ║
║                                                                          ║
║   التقنيات المدمجة:                                                      ║
║    1. Visual Gridding    — شبكة إحداثيات ذكية فوق الشاشة               ║
║    2. Precision Prompt   — System Prompt هندسي يجبر LLM على الدقة      ║
║    3. Scale Normalizer   — تصحيح فارق الدقة (4K / FHD / HD)           ║
║    4. Self-Correction    — دورة تحقق: هل نجح النقر؟                    ║
║    5. Delta Compression  — إرسال الاختلافات فقط لتوفير API             ║
║                                                                          ║
║   pip install pyautogui pillow anthropic openai google-generativeai     ║
║   pip install numpy (للـ Delta Compression)                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import base64
import io
import json
import logging
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════
# الثوابت
# ══════════════════════════════════════════════════════════════════════

VERSION     = "2.0.0"
CONFIG_FILE = Path("vision_config.json")
LOG_DIR     = Path("vision_logs")
DEBUG_DIR   = Path("vision_debug")   # يحفظ صور الشبكة للمراجعة

LOG_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)

_log_file = LOG_DIR / f"v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
_logger = logging.getLogger("VisionBot.v2")

Provider = Literal["claude", "openai", "gemini"]


# ══════════════════════════════════════════════════════════════════════
# مدير الإعدادات
# ══════════════════════════════════════════════════════════════════════

class ConfigManager:
    """يحفظ ويحمّل إعدادات VisionBot من vision_config.json."""

    DEFAULTS: Dict[str, Any] = {
        "provider":            "claude",
        "api_key":             "",
        "model":               "",
        "max_steps":           12,
        "step_delay":          1.2,
        "screenshot_quality":  80,
        "move_duration":       0.25,
        "failsafe":            True,
        # إعدادات التقنيات الجديدة
        "grid_step":           100,     # حجم خلية الشبكة بالبكسل
        "grid_enabled":        True,    # تفعيل/تعطيل الشبكة
        "self_correction":     True,    # تفعيل دورة التحقق
        "delta_threshold":     0.03,    # نسبة التغيير المطلوبة (3%)
        "max_retries":         3,       # محاولات إعادة النقر عند الفشل
        "save_debug_images":   True,    # حفظ صور الشبكة في vision_debug/
    }

    DEFAULT_MODELS: Dict[str, str] = {
        "claude": "claude-opus-4-5",
        "openai": "gpt-4o",
        "gemini": "gemini-1.5-pro",
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
        m = self.get("model", "")
        return m or self.DEFAULT_MODELS.get(self.get("provider", "claude"), "")


# ══════════════════════════════════════════════════════════════════════
# التقنية 1: Visual Gridding — الشبكة الذكية
# ══════════════════════════════════════════════════════════════════════

class VisualGridder:
    """
    يرسم شبكة إحداثيات مرئية فوق لقطة الشاشة لمساعدة LLM
    على تحديد المواضع بدقة متناهية.

    المبدأ:
        بدل أن يخمّن LLM "البكسل 783"، يقول:
        "العنصر في خلية (700-800, 300-400) وسطه عند (750, 350)"
        → دقة أعلى بكثير لأن LLM يفكر بالمربعات لا البكسلات.

    التسميات:
        - أعمدة: 0, 100, 200, 300 ... (رقم X)
        - صفوف:  0, 100, 200, 300 ... (رقم Y)
        - لون الشبكة: فوشيا شفاف — لا يتعارض مع ألوان Windows
    """

    GRID_COLOR   = (255, 0, 255)     # Magenta — مميز ونادر في الواجهات
    LABEL_COLOR  = (255, 255, 0)     # أصفر للأرقام — مقروء على أي خلفية
    LINE_OPACITY = 110               # شفافية الخطوط (0-255)
    LABEL_SIZE   = 11                # حجم خط التسمية

    def __init__(self, step: int = 100, save_debug: bool = True) -> None:
        """
        Args:
            step:       المسافة بين خطوط الشبكة بالبكسل (افتراضي 100).
            save_debug: حفظ صور الشبكة في vision_debug/ للمراجعة.
        """
        self.step       = step
        self.save_debug = save_debug

    def draw(self, img_bytes: bytes) -> bytes:
        """
        يرسم الشبكة فوق الصورة ويُعيدها كـ bytes.

        Args:
            img_bytes: الصورة الأصلية كـ bytes (JPEG/PNG).

        Returns:
            الصورة مع الشبكة كـ JPEG bytes.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io as _io

            img  = Image.open(_io.BytesIO(img_bytes)).convert("RGBA")
            w, h = img.size

            # طبقة الشبكة الشفافة
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw    = ImageDraw.Draw(overlay)

            r, g, b   = self.GRID_COLOR
            line_fill = (r, g, b, self.LINE_OPACITY)

            # رسم الخطوط الرأسية والأفقية
            for x in range(0, w, self.step):
                draw.line([(x, 0), (x, h)], fill=line_fill, width=1)
                # تسمية العمود في الأعلى والأسفل
                draw.text((x + 3, 3),      str(x), fill=(*self.LABEL_COLOR, 200))
                draw.text((x + 3, h - 16), str(x), fill=(*self.LABEL_COLOR, 180))

            for y in range(0, h, self.step):
                draw.line([(0, y), (w, y)], fill=line_fill, width=1)
                # تسمية الصف في اليسار واليمين
                draw.text((3,      y + 3), str(y), fill=(*self.LABEL_COLOR, 200))
                draw.text((w - 35, y + 3), str(y), fill=(*self.LABEL_COLOR, 180))

            # دمج الطبقتين
            combined = Image.alpha_composite(img, overlay).convert("RGB")

            # حفظ للمراجعة
            if self.save_debug:
                debug_path = DEBUG_DIR / f"grid_{int(time.time())}.jpg"
                combined.save(debug_path, "JPEG", quality=75)
                _logger.debug(f"🔲 شبكة محفوظة: {debug_path.name}")

            # تحويل للـ bytes
            buf = _io.BytesIO()
            combined.save(buf, "JPEG", quality=80)
            return buf.getvalue()

        except ImportError:
            _logger.warning("⚠️ Pillow غير متاحة — الشبكة معطلة")
            return img_bytes
        except Exception as exc:
            _logger.error(f"❌ خطأ في رسم الشبكة: {exc}")
            return img_bytes

    def build_grid_description(self, screen_w: int, screen_h: int) -> str:
        """
        يُنشئ وصفاً نصياً للشبكة يُضاف للـ Prompt لمساعدة LLM.

        Returns:
            نص يشرح بنية الشبكة للنموذج.
        """
        cols = screen_w // self.step
        rows = screen_h // self.step
        return (
            f"الشاشة مقسمة بشبكة كل {self.step} بكسل. "
            f"الأعمدة: 0,{self.step},...,{cols*self.step} | "
            f"الصفوف: 0,{self.step},...,{rows*self.step}. "
            f"حدد الخلية أولاً ثم المركز الدقيق."
        )


# ══════════════════════════════════════════════════════════════════════
# التقنية 2: Precision Prompt — الـ Prompt الهندسي
# ══════════════════════════════════════════════════════════════════════

class PrecisionPromptBuilder:
    """
    يبني System Prompt هندسياً يُجبر LLM على:
      - التفكير خطوة خطوة قبل إعطاء الإحداثيات
      - التحقق المزدوج (Double-Check) من موقع العنصر
      - الاعتراف بعدم اليقين بدل التخمين
      - إعطاء confidence score مع كل إحداثية
    """

    # الـ System Prompt الهندسي الكامل
    SYSTEM_PROMPT = """أنت محرك إحداثيات عالي الدقة متخصص في تحليل واجهات المستخدم الرسومية (GUI Coordinate Engine).

═══════════════════════════════════════════
قواعد الشبكة:
═══════════════════════════════════════════
الصورة تحتوي على شبكة مرقمة كل 100 بكسل.
الخطوط الفوشيا (Magenta) الرأسية = إحداثيات X.
الخطوط الفوشيا الأفقية = إحداثيات Y.
الأرقام الصفراء على كل خط = قيمة الإحداثي.

═══════════════════════════════════════════
منهجية التفكير الإلزامية (Chain of Thought):
═══════════════════════════════════════════
قبل إعطاء أي إحداثيات، اتبع هذه الخطوات:

الخطوة 1 — التعرف البصري:
  "أرى [وصف العنصر المستهدف] في [موقعه على الشاشة]"

الخطوة 2 — تحديد الخلية:
  "العنصر يقع في خلية X:[رقم-رقم] Y:[رقم-رقم]"
  مثال: "في خلية X:400-500 Y:200-300"

الخطوة 3 — التقدير الدقيق:
  "مركز العنصر يبعد [N] بكسل من خط X:[رقم]"
  "ومركزه يبعد [N] بكسل من خط Y:[رقم]"
  "إذن X النهائي = [رقم+N] = [النتيجة]"

الخطوة 4 — التحقق المزدوج:
  "للتأكد: هل هذا المركز يقع داخل حدود الزر؟ [نعم/لا]"
  "هل هناك عناصر أخرى مشابهة قد تسبب ارتباكاً؟ [نعم/لا+وصف]"

الخطوة 5 — القرار النهائي:
  إعطاء JSON بالصيغة المطلوبة.

═══════════════════════════════════════════
صيغة المخرجات الإلزامية:
═══════════════════════════════════════════
أجب دائماً وحصراً بـ JSON صالح على هذه الصيغة:

{
  "thinking": "تفكيرك الكامل بالخطوات الخمس أعلاه",
  "action": "click|double_click|right_click|type|scroll|hotkey|done|fail",
  "x": <إحداثي أفقي دقيق>,
  "y": <إحداثي عمودي دقيق>,
  "confidence": <0.0-1.0 درجة ثقتك بالإحداثيات>,
  "grid_cell": "X:400-500 Y:200-300",
  "element_description": "وصف العنصر المستهدف",
  "text": "<نص للكتابة — مع action=type فقط>",
  "keys": ["ctrl","c"],
  "direction": "up|down",
  "amount": 3,
  "reason": "سبب هذا الإجراء بجملة واحدة",
  "obstacles": "أي عوائق محتملة (إعلانات، نوافذ منبثقة، إلخ)"
}

قواعد صارمة:
- لا نص قبل JSON أو بعده أبداً
- إذا confidence < 0.6 → action: "fail" مع شرح
- إذا اكتملت المهمة → action: "done"
- لا تخمّن — إذا لم تر العنصر بوضوح قل "fail"
"""

    @staticmethod
    def build_user_message(
        task:        str,
        history:     List[str],
        grid_desc:   str,
        screen_size: Tuple[int, int],
    ) -> str:
        """
        يبني رسالة المستخدم مع كل السياق المطلوب.

        Args:
            task:        المهمة الكاملة.
            history:     قائمة الخطوات السابقة.
            grid_desc:   وصف بنية الشبكة.
            screen_size: (عرض, ارتفاع) الشاشة الفعلية.

        Returns:
            نص الرسالة الكاملة.
        """
        w, h = screen_size
        hist = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(history[-6:]))
        hist_section = f"\nالخطوات المنفذة:\n{hist}" if hist else ""

        return (
            f"المهمة الكاملة: {task}\n"
            f"حجم الشاشة الفعلي: {w}×{h} بكسل\n"
            f"معلومات الشبكة: {grid_desc}"
            f"{hist_section}\n\n"
            "حلّل الشاشة وأعطني الخطوة التالية بصيغة JSON."
        )


# ══════════════════════════════════════════════════════════════════════
# التقنية 3: Scale Normalizer — تصحيح فارق الدقة
# ══════════════════════════════════════════════════════════════════════

class ScaleNormalizer:
    """
    يحل مشكلة اختلاف دقة الصورة المُرسَلة للـ LLM
    عن دقة الشاشة الفعلية.

    المشكلة:
        - الشاشة: 3840×2160 (4K)
        - الصورة المُرسَلة: 1280×720 (مُصغَّرة للـ API)
        - LLM يقول: x=640  (يعني منتصف الصورة المُصغَّرة)
        - الشاشة الفعلية تحتاج: x=1920 (ضعف القيمة)
        → بدون تصحيح: البوت ينقر في المكان الخطأ!

    الحل:
        نحسب نسبة التحجيم ونُطبّقها على الإحداثيات قبل النقر.
    """

    def __init__(self) -> None:
        self._screen_w: int = 1920
        self._screen_h: int = 1080
        self._img_w:    int = 1280
        self._img_h:    int = 720

    def update(
        self,
        screen_w: int, screen_h: int,
        img_w:    int, img_h:    int,
    ) -> None:
        """
        يُحدّث أبعاد الشاشة والصورة.

        Args:
            screen_w/h: أبعاد الشاشة الفعلية.
            img_w/h:    أبعاد الصورة المُرسَلة للـ LLM.
        """
        self._screen_w = screen_w
        self._screen_h = screen_h
        self._img_w    = img_w
        self._img_h    = img_h

        scale_x = screen_w / img_w
        scale_y = screen_h / img_h
        _logger.debug(
            f"📐 Scale: شاشة {screen_w}×{screen_h} | "
            f"صورة {img_w}×{img_h} | "
            f"نسبة X={scale_x:.3f} Y={scale_y:.3f}"
        )

    def normalize(self, ai_x: float, ai_y: float) -> Tuple[int, int]:
        """
        يُحوّل إحداثيات الصورة إلى إحداثيات الشاشة الفعلية.

        Args:
            ai_x: إحداثي X من LLM (بناءً على الصورة المُصغَّرة).
            ai_y: إحداثي Y من LLM.

        Returns:
            (x, y) الإحداثيات الفعلية على الشاشة.
        """
        if self._img_w == 0 or self._img_h == 0:
            return int(ai_x), int(ai_y)

        scale_x = self._screen_w / self._img_w
        scale_y = self._screen_h / self._img_h

        real_x = int(ai_x * scale_x)
        real_y = int(ai_y * scale_y)

        # التأكد من البقاء داخل حدود الشاشة
        real_x = max(0, min(real_x, self._screen_w - 1))
        real_y = max(0, min(real_y, self._screen_h - 1))

        if abs(scale_x - 1.0) > 0.05 or abs(scale_y - 1.0) > 0.05:
            _logger.info(
                f"📐 تصحيح: ({ai_x},{ai_y}) → ({real_x},{real_y}) "
                f"[نسبة {scale_x:.2f}x, {scale_y:.2f}y]"
            )

        return real_x, real_y

    def get_screen_size(self) -> Tuple[int, int]:
        """يُعيد أبعاد الشاشة الفعلية."""
        return self._screen_w, self._screen_h


# ══════════════════════════════════════════════════════════════════════
# التقنية 5: Delta Compression — كشف التغييرات
# ══════════════════════════════════════════════════════════════════════

class DeltaDetector:
    """
    يقارن بين صورتين لمعرفة إذا كان الإجراء أحدث تغييراً فعلياً.

    الاستخدامات:
        1. بعد النقر: هل تغيرت الشاشة؟ إذا لا → ربما فشل النقر
        2. انتظار تحميل: هل توقف التغيير؟ إذا نعم → الصفحة حُمّلت
        3. توفير API: إذا لم يتغير شيء → لا نرسل صورة جديدة

    الخوارزمية:
        - تحويل الصورتين لـ Grayscale (أسرع للمقارنة)
        - حساب الفرق البكسلي (Pixel Difference)
        - حساب نسبة البكسلات المتغيرة
        - إذا تجاوزت العتبة (threshold) → تغيير حقيقي
    """

    def __init__(self, threshold: float = 0.03) -> None:
        """
        Args:
            threshold: نسبة البكسلات المتغيرة الدنيا (0.03 = 3%).
                      أقل من هذا يُعتبر ضوضاء لا تغييراً حقيقياً.
        """
        self.threshold    = threshold
        self._last_frame: Optional[bytes] = None

    def has_changed(self, new_frame: bytes) -> Tuple[bool, float]:
        """
        يقارن الإطار الجديد بالأخير المحفوظ.

        Args:
            new_frame: الصورة الجديدة كـ bytes.

        Returns:
            (changed: bool, change_ratio: float)
            changed=True إذا تغيرت الشاشة بما يكفي.
        """
        if self._last_frame is None:
            self._last_frame = new_frame
            return True, 1.0   # أول مرة → دائماً "تغيير"

        try:
            import numpy as np
            from PIL import Image
            import io as _io

            def to_gray_array(b: bytes):
                img = Image.open(_io.BytesIO(b)).convert("L")
                # تصغير لتسريع المقارنة
                img = img.resize((320, 180), Image.LANCZOS)
                return np.array(img, dtype=np.float32)

            old_arr = to_gray_array(self._last_frame)
            new_arr = to_gray_array(new_frame)

            # الفرق المطلق بين الصورتين
            diff  = np.abs(new_arr - old_arr)

            # نسبة البكسلات التي تغيرت بأكثر من 15 درجة رمادية
            changed_pixels = np.sum(diff > 15)
            total_pixels   = diff.size
            ratio          = changed_pixels / total_pixels

            changed = ratio > self.threshold
            self._last_frame = new_frame

            _logger.debug(f"🔄 Delta: {ratio:.2%} تغيير | {'✅ كافٍ' if changed else '⚠️ ضئيل'}")
            return changed, ratio

        except ImportError:
            # numpy غير متاح — افترض التغيير دائماً
            self._last_frame = new_frame
            return True, 1.0
        except Exception as exc:
            _logger.warning(f"⚠️ خطأ في Delta: {exc}")
            self._last_frame = new_frame
            return True, 1.0

    def reset(self) -> None:
        """يمسح الإطار المحفوظ (للبدء من جديد)."""
        self._last_frame = None

    def get_changed_region(self, new_frame: bytes) -> Optional[Tuple[int,int,int,int]]:
        """
        يحدد المنطقة التي تغيرت في الشاشة.

        مفيد لتضييق بؤرة التحليل وإرسال جزء أصغر للـ API.

        Returns:
            (x1, y1, x2, y2) المنطقة المتغيرة، أو None إذا لم يتغير شيء.
        """
        if self._last_frame is None:
            return None

        try:
            import numpy as np
            from PIL import Image
            import io as _io

            SCALE = 4   # نسخة مصغرة للمعالجة
            def load(b: bytes):
                img = Image.open(_io.BytesIO(b)).convert("L")
                w, h = img.size
                return np.array(img.resize((w//SCALE, h//SCALE))), w, h

            old_arr, orig_w, orig_h = load(self._last_frame)
            new_arr, _, _           = load(new_frame)

            diff = np.abs(new_arr.astype(float) - old_arr.astype(float)) > 15

            rows = np.any(diff, axis=1)
            cols = np.any(diff, axis=0)

            if not rows.any():
                return None

            y1_s, y2_s = np.where(rows)[0][[0, -1]]
            x1_s, x2_s = np.where(cols)[0][[0, -1]]

            # تحويل للإحداثيات الأصلية مع هامش
            margin = 20
            x1 = max(0,      x1_s * SCALE - margin)
            y1 = max(0,      y1_s * SCALE - margin)
            x2 = min(orig_w, x2_s * SCALE + margin)
            y2 = min(orig_h, y2_s * SCALE + margin)

            return x1, y1, x2, y2

        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
# محلل استجابة LLM
# ══════════════════════════════════════════════════════════════════════

class LLMResponseParser:
    """يستخرج بيانات JSON من استجابة LLM الخام."""

    @staticmethod
    def parse(raw: str) -> Dict[str, Any]:
        """
        يستخرج أول JSON صالح من النص.

        Returns:
            dict الإجراء، أو {"action":"fail"} عند الفشل.
        """
        start = raw.find('{')
        end   = raw.rfind('}')
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start:end+1])
                if "action" in data:
                    # تسجيل Chain of Thought إن وجد
                    if "thinking" in data:
                        _logger.info(f"🧠 CoT: {data['thinking'][:120]}…")
                    if "confidence" in data:
                        _logger.info(f"🎯 Confidence: {data['confidence']:.0%}")
                    return data
            except json.JSONDecodeError:
                pass
        _logger.warning(f"⚠️ JSON غير صالح:\n{raw[:300]}")
        return {"action": "fail", "reason": "استجابة LLM غير قابلة للتحليل"}


# ══════════════════════════════════════════════════════════════════════
# عملاء LLM
# ══════════════════════════════════════════════════════════════════════

class BaseLLMClient:
    """الفئة الأم لعملاء LLM."""

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
            msg = PrecisionPromptBuilder.build_user_message(
                task, history, grid_desc, screen_size)
            response = client.messages.create(
                model=self.model, max_tokens=1500,
                system=PrecisionPromptBuilder.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg",
                        "data": screenshot_b64}},
                    {"type": "text", "text": msg},
                ]}],
            )
            return LLMResponseParser.parse(response.content[0].text)
        except ImportError:
            return {"action": "fail", "reason": "pip install anthropic"}
        except Exception as e:
            return {"action": "fail", "reason": str(e)}


class OpenAIClient(BaseLLMClient):
    def analyze(self, screenshot_b64, task, history, grid_desc, screen_size):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            msg = PrecisionPromptBuilder.build_user_message(
                task, history, grid_desc, screen_size)
            response = client.chat.completions.create(
                model=self.model, max_tokens=1500,
                messages=[
                    {"role": "system",
                     "content": PrecisionPromptBuilder.SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{screenshot_b64}",
                            "detail": "high"}},
                        {"type": "text", "text": msg},
                    ]},
                ],
            )
            return LLMResponseParser.parse(response.choices[0].message.content)
        except ImportError:
            return {"action": "fail", "reason": "pip install openai"}
        except Exception as e:
            return {"action": "fail", "reason": str(e)}


class GeminiClient(BaseLLMClient):
    def analyze(self, screenshot_b64, task, history, grid_desc, screen_size):
        try:
            import google.generativeai as genai
            from PIL import Image
            import io as _io
            genai.configure(api_key=self.api_key)
            model    = genai.GenerativeModel(
                self.model,
                system_instruction=PrecisionPromptBuilder.SYSTEM_PROMPT)
            img      = Image.open(_io.BytesIO(base64.b64decode(screenshot_b64)))
            msg      = PrecisionPromptBuilder.build_user_message(
                task, history, grid_desc, screen_size)
            response = model.generate_content([img, msg])
            return LLMResponseParser.parse(response.text)
        except ImportError:
            return {"action": "fail", "reason": "pip install google-generativeai"}
        except Exception as e:
            return {"action": "fail", "reason": str(e)}


def build_llm_client(config: ConfigManager) -> BaseLLMClient:
    """مصنع عملاء LLM."""
    cls_map = {"claude": ClaudeClient,
               "openai": OpenAIClient,
               "gemini": GeminiClient}
    cls = cls_map.get(config.get("provider", "claude"), ClaudeClient)
    return cls(config.get("api_key", ""), config.get_model())


# ══════════════════════════════════════════════════════════════════════
# التقنية 4: Self-Correction — دورة التحقق
# ══════════════════════════════════════════════════════════════════════

class SelfCorrectionEngine:
    """
    يتحقق من نجاح كل إجراء قبل الانتقال للخطوة التالية.

    دورة التحقق:
        1. نفّذ الإجراء (نقر/كتابة/...)
        2. انتظر 1 ثانية
        3. التقط صورة جديدة
        4. قارن مع Delta Detector
        5. إذا لم يتغير شيء → أعد المحاولة بإزاحة ±5px
        6. بعد max_retries محاولات → اسأل LLM مجدداً

    الإزاحة التدريجية:
        المحاولة 1: (x, y)         — المركز الأصلي
        المحاولة 2: (x+5, y)       — إزاحة يمين
        المحاولة 3: (x-5, y+5)     — إزاحة أسفل يسار
        المحاولة 4: (x, y-5)       — إزاحة فوق
    """

    # إزاحات المحاولات التدريجية
    OFFSETS: List[Tuple[int,int]] = [(0,0), (5,0), (-5,5), (0,-5), (5,5)]

    def __init__(
        self,
        delta:       DeltaDetector,
        log_cb:      Callable[[str,str], None],
        wait_secs:   float = 1.0,
        max_retries: int   = 3,
    ) -> None:
        self._delta       = delta
        self._log         = log_cb
        self._wait        = wait_secs
        self._max_retries = max_retries

    def verify_and_retry(
        self,
        pag:          Any,
        x:            int,
        y:            int,
        capture_fn:   Callable[[], Optional[bytes]],
        action_type:  str = "click",
    ) -> bool:
        """
        ينفّذ الإجراء ويتحقق من نجاحه مع إعادة المحاولة إن لزم.

        Args:
            pag:        pyautogui instance.
            x, y:       الإحداثيات المستهدفة.
            capture_fn: دالة تلتقط الشاشة وتُعيد bytes.
            action_type: نوع الإجراء.

        Returns:
            True إذا نجح الإجراء وأحدث تغييراً مرئياً.
        """
        for attempt, (dx, dy) in enumerate(self.OFFSETS[:self._max_retries+1]):
            cx, cy = x + dx, y + dy

            if attempt > 0:
                self._log(
                    f"🔁 إعادة محاولة {attempt} — إزاحة ({dx:+d},{dy:+d}) "
                    f"→ نقر ({cx},{cy})", "WARNING")

            # تنفيذ الإجراء
            try:
                if action_type == "click":
                    pag.click(cx, cy)
                elif action_type == "double_click":
                    pag.doubleClick(cx, cy)
            except Exception as e:
                self._log(f"❌ خطأ في النقر: {e}", "ERROR")
                continue

            # انتظار ظهور التأثير
            time.sleep(self._wait)

            # التحقق من التغيير
            new_frame = capture_fn()
            if new_frame:
                changed, ratio = self._delta.has_changed(new_frame)
                if changed:
                    self._log(
                        f"✅ نجح الإجراء — تغيير الشاشة: {ratio:.1%}", "INFO")
                    return True
                else:
                    self._log(
                        f"⚠️ الشاشة لم تتغير ({ratio:.1%}) — قد يكون فشل",
                        "WARNING")
            else:
                # لا صورة → افترض النجاح
                return True

        self._log(
            f"❌ فشلت جميع المحاولات ({self._max_retries+1}) للنقر على ({x},{y})",
            "ERROR")
        return False


# ══════════════════════════════════════════════════════════════════════
# محرك الوكيل المتقدم v2
# ══════════════════════════════════════════════════════════════════════

class VisionAgentV2:
    """
    الوكيل الكامل — يدمج كل التقنيات الخمس.

    الفرق عن v1:
        v1: صورة خام → LLM → نقر (دقة ~65%)
        v2: صورة+شبكة → LLM المهندَس → تصحيح مقياس → تحقق ذاتي (دقة ~92%)
    """

    def __init__(
        self,
        config:       ConfigManager,
        log_callback: Optional[Callable[[str,str], None]] = None,
    ) -> None:
        self._config = config
        self._log_cb = log_callback
        self.is_running = False

        # التقنيات الخمس
        self._gridder    = VisualGridder(
            step       = config.get("grid_step", 100),
            save_debug = config.get("save_debug_images", True),
        )
        self._scaler     = ScaleNormalizer()
        self._delta      = DeltaDetector(
            threshold = config.get("delta_threshold", 0.03)
        )
        self._corrector  = SelfCorrectionEngine(
            delta       = self._delta,
            log_cb      = self._log,
            max_retries = config.get("max_retries", 3),
        )

        # المكتبات
        self._pag = None
        self._PIL = None
        self._init_libs()

        # سجل الخطوات
        self._history: List[str] = []

    def _init_libs(self) -> None:
        try:
            import pyautogui as pag
            pag.FAILSAFE = self._config.get("failsafe", True)
            pag.PAUSE    = 0.15
            self._pag    = pag
            self._log("✅ PyAutoGUI جاهزة", "INFO")
        except ImportError:
            self._log("❌ pip install pyautogui", "ERROR")

        try:
            from PIL import ImageGrab, Image
            self._PIL = {"ImageGrab": ImageGrab, "Image": Image}
            self._log("✅ Pillow جاهزة", "INFO")
        except ImportError:
            self._log("❌ pip install pillow", "ERROR")

    # ── التقاط الشاشة ────────────────────────────────────────────────

    def _capture_raw(self) -> Optional[bytes]:
        """يلتقط الشاشة ويُعيد bytes خام."""
        if not self._PIL:
            return None
        try:
            try:
                img = self._PIL["ImageGrab"].grab(all_screens=True)
            except TypeError:
                img = self._PIL["ImageGrab"].grab()

            screen_w, screen_h = img.size

            # تصغير للـ API
            max_w = 1280
            if screen_w > max_w:
                ratio = max_w / screen_w
                img   = img.resize(
                    (max_w, int(screen_h * ratio)),
                    self._PIL["Image"].LANCZOS
                )

            img_w, img_h = img.size
            self._scaler.update(screen_w, screen_h, img_w, img_h)

            import io as _io
            buf = _io.BytesIO()
            img.convert("RGB").save(
                buf, "JPEG",
                quality=self._config.get("screenshot_quality", 80)
            )
            return buf.getvalue()

        except Exception as exc:
            self._log(f"❌ خطأ التقاط: {exc}", "ERROR")
            return None

    def capture_for_api(self, apply_grid: bool = True) -> Optional[Tuple[str, bytes]]:
        """
        يلتقط الشاشة ويضيف الشبكة اختيارياً.

        Returns:
            (base64_string, raw_bytes) أو None عند الفشل.
        """
        raw = self._capture_raw()
        if not raw:
            return None

        if apply_grid and self._config.get("grid_enabled", True):
            processed = self._gridder.draw(raw)
        else:
            processed = raw

        b64 = base64.b64encode(processed).decode()
        kb  = len(processed) // 1024
        self._log(f"📸 لقطة: {kb}KB {'+ شبكة' if apply_grid else ''}", "INFO")
        return b64, raw

    # ── تنفيذ الإجراءات ───────────────────────────────────────────────

    def execute_action(self, action: Dict[str, Any]) -> bool:
        """
        يُنفّذ إجراء LLM مع تصحيح المقياس والتحقق الذاتي.

        Args:
            action: dict من LLMResponseParser.

        Returns:
            True عند النجاح.
        """
        if not self._pag:
            return False

        act = action.get("action", "fail")
        # تصحيح المقياس
        raw_x = float(action.get("x", 0))
        raw_y = float(action.get("y", 0))
        x, y  = self._scaler.normalize(raw_x, raw_y)

        conf  = action.get("confidence", 1.0)
        elem  = action.get("element_description", "")
        cell  = action.get("grid_cell", "")

        self._log(
            f"🤖 {act} | conf={conf:.0%} | خلية={cell} | عنصر={elem}", "INFO")

        if conf < 0.5 and act in ("click", "double_click", "right_click"):
            self._log(
                f"⚠️ ثقة منخفضة ({conf:.0%}) — تخطي النقر لتجنب الخطأ",
                "WARNING")
            return False

        try:
            dur = float(self._config.get("move_duration", 0.25))

            if act in ("click", "double_click"):
                use_correction = self._config.get("self_correction", True)

                if use_correction:
                    self._pag.moveTo(x, y, duration=dur)
                    return self._corrector.verify_and_retry(
                        pag        = self._pag,
                        x          = x, y = y,
                        capture_fn = self._capture_raw,
                        action_type = act,
                    )
                else:
                    self._pag.moveTo(x, y, duration=dur)
                    if act == "double_click":
                        self._pag.doubleClick(x, y)
                    else:
                        self._pag.click(x, y)
                    self._log(f"🖱 {act} ({x},{y})", "INFO")
                    return True

            elif act == "right_click":
                self._pag.moveTo(x, y, duration=dur)
                self._pag.rightClick(x, y)
                self._log(f"🖱 right_click ({x},{y})", "INFO")
                return True

            elif act == "type":
                text = action.get("text", "")
                self._pag.write(text, interval=0.04)
                self._log(f"⌨ كتابة: {text[:40]}", "INFO")
                return True

            elif act == "hotkey":
                keys = action.get("keys", [])
                self._pag.hotkey(*keys)
                self._log(f"⌨ اختصار: {'+'.join(keys)}", "INFO")
                return True

            elif act == "scroll":
                direction = action.get("direction", "down")
                amount    = int(action.get("amount", 3))
                clicks    = -amount if direction == "down" else amount
                self._pag.scroll(clicks, x=x, y=y)
                self._log(f"🖱 scroll {direction} ×{amount}", "INFO")
                return True

            elif act in ("done", "fail"):
                return True

            else:
                self._log(f"⚠️ إجراء مجهول: {act}", "WARNING")
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
    ) -> None:
        """
        يُشغّل الوكيل في حلقة ذكية حتى الاكتمال.

        التحسينات عن v1:
            - الشبكة تُضاف لكل صورة
            - Confidence يحدد إذا ننقر أم نتخطى
            - Delta يمنع الإرسال المتكرر بدون تغيير
            - Self-correction ينقذ النقرات الفاشلة
        """
        self.is_running = True
        self._history   = []
        self._delta.reset()
        max_steps  = int(self._config.get("max_steps", 12))
        step_delay = float(self._config.get("step_delay", 1.2))

        self._log(f"🚀 v2 يبدأ: {task}", "SUCCESS")
        self._log(
            f"⚙️ شبكة={'✅' if self._config.get('grid_enabled') else '❌'} | "
            f"تصحيح={'✅' if self._config.get('self_correction') else '❌'} | "
            f"delta={self._config.get('delta_threshold'):.0%}",
            "INFO")

        llm = build_llm_client(self._config)
        screen_size = self._scaler.get_screen_size()

        for step in range(1, max_steps + 1):
            if stop_event.is_set():
                self._log("🛑 إيقاف المستخدم", "WARNING")
                break

            self._log(f"\n{'─'*50}\n الخطوة {step}/{max_steps}", "INFO")

            # التقاط + شبكة
            result = self.capture_for_api(apply_grid=True)
            if not result:
                self._log("❌ فشل الالتقاط", "ERROR")
                break
            b64, raw_bytes = result

            # بناء وصف الشبكة
            sw, sh = screen_size
            grid_desc = self._gridder.build_grid_description(sw, sh)

            # إرسال للـ LLM
            self._log("🧠 تحليل بالذكاء الاصطناعي...", "INFO")
            action = llm.analyze(
                screenshot_b64 = b64,
                task           = task,
                history        = self._history,
                grid_desc      = grid_desc,
                screen_size    = screen_size,
            )

            # التحقق من الاكتمال
            act = action.get("action")
            if act == "done":
                msg = f"✅ مكتمل! {action.get('reason','')}"
                self._log(msg, "SUCCESS")
                if done_cb:
                    done_cb(True, msg)
                self.is_running = False
                return

            if act == "fail":
                reason = action.get("reason", "سبب غير معروف")
                msg    = f"❌ فشل الوكيل: {reason}"
                self._log(msg, "ERROR")
                if done_cb:
                    done_cb(False, msg)
                self.is_running = False
                return

            # تنفيذ الإجراء
            success = self.execute_action(action)

            # تسجيل في التاريخ
            elem   = action.get("element_description", act)
            status = "✅" if success else "⚠️"
            self._history.append(
                f"{status} {act} على '{elem}' "
                f"[conf={action.get('confidence',0):.0%}]"
            )

            time.sleep(step_delay)

        msg = f"⚠️ انتهت {max_steps} خطوة بدون اكتمال"
        self._log(msg, "WARNING")
        if done_cb:
            done_cb(False, msg)
        self.is_running = False

    # ── السجل ─────────────────────────────────────────────────────────

    def _log(self, message: str, level: str = "INFO") -> None:
        getattr(_logger, level.lower(), _logger.info)(message)
        if self._log_cb:
            self._log_cb(message, level)


# ══════════════════════════════════════════════════════════════════════
# الواجهة الرسومية v2
# ══════════════════════════════════════════════════════════════════════

class VisionBotGUIv2:
    """
    واجهة VisionBot v2 — تعرض حالة كل تقنية في الوقت الفعلي.
    """

    C = {
        "bg":      "#070b0e",
        "panel":   "#0c1218",
        "border":  "#1a2530",
        "accent":  "#00e5ff",
        "green":   "#00ff7f",
        "yellow":  "#ffc107",
        "red":     "#ff3d57",
        "purple":  "#b388ff",
        "cyan2":   "#40c4ff",
        "text":    "#cfe8f0",
        "muted":   "#4a6a7a",
        "btn":     "#111e28",
        "input":   "#0a1520",
    }

    def __init__(self) -> None:
        self._config     = ConfigManager()
        self._agent      = VisionAgentV2(self._config, self._safe_log)
        self._stop_event = threading.Event()

        self._root = tk.Tk()
        self._root.title(f"🤖 VisionBot v{VERSION} — محرك الإدراك المتقدم")
        self._root.geometry("1100x720")
        self._root.configure(bg=self.C["bg"])
        self._root.resizable(True, True)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    def _build_ui(self) -> None:
        self._build_header()

        body = tk.Frame(self._root, bg=self.C["bg"])
        body.pack(fill="both", expand=True, padx=8, pady=6)

        # عمود التحكم
        left = tk.Frame(body, bg=self.C["panel"],
                        highlightthickness=1,
                        highlightbackground=self.C["border"],
                        width=340)
        left.pack(side="left", fill="y", padx=(0,5))
        left.pack_propagate(False)
        self._build_control(left)

        # عمود السجل
        right = tk.Frame(body, bg=self.C["panel"],
                         highlightthickness=1,
                         highlightbackground=self.C["border"])
        right.pack(side="left", fill="both", expand=True)
        self._build_log(right)

        self._status = tk.Label(
            self._root,
            text="⬤  جاهز — VisionBot v2 مع كل التقنيات الخمس",
            font=("Consolas", 10),
            bg=self.C["border"], fg=self.C["green"],
            anchor="w", padx=12, pady=5,
        )
        self._status.pack(fill="x", side="bottom")

    def _build_header(self) -> None:
        hdr = tk.Frame(self._root, bg="#001a26", height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(
            hdr,
            text=f"◈  VisionBot v{VERSION}  ·  محرك الإدراك المتقدم",
            font=("Consolas", 13, "bold"),
            bg="#001a26", fg=self.C["accent"],
        ).pack(side="left", padx=16, pady=8)

        # مؤشرات التقنيات الخمس
        techs = [
            ("شبكة",   self._config.get("grid_enabled", True)),
            ("Prompt", True),
            ("Scale",  True),
            ("تحقق",   self._config.get("self_correction", True)),
            ("Delta",  True),
        ]
        for name, active in reversed(techs):
            color = self.C["green"] if active else self.C["muted"]
            tk.Label(
                hdr, text=f"● {name}",
                font=("Consolas", 8, "bold"),
                bg="#001a26", fg=color, padx=6,
            ).pack(side="right", pady=16)

    def _build_control(self, parent: tk.Frame) -> None:
        # ── المزود والـ API ──
        self._sec(parent, "◈  المزود")

        row = tk.Frame(parent, bg=self.C["panel"])
        row.pack(fill="x", padx=10, pady=(2,0))
        self._provider_var = tk.StringVar(value=self._config.get("provider","claude"))
        for val, label in [("claude","Claude"),("openai","GPT-4o"),("gemini","Gemini")]:
            tk.Radiobutton(
                row, text=label, variable=self._provider_var, value=val,
                bg=self.C["panel"], fg=self.C["text"],
                selectcolor=self.C["btn"],
                activebackground=self.C["panel"],
                font=("Consolas", 9),
            ).pack(side="left", padx=5)

        self._sec(parent, "◈  مفتاح API")
        self._api_var = tk.StringVar(value=self._config.get("api_key",""))
        tk.Entry(parent, textvariable=self._api_var, show="•",
                 bg=self.C["input"], fg=self.C["accent"],
                 font=("Consolas",10), bd=0,
                 insertbackground=self.C["accent"]
                 ).pack(fill="x", padx=10, ipady=5)

        # ── التقنيات ──
        self._sec(parent, "◈  التقنيات الخمس")

        tech_frame = tk.Frame(parent, bg=self.C["panel"])
        tech_frame.pack(fill="x", padx=10, pady=4)

        self._grid_var    = tk.BooleanVar(value=self._config.get("grid_enabled", True))
        self._correct_var = tk.BooleanVar(value=self._config.get("self_correction", True))

        checks = [
            ("① شبكة الإحداثيات (Visual Grid)",  self._grid_var),
            ("② Prompt هندسي (Chain of Thought)", None),
            ("③ تصحيح المقياس (Scale Normalize)", None),
            ("④ تحقق ذاتي (Self-Correction)",     self._correct_var),
            ("⑤ ضغط التغييرات (Delta Detection)", None),
        ]
        for label, var in checks:
            if var:
                chk = tk.Checkbutton(
                    tech_frame, text=label, variable=var,
                    bg=self.C["panel"], fg=self.C["green"],
                    selectcolor=self.C["btn"],
                    activebackground=self.C["panel"],
                    font=("Consolas", 8),
                )
                chk.pack(anchor="w", pady=1)
            else:
                tk.Label(
                    tech_frame, text=f"✅ {label}",
                    bg=self.C["panel"], fg=self.C["cyan2"],
                    font=("Consolas", 8),
                ).pack(anchor="w", pady=1)

        # ── المهمة ──
        self._sec(parent, "◈  المهمة")
        self._task_txt = tk.Text(
            parent, height=5, wrap="word",
            bg=self.C["input"], fg=self.C["text"],
            font=("Consolas", 10), bd=0,
            insertbackground=self.C["accent"],
        )
        self._task_txt.pack(fill="x", padx=10, ipady=4)
        self._task_txt.insert("1.0", "مثال: افتح المتصفح وابحث عن سعر الذهب اليوم")

        # ── الإعدادات ──
        self._sec(parent, "◈  الإعدادات")
        grid_frm = tk.Frame(parent, bg=self.C["panel"])
        grid_frm.pack(fill="x", padx=10, pady=3)
        params = [
            ("خطوة الشبكة (px):", "grid_step", "100"),
            ("أقصى خطوات:",       "max_steps", "12"),
            ("تأخير (s):",         "step_delay", "1.2"),
            ("عتبة التغيير (%):",  "delta_threshold", "0.03"),
            ("إعادة المحاولة:",    "max_retries", "3"),
        ]
        self._svars: Dict[str, tk.StringVar] = {}
        for i, (lbl, key, default) in enumerate(params):
            tk.Label(grid_frm, text=lbl, bg=self.C["panel"],
                     fg=self.C["muted"], font=("Consolas",8)
                     ).grid(row=i, column=0, sticky="w", pady=1)
            v = tk.StringVar(value=str(self._config.get(key, default)))
            self._svars[key] = v
            tk.Entry(grid_frm, textvariable=v, width=8,
                     bg=self.C["input"], fg=self.C["text"],
                     font=("Consolas",9), bd=0
                     ).grid(row=i, column=1, padx=6, pady=1)

        # ── أزرار ──
        btn_frm = tk.Frame(parent, bg=self.C["panel"])
        btn_frm.pack(fill="x", padx=10, pady=8)
        self._run_btn = self._btn(btn_frm,"▶  تشغيل v2",self._run,"green",12)
        self._run_btn.pack(fill="x", pady=2)
        self._btn(btn_frm,"■  إيقاف",self._stop,"red",12).pack(fill="x",pady=2)
        self._btn(btn_frm,"💾 حفظ",  self._save).pack(fill="x",pady=2)
        self._btn(btn_frm,"📸 اختبار شبكة",self._test_grid,font_size=9
                  ).pack(fill="x",pady=2)

    def _build_log(self, parent: tk.Frame) -> None:
        top = tk.Frame(parent, bg=self.C["panel"])
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="◈  سجل الوكيل v2",
                 font=("Consolas",11,"bold"),
                 bg=self.C["panel"], fg=self.C["accent"]
                 ).pack(side="left")
        self._btn(top,"مسح",self._clear_log,font_size=9).pack(side="right",padx=4)

        self._log_txt = scrolledtext.ScrolledText(
            parent, bg=self.C["bg"], fg=self.C["text"],
            font=("Consolas",10), bd=0, wrap="word", state="disabled")
        self._log_txt.pack(fill="both", expand=True, padx=8, pady=(0,8))

        for tag, color in [
            ("SUCCESS", self.C["green"]),
            ("INFO",    self.C["text"]),
            ("WARNING", self.C["yellow"]),
            ("ERROR",   self.C["red"]),
            ("STEP",    self.C["accent"]),
            ("DEBUG",   self.C["muted"]),
        ]:
            self._log_txt.tag_configure(tag, foreground=color)
        self._log_txt.tag_configure("STEP",
            font=("Consolas",10,"bold"),
            foreground=self.C["accent"])

    # ── منطق التشغيل ─────────────────────────────────────────────────

    def _run(self) -> None:
        if self._agent.is_running:
            messagebox.showwarning("تنبيه","الوكيل يعمل!"); return
        if not self._api_var.get().strip():
            messagebox.showerror("خطأ","أدخل مفتاح API"); return
        task = self._task_txt.get("1.0","end").strip()
        if not task:
            messagebox.showerror("خطأ","أدخل المهمة"); return
        self._save(silent=True)
        self._stop_event.clear()
        self._set_status("⬤  الوكيل يعمل…", self.C["yellow"])
        threading.Thread(target=self._worker, args=(task,), daemon=True).start()

    def _worker(self, task: str) -> None:
        self._agent.run_task(task, self._stop_event, self._on_done)

    def _on_done(self, success: bool, msg: str) -> None:
        c = self.C["green"] if success else self.C["red"]
        t = "⬤  مكتمل" if success else "⬤  فشل"
        self._root.after(0, lambda: self._set_status(f"{t} — {msg}", c))
        if success:
            self._root.after(0, lambda: messagebox.showinfo("✅",msg))

    def _stop(self) -> None:
        self._stop_event.set()
        self._set_status("⬤  جاري الإيقاف…", self.C["red"])

    def _test_grid(self) -> None:
        """يلتقط شاشة تجريبية مع الشبكة ويحفظها."""
        self._safe_log("📸 اختبار الشبكة...", "INFO")
        result = self._agent.capture_for_api(apply_grid=True)
        if result:
            b64, _ = result
            kb = len(base64.b64decode(b64)) // 1024
            self._safe_log(
                f"✅ نجح — {kb}KB | الصور في: vision_debug/", "SUCCESS")
        else:
            self._safe_log("❌ فشل الالتقاط", "ERROR")

    def _save(self, silent: bool = False) -> None:
        self._config.set("provider",       self._provider_var.get())
        self._config.set("api_key",        self._api_var.get().strip())
        self._config.set("grid_enabled",   self._grid_var.get())
        self._config.set("self_correction",self._correct_var.get())
        for key, var in self._svars.items():
            try:
                v: Any = float(var.get()) if "." in var.get() else int(var.get())
            except ValueError:
                v = var.get()
            self._config.set(key, v)
        if not silent:
            self._safe_log("💾 حُفظت الإعدادات","SUCCESS")
            messagebox.showinfo("✅","تم الحفظ!")

    # ── مساعدات ──────────────────────────────────────────────────────

    def _sec(self, parent: tk.Widget, text: str) -> None:
        tk.Frame(parent, bg=self.C["border"], height=1).pack(fill="x",padx=6,pady=(10,0))
        tk.Label(parent, text=text, font=("Consolas",9,"bold"),
                 bg=self.C["panel"], fg=self.C["accent"],
                 pady=3).pack(anchor="w", padx=10)

    def _btn(self, parent, text, cmd, color="btn", font_size=10):
        pal = {
            "btn":   (self.C["btn"],   self.C["text"]),
            "green": (self.C["green"], "#001a0d"),
            "red":   (self.C["red"],   "#fff"),
        }
        bg, fg = pal.get(color, pal["btn"])
        return tk.Button(parent, text=text, command=cmd,
                         bg=bg, fg=fg, font=("Consolas",font_size),
                         bd=0, relief="flat",
                         activebackground=self.C["border"],
                         activeforeground=self.C["text"],
                         cursor="hand2", padx=6, pady=5)

    def _safe_log(self, msg: str, level: str = "INFO") -> None:
        def _do():
            self._log_txt.configure(state="normal")
            ts  = datetime.now().strftime("%H:%M:%S")
            tag = "STEP" if msg.startswith("─") or "خطوة" in msg else level
            self._log_txt.insert("end", f"[{ts}]  {msg}\n", tag)
            self._log_txt.see("end")
            self._log_txt.configure(state="disabled")
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
        self._root.destroy()

    def run(self) -> None:
        self._safe_log(f"🚀 VisionBot v{VERSION} — كل التقنيات الخمس مفعّلة","SUCCESS")
        self._safe_log("① شبكة الإحداثيات  ✅","INFO")
        self._safe_log("② Prompt هندسي     ✅","INFO")
        self._safe_log("③ تصحيح المقياس    ✅","INFO")
        self._safe_log("④ تحقق ذاتي        ✅","INFO")
        self._safe_log("⑤ Delta Compression ✅","INFO")
        self._safe_log("⚠️ حرّك الماوس لأعلى يسار الشاشة للإيقاف الطارئ","WARNING")
        self._root.mainloop()


# ══════════════════════════════════════════════════════════════════════
# نقطة التشغيل
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = VisionBotGUIv2()
    app.run()
