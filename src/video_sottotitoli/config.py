from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Stable language codes. Display labels belong to the localization layer.
TARGET_LANGUAGE_CODES = ("en", "it", "ja")
SOURCE_LANGUAGE_CODES = ("auto", "en", "it", "ja", "fr")

# Legacy names are kept for prompt and old-job compatibility. The interface no
# longer uses these values; it renders labels through i18n.language_label().
LANGUAGES = {"en": "Inglese", "it": "Italiano", "ja": "Giapponese"}

LANGUAGE_NAMES = {
    **LANGUAGES,
    "fr": "Francese",
}

SOURCE_LANGUAGES = {
    "auto": "Automatico",
    **LANGUAGE_NAMES,
}

# Deprecated compatibility maps. New UI code stores codes directly.
LANGUAGE_CODES_BY_LABEL = {label: code for code, label in LANGUAGES.items()}
SOURCE_LANGUAGE_CODES_BY_LABEL = {label: code for code, label in SOURCE_LANGUAGES.items()}

PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "VideoSottotitoli"
PREFERENCES_PATH = APP_SUPPORT / "preferences.json"
JOBS_DIR = APP_SUPPORT / "jobs"
REVISION_JOBS_DIR = APP_SUPPORT / "revision-jobs"
DOWNLOAD_JOBS_DIR = APP_SUPPORT / "download-jobs"
MAX_VIDEO_SECONDS = 5 * 60 * 60
CHUNK_SECONDS = 10 * 60
WHISPER_COST_PER_MINUTE_USD = 0.006
MODEL_MINI = "gpt-4.1-mini-2025-04-14"
MODEL_SOL = "gpt-6-sol"
MODEL_SOL_LEGACY = "gpt-5.6-sol"
PROVIDER_OPENAI = "openai"
PROVIDER_DEEPSEEK = "deepseek"
AI_PROVIDERS = (PROVIDER_OPENAI, PROVIDER_DEEPSEEK)
DEEPSEEK_FLASH = "deepseek-flash"
DEEPSEEK_PRO = "deepseek-v4-pro"
PROVIDER_MODELS = {
    PROVIDER_OPENAI: (MODEL_MINI, MODEL_SOL_LEGACY, MODEL_SOL),
    PROVIDER_DEEPSEEK: (DEEPSEEK_FLASH, DEEPSEEK_PRO),
}
MODEL_PRICING = {
    MODEL_MINI: {"input": 0.40, "output": 1.60},
    MODEL_SOL: {"input": 2.00, "output": 10.00},
    MODEL_SOL_LEGACY: {"input": 4.00, "output": 20.00},
    DEEPSEEK_FLASH: {"input": 0.14, "output": 0.28},
    DEEPSEEK_PRO: {"input": 0.435, "output": 0.87},
}
REASONING_MODELS = {MODEL_SOL, MODEL_SOL_LEGACY}
REVISION_MODEL = MODEL_MINI
REVISION_INPUT_USD_PER_MILLION = MODEL_PRICING[MODEL_MINI]["input"]
REVISION_OUTPUT_USD_PER_MILLION = MODEL_PRICING[MODEL_MINI]["output"]


def ensure_app_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    REVISION_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_JOBS_DIR.mkdir(parents=True, exist_ok=True)


def load_provider_api_key(provider: str = PROVIDER_OPENAI) -> str | None:
    """Legge la chiave senza stamparla; l'ambiente ha la precedenza."""
    provider = provider if provider in AI_PROVIDERS else PROVIDER_OPENAI
    env_name = "OPENAI_API_KEY" if provider == PROVIDER_OPENAI else "DEEPSEEK_API_KEY"
    account = "openai-api-key" if provider == PROVIDER_OPENAI else "deepseek-api-key"
    value = os.environ.get(env_name, "").strip()
    if value:
        return value

    security = shutil.which("security")
    if security:
        result = subprocess.run(
            [
                security,
                "find-generic-password",
                "-s",
                "VideoSottotitoli",
                "-a",
                account,
                "-w",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    env_file = PROJECT_ROOT / ".env.local"
    if not env_file.is_file():
        return None
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{env_name}="):
                value = line.partition("=")[2].strip().strip("\"'")
                return value or None
    except OSError:
        return None
    return None


def load_api_key() -> str | None:
    """Compatibilità: la chiave storica è quella OpenAI."""
    return load_provider_api_key(PROVIDER_OPENAI)


def save_provider_api_key(api_key: str, provider: str = PROVIDER_OPENAI) -> None:
    """Salva la chiave nel Portachiavi macOS, senza registrarla nei log dell'app."""
    security = shutil.which("security")
    if not security:
        raise RuntimeError("Il Portachiavi macOS non è disponibile su questo computer.")
    provider = provider if provider in AI_PROVIDERS else PROVIDER_OPENAI
    account = "openai-api-key" if provider == PROVIDER_OPENAI else "deepseek-api-key"
    result = subprocess.run(
        [
            security,
            "add-generic-password",
            "-U",
            "-s",
            "VideoSottotitoli",
            "-a",
            account,
            "-w",
            api_key,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Non riesco a salvare la chiave nel Portachiavi macOS.")


def save_api_key(api_key: str) -> None:
    """Compatibilità: salva la chiave storica OpenAI."""
    save_provider_api_key(api_key, PROVIDER_OPENAI)


def estimate_cost_usd(duration_seconds: float) -> float:
    return (duration_seconds / 60) * WHISPER_COST_PER_MINUTE_USD
