import asyncio
import json
import logging
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = "8617664721:AAGZIaFutCbjfUEwdbIO6ogdsL5Pk6la_Tg"
API_URL = "https://tg-20-likes-one.vercel.app/like"
API_KEY = "CRAXX"

# Optional fixed admin IDs. Leave empty if every Telegram group admin
# should be allowed to use /admin.
ADMIN_IDS = set()
DATA_FILE = Path("bot_data.json")
IST = ZoneInfo("Asia/Kolkata")
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

LOADING_FRAMES = [
    "⚡ [▱▱▱▱▱▱▱▱▱▱] 0%",
    "⚡ [▰▱▱▱▱▱▱▱▱▱] 10%",
    "⚡ [▰▰▱▱▱▱▱▱▱▱] 20%",
    "⚡ [▰▰▰▱▱▱▱▱▱▱] 30%",
    "⚡ [▰▰▰▰▱▱▱▱▱▱] 40%",
    "⚡ [▰▰▰▰▰▱▱▱▱▱] 50%",
    "⚡ [▰▰▰▰▰▰▱▱▱▱] 60%",
    "⚡ [▰▰▰▰▰▰▰▱▱▱] 70%",
    "⚡ [▰▰▰▰▰▰▰▰▱▱] 80%",
    "⚡ [▰▰▰▰▰▰▰▰▰▱] 90%",
    "⚡ [▰▰▰▰▰▰▰▰▰▰] 100%",
]

# Per-user lock prevents two simultaneous /like requests from consuming
# the same daily slot.
USER_LOCKS = {}
AUTO_KICK_TASK = None


def load_db():
    if not DATA_FILE.exists():
        return {
            "users": {},          # chat_id -> user_id -> profile
            "usage": {},          # chat_id -> user_id -> usage record
            "auto_kick": {},      # chat_id -> settings
        }
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        data.setdefault("users", {})
        data.setdefault("usage", {})
        data.setdefault("auto_kick", {})
        return data
    except Exception:
        logger.exception("Could not read bot_data.json; starting fresh.")
        return {"users": {}, "usage": {}, "auto_kick": {}}


DB = load_db()


def save_db():
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(DB, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(DATA_FILE)


def now_ist():
    return datetime.now(IST)


def usage_day():
    """Daily window is 04:00 IST -> next day's 03:59:59 IST."""
    now = now_ist()
    if now.time() < dtime(4, 0):
        return (now.date() - timedelta(days=1)).isoformat()
    return now.date().isoformat()


def get_user_lock(chat_id, user_id):
    key = (chat_id, user_id)
    if key not in USER_LOCKS:
        USER_LOCKS[key] = asyncio.Lock()
    return USER_LOCKS[key]


def remember_user(chat_id, user):
    if not user or user.is_bot:
        return
    chat_key = str(chat_id)
    user_key = str(user.id)
    DB["users"].setdefault(chat_key, {})
    old = DB["users"][chat_key].get(user_key, {})
    DB["users"][chat_key][user_key] = {
        "id": user.id,
        "name": user.full_name,
        "username": user.username or old.get("username"),
        "first_seen": old.get("first_seen", now_ist().isoformat()),
        "last_seen": now_ist().isoformat(),
    }


async def is_group_admin(update, user_id=None):
    chat = update.effective_chat
    user = update.effective_user
    target_id = user_id or (user.id if user else None)
    if not chat or chat.type not in ("group", "supergroup") or target_id is None:
        return False

    if target_id in ADMIN_IDS:
        return True

    try:
        member = await chat.get_member(target_id)
        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except Exception:
        return False


async def require_admin(update):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text(
            "❌ <b>This command can only be used inside the group.</b>",
            parse_mode="HTML",
        )
        return False

    if not await is_group_admin(update):
        await update.effective_message.reply_text(
            "❌ <b>Only group admins can use this.</b>",
            parse_mode="HTML",
        )
        return False
    return True


async def track_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remember members whenever they interact with the bot/group."""
    chat = update.effective_chat
    user = update.effective_user
    if chat and chat.type in ("group", "supergroup") and user:
        remember_user(chat.id, user)
        save_db()


async def track_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or not cm.chat:
        return

    chat_id = cm.chat.id
    new_status = cm.new_chat_member.status
    user = cm.new_chat_member.user

    if new_status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    ):
        remember_user(chat_id, user)
        save_db()


def progress_bar(used: int, limit: int, length: int = 10) -> str:
    if limit <= 0:
        return "▱" * length
    filled = min(int((used / limit) * length), length)
    return "▰" * filled + "▱" * (length - filled)


async def animate_loading(message, region: str, uid: str):
    header = (
        "<b>🚀 ʟɪᴋᴇ ʀᴇǫᴜᴇsᴛ ᴘʀᴏᴄᴇssɪɴɢ</b>\n"
        "<i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>\n\n"
        f"🌍 <b>ʀᴇɢɪᴏɴ:</b> <code>{region}</code>\n"
        f"🆔 <b>ᴜɪᴅ:</b> <code>{uid}</code>\n\n"
    )
    for frame in LOADING_FRAMES:
        try:
            await message.edit_text(
                header + f"<code>{frame}</code>",
                parse_mode="HTML",
            )
            await asyncio.sleep(0.18)
        except Exception:
            return


async def call_api(region: str, uid: str):
    params = {"uid": uid, "region": region, "key": API_KEY}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(API_URL, params=params) as resp:
            data = await resp.json(content_type=None)
            return resp.status, data


def get_usage(chat_id, user_id):
    chat_key, user_key = str(chat_id), str(user_id)
    usage = DB["usage"].setdefault(chat_key, {}).setdefault(
        user_key, {"day": usage_day(), "used": 0}
    )
    if usage.get("day") != usage_day():
        usage["day"] = usage_day()
        usage["used"] = 0
    return usage


def has_used_today(chat_id, user_id):
    return get_usage(chat_id, user_id).get("used", 0) >= 1


def consume_slot(chat_id, user_id):
    usage = get_usage(chat_id, user_id)
    usage["used"] = 1
    usage["last_success"] = now_ist().isoformat()
    save_db()


def get_like_values(data, region, uid):
    """Read the current API response fields.

    Current API response:
      Nickname, Before, After, Given, Region, UID, status
    The old field names are kept as fallbacks so an older API response
    will still work.
    """
    nickname = data.get("Nickname", data.get("PlayerNickname", "N/A"))
    level = data.get("Level", "N/A")
    reg = data.get("Region", region)
    uid_resp = data.get("UID", uid)
    before = data.get("Before", data.get("LikesbeforeCommand", 0))
    after = data.get("After", data.get("LikesafterCommand", 0))
    given = data.get("Given", data.get("LikesGivenByAPI", 0))
    return nickname, level, reg, uid_resp, before, after, given


def api_response_is_valid(data):
    """The user's current API returns status=1 and Nickname/Before/After/Given."""
    return (
        isinstance(data, dict)
        and data.get("status") == 1
        and "Nickname" in data
    ) or (
        isinstance(data, dict)
        and data.get("status") in (1, 2)
        and "PlayerNickname" in data
    )


def format_like_result(data, region, uid, used):
    nickname, level, reg, uid_resp, before, after, given = get_like_values(
        data, region, uid
    )

    return (
        "🎉 <b>HQ FREE LIKES SENT SUCCESSFULLY!</b> 🎉\n\n"
        "<blockquote>"
        f"👑 <b>ɴᴀᴍᴇ:</b> <code>{nickname}</code>\n"
        f"🌍 <b>ʀᴇɢɪᴏɴ:</b> <code>{reg}</code>\n"
        f"🆔 <b>ᴜɪᴅ:</b> <code>{uid_resp}</code>"
        "</blockquote>\n\n"
        f"  📉 <b>ʙᴇꜰᴏʀᴇ:</b> <code>{before}</code>\n"
        f"  📈 <b>ᴀꜰᴛᴇʀ:</b> <code>{after}</code>\n"
        f"  💖 <b>ɢɪᴠᴇɴ:</b> <code>+{given}</code>\n\n"
        f"🎁 <b>ʏᴏᴜʀ ʟɪᴍɪᴛ:</b> <code>{used}/1</code>\n\n"
        "📌 Verify & get free likes daily via @getset20_bot"
    )


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎮 <b>WELCOME TO FREE LIKE BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 <b>ᴜsᴀɢᴇ:</b>\n"
        "<code>/like &lt;region&gt; &lt;uid&gt;</code>\n\n"
        "📌 <b>ᴇxᴀᴍᴘʟᴇ:</b>\n"
        "<code>/like IND 12345609</code>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await update.effective_message.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def like_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if not chat or chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text(
            "❌ <b>/like can only be used in the group.</b>",
            parse_mode="HTML",
        )
        return

    remember_user(chat.id, user)
    save_db()

    # Admins can use the normal command without consuming the user slot.
    admin = await is_group_admin(update)

    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text(
            "❌ <b>ɪɴᴠᴀʟɪᴅ ᴜsᴀɢᴇ!</b>\n\n"
            "✅ <b>ᴄᴏʀʀᴇᴄᴛ:</b> <code>/like &lt;region&gt; &lt;uid&gt;</code>\n"
            "📌 <b>ᴇxᴀᴍᴘʟᴇ:</b> <code>/like BD 16983198706</code>",
            parse_mode="HTML",
        )
        return

    region = args[0].upper().strip()
    uid = args[1].strip()

    if not uid.isdigit():
        await update.effective_message.reply_text(
            "❌ <b>ᴜɪᴅ ᴍᴜsᴛ ʙᴇ ɴᴜᴍᴇʀɪᴄ!</b>",
            parse_mode="HTML",
        )
        return

    lock = get_user_lock(chat.id, user.id)

    async with lock:
        if not admin and has_used_today(chat.id, user.id):
            await update.effective_message.reply_text(
                "⛔ <b>Daily like limit already used.</b>\n\n"
                "You can use <code>/like</code> again after <b>04:00 IST</b>.",
                parse_mode="HTML",
            )
            return

        msg = await update.effective_message.reply_text(
            "⏳ <b>ɪɴɪᴛɪᴀʟɪᴢɪɴɢ...</b>",
            parse_mode="HTML",
        )
        anim_task = asyncio.create_task(animate_loading(msg, region, uid))

        try:
            status, data = await call_api(region, uid)
        except Exception as e:
            anim_task.cancel()
            await msg.edit_text(
                f"⚠️ <b>ɴᴇᴛᴡᴏʀᴋ ᴇʀʀᴏʀ!</b>\n<code>{e}</code>",
                parse_mode="HTML",
            )
            return

        anim_task.cancel()

        if not isinstance(data, dict):
            await msg.edit_text(
                "❌ <b>ɪɴᴠᴀʟɪᴅ ʀᴇsᴘᴏɴsᴇ ꜰʀᴏᴍ ᴀᴘɪ</b>",
                parse_mode="HTML",
            )
            return

        if not api_response_is_valid(data):
            err = data.get("error") or data.get("message") or "ᴜɴᴋɴᴏᴡɴ ᴇʀʀᴏʀ"
            await msg.edit_text(
                f"❌ <b>ꜰᴀɪʟᴇᴅ!</b>\n\n"
                f"📝 <b>ʀᴇᴀsᴏɴ:</b> ʟɪᴋᴇ ʟɪᴍɪᴛ ʀᴇᴀᴄʜᴇᴅ\n"
                f"🌍 <b>ʀᴇɢɪᴏɴ:</b> <code>{region}</code>\n"
                f"🆔 <b>ᴜɪᴅ:</b> <code>{uid}</code>",
                parse_mode="HTML",
            )
            return

        given = data.get("Given", data.get("LikesGivenByAPI", 0))
        try:
            given_num = int(given or 0)
        except (TypeError, ValueError):
            given_num = 0

        # IMPORTANT: the user's one-use slot is consumed ONLY when API
        # actually gives at least one like.
        if not admin and given_num > 0:
            consume_slot(chat.id, user.id)
            used = 1
        else:
            used = get_usage(chat.id, user.id).get("used", 0)

        text = format_like_result(data, region, uid, used)

        await msg.edit_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def help_callback(query):
    await query.message.reply_text(
        "❤️ <b>WELCOME TO FREE LIKE BOT</b>\n\n"
        "• <code>/like &lt;region&gt; &lt;uid&gt;</code> — sᴇɴᴅ ʟɪᴋᴇ\n"
        "• <code>/start</code> — sᴛᴀʀᴛ ʙᴏᴛ\n"
        "• <code>/help</code> — ᴏᴘᴇɴ ʜᴇʟᴘ\n\n"
        "⏰ <b>Daily limit resets at 04:00 IST.</b>",
        parse_mode="HTML",
    )


