"""Configuration, loaded from environment variables (.env supported).

Only BOT_TOKEN is required. Everything else is auto-detected or optional.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str) -> set[int]:
    out = set()
    for part in raw.replace(" ", "").split(","):
        if part:
            try:
                out.add(int(part))
            except ValueError:
                pass
    return out


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _detect_public_url() -> str:
    """Figure out this deployment's public HTTPS URL without configuration.

    Checks an explicit PUBLIC_URL/BASE_URL first, then the env vars that
    common platforms inject automatically.
    """
    explicit = os.getenv("PUBLIC_URL") or os.getenv("BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    render = os.getenv("RENDER_EXTERNAL_URL")           # Render
    if render:
        return render.rstrip("/")
    railway = os.getenv("RAILWAY_PUBLIC_DOMAIN")        # Railway
    if railway:
        return f"https://{railway}"
    fly = os.getenv("FLY_APP_NAME")                     # Fly.io
    if fly:
        return f"https://{fly}.fly.dev"
    return ""


@dataclass
class Settings:
    # --- required ---
    bot_token: str = os.getenv("BOT_TOKEN", "")

    # --- optional overrides ---
    # Extra tracker admins beyond the group's own admins (auto-detected).
    admin_ids: set[int] = field(default_factory=lambda: _parse_ids(os.getenv("ADMIN_IDS", "")))
    # Force a specific announcement chat; normally captured automatically
    # when the bot is added to the group.
    group_chat_id: int | None = field(default_factory=lambda: _parse_optional_int(os.getenv("GROUP_CHAT_ID")))
    # t.me direct link from @BotFather /newapp (optional one-tap polish).
    miniapp_link: str = os.getenv("MINIAPP_LINK", "")

    # --- auto-detected ---
    public_url: str = field(default_factory=_detect_public_url)

    # --- storage ---
    db_path: Path = field(default_factory=lambda: Path(os.getenv("DB_PATH", "tracker.db")))
    upload_dir: Path = field(default_factory=lambda: Path(os.getenv("UPLOAD_DIR", "uploads")))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))

    # --- local development ONLY ---
    dev_user_id: int | None = field(default_factory=lambda: _parse_optional_int(os.getenv("DEV_USER_ID")))

    @property
    def bot_configured(self) -> bool:
        return bool(self.bot_token) and ":" in self.bot_token


settings = Settings()
settings.db_path.parent.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
