import os
from aiogram import Bot
from aiogram.utils.exceptions import (
    ChatNotFound, BotBlocked, CantInitiateConversation,
    WrongFileIdentifier, TelegramAPIError
)
from bot.misc import EnvKeys
from bot.logger_mesh import logger
from bot.keyboards import close


async def notify_owner_of_purchase(
    bot: Bot,
    username: str,
    formatted_time: str,
    item_name: str,
    item_price: float,
    parent_cat: str | None,
    category_name: str,
    photo_description: str,
    file_path: str | None,
):
    """
    Send a purchase notification to the OWNER_ID with details.
    If a media file path is provided and exists, send photo/video + caption,
    otherwise send a text message. All sends are protected with try/except.
    """
    # 1) Resolve & validate OWNER_ID
    try:
        owner_id = int(EnvKeys.OWNER_ID) if EnvKeys.OWNER_ID else None
    except (TypeError, ValueError):
        owner_id = None

    if not owner_id:
        logger.warning("notify_owner_of_purchase: OWNER_ID is missing or invalid.")
        return

    # 2) Build caption (HTML)
    prefix = f"{parent_cat} → " if parent_cat else ""
    text = (
        f"🛒 <b>New purchase</b>\n"
        f"👤 Buyer: {username}\n"
        f"🗓️ Time: {formatted_time}\n"
        f"📦 Item: {prefix}{category_name} / <b>{item_name}</b>\n"
        f"💶 Price: <b>{item_price}€</b>\n"
        f"\n{photo_description or ''}"
    ).strip()

    # 3) Try media first if available, else text; fall back to plain text on errors
    try:
        if file_path and os.path.isfile(file_path):
            with open(file_path, "rb") as media:
                if file_path.lower().endswith(".mp4"):
                    await bot.send_video(owner_id, media, caption=text, parse_mode="HTML", reply_markup=close())
                else:
                    await bot.send_photo(owner_id, media, caption=text, parse_mode="HTML", reply_markup=close())
        else:
            await bot.send_message(owner_id, text, parse_mode="HTML", reply_markup=close())

    except (BotBlocked, CantInitiateConversation):
        logger.error(
            "notify_owner_of_purchase: Cannot DM OWNER_ID=%s (bot blocked or no conversation). "
            "Ask the owner to /start the bot once.", owner_id
        )
    except (ChatNotFound, WrongFileIdentifier) as e:
        logger.exception("notify_owner_of_purchase: Chat/file issue: %s", e)
        try:
            await bot.send_message(owner_id, text, parse_mode="HTML", reply_markup=close())
        except TelegramAPIError as e2:
            logger.exception("notify_owner_of_purchase: Fallback send_message failed: %s", e2)
    except TelegramAPIError as e:
        logger.exception("notify_owner_of_purchase: Telegram API error: %s", e)