async def relike_callback(query, context):
    # Re-like follows the same user limit. It is NOT a loophole around /like.
    _, region, uid = query.data.split("|", 2)
    fake_update = query
    chat = query.message.chat
    user = query.from_user

    admin = False
    try:
        member = await chat.get_member(user.id)
        admin = member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except Exception:
        pass

    lock = get_user_lock(chat.id, user.id)
    async with lock:
        if not admin and has_used_today(chat.id, user.id):
            await query.message.reply_text(
                "⛔ <b>Daily like limit already used.</b>\n"
                "Try again after <b>04:00 IST</b>.",
                parse_mode="HTML",
            )
            return

        msg = await query.message.reply_text(
            "⏳ <b>ʀᴇ-sᴇɴᴅɪɴɢ ʟɪᴋᴇ...</b>",
            parse_mode="HTML",
        )
        anim_task = asyncio.create_task(animate_loading(msg, region, uid))
        try:
            _, resp = await call_api(region, uid)
        except Exception as e:
            anim_task.cancel()
            await msg.edit_text(f"⚠️ <code>{e}</code>", parse_mode="HTML")
            return
        anim_task.cancel()

        if not api_response_is_valid(resp):
            await msg.edit_text(
                "❌ <b>ꜰᴀɪʟᴇᴅ ᴛᴏ ʀᴇ-ʟɪᴋᴇ</b>",
                parse_mode="HTML",
            )
            return

        given = resp.get("Given", resp.get("LikesGivenByAPI", 0))
        try:
            given_num = int(given or 0)
        except (TypeError, ValueError):
            given_num = 0

        if not admin and given_num > 0:
            consume_slot(chat.id, user.id)
            used = 1
        else:
            used = get_usage(chat.id, user.id).get("used", 0)

        await msg.edit_text(
            format_like_result(resp, region, uid, used),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def credits_callback(query):
    await query.message.reply_text(
        "<b>Information</b>\n\n"
        "ᴛᴏ ɢᴇᴛ ᴅᴀɪʟʏ ꜰʀᴇᴇ ʟɪᴋᴇꜱ ᴏɴ ᴀɴʏ ᴏꜰ ʏᴏᴜʀ ᴜɪᴅꜱ, ᴠᴇʀɪꜰʏ ᴛʜᴇ ʟɪɴᴋ ᴡɪᴛʜ ᴛʜɪꜱ ʙᴏᴛ @ɢᴇᴛꜱᴇᴛ𝟤𝟢_ʙᴏᴛ ᴅᴀɪʟʏ ᴀɴᴅ ɢᴇᴛ ꜰʀᴇᴇ ʟɪᴋᴇꜱ.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help":
        await help_callback(query)
    elif query.data == "credits":
        await credits_callback(query)
    elif query.data == "admin_panel":
        await show_admin_panel(query, context)
    elif query.data == "admin_users":
        await admin_users(query)
    elif query.data == "admin_status":
        await admin_status(query)
    elif query.data == "admin_like":
        context.user_data["admin_action"] = "like"
        await query.message.reply_text(
            "🆔 <b>Enter UID:</b>",
            parse_mode="HTML",
        )
    elif query.data == "admin_kickall":
        await kick_all(query, context)
    elif query.data == "admin_auto":
        await show_auto_menu(query, context)
    elif query.data == "auto_on":
        await set_auto_mode(query, context, True, False)
    elif query.data == "auto_off":
        await set_auto_mode(query, context, False, False)
    elif query.data == "auto_start":
        await set_auto_mode(query, context, True, True)
    elif query.data == "auto_end":
        await set_auto_mode(query, context, False, True)
    elif query.data.startswith("relike|"):
        await relike_callback(query, context)


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="admin_users"),
         InlineKeyboardButton("📊 Status", callback_data="admin_status")],
        [InlineKeyboardButton("❤️ Like", callback_data="admin_like"),
         InlineKeyboardButton("🦶 Kick All", callback_data="admin_kickall")],
        [InlineKeyboardButton("⚙️ Auto Kick", callback_data="admin_auto")],
    ])


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    await update.effective_message.reply_text(
        "❤️ <b>WELCOME TO ADMIN PANEL</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


async def admin_users(query):
    if not await is_group_admin(query, query.from_user.id):
        await query.message.reply_text("❌ <b>Admins only.</b>", parse_mode="HTML")
        return

    chat_id = query.message.chat.id
    users = DB["users"].get(str(chat_id), {})
    if not users:
        await query.message.reply_text(
            "👥 <b>No tracked users yet.</b>",
            parse_mode="HTML",
        )
        return

    # Telegram does not expose a general "list every group member" API.
    # This list is therefore the users the bot has observed/tracked.
    lines = ["👥 <b>TRACKED USERS</b>\n"]
    for i, (uid, info) in enumerate(users.items(), 1):
        name = info.get("name", "Unknown")
        username = info.get("username")
        tag = f" @{username}" if username else ""
        lines.append(f"{i}. <code>{uid}</code> — {name}{tag}")

    text = "\n".join(lines)
    # Keep each Telegram message under the practical message size limit.
    for start in range(0, len(text), 3800):
        await query.message.reply_text(
            text[start:start + 3800],
            parse_mode="HTML",
        )


async def admin_status(query):
    if not await is_group_admin(query, query.from_user.id):
        await query.message.reply_text("❌ <b>Admins only.</b>", parse_mode="HTML")
        return

    chat_id = query.message.chat.id
    day = usage_day()
    users = DB["users"].get(str(chat_id), {})
    usage = DB["usage"].get(str(chat_id), {})

    lines = [f"📊 <b>LIKE STATUS — {day}</b>\n"]
    count = 0
    for uid, info in users.items():
        record = usage.get(uid, {})
        used = 1 if record.get("day") == day and record.get("used", 0) else 0
        if used:
            count += 1
            name = info.get("name", "Unknown")
            lines.append(f"• <code>{uid}</code> — {name} — <b>{used}/1</b>")

    if count == 0:
        lines.append("No successful likes claimed today.")

    lines.append(f"\n<b>Total users who claimed:</b> {count}")
    await query.message.reply_text("\n".join(lines), parse_mode="HTML")


async def get_member_status(chat, user_id):
    try:
        return await chat.get_member(user_id)
    except Exception:
        return None


async def kick_one(chat, user_id, bot_id):
    if user_id == bot_id:
        return False

    member = await get_member_status(chat, user_id)
    if not member:
        return False

    if member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    ):
        return False

    if member.status not in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    ):
        return False

    try:
        # Ban first, then immediately unban = kick without permanent ban.
        await chat.ban_member(user_id)
        await asyncio.sleep(0.15)
        await chat.unban_member(user_id, only_if_banned=True)
        return True
    except Exception:
        logger.exception("Could not kick %s from %s", user_id, chat.id)
        return False


