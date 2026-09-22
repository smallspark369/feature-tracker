"""Telegram bot: entry points into the Mini App + group announcements.

Security model — the tracker is bound to ONE community:
- The bot locks to the first group it's added to. Adding it to any other
  group does nothing; it stays bound.
- Only members of the bound group can use the Mini App at all (verified
  live via getChatMember, cached 5 minutes).
- Only the bound group's admins (plus ADMIN_IDS extras) can triage/delete.
- Moving the binding requires a current admin to run /setgroup in the new
  group. A GROUP_CHAT_ID env var pins it harder than anything else.
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
    _admin_cache.clear()
    _member_cache.clear()


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


# ---- group binding ----

def current_group_id() -> int | None:
    """The bound community chat: env override first, else the locked one."""
    if settings.group_chat_id is not None:
        return settings.group_chat_id
    raw = db.get_kv("group_chat_id")
    return int(raw) if raw else None


def _lock_group(chat_id: int) -> None:
    db.set_kv("group_chat_id", str(chat_id))
    _admin_cache.clear()
    _member_cache.clear()


def _try_capture(chat_id: int) -> bool:
    """Bind only if nothing is bound yet — first group wins, permanently."""
    if current_group_id() is None:
        _lock_group(chat_id)
        return True
    return False


# ---- access control: the bound group's members and admins ----

_TTL = 300
_admin_cache: dict[int, tuple[float, set[int]]] = {}
_member_cache: dict[int, tuple[float, bool]] = {}
_MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}


async def resolve_admin_ids() -> set[int]:
    """Tracker admins = the bound group's admins + ADMIN_IDS extras."""
    ids = set(settings.admin_ids)
    bot = get_bot()
    gid = current_group_id()
    if bot is None or gid is None:
        return ids
    ts, cached = _admin_cache.get(gid, (0.0, set()))
    if time.time() - ts > _TTL:
        try:
            members = await bot.get_chat_administrators(gid)
            cached = {m.user.id for m in members if not m.user.is_bot}
        except Exception:
            log.warning("Could not fetch group admins; using cached/env admins.")
        _admin_cache[gid] = (time.time(), cached)
    return ids | cached


async def is_group_member(user_id: int) -> bool:
    """Is this user in the bound group? Unbound (fresh deploy) or web-only
    dev mode means no gate yet. On Telegram API errors, reuse the last
    known answer; unknown users stay out (fail closed)."""
    bot = get_bot()
    gid = current_group_id()
    if bot is None or gid is None:
        return True
    now = time.time()
    cached = _member_cache.get(user_id)
    if cached and now - cached[0] <= _TTL:
        return cached[1]
    try:
        member = await bot.get_chat_member(gid, user_id)
        ok = member.status in _MEMBER_STATUSES
    except Exception:
        ok = cached[1] if cached else False
        log.warning("Could not verify group membership for user %s.", user_id)
    _member_cache[user_id] = (now, ok)
    return ok


# ---- buttons ----

async def _group_button() -> InlineKeyboardMarkup | None:
    """Open-the-tracker button that works from a group chat."""
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
    if event.chat.type in GROUP_TYPES and event.new_chat_member.status in ("member", "administrator"):
        if _try_capture(event.chat.id):
            log.info("Bound to group %s (%s).", event.chat.id, event.chat.title)
        elif event.chat.id != current_group_id():
            log.info("Added to group %s but already bound elsewhere; ignoring.", event.chat.id)


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
    """Post an open-the-tracker button. In the bound group, pin the reply."""
    if message.chat.type in GROUP_TYPES:
        gid = current_group_id()
        if gid is None:
            _lock_group(message.chat.id)
        elif message.chat.id != gid:
            await message.answer("This tracker is bound to another community's group chat.")
            return
        kb = await _group_button()
    else:
        kb = _private_button()
    if kb is None:
        await message.answer("No public URL detected yet — see DEPLOY.md.")
        return
    await message.answer("Ideas &amp; bug reports go here — not into the scroll void:", reply_markup=kb)


@router.message(Command("setgroup"))
async def cmd_setgroup(message: Message) -> None:
    """Move the binding to this group — current admins only."""
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Run /setgroup inside the group you want the tracker bound to.")
        return
    gid = current_group_id()
    if gid == message.chat.id:
        await message.answer("Already bound to this group.")
        return
    if settings.group_chat_id is not None:
        await message.answer("The group is pinned by the GROUP_CHAT_ID environment variable — change it there.")
        return
    sender = message.from_user.id if message.from_user else 0
    if gid is None or sender in await resolve_admin_ids():
        _lock_group(message.chat.id)
        await message.answer(
            "Done — the tracker is now bound to this group. "
            "Its members can use the app; its admins are the tracker admins."
        )
    else:
        await message.answer("Only an admin of the currently bound community can move the tracker.")


@router.message(Command("chatid"))
async def cmd_chatid(message: Message) -> None:
    gid = current_group_id()
    note = " (the bound community chat)" if gid == message.chat.id else ""
    await message.answer(f"Chat ID: <code>{message.chat.id}</code>{note}")


# ---- announcements ----

async def announce_completed(sub: dict, votes: int) -> bool:
    """Post a completion notice to the bound group. Returns True if sent."""
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
