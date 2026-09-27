import logging
import aiohttp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ================= CONFIG =================
BOT_TOKEN = "8617664721:AAGZIaFutCbjfUEwdbIO6ogdsL5Pk6la_Tg"   # <-- apna bot token daalo
API_URL = "https://like-test-bhuwan.vercel.app/like"
API_KEY = "CRAXX"
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Animated loading frames
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

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def progress_bar(used: int, limit: int, length: int = 10) -> str:
    if limit <= 0:
        return "▱" * length
    filled = int((used / limit) * length)
    filled = min(filled, length)
    return "▰" * filled + "▱" * (length - filled)


async def animate_loading(message, region: str, uid: str):
    """Animate loading bar on the message."""
    text_header = (
        f"<b>🚀 ʟɪᴋᴇ ʀᴇǫᴜᴇsᴛ ᴘʀᴏᴄᴇssɪɴɢ</b>\n"
        f"<i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>\n\n"
        f"🌍 <b>ʀᴇɢɪᴏɴ:</b> <code>{region}</code>\n"
        f"🆔 <b>ᴜɪᴅ:</b> <code>{uid}</code>\n\n"
    )
    for frame in LOADING_FRAMES:
        try:
            await message.edit_text(
                text_header + f"<code>{frame}</code>",
                parse_mode="HTML",
            )
            await asyncio.sleep(0.18)
        except Exception:
            pass


async def call_api(region: str, uid: str):
    params = {"uid": uid, "region": region, "key": API_KEY}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(API_URL, params=params) as resp:
            data = await resp.json(content_type=None)
            return resp.status, data


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>✨ ʟɪᴋᴇ ʙᴏᴛ ✨</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 <b>ᴜsᴀɢᴇ:</b>\n"
        "<code>/like &lt;region&gt; &lt;uid&gt;</code>\n\n"
        "📌 <b>ᴇxᴀᴍᴘʟᴇ:</b>\n"
        "<code>/like BD 16983198706</code>\n\n"
        "🌍 <b>sᴜᴘᴘᴏʀᴛᴇᴅ ʀᴇɢɪᴏɴs:</b>\n"
        "<code>BD, IN, PK, SG, ID, MY, TH, VN, BR, US</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>ᴄʀᴇᴅɪᴛs:</b> <a href='https://t.me/Binnay'>Binnay</a>"
    )
    keyboard = [
        [InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
         InlineKeyboardButton("👑 ᴄʀᴇᴅɪᴛs", callback_data="credits")]
    ]
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )


async def like_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ <b>ɪɴᴠᴀʟɪᴅ ᴜsᴀɢᴇ!</b>\n\n"
            "✅ <b>ᴄᴏʀʀᴇᴄᴛ:</b> <code>/like &lt;region&gt; &lt;uid&gt;</code>\n"
            "📌 <b>ᴇxᴀᴍᴘʟᴇ:</b> <code>/like BD 16983198706</code>",
            parse_mode="HTML",
        )
        return

    region = args[0].upper().strip()
    uid = args[1].strip()

    if not uid.isdigit():
        await update.message.reply_text(
            "❌ <b>ᴜɪᴅ ᴍᴜsᴛ ʙᴇ ɴᴜᴍᴇʀɪᴄ!</b>",
            parse_mode="HTML",
        )
        return

    msg = await update.message.reply_text(
        "⏳ <b>ɪɴɪᴛɪᴀʟɪᴢɪɴɢ...</b>",
        parse_mode="HTML",
    )

    # Start animation in background
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

    # Error handling
    if data.get("status") not in (2, 1) and "PlayerNickname" not in data:
        err = data.get("error") or data.get("message") or "ᴜɴᴋɴᴏᴡɴ ᴇʀʀᴏʀ"
        await msg.edit_text(
            f"❌ <b>ꜰᴀɪʟᴇᴅ!</b>\n\n"
            f"📝 <b>ʀᴇᴀsᴏɴ:</b> <code>{err}</code>\n"
            f"🌍 <b>ʀᴇɢɪᴏɴ:</b> <code>{region}</code>\n"
            f"🆔 <b>ᴜɪᴅ:</b> <code>{uid}</code>",
            parse_mode="HTML",
        )
        return

    nickname = data.get("PlayerNickname", "N/A")
    level = data.get("Level", "N/A")
    reg = data.get("Region", region)
    uid_resp = data.get("UID", uid)
    before = data.get("LikesbeforeCommand", 0)
    after = data.get("LikesafterCommand", 0)
    given = data.get("LikesGivenByAPI", 0)
    daily = data.get("daily_limit", 0)
    used = data.get("used", 0)
    remaining = data.get("remaining", 0)

    bar = progress_bar(used, daily)

    text = (
        "╔══════════════════════╗\n"
        "   ✅ <b>ʟɪᴋᴇ sᴜᴄᴄᴇssꜰᴜʟ</b> ✅\n"
        "╚══════════════════════╝\n\n"
        f"👤 <b>ɴɪᴄᴋɴᴀᴍᴇ:</b> <code>{nickname}</code>\n"
        f"🎚️ <b>ʟᴇᴠᴇʟ:</b> <code>{level}</code>\n"
        f"🌍 <b>ʀᴇɢɪᴏɴ:</b> <code>{reg}</code>\n"
        f"🆔 <b>ᴜɪᴅ:</b> <code>{uid_resp}</code>\n\n"
        "┌──── 📊 <b>ʟɪᴋᴇ sᴛᴀᴛs</b> ────┐\n"
        f"  ⬅️ <b>ʙᴇꜰᴏʀᴇ:</b> <code>{before}</code>\n"
        f"  ➡️ <b>ᴀꜰᴛᴇʀ:</b> <code>{after}</code>\n"
        f"  🎯 <b>ɢɪᴠᴇɴ:</b> <code>+{given}</code>\n"
        "└──────────────────────┘\n\n"
        "┌──── 📅 <b>ᴅᴀɪʟʏ ʟɪᴍɪᴛ</b> ───┐\n"
        f"  <code>{bar}</code>\n"
        f"  🔢 <b>ᴜsᴇᴅ:</b> <code>{used}/{daily}</code>\n"
        f"  💎 <b>ʀᴇᴍᴀɪɴɪɴɢ:</b> <code>{remaining}</code>\n"
        "└──────────────────────┘\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>ᴄʀᴇᴅɪᴛs:</b> <a href='https://t.me/Binnay'>Binnay</a>"
    )

    keyboard = [
        [InlineKeyboardButton(
            "🔄 ᴀɢᴀɪɴ ʟɪᴋᴇ",
            callback_data=f"relike|{reg}|{uid_resp}"
        )]
    ]

    await msg.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "help":
        await query.message.reply_text(
            "📖 <b>ʜᴇʟᴘ</b>\n\n"
            "• <code>/like &lt;region&gt; &lt;uid&gt;</code> — sᴇɴᴅ ʟɪᴋᴇ\n"
            "• <code>/start</code> — sᴛᴀʀᴛ ʙᴏᴛ\n\n"
            "🌍 <b>ʀᴇɢɪᴏɴ ᴄᴏᴅᴇs:</b> BD, IN, PK, SG, ID, MY, TH, VN, BR, US",
            parse_mode="HTML",
        )
    elif data == "credits":
        await query.message.reply_text(
            "👑 <b>ᴄʀᴇᴅɪᴛs</b>\n\n"
            "🔧 <b>ᴅᴇᴠᴇʟᴏᴘᴇʀ:</b> <a href='https://t.me/Binnay'>Binnay</a>\n"
            "⚡ <b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ:</b> Binnay API\n"
            "💎 <b>ᴋᴇʏ:</b> <code>CRAXX</code>",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    elif data.startswith("relike|"):
        _, region, uid = data.split("|")
        # simulate the like command
        class FakeMsg:
            pass
        # Reuse the API call directly
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

        if not isinstance(resp, dict) or "PlayerNickname" not in resp:
            await msg.edit_text("❌ <b>ꜰᴀɪʟᴇᴅ ᴛᴏ ʀᴇ-ʟɪᴋᴇ</b>", parse_mode="HTML")
            return

        nickname = resp.get("PlayerNickname", "N/A")
        after = resp.get("LikesafterCommand", 0)
        given = resp.get("LikesGivenByAPI", 0)
        used = resp.get("used", 0)
        daily = resp.get("daily_limit", 0)
        remaining = resp.get("remaining", 0)
        bar = progress_bar(used, daily)

        text = (
            "✅ <b>ʀᴇ-ʟɪᴋᴇ sᴜᴄᴄᴇss</b>\n\n"
            f"👤 <code>{nickname}</code>\n"
            f"➡️ <b>ᴀꜰᴛᴇʀ:</b> <code>{after}</code>\n"
            f"🎯 <b>ɢɪᴠᴇɴ:</b> <code>+{given}</code>\n\n"
            f"<code>{bar}</code>\n"
            f"🔢 <code>{used}/{daily}</code>  |  💎 <code>{remaining}</code>\n\n"
            "👑 <b>ᴄʀᴇᴅɪᴛs:</b> <a href=https://t.me/nrzravi'>Binnay</a>"
        )
        await msg.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("like", like_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("🤖 Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()