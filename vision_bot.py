"""
╔═══════════════════════════════════════════════════════════════════════╗
║         VisionBot — وكيل ذكاء اصطناعي للتحكم في الشاشة              ║
║                                                                       ║
║  المبدأ:                                                              ║
║   1. يلتقط لقطة شاشة                                                 ║
║   2. يرسلها لـ LLM (Claude / GPT-4V / Gemini)                       ║
║   3. يطلب منه: "أين تنقر لتنفيذ المهمة؟"                            ║
║   4. LLM يُعيد إحداثيات دقيقة + وصف                                 ║
║   5. البوت ينقر تلقائياً على تلك الإحداثيات                         ║
║                                                                       ║
║  يدعم: Claude (Anthropic) | GPT-4V (OpenAI) | Gemini (Google)       ║
║                                                                       ║
║  pip install pyautogui pillow anthropic openai google-generativeai   ║
╚═══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════
# الثوابت
# ══════════════════════════════════════════════════════════════════════

VERSION    = "1.0.0"
CONFIG_FILE = Path("vision_config.json")
LOG_DIR     = Path("vision_logs")
LOG_DIR.mkdir(exist_ok=True)

_log_file = LOG_DIR / f"vision_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
_logger = logging.getLogger("VisionBot")

Provider = Literal["claude", "openai", "gemini"]


# ══════════════════════════════════════════════════════════════════════
# مدير الإعدادات
# ══════════════════════════════════════════════════════════════════════

class ConfigManager:
    DEFAULTS: Dict[str, Any] = {
        "provider":        "claude",
        "api_key":         "",
        "model":           "",
        "max_steps":       10,
        "step_delay":      1.5,
        "screenshot_quality": 85,
        "move_duration":   0.3,
        "failsafe":        True,
    }

    # النماذج الافتراضية لكل مزود
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
            except Exception:
                self._data = dict(self.DEFAULTS)
        else:
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
        """يُعيد النموذج المحدد أو الافتراضي للمزود الحالي."""
        m = self.get("model", "")
        if not m:
            return self.DEFAULT_MODELS.get(self.get("provider", "claude"), "")
        return m


# ══════════════════════════════════════════════════════════════════════
# محلل استجابة LLM — يستخرج الإحداثيات والقرار
# ══════════════════════════════════════════════════════════════════════

class LLMResponseParser:
    """
    يحوّل استجابة LLM النصية إلى إجراء محدد.

    الصيغة المتوقعة من LLM (JSON):
    {
      "action": "click" | "type" | "scroll" | "done" | "fail",
      "x": 450,
      "y": 320,
      "text": "النص للكتابة (إن كان action=type)",
      "direction": "up" | "down" (إن كان action=scroll),
      "reason": "وصف سبب هذا الإجراء"
    }
    """

    @staticmethod
    def parse(raw: str) -> Dict[str, Any]:
        """
        يستخرج JSON من نص الاستجابة.

        Args:
            raw: النص الخام من LLM.

        Returns:
            dict يحتوي على action و x و y وغيرها.
            عند الفشل يُعيد {"action": "fail", "reason": "..."}.
        """
        # محاولة إيجاد JSON داخل النص
        for start_char, end_char in [('{', '}'), ]:
            start = raw.find(start_char)
            end   = raw.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                candidate = raw[start:end+1]
                try:
                    data = json.loads(candidate)
                    # التحقق من الحقول الأساسية
                    if "action" in data:
                        return data
                except json.JSONDecodeError:
                    pass

        _logger.warning(f"⚠️ لم يُعثر على JSON في الاستجابة:\n{raw[:200]}")
        return {"action": "fail", "reason": "استجابة LLM غير قابلة للتحليل"}


# ══════════════════════════════════════════════════════════════════════
# عملاء LLM — واجهة موحدة لكل المزودين
# ══════════════════════════════════════════════════════════════════════

class BaseLLMClient:
    """الفئة الأم لجميع عملاء LLM."""

    SYSTEM_PROMPT = """أنت وكيل ذكاء اصطناعي متخصص في التحكم بواجهات المستخدم الرسومية.

مهمتك: تحليل لقطة الشاشة المرفقة وتحديد الإجراء التالي لتنفيذ المهمة المطلوبة.

