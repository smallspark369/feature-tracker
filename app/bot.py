"""Telegram bot: entry points into the Mini App + group announcements.

Zero-config behavior:
- The announcement group is captured automatically when the bot is added to
  a group (and re-captured wherever /app is run, so moving groups is just
  running /app in the new one).
- Tracker admins are the group's own admins, fetched live from Telegram and
  cached for 5 minutes. ADMIN_IDS in the environment adds extra admins.
"""
import html
import logging
import time

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from . import db
from .config import settings

log = logging.getLogger(__name__)
router = Router()

GROUP_TYPES = ("group", "supergroup")

_bot: Bot | None = None
_bot_username: str | None = None


def set_bot(bot: Bot | None) -> None:
    global _bot, _bot_username
    _bot = bot
    _bot_username = None


def get_bot() -> Bot | None:
    return _bot


async def bot_username() -> str | None:
    global _bot_username
    if _bot_username is None and _bot is not None:
        try:
            _bot_username = (await _bot.get_me()).username
        except Exception:
            return None
    return _bot_username


def current_group_id() -> int | None:
    """Announcement chat: explicit env override, else the auto-captured one."""
    if settings.group_chat_id is not None:
        return settings.group_chat_id
    raw = db.get_kv("group_chat_id")
    return int(raw) if raw else None


def _remember_group(chat_id: int) -> None:
    db.set_kv("group_chat_id", str(chat_id))


# ---- admin resolution: the group's admins are the tracker's admins ----

_ADMIN_TTL = 300
_admin_cache: dict[int, tuple[float, set[int]]] = {}


async def resolve_admin_ids() -> set[int]:
    ids = set(settings.admin_ids)
    bot = get_bot()
    gid = current_group_id()
    if bot is None or gid is None:
        return ids
    ts, cached = _admin_cache.get(gid, (0.0, set()))
    if time.time() - ts > _ADMIN_TTL:
        try:
            members = await bot.get_chat_administrators(gid)
            cached = {m.user.id for m in members if not m.user.is_bot}
        except Exception:
            log.warning("Could not fetch group admins; using cached/env admins.")
        _admin_cache[gid] = (time.time(), cached)
    return ids | cached


# ---- buttons ----

async def _group_button() -> InlineKeyboardMarkup | None:
    """Open-the-tracker button that works from a group chat.

    Telegram forbids instant-open web_app buttons in groups, so use the
    /newapp direct link when configured, else a deep link into the bot's
    private chat (one extra tap, zero configuration).
    """
    if settings.miniapp_link:
        btn = InlineKeyboardButton(text="Open the tracker", url=settings.miniapp_link)
    else:
        username = await bot_username()
        if not username:
            return None
        btn = InlineKeyboardButton(text="Open the tracker", url=f"https://t.me/{username}?start=open")
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


def _private_button() -> InlineKeyboardMarkup | None:
    """In private chats a web_app button opens the app instantly."""
    if settings.public_url:
        btn = InlineKeyboardButton(text="Open the tracker", web_app=WebAppInfo(url=settings.public_url))
    elif settings.miniapp_link:
        btn = InlineKeyboardButton(text="Open the tracker", url=settings.miniapp_link)
    else:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


# ---- handlers ----

@router.my_chat_member()
async def on_membership_change(event: ChatMemberUpdated) -> None:
    """Capture the group automatically the moment the bot is added to it."""
    if event.chat.type in GROUP_TYPES and event.new_chat_member.status in ("member", "administrator"):
        _remember_group(event.chat.id)
        log.info("Captured group chat %s (%s) for announcements.", event.chat.id, event.chat.title)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.chat.type != "private":
        return
    kb = _private_button()
    text = (
        "This bot runs the community feature &amp; bug tracker.\n\n"
        "File ideas and bug reports, vote on what matters, and get pinged "
        "in the group chat when something ships."
    )
    if kb is None:
        text += "\n\n⚠️ No public URL detected yet — see DEPLOY.md."
    await message.answer(text, reply_markup=kb)


@router.message(Command("feedback"))
async def cmd_feedback(message: Message) -> None:
    """Post an open-the-tracker button. In the group, pin the reply."""
    if message.chat.type in GROUP_TYPES:
        _remember_group(message.chat.id)
    kb = await _group_button() if message.chat.type in GROUP_TYPES else _private_button()
    if kb is None:
        await message.answer("No public URL detected yet — see DEPLOY.md.")
        return
    await message.answer("Ideas &amp; bug reports go here — not into the scroll void:", reply_markup=kb)


@router.message(Command("chatid"))
async def cmd_chatid(message: Message) -> None:
    gid = current_group_id()
    note = " (currently set for announcements)" if gid == message.chat.id else ""
    await message.answer(f"Chat ID: <code>{message.chat.id}</code>{note}")


# ---- announcements ----

async def announce_completed(sub: dict, votes: int) -> bool:
    """Post a completion notice to the group chat. Returns True if sent."""
    bot = get_bot()
    gid = current_group_id()
    if bot is None or gid is None:
        return False

    headline = "🐞 Fixed" if sub["kind"] == "bug" else "✅ Shipped"
    title = html.escape(sub["title"])
    by = html.escape(sub["submitter_name"])
    vote_str = f" · {votes} vote{'s' if votes != 1 else ''}" if votes else ""
    text = f"{headline}: <b>{title}</b>  (#{sub['id']})\nFiled by {by}{vote_str}"

    try:
        await bot.send_message(gid, text, reply_markup=await _group_button())
        return True
    except Exception:
        log.exception("Failed to announce completion to group chat")
        return False