async def kick_all(query, context):
    if not await is_group_admin(query, query.from_user.id):
        await query.message.reply_text("❌ <b>Admins only.</b>", parse_mode="HTML")
        return

    chat = query.message.chat
    bot_me = await context.bot.get_me()
    users = list(DB["users"].get(str(chat.id), {}).keys())

    kicked = 0
    for uid in users:
        try:
            if await kick_one(chat, int(uid), bot_me.id):
                kicked += 1
        except (ValueError, TypeError):
            pass

    await query.message.reply_text(
        f"🦶 <b>Kick all completed.</b>\n\n"
        f"Removed: <code>{kicked}</code>\n"
        "Admins, owner and bot were skipped.",
        parse_mode="HTML",
    )


async def show_auto_menu(query, context):
    if not await is_group_admin(query, query.from_user.id):
        await query.message.reply_text("❌ <b>Admins only.</b>", parse_mode="HTML")
        return

    settings = DB["auto_kick"].get(str(query.message.chat.id), {})
    daily_on = settings.get("daily_on", False)
    timer_on = settings.get("timer_on", False)

    await query.message.reply_text(
        "⚙️ <b>AUTO KICK</b>\n\n"
        f"Daily 04:00: <b>{'ON' if daily_on else 'OFF'}</b>\n"
        f"24h timer: <b>{'ON' if timer_on else 'OFF'}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 ON", callback_data="auto_on"),
             InlineKeyboardButton("🔴 OFF", callback_data="auto_off")],
            [InlineKeyboardButton("▶️ START", callback_data="auto_start"),
             InlineKeyboardButton("⏹ END", callback_data="auto_end")],
        ]),
    )