قواعد صارمة:
1. أجب دائماً بـ JSON صالح فقط، لا نصوص إضافية قبله أو بعده.
2. الإحداثيات يجب أن تكون دقيقة وتشير إلى مركز العنصر المستهدف.
3. إذا اكتملت المهمة أجب بـ action: "done".
4. إذا استحال التنفيذ أجب بـ action: "fail" مع سبب واضح.

صيغة الإجابة الإلزامية:
{
  "action": "click" | "type" | "scroll" | "hotkey" | "done" | "fail",
  "x": <رقم الإحداثي الأفقي>,
  "y": <رقم الإحداثي العمودي>,
  "text": "<النص للكتابة — فقط مع action=type>",
  "keys": ["ctrl", "c"],
  "direction": "up" | "down",
  "amount": <عدد وحدات التمرير>,
  "reason": "<وصف موجز لسبب هذا الإجراء>"
}"""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model   = model

    def analyze(self, screenshot_b64: str, task: str, history: str) -> Dict[str, Any]:
        """
        يرسل لقطة الشاشة والمهمة لـ LLM ويُعيد الإجراء المطلوب.

        Args:
            screenshot_b64: الصورة مشفرة بـ Base64.
            task:           وصف المهمة الكاملة.
            history:        ملخص الخطوات السابقة.

        Returns:
            dict من LLMResponseParser.parse()
        """
        raise NotImplementedError

    def _build_user_message(self, task: str, history: str) -> str:
        hist_section = f"\n\nالخطوات المنفذة حتى الآن:\n{history}" if history else ""
        return (
            f"المهمة: {task}"
            f"{hist_section}\n\n"
            "حلّل الشاشة الحالية وأخبرني بالإجراء التالي بصيغة JSON."
        )


class ClaudeClient(BaseLLMClient):
    """عميل Anthropic Claude (claude-opus-4-5 / claude-sonnet-4-6 ...)."""

    def analyze(self, screenshot_b64: str, task: str, history: str) -> Dict[str, Any]:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            response = client.messages.create(
                model      = self.model,
                max_tokens = 1024,
                system     = self.SYSTEM_PROMPT,
                messages   = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type":       "base64",
                                    "media_type": "image/jpeg",
                                    "data":       screenshot_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": self._build_user_message(task, history),
                            },
                        ],
                    }
                ],
            )
            raw = response.content[0].text
            _logger.debug(f"Claude raw: {raw[:300]}")
            return LLMResponseParser.parse(raw)

        except ImportError:
            return {"action": "fail", "reason": "مكتبة anthropic غير مثبتة — pip install anthropic"}
        except Exception as exc:
            return {"action": "fail", "reason": str(exc)}


class OpenAIClient(BaseLLMClient):
    """عميل OpenAI GPT-4V / GPT-4o."""

    def analyze(self, screenshot_b64: str, task: str, history: str) -> Dict[str, Any]:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            response = client.chat.completions.create(
                model      = self.model,
                max_tokens = 1024,
                messages   = [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url":    f"data:image/jpeg;base64,{screenshot_b64}",
                                    "detail": "high",
                                },
                            },
                            {
                                "type": "text",
                                "text": self._build_user_message(task, history),
                            },
                        ],
                    },
                ],
            )
            raw = response.choices[0].message.content
            return LLMResponseParser.parse(raw)

        except ImportError:
            return {"action": "fail", "reason": "مكتبة openai غير مثبتة — pip install openai"}
        except Exception as exc:
            return {"action": "fail", "reason": str(exc)}


class GeminiClient(BaseLLMClient):
    """عميل Google Gemini 1.5 Pro."""

    def analyze(self, screenshot_b64: str, task: str, history: str) -> Dict[str, Any]:
        try:
            import google.generativeai as genai
            from PIL import Image

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(
                model_name    = self.model,
                system_instruction = self.SYSTEM_PROMPT,
            )

            img_bytes = base64.b64decode(screenshot_b64)
            img       = Image.open(io.BytesIO(img_bytes))

            response = model.generate_content(
                [img, self._build_user_message(task, history)]
            )
            return LLMResponseParser.parse(response.text)

        except ImportError:
            return {"action": "fail", "reason": "مكتبة google-generativeai غير مثبتة — pip install google-generativeai"}
        except Exception as exc:
            return {"action": "fail", "reason": str(exc)}


def build_llm_client(config: ConfigManager) -> BaseLLMClient:
    """
    مصنع يُنشئ العميل المناسب بناءً على الإعدادات.

    Args:
        config: مدير الإعدادات.

    Returns:
        نسخة من ClaudeClient أو OpenAIClient أو GeminiClient.
    """
    provider = config.get("provider", "claude")
    api_key  = config.get("api_key", "")
    model    = config.get_model()

    clients: Dict[str, type] = {
        "claude": ClaudeClient,
        "openai": OpenAIClient,
        "gemini": GeminiClient,
    }
    cls = clients.get(provider, ClaudeClient)
    return cls(api_key=api_key, model=model)


# ══════════════════════════════════════════════════════════════════════
# محرك الوكيل (VisionAgent)
# ══════════════════════════════════════════════════════════════════════

class VisionAgent:
    """
    الوكيل الرئيسي — يجمع بين التقاط الشاشة وتحليل LLM وتنفيذ الإجراءات.

    دورة العمل (حلقة):
        1. screenshot()      → لقطة مضغوطة
        2. llm.analyze()     → إجراء JSON
        3. execute_action()  → تنفيذ فعلي
        4. تكرار حتى done/fail/max_steps
    """

    def __init__(
        self,
        config:       ConfigManager,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._config       = config
        self._log_callback = log_callback
        self.is_running    = False
        self._step_history: List[str] = []

        self._pag = None
        self._PIL = None
        self._init_libs()

    def _init_libs(self) -> None:
        try:
            import pyautogui as pag
            pag.FAILSAFE = self._config.get("failsafe", True)
            pag.PAUSE    = 0.2
            self._pag = pag
            self._log("✅ PyAutoGUI جاهزة", "INFO")
        except ImportError:
            self._log("❌ pip install pyautogui", "ERROR")

        try:
            from PIL import ImageGrab, Image
            self._PIL = {"ImageGrab": ImageGrab, "Image": Image}
            self._log("✅ Pillow جاهزة", "INFO")
        except ImportError:
            self._log("❌ pip install pillow", "ERROR")

    # ── التقاط وضغط الشاشة ───────────────────────────────────────────

    def capture_screenshot(self) -> Optional[str]:
        """
        يلتقط لقطة الشاشة الكاملة ويضغطها بـ JPEG ويُعيدها Base64.

        الضغط يقلل حجم الصورة بنسبة ~80% مما يُسرّع إرسالها للـ API
        ويخفض التكلفة.

        Returns:
            سلسلة Base64 للصورة، أو None عند الفشل.
        """
        if not self._PIL:
            self._log("❌ Pillow غير متاحة", "ERROR")
            return None

        try:
            # دعم الشاشات المتعددة
            try:
                img = self._PIL["ImageGrab"].grab(all_screens=True)
            except TypeError:
                img = self._PIL["ImageGrab"].grab()

            # تصغير الصورة للـ API (1280px عرض كحد أقصى)
            w, h = img.size
            if w > 1280:
                ratio = 1280 / w
                img = img.resize((1280, int(h * ratio)),
                                 self._PIL["Image"].LANCZOS)

            # ضغط بـ JPEG
            quality = self._config.get("screenshot_quality", 85)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=quality)
            b64 = base64.b64encode(buf.getvalue()).decode()

            size_kb = len(buf.getvalue()) // 1024
            self._log(f"📸 لقطة شاشة: {img.size[0]}×{img.size[1]}px | {size_kb}KB", "INFO")
            return b64

        except Exception as exc:
            self._log(f"❌ خطأ في التقاط الشاشة: {exc}", "ERROR")
            return None

    # ── تنفيذ الإجراءات ───────────────────────────────────────────────

    def execute_action(self, action: Dict[str, Any]) -> bool:
        """
        يُنفّذ الإجراء الذي قرره LLM على الشاشة الفعلية.

        Args:
            action: dict من LLMResponseParser يحتوي على type وإحداثيات.

        Returns:
            True إن نُفّذ بنجاح، False عند الخطأ.
        """
        if not self._pag:
            return False

        act  = action.get("action", "fail")
        x    = action.get("x", 0)
        y    = action.get("y", 0)
        reason = action.get("reason", "")

        self._log(f"🤖 LLM قرر: {act} | {reason}", "INFO")

        try:
            dur = float(self._config.get("move_duration", 0.3))

            if act == "click":
                self._pag.moveTo(x, y, duration=dur)
                self._pag.click(x, y)
                self._log(f"🖱 نقر على ({x}, {y})", "INFO")

            elif act == "double_click":
                self._pag.moveTo(x, y, duration=dur)
                self._pag.doubleClick(x, y)
                self._log(f"🖱 نقر مزدوج ({x}, {y})", "INFO")

            elif act == "right_click":
                self._pag.moveTo(x, y, duration=dur)
                self._pag.rightClick(x, y)
                self._log(f"🖱 نقر يمين ({x}, {y})", "INFO")

            elif act == "type":
                text = action.get("text", "")
                self._pag.write(text, interval=0.04)
                self._log(f"⌨ كتابة: {text[:40]}", "INFO")

            elif act == "hotkey":
                keys = action.get("keys", [])
                if keys:
                    self._pag.hotkey(*keys)
                    self._log(f"⌨ اختصار: {'+'.join(keys)}", "INFO")

            elif act == "scroll":
                direction = action.get("direction", "down")
                amount    = int(action.get("amount", 3))
                clicks    = amount if direction == "down" else -amount
                self._pag.scroll(clicks, x=x, y=y)
                self._log(f"🖱 تمرير {direction} بمقدار {amount}", "INFO")

            elif act == "move":
                self._pag.moveTo(x, y, duration=dur)
                self._log(f"🖱 تحريك إلى ({x}, {y})", "INFO")

            elif act in ("done", "fail"):
                return True   # تُعالَج في run_task

            else:
                self._log(f"⚠️ إجراء غير معروف: {act}", "WARNING")
                return False

            # تسجيل في السجل التاريخي
            self._step_history.append(
                f"الخطوة {len(self._step_history)+1}: {act} على ({x},{y}) — {reason}"
            )
            return True

        except Exception as exc:
            self._log(f"❌ خطأ في تنفيذ {act}: {exc}", "ERROR")
            return False

    # ── حلقة التنفيذ الرئيسية ─────────────────────────────────────────

    def run_task(
        self,
        task:       str,
        stop_event: threading.Event,
        done_cb:    Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        """
        يُشغّل الوكيل في حلقة تلقائية حتى اكتمال المهمة أو الإيقاف.

        Args:
            task:       وصف المهمة بالعربية أو الإنجليزية.
            stop_event: حدث إيقاف من الواجهة.
            done_cb:    دالة تُستدعى عند الانتهاء (success: bool, message: str).
        """
        self.is_running    = True
        self._step_history = []
        max_steps          = int(self._config.get("max_steps", 10))
        step_delay         = float(self._config.get("step_delay", 1.5))

        self._log(f"🚀 بدء المهمة: {task}", "SUCCESS")
        self._log(f"⚙️ المزود: {self._config.get('provider')} | النموذج: {self._config.get_model()}", "INFO")

        llm = build_llm_client(self._config)

        for step in range(1, max_steps + 1):
            if stop_event.is_set():
                self._log("🛑 إيقاف المستخدم", "WARNING")
                break

            self._log(f"\n── الخطوة {step}/{max_steps} ──────────────────", "INFO")

            # 1. التقاط الشاشة
            screenshot_b64 = self.capture_screenshot()
            if not screenshot_b64:
                self._log("❌ فشل التقاط الشاشة", "ERROR")
                break

            # 2. إرسال للـ LLM
            self._log("🧠 تحليل الشاشة بالذكاء الاصطناعي...", "INFO")
            history_str = "\n".join(self._step_history[-5:])  # آخر 5 خطوات فقط
            action = llm.analyze(screenshot_b64, task, history_str)

            self._log(f"💬 قرار LLM: {json.dumps(action, ensure_ascii=False)}", "INFO")

            # 3. التحقق من الاكتمال
            if action.get("action") == "done":
                msg = f"✅ المهمة مكتملة! {action.get('reason','')}"
                self._log(msg, "SUCCESS")
                if done_cb:
                    done_cb(True, msg)
                self.is_running = False
                return

            if action.get("action") == "fail":
                msg = f"❌ فشل الوكيل: {action.get('reason','')}"
                self._log(msg, "ERROR")
                if done_cb:
                    done_cb(False, msg)
                self.is_running = False
                return

            # 4. تنفيذ الإجراء
            self.execute_action(action)

            # 5. انتظار قبل الخطوة التالية
            self._log(f"⏳ انتظار {step_delay}s قبل الخطوة التالية...", "INFO")
            time.sleep(step_delay)

        # تجاوز الحد الأقصى
        msg = f"⚠️ وصل الوكيل لحد {max_steps} خطوة بدون اكتمال"
        self._log(msg, "WARNING")
        if done_cb:
            done_cb(False, msg)
        self.is_running = False

    # ── السجل ─────────────────────────────────────────────────────────

    def _log(self, message: str, level: str = "INFO") -> None:
        getattr(_logger, level.lower(), _logger.info)(message)
        if self._log_callback:
            self._log_callback(message, level)


# ══════════════════════════════════════════════════════════════════════
# الواجهة الرسومية
# ══════════════════════════════════════════════════════════════════════

class VisionBotGUI:
    """
    واجهة VisionBot الرسومية — تصميم مستوحى من أدوات AI الاحترافية.
    """

    C = {
        "bg":      "#080c10",
        "panel":   "#0e1318",
        "border":  "#1e2a35",
        "accent":  "#00d4ff",
        "green":   "#00ff88",
        "yellow":  "#ffd700",
        "red":     "#ff4455",
        "purple":  "#a78bfa",
        "text":    "#d4e5f0",
        "muted":   "#5a7a8a",
        "btn":     "#162030",
        "input_bg":"#111820",
    }

    def __init__(self) -> None:
        self._config     = ConfigManager()
        self._agent      = VisionAgent(self._config, log_callback=self._safe_log)
        self._stop_event = threading.Event()

        self._root = tk.Tk()
        self._root.title(f"🤖 VisionBot v{VERSION} — وكيل الذكاء الاصطناعي")
        self._root.geometry("960x680")
        self._root.configure(bg=self.C["bg"])
        self._root.resizable(True, True)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    # ── بناء الواجهة ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_header()

        # ── منطقة المحتوى الرئيسية ──
        content = tk.Frame(self._root, bg=self.C["bg"])
        content.pack(fill="both", expand=True, padx=10, pady=6)

        # ── العمود الأيسر: الإدخال والتحكم ──
        left = tk.Frame(content, bg=self.C["panel"],
                        highlightthickness=1,
                        highlightbackground=self.C["border"])
        left.pack(side="left", fill="y", padx=(0, 5))
        left.pack_propagate(False)
        left.configure(width=320)
        self._build_control_panel(left)

        # ── العمود الأيمن: السجل ──
        right = tk.Frame(content, bg=self.C["panel"],
                         highlightthickness=1,
                         highlightbackground=self.C["border"])
        right.pack(side="left", fill="both", expand=True)
        self._build_log_panel(right)

        # ── شريط الحالة ──
        self._status = tk.Label(
            self._root,
            text="⬤  جاهز — أدخل مهمتك وأضف مفتاح API",
            font=("Consolas", 10),
            bg=self.C["border"], fg=self.C["green"],
            anchor="w", padx=12, pady=5,
        )
        self._status.pack(fill="x", side="bottom")

    def _build_header(self) -> None:
        hdr = tk.Frame(self._root, bg=self.C["accent"], height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # شريط متحرك ضوئي
        canvas = tk.Canvas(hdr, bg=self.C["accent"], height=50,
                           highlightthickness=0)
        canvas.pack(fill="x")

        canvas.create_text(
            20, 25, anchor="w",
            text=f"◈  VisionBot  —  وكيل ذكاء اصطناعي للتحكم بالشاشة  |  v{VERSION}",
            font=("Consolas", 13, "bold"),
            fill="#001a26",
        )

        # مؤشرات المكتبات
        libs = [
            ("PyAutoGUI", self._agent._pag is not None),
            ("Pillow",    self._agent._PIL is not None),
        ]
        x_pos = 900
        for name, ok in reversed(libs):
            color = "#00331a" if ok else "#330008"
            fg    = self.C["green"] if ok else self.C["red"]
            icon  = "●" if ok else "○"
            canvas.create_rectangle(x_pos-80, 12, x_pos+2, 38,
                                    fill=color, outline="")
            canvas.create_text(x_pos-38, 25, text=f"{icon} {name}",
                               font=("Consolas", 9, "bold"), fill=fg)
            x_pos -= 100

    def _build_control_panel(self, parent: tk.Frame) -> None:
        """لوحة التحكم اليسرى."""

        # ── المزود والـ API ──
        self._section(parent, "◈  مزود الذكاء الاصطناعي")

        provider_row = tk.Frame(parent, bg=self.C["panel"])
        provider_row.pack(fill="x", padx=12, pady=(4, 0))
        tk.Label(provider_row, text="المزود:", bg=self.C["panel"],
                 fg=self.C["muted"], font=("Consolas", 9)).pack(side="left")
        self._provider_var = tk.StringVar(value=self._config.get("provider", "claude"))
        for val, label in [("claude","Claude"), ("openai","GPT-4o"), ("gemini","Gemini")]:
            tk.Radiobutton(
                provider_row, text=label, variable=self._provider_var,
                value=val, command=self._on_provider_change,
                bg=self.C["panel"], fg=self.C["text"],
                selectcolor=self.C["btn"],
                activebackground=self.C["panel"],
                font=("Consolas", 9),
            ).pack(side="left", padx=6)

        # مفتاح API
        tk.Label(parent, text="مفتاح API:", bg=self.C["panel"],
                 fg=self.C["muted"], font=("Consolas", 9)).pack(
            anchor="w", padx=12, pady=(8, 2))
        self._api_key_var = tk.StringVar(value=self._config.get("api_key", ""))
        api_entry = tk.Entry(
            parent, textvariable=self._api_key_var,
            show="•", bg=self.C["input_bg"], fg=self.C["accent"],
            font=("Consolas", 10), bd=0, insertbackground=self.C["accent"],
        )
        api_entry.pack(fill="x", padx=12, ipady=5)

        # نموذج LLM
        tk.Label(parent, text="النموذج (اتركه فارغاً للافتراضي):",
                 bg=self.C["panel"], fg=self.C["muted"],
                 font=("Consolas", 9)).pack(anchor="w", padx=12, pady=(8, 2))
        self._model_var = tk.StringVar(value=self._config.get("model", ""))
        tk.Entry(
            parent, textvariable=self._model_var,
            bg=self.C["input_bg"], fg=self.C["text"],
            font=("Consolas", 10), bd=0, insertbackground=self.C["accent"],
        ).pack(fill="x", padx=12, ipady=5)

        self._btn(parent, "💾  حفظ الإعدادات", self._save_settings,
                  "accent").pack(fill="x", padx=12, pady=8)

        # ── المهمة ──
        self._section(parent, "◈  المهمة")

        tk.Label(parent, text="صف ما تريد البوت أن يفعله:",
                 bg=self.C["panel"], fg=self.C["muted"],
                 font=("Consolas", 9)).pack(anchor="w", padx=12, pady=(4, 2))

        self._task_text = tk.Text(
            parent, height=5, wrap="word",
            bg=self.C["input_bg"], fg=self.C["text"],
            font=("Consolas", 10), bd=0,
            insertbackground=self.C["accent"],
        )
        self._task_text.pack(fill="x", padx=12, ipady=4)
        self._task_text.insert("1.0",
            "مثال: افتح المتصفح وابحث عن سعر الذهب اليوم")

        # ── الإعدادات المتقدمة ──
        self._section(parent, "◈  الإعدادات")

        settings_grid = tk.Frame(parent, bg=self.C["panel"])
        settings_grid.pack(fill="x", padx=12, pady=4)

        params = [
            ("أقصى خطوات:", "max_steps", "10"),
            ("تأخير بين الخطوات (s):", "step_delay", "1.5"),
            ("جودة الصورة (%):", "screenshot_quality", "85"),
        ]
        self._setting_vars: Dict[str, tk.StringVar] = {}
        for i, (label, key, default) in enumerate(params):
            tk.Label(settings_grid, text=label,
                     bg=self.C["panel"], fg=self.C["muted"],
                     font=("Consolas", 8)).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(self._config.get(key, default)))
            self._setting_vars[key] = var
            tk.Entry(settings_grid, textvariable=var, width=8,
                     bg=self.C["input_bg"], fg=self.C["text"],
                     font=("Consolas", 9), bd=0).grid(row=i, column=1, padx=6, pady=2)

        # ── أزرار التشغيل ──
        run_frame = tk.Frame(parent, bg=self.C["panel"])
        run_frame.pack(fill="x", padx=12, pady=10)

        self._run_btn = self._btn(
            run_frame, "▶  تشغيل الوكيل", self._run_agent, "green", 12)
        self._run_btn.pack(fill="x", pady=2)

        self._stop_btn = self._btn(
            run_frame, "■  إيقاف", self._stop_agent, "red", 12)
        self._stop_btn.pack(fill="x", pady=2)

        self._btn(run_frame, "📸  التقاط شاشة تجريبي",
                  self._test_screenshot, font_size=9).pack(fill="x", pady=2)

    def _build_log_panel(self, parent: tk.Frame) -> None:
        """لوحة السجل اليمنى."""

        top = tk.Frame(parent, bg=self.C["panel"])
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="◈  سجل الوكيل — مباشر",
                 font=("Consolas", 11, "bold"),
                 bg=self.C["panel"], fg=self.C["accent"]).pack(side="left")
        self._btn(top, "مسح", self._clear_log, font_size=9).pack(side="right", padx=4)

        self._log_text = scrolledtext.ScrolledText(
            parent,
            bg=self.C["bg"], fg=self.C["text"],
            font=("Consolas", 10), bd=0,
            wrap="word", state="disabled",
        )
        self._log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ألوان السجل
        self._log_text.tag_configure("SUCCESS", foreground=self.C["green"])
        self._log_text.tag_configure("INFO",    foreground=self.C["text"])
        self._log_text.tag_configure("WARNING", foreground=self.C["yellow"])
        self._log_text.tag_configure("ERROR",   foreground=self.C["red"])
        self._log_text.tag_configure("DEBUG",   foreground=self.C["muted"])
        self._log_text.tag_configure("STEP",
            foreground=self.C["accent"],
            font=("Consolas", 10, "bold"))

    # ── منطق التشغيل ─────────────────────────────────────────────────

    def _run_agent(self) -> None:
        if self._agent.is_running:
            messagebox.showwarning("تنبيه", "الوكيل يعمل بالفعل!")
            return

        api_key = self._api_key_var.get().strip()
        if not api_key:
            messagebox.showerror("خطأ", "أدخل مفتاح API أولاً!")
            return

        task = self._task_text.get("1.0", "end").strip()
        if not task:
            messagebox.showerror("خطأ", "أدخل وصف المهمة أولاً!")
            return

        # حفظ الإعدادات
        self._save_settings(silent=True)

        self._stop_event.clear()
        self._set_status("⬤  الوكيل يعمل…", self.C["yellow"])

        threading.Thread(
            target=self._agent_worker,
            args=(task,),
            daemon=True,
        ).start()

    def _agent_worker(self, task: str) -> None:
        """Thread الخلفي لتشغيل الوكيل."""
        self._agent.run_task(
            task       = task,
            stop_event = self._stop_event,
            done_cb    = self._on_agent_done,
        )

    def _on_agent_done(self, success: bool, message: str) -> None:
        color = self.C["green"] if success else self.C["red"]
        icon  = "⬤  مكتمل" if success else "⬤  فشل"
        self._root.after(0, lambda: self._set_status(f"{icon} — {message}", color))
        if success:
            self._root.after(0, lambda: messagebox.showinfo("✅ مكتمل", message))

    def _stop_agent(self) -> None:
        self._stop_event.set()
        self._set_status("⬤  جاري الإيقاف…", self.C["red"])

    def _test_screenshot(self) -> None:
        """يلتقط شاشة تجريبية ويعرض حجمها."""
        self._safe_log("📸 اختبار التقاط الشاشة...", "INFO")
        b64 = self._agent.capture_screenshot()
        if b64:
            kb = len(base64.b64decode(b64)) // 1024
            self._safe_log(f"✅ لقطة ناجحة — الحجم: {kb}KB", "SUCCESS")
        else:
            self._safe_log("❌ فشل الالتقاط", "ERROR")

    # ── الإعدادات ─────────────────────────────────────────────────────

    def _on_provider_change(self) -> None:
        provider = self._provider_var.get()
        default  = ConfigManager.DEFAULT_MODELS.get(provider, "")
        self._model_var.set("")
        self._safe_log(f"🔄 تغيير المزود إلى: {provider} (النموذج الافتراضي: {default})", "INFO")

    def _save_settings(self, silent: bool = False) -> None:
        self._config.set("provider", self._provider_var.get())
        self._config.set("api_key",  self._api_key_var.get().strip())
        self._config.set("model",    self._model_var.get().strip())

        for key, var in self._setting_vars.items():
            try:
                val = float(var.get()) if "." in var.get() else int(var.get())
            except ValueError:
                val = var.get()
            self._config.set(key, val)

        if not silent:
            self._safe_log("💾 تم حفظ الإعدادات", "SUCCESS")
            messagebox.showinfo("✅", "تم حفظ الإعدادات!")

    # ── مساعدات الواجهة ──────────────────────────────────────────────

    def _section(self, parent: tk.Widget, text: str) -> None:
        f = tk.Frame(parent, bg=self.C["border"], height=1)
        f.pack(fill="x", padx=8, pady=(12, 0))
        tk.Label(parent, text=text,
                 font=("Consolas", 9, "bold"),
                 bg=self.C["panel"], fg=self.C["accent"],
                 pady=4).pack(anchor="w", padx=12)

    def _btn(self, parent: tk.Widget, text: str, command: Callable,
             color: str = "btn", font_size: int = 10) -> tk.Button:
        palette = {
            "btn":    (self.C["btn"],    self.C["text"]),
            "green":  (self.C["green"],  "#001a0d"),
            "red":    (self.C["red"],    "#fff"),
            "accent": (self.C["accent"], "#00111a"),
        }
        bg, fg = palette.get(color, palette["btn"])
        return tk.Button(
            parent, text=text, command=command,
            bg=bg, fg=fg, font=("Consolas", font_size),
            bd=0, relief="flat",
            activebackground=self.C["border"],
            activeforeground=self.C["text"],
            cursor="hand2", padx=8, pady=5,
        )

    def _safe_log(self, message: str, level: str = "INFO") -> None:
        """يُضيف رسالة للسجل بأمان من أي thread."""
        def _do() -> None:
            self._log_text.configure(state="normal")
            ts  = datetime.now().strftime("%H:%M:%S")
            tag = "STEP" if message.startswith("──") else level
            self._log_text.insert("end", f"[{ts}]  {message}\n", tag)
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
        self._root.after(0, _do)

    def _clear_log(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete(1.0, "end")
        self._log_text.configure(state="disabled")

    def _set_status(self, text: str, color: str) -> None:
        self._status.configure(text=text, fg=color)

    def _on_close(self) -> None:
        if self._agent.is_running:
            if not messagebox.askyesno("تأكيد", "الوكيل يعمل. إيقاف والخروج؟"):
                return
            self._stop_event.set()
        self._root.destroy()

    def run(self) -> None:
        self._safe_log(f"🚀 VisionBot v{VERSION} جاهز!", "SUCCESS")
        self._safe_log("1. أضف مفتاح API", "INFO")
        self._safe_log("2. اختر المزود (Claude / GPT-4o / Gemini)", "INFO")
        self._safe_log("3. اكتب المهمة بالعربية أو الإنجليزية", "INFO")
        self._safe_log("4. اضغط ▶ تشغيل الوكيل", "INFO")
        self._safe_log("⚠️  حرّك الماوس لأعلى يسار الشاشة للإيقاف الطارئ", "WARNING")
        self._root.mainloop()


# ══════════════════════════════════════════════════════════════════════
# نقطة التشغيل
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = VisionBotGUI()
    app.run()
