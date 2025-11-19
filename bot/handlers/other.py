import time

from aiogram import Dispatcher, Bot
from aiogram.dispatcher.handler import CancelHandler

from bot.database.methods import get_user_language
from bot.localization import t
from bot.misc import TgConfig


async def get_bot_user_ids(query):
    bot: Bot = query.bot
    user_id = query.from_user.id
    now = time.monotonic()
    record = TgConfig.RATE_LIMIT.setdefault(user_id, {
        'window_start': now,
        'count': 0,
        'last_notice': 0.0,
    })
    if now - record['window_start'] > TgConfig.RATE_LIMIT_WINDOW:
        record['window_start'] = now
        record['count'] = 0
    record['count'] += 1
    if record['count'] > TgConfig.RATE_LIMIT_MAX_CALLS:
        if now - record['last_notice'] > 1.0:
            lang = get_user_language(user_id) or 'en'
            await bot.send_message(user_id, t(lang, 'rate_limited'))
            record['last_notice'] = now
        raise CancelHandler()
    return bot, user_id


async def check_sub_channel(chat_member):
    return str(chat_member.status) != 'left'


async def get_bot_info(query):
    bot: Bot = query.bot
    bot_info = await bot.me
    username = bot_info.username
    return username


def register_other_handlers(dp: Dispatcher) -> None:
    pass
