# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import os
import tempfile

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


API_ID = _int("API_ID")
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

OWNER_ID = _int("OWNER_ID", 0)
DEV_USERNAME = os.getenv("DEV_USERNAME", "K0_MG").lstrip("@")
DEV_URL = os.getenv("DEV_URL") or (
    f"https://t.me/{DEV_USERNAME}" if DEV_USERNAME else f"tg://user?id={OWNER_ID}"
)

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")

MAX_FILE_MB = _int("MAX_FILE_MB", 500)
if MAX_FILE_MB < 1:
    MAX_FILE_MB = 500
MAX_CONCURRENT_JOBS = max(1, _int("MAX_CONCURRENT_JOBS", 2))
WORK_DIR = os.getenv("WORK_DIR", tempfile.gettempdir())
JOB_LOCK_TTL_SECONDS = max(30, _int("JOB_LOCK_TTL_SECONDS", 10 * 60))
MAX_CONCURRENT_TRANSMISSIONS = max(1, _int("MAX_CONCURRENT_TRANSMISSIONS", 4))
MIN_FREE_DISK_MB = max(64, _int("MIN_FREE_DISK_MB", 256))
VERIFY_INTEGRITY = os.getenv("VERIFY_INTEGRITY", "1") not in ("0", "false", "False", "")


PATCH_METHODS = ("ZETA1", "ZETA2", "TIMECODE")
PATCH_METHOD = os.getenv("PATCH_METHOD", "ZETA1").strip().upper()
if PATCH_METHOD == "ZETA3":
    PATCH_METHOD = "TIMECODE"
if PATCH_METHOD not in PATCH_METHODS:
    PATCH_METHOD = "ZETA1"

SMART_REENCODE = _bool("SMART_REENCODE", False)
REENCODE_CRF = max(0, min(_int("REENCODE_CRF", 18), 51))
REENCODE_PRESET = os.getenv("REENCODE_PRESET", "medium")
REENCODE_TIMEOUT = _int("REENCODE_TIMEOUT", 1800)
LOW_BITRATE_KBPS = _int("LOW_BITRATE_KBPS", 4000)
COMPRESS_SHORT_SIDE = max(240, _int("COMPRESS_SHORT_SIDE", 1080))

QUALITY_METRIC = os.getenv("QUALITY_METRIC", "auto").strip().lower()
CHECK_MAX_SECONDS = max(1, _int("CHECK_MAX_SECONDS", 30))
CHECK_MAX_DOWNLOAD_MB = _int("CHECK_MAX_DOWNLOAD_MB", 300)
KEEP_REFERENCE = _bool("KEEP_REFERENCE", True)
CHECK_REF_MAX_MB = _int("CHECK_REF_MAX_MB", 500)
CHECK_REF_TTL_HOURS = _int("CHECK_REF_TTL_HOURS", 48)
REF_DIR = os.getenv("REF_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tfps_refs"))
STARS_VIDEO_PRICE = max(1, _int("STARS_VIDEO_PRICE", 250))
STARS_SUB_30D_PRICE = max(0, _int("STARS_SUB_30D_PRICE", 0))
MAX_OPEN_STAR_INVOICES = max(1, _int("MAX_OPEN_STAR_INVOICES", 3))
STAR_INVOICE_COOLDOWN_SECONDS = max(1, _int("STAR_INVOICE_COOLDOWN_SECONDS", 30))
STAR_INVOICE_TTL_HOURS = max(1, _int("STAR_INVOICE_TTL_HOURS", 24))

PROXY_URL = os.getenv("PROXY_URL", "").strip()
LOG_CHAT_ID = _int("LOG_CHAT_ID", 0)


def exceeds_size_limit(size_bytes: int) -> bool:
    return bool(size_bytes) and size_bytes > MAX_FILE_MB * 1024 * 1024


EXPIRY_WARN_DAYS = _int("EXPIRY_WARN_DAYS", 3)


def validate() -> None:
    missing = [
        n
        for n, v in (
            ("API_ID", API_ID),
            ("API_HASH", API_HASH),
            ("BOT_TOKEN", BOT_TOKEN),
            ("OWNER_ID", OWNER_ID),
            ("DATABASE_URL", DATABASE_URL),
        )
        if not v
    ]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