async def set_auto_mode(query, context, enable, start_timer):
    if not await is_group_admin(query, query.from_user.id):
        await query.message.reply_text("❌ <b>Admins only.</b>", parse_mode="HTML")
        return

    chat_id = str(query.message.chat.id)
    settings = DB["auto_kick"].setdefault(chat_id, {})

    if start_timer:
        if enable:
            settings["timer_on"] = True
            settings["timer_started_at"] = now_ist().isoformat()
            settings["last_timer_kick"] = now_ist().isoformat()
            save_db()
            kicked = await perform_kick_for_chat(context.application, query.message.chat.id)
            await query.message.reply_text(
                f"▶️ <b>Auto-kick started.</b> Immediate kick removed <code>{kicked}</code> users.\n"
                "The 24-hour timer is now running.",
                parse_mode="HTML",
            )
        else:
            settings["timer_on"] = False
            settings.pop("timer_started_at", None)
            settings.pop("last_timer_kick", None)
            save_db()
            await query.message.reply_text(
                "⏹ <b>24-hour auto-kick timer ended.</b>",
                parse_mode="HTML",
            )
        return

    settings["daily_on"] = enable
    save_db()

    await query.message.reply_text(
        f"{'🟢 <b>Daily 04:00 auto-kick ON.</b>' if enable else '🔴 <b>Daily 04:00 auto-kick OFF.</b>'}",
        parse_mode="HTML",
    )


