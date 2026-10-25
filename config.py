"""Загрузка настроек из .env рядом с ботом."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")

# Открытый ключ OpenRouter (бесплатные модели). См. ЧИТАЙ_МЕНЯ.txt
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "LonneyNew").strip().lstrip("@").lower()
OWNER_ID = _int("OWNER_ID", 0)

# Публичный https-адрес мини-приложения.
# Локально: туннель (.env). На Render: подставится автоматически из RENDER_EXTERNAL_URL.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
if not PUBLIC_URL:
    PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
# Render передаёт порт через PORT, локально используем WEBAPP_PORT
WEBAPP_PORT = _int("PORT", 0) or _int("WEBAPP_PORT", 8080)

# Тарифы: цены в Telegram-звёздах (XTR) и дневные лимиты генераций
PRO_STARS = _int("PRO_STARS", 50)
CREATOR_STARS = _int("CREATOR_STARS", 100)
FREE_DAILY = _int("FREE_DAILY", 5)
PRO_DAILY = _int("PRO_DAILY", 50)
CREATOR_DAILY = _int("CREATOR_DAILY", 200)
SUB_DAYS = _int("SUB_DAYS", 30)

# Модели по тарифам (OpenRouter, суффикс :free = бесплатно)
MODEL_FREE = os.environ.get("MODEL_FREE", "google/gemini-2.0-flash-exp:free")
MODEL_PRO = os.environ.get("MODEL_PRO", "deepseek/deepseek-chat-v3-0324:free")
MODEL_CREATOR = os.environ.get("MODEL_CREATOR", "qwen/qwen3-coder:free")

MODELS = {"free": MODEL_FREE, "pro": MODEL_PRO, "creator": MODEL_CREATOR}
MAX_TOKENS = {"free": 30000, "pro": 30000, "creator": 30000}

# Почтовые отчёты о покупках (Gmail + пароль приложения)
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
REPORT_EMAIL = os.environ.get("REPORT_EMAIL", "ferdinand972@gmail.com").strip()

LLM_TIMEOUT = _int("LLM_TIMEOUT", 420)
