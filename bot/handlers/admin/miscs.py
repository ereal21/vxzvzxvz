from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Message
import random

from bot.database.methods import (
    check_role,
    get_users_with_tickets,
    reset_lottery_tickets,
    get_all_users,
    get_user_language,
)
from bot.database.models import Permission
from bot.handlers.other import get_bot_user_ids
from bot.keyboards import (
    miscs_menu,
    lottery_menu,
    lottery_run_menu,
    lottery_broadcast_menu,
    back,
)
from bot.misc import TgConfig
from bot.localization import t


def _pick_winner():
    users = get_users_with_tickets()
    if not users:
        return None
    total = sum(u[2] for u in users)
    r = random.randint(1, total)
    cumulative = 0
    for u in users:
        cumulative += u[2]
        if r <= cumulative:
            return u
    return None


async def miscs_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if role != Permission.USE:
        await bot.edit_message_text(
            t(lang, 'tools'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=miscs_menu(),
        )
        return
    await call.answer(t(lang, 'insufficient_rights'))


async def lottery_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if role != Permission.USE:
        await bot.edit_message_text(
            t(lang, 'lottery'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=lottery_menu(),
        )
        return
    await call.answer(t(lang, 'insufficient_rights'))


async def view_tickets_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    users = get_users_with_tickets()
    lines = [t(lang, 'users_tickets')]
    if not users:
        lines.append(t(lang, 'no_tickets'))
    else:
        for uid, username, count in users:
            name = f'@{username}' if username else str(uid)
            lines.append(f'{name} — {count}')
    await bot.edit_message_text(
        '\n'.join(lines),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('lottery'),
    )


async def run_lottery_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    winner = _pick_winner()
    if not winner:
        await bot.edit_message_text(
            t(lang, 'no_tickets'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=back('lottery'),
        )
        return
    TgConfig.STATE['lottery_winner'] = winner
    username = f'@{winner[1]}' if winner[1] else str(winner[0])
    text = t(lang, 'lottery_winner', username=username, tickets=winner[2])
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=lottery_run_menu(lang),
    )


async def lottery_confirm_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if not TgConfig.STATE.get('lottery_winner'):
        lang = get_user_language(user_id) or 'en'
        await call.answer(t(lang, 'no_winner'))
        return
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    await bot.edit_message_text(
        t(lang, 'lottery_broadcast_prompt'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=lottery_broadcast_menu(role, lang),
    )


async def lottery_rerun_handler(call: CallbackQuery):
    await run_lottery_handler(call)


async def lottery_cancel_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE.pop('lottery_winner', None)
    await bot.edit_message_text(
        '🎟️ Loterija',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=lottery_menu(),
    )


async def lottery_broadcast_yes(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    TgConfig.STATE[user_id] = 'lottery_broadcast_message'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text(
        t(lang, 'lottery_enter_message'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )


async def lottery_broadcast_no(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    reset_lottery_tickets()
    TgConfig.STATE.pop('lottery_winner', None)
    await bot.edit_message_text(
        t(lang, 'lottery_finished'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('lottery'),
    )


async def lottery_broadcast_message(message: Message):
    bot = message.bot
    user_id = message.from_user.id
    if TgConfig.STATE.get(user_id) != 'lottery_broadcast_message':
        return
    text = message.text
    users = get_all_users()
    for uid, in users:
        try:
            await bot.send_message(uid, text)
        except Exception:
            continue
    reset_lottery_tickets()
    TgConfig.STATE.pop('lottery_winner', None)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_message_id', None)
    await bot.send_message(user_id, '✅ Loterija baigta.', reply_markup=back('lottery'))


def register_miscs(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(miscs_callback_handler, lambda c: c.data == 'miscs', state='*')
    dp.register_callback_query_handler(lottery_callback_handler, lambda c: c.data == 'lottery', state='*')
    dp.register_callback_query_handler(view_tickets_handler, lambda c: c.data == 'view_tickets', state='*')
    dp.register_callback_query_handler(run_lottery_handler, lambda c: c.data == 'run_lottery', state='*')
    dp.register_callback_query_handler(lottery_confirm_handler, lambda c: c.data == 'lottery_confirm', state='*')
    dp.register_callback_query_handler(lottery_rerun_handler, lambda c: c.data == 'lottery_rerun', state='*')
    dp.register_callback_query_handler(lottery_cancel_handler, lambda c: c.data == 'lottery_cancel', state='*')
    dp.register_callback_query_handler(lottery_broadcast_yes, lambda c: c.data == 'lottery_broadcast_yes', state='*')
    dp.register_callback_query_handler(lottery_broadcast_no, lambda c: c.data == 'lottery_broadcast_no', state='*')
    dp.register_message_handler(
        lottery_broadcast_message,
        lambda m: TgConfig.STATE.get(m.from_user.id) == 'lottery_broadcast_message',
    )