async def perform_kick_for_chat(app, chat_id):
    users = list(DB["users"].get(str(chat_id), {}).keys())
    bot_me = await app.bot.get_me()

    try:
        chat = await app.bot.get_chat(chat_id)
    except Exception:
        return 0

    kicked = 0
    for uid in users:
        try:
            if await kick_one(chat, int(uid), bot_me.id):
                kicked += 1
        except Exception:
            pass
    return kicked


async def auto_kick_loop(app):
    global AUTO_KICK_TASK
    last_daily_day = {}

    while True:
        try:
            now = now_ist()
            for chat_key, settings in list(DB["auto_kick"].items()):
                try:
                    chat_id = int(chat_key)
                except ValueError:
                    continue

                # Daily 04:00 mode. Run once per 04:00 window.
                if settings.get("daily_on") and now.time() >= dtime(4, 0):
                    day = now.date().isoformat()
                    if last_daily_day.get(chat_id) != day:
                        await perform_kick_for_chat(app, chat_id)
                        last_daily_day[chat_id] = day
                        save_db()

                # START mode: immediate kick happened when START was clicked,
                # then repeat every 24 hours.
                if settings.get("timer_on"):
                    started_raw = settings.get("timer_started_at")
                    if started_raw:
                        started = datetime.fromisoformat(started_raw)
                        last_raw = settings.get("last_timer_kick")
                        last_kick = (
                            datetime.fromisoformat(last_raw)
                            if last_raw else started
                        )
                        if now - last_kick >= timedelta(hours=24):
                            await perform_kick_for_chat(app, chat_id)
                            settings["last_timer_kick"] = now.isoformat()
                            save_db()

        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Auto-kick loop error")

        await asyncio.sleep(30)


