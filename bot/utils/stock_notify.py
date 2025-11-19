from bot.database.methods.read import get_item_subscribers, get_user_language
from bot.database.methods.update import clear_stock_notifications
from bot.localization import t
from .names import display_name


async def notify_restock(bot, item_name: str) -> None:
    subs = get_item_subscribers(item_name)
    if not subs:
        return
    clear_stock_notifications(item_name)
    for uid in subs:
        lang = get_user_language(uid) or 'en'
        await bot.send_message(uid, t(lang, 'stock_back_in', item=display_name(item_name)))