async def text_admin_uid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        return

    if context.user_data.get("admin_action") != "like":
        return

    if not await is_group_admin(update):
        context.user_data.pop("admin_action", None)
        return

    uid = (update.effective_message.text or "").strip()
    if not uid.isdigit():
        await update.effective_message.reply_text(
            "❌ <b>UID must be numeric.</b>\nSend the UID again.",
            parse_mode="HTML",
        )
        return

    context.user_data.pop("admin_action", None)

    msg = await update.effective_message.reply_text(
        "⏳ <b>Admin like processing...</b>",
        parse_mode="HTML",
    )
    # Admin panel only asks for UID. Use a region if the admin sends
    # /adminlike REGION UID through the command below; otherwise default IN.
    region = "IN"

    anim_task = asyncio.create_task(animate_loading(msg, region, uid))
    try:
        _, data = await call_api(region, uid)
    except Exception as e:
        anim_task.cancel()
        await msg.edit_text(f"⚠️ <code>{e}</code>", parse_mode="HTML")
        return
    anim_task.cancel()

    if not api_response_is_valid(data):
        await msg.edit_text(
            "❌ <b>Failed to get a valid API response.</b>",
            parse_mode="HTML",
        )
        return

    await msg.edit_text(
        format_like_result(data, region, uid, 0),
        parse_mode="HTML",
    )


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text(
            "Usage: <code>/ban 23456543</code>",
            parse_mode="HTML",
        )
        return

    user_id = int(context.args[0])
    chat = update.effective_chat

    member = await get_member_status(chat, user_id)
    if member and member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    ):
        await update.effective_message.reply_text(
            "❌ <b>Admins/owner cannot be banned by this command.</b>",
            parse_mode="HTML",
        )
        return

    try:
        await chat.ban_member(user_id)
        await update.effective_message.reply_text(
            f"🔨 <b>User</b> <code>{user_id}</code> <b>permanently banned.</b>\n"
            "They can only return after an admin uses <code>/unban USER_ID</code>.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Ban failed:</b> <code>{e}</code>",
            parse_mode="HTML",
        )


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text(
            "Usage: <code>/unban 23456543</code>",
            parse_mode="HTML",
        )
        return

    user_id = int(context.args[0])
    try:
        await update.effective_chat.unban_member(user_id, only_if_banned=True)
        await update.effective_message.reply_text(
            f"✅ <b>User</b> <code>{user_id}</code> <b>unbanned.</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Unban failed:</b> <code>{e}</code>",
            parse_mode="HTML",
        )


async def post_init(app):
    global AUTO_KICK_TASK
    AUTO_KICK_TASK = asyncio.create_task(auto_kick_loop(app))


async def post_shutdown(app):
    global AUTO_KICK_TASK
    if AUTO_KICK_TASK:
        AUTO_KICK_TASK.cancel()
        try:
            await AUTO_KICK_TASK
        except asyncio.CancelledError:
            pass


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CommandHandler("like", like_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))

    # Admin panel "Like" asks for a plain UID.
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_admin_uid_handler,
        )
    )

    # Track users and join events for the users list / kick features.
    app.add_handler(
        ChatMemberHandler(
            track_membership,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            track_update,
        ),
        group=1,
    )

    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🤖 Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
