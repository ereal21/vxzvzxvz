from __future__ import annotations

import contextlib
import datetime
import secrets
import string
from typing import Any

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Message

from bot.database.methods import (
    check_role,
    get_user_language,
    create_category_passwords,
    get_categories_with_lock_status,
    set_category_requires_password,
    is_category_locked,
    get_category_title,
    get_category_titles,
    list_users_with_category_passwords,
    get_user_category_passwords,
    delete_user_category_password,
    get_user_category_password,
    upsert_user_category_password,
    clear_generated_password_usage,
    get_generated_password,
    check_user,
)
from bot.handlers.other import get_bot_user_ids
from bot.keyboards import (
    passwords_menu,
    passwords_lock_keyboard,
    passwords_users_keyboard,
    passwords_user_detail_keyboard,
    back,
)
from bot.localization import t
from bot.misc import TgConfig
from bot.database.models import Permission


PASSWORD_LENGTH = 10
PASSWORD_CHARSET = string.ascii_uppercase + string.digits


def _generate_unique_passwords(count: int) -> list[str]:
    passwords: set[str] = set()
    while len(passwords) < count:
        candidate = ''.join(secrets.choice(PASSWORD_CHARSET) for _ in range(PASSWORD_LENGTH))
        if candidate in passwords:
            continue
        if get_generated_password(candidate) is not None:
            continue
        passwords.add(candidate)
    return list(passwords)


def _format_timestamp(value: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value or '-'
    return dt.strftime('%Y-%m-%d %H:%M')


def _owner_only(role: int) -> bool:
    return bool(role & Permission.OWN)


async def _show_lock_menu(bot, chat_id: int, message_id: int, lang: str) -> None:
    entries = get_categories_with_lock_status()
    if not entries:
        await bot.edit_message_text(
            t(lang, 'passwords_no_categories'),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=back('passwords_menu'),
        )
        return
    await bot.edit_message_text(
        t(lang, 'passwords_lock_title'),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=passwords_lock_keyboard(entries),
    )


async def _show_users_list(bot, chat_id: int, message_id: int, lang: str) -> None:
    users = list_users_with_category_passwords()
    if not users:
        await bot.edit_message_text(
            t(lang, 'passwords_no_user_entries'),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=back('passwords_menu'),
        )
        return
    await bot.edit_message_text(
        t(lang, 'passwords_view_users_title'),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=passwords_users_keyboard(users),
    )


async def _show_user_detail(bot, chat_id: int, message_id: int, lang: str, target_id: int) -> None:
    entries = get_user_category_passwords(target_id)
    if not entries:
        await _show_users_list(bot, chat_id, message_id, lang)
        return
    titles_map = get_category_titles([entry.category_name for entry in entries])
    user_obj = check_user(target_id)
    display = f"@{user_obj.username}" if user_obj and user_obj.username else str(target_id)
    lines = [t(lang, 'passwords_user_overview', user=display), '']
    for entry in entries:
        title = titles_map.get(entry.category_name, entry.category_name)
        status_key = 'passwords_user_entry_changed' if entry.generated_password_id is None else 'passwords_user_entry_generated'
        status = t(lang, status_key)
        updated = _format_timestamp(entry.updated_at)
        lines.append(
            t(
                lang,
                'passwords_user_entry',
                category=title,
                password=entry.password,
                status=status,
                updated=updated,
            )
        )
    text = '\n'.join(lines)
    keyboard_entries = [
        (entry.category_name, titles_map.get(entry.category_name, entry.category_name))
        for entry in entries
    ]
    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=passwords_user_detail_keyboard(target_id, keyboard_entries),
    )


async def passwords_menu_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    TgConfig.STATE[user_id] = None
    await bot.edit_message_text(
        t(lang, 'passwords_menu_title'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=passwords_menu(),
    )


async def passwords_generate_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    TgConfig.STATE[user_id] = {
        'mode': 'passwords_generate_count',
        'message_id': call.message.message_id,
        'chat_id': call.message.chat.id,
    }
    await bot.edit_message_text(
        t(lang, 'passwords_generate_prompt'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('passwords_menu'),
    )


async def passwords_generate_message_handler(message: Message):
    user_id = message.from_user.id
    state = TgConfig.STATE.get(user_id)
    if not isinstance(state, dict) or state.get('mode') != 'passwords_generate_count':
        return
    lang = get_user_language(user_id) or 'en'
    text = (message.text or '').strip()
    try:
        amount = int(text)
    except (TypeError, ValueError):
        await message.reply(t(lang, 'passwords_generate_invalid'))
        return
    if amount <= 0 or amount > 100:
        await message.reply(t(lang, 'passwords_generate_limit'))
        return
    passwords = _generate_unique_passwords(amount)
    create_category_passwords(passwords)
    formatted = '\n'.join(f'<code>{pwd}</code>' for pwd in passwords)
    await message.answer(
        t(lang, 'passwords_generated', count=len(passwords)) + '\n' + formatted
    )
    chat_id = state.get('chat_id', message.chat.id)
    message_id = state.get('message_id')
    TgConfig.STATE[user_id] = None
    if message_id is not None:
        with contextlib.suppress(Exception):
            await message.bot.edit_message_text(
                t(lang, 'passwords_menu_title'),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=passwords_menu(),
            )


async def passwords_lock_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    TgConfig.STATE[user_id] = None
    await _show_lock_menu(bot, call.message.chat.id, call.message.message_id, lang)


async def passwords_toggle_category_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    _, category_name = call.data.split(':', 1)
    currently_locked = is_category_locked(category_name)
    set_category_requires_password(category_name, not currently_locked)
    title = get_category_title(category_name)
    key = 'passwords_lock_applied' if not currently_locked else 'passwords_lock_removed'
    await call.answer(t(lang, key, category=title), show_alert=False)
    await _show_lock_menu(bot, call.message.chat.id, call.message.message_id, lang)


async def passwords_view_users_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    TgConfig.STATE[user_id] = None
    await _show_users_list(bot, call.message.chat.id, call.message.message_id, lang)


async def passwords_view_user_detail_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    try:
        target_id = int(call.data.split(':', 1)[1])
    except (ValueError, IndexError):
        await call.answer('Invalid user')
        return
    await _show_user_detail(bot, call.message.chat.id, call.message.message_id, lang, target_id)


async def passwords_delete_user_password_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    try:
        _, target, category = call.data.split(':', 2)
        target_id = int(target)
    except (ValueError, IndexError):
        await call.answer('Invalid data')
        return
    delete_user_category_password(target_id, category)
    await call.answer(t(lang, 'passwords_user_deleted'), show_alert=False)
    await _show_user_detail(bot, call.message.chat.id, call.message.message_id, lang, target_id)


async def passwords_change_user_password_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    lang = get_user_language(user_id) or 'en'
    if not _owner_only(role):
        await call.answer(t(lang, 'insufficient_rights'), show_alert=True)
        return
    try:
        _, target, category = call.data.split(':', 2)
        target_id = int(target)
    except (ValueError, IndexError):
        await call.answer('Invalid data')
        return
    user_obj = check_user(target_id)
    title = get_category_title(category)
    display = f"@{user_obj.username}" if user_obj and user_obj.username else str(target_id)
    TgConfig.STATE[user_id] = {
        'mode': 'passwords_admin_change',
        'target_user': target_id,
        'category': category,
        'origin': {
            'chat_id': call.message.chat.id,
            'message_id': call.message.message_id,
        },
    }
    await bot.send_message(
        user_id,
        t(lang, 'passwords_admin_change_prompt', user=display, category=title),
    )


async def passwords_admin_change_message_handler(message: Message):
    user_id = message.from_user.id
    state = TgConfig.STATE.get(user_id)
    if not isinstance(state, dict) or state.get('mode') != 'passwords_admin_change':
        return
    lang = get_user_language(user_id) or 'en'
    new_password = (message.text or '').strip()
    if not new_password:
        await message.reply(t(lang, 'passwords_change_empty'))
        return
    if len(new_password) > 64:
        await message.reply(t(lang, 'passwords_change_too_long'))
        return
    target_id = state['target_user']
    category = state['category']
    existing = get_user_category_password(target_id, category)
    if existing and existing.generated_password_id:
        clear_generated_password_usage(existing.generated_password_id)
    upsert_user_category_password(
        target_id,
        category,
        new_password,
        None,
        acknowledged=False,
    )
    user_obj = check_user(target_id)
    title = get_category_title(category)
    display = f"@{user_obj.username}" if user_obj and user_obj.username else str(target_id)
    await message.answer(
        t(lang, 'passwords_admin_change_done', user=display, category=title)
        + '\n'
        + f'<code>{new_password}</code>'
    )
    origin: dict[str, Any] | None = state.get('origin')
    TgConfig.STATE[user_id] = None
    if origin:
        with contextlib.suppress(Exception):
            await _show_user_detail(
                message.bot,
                origin.get('chat_id', message.chat.id),
                origin.get('message_id', 0),
                lang,
                target_id,
            )


def register_passwords(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(passwords_menu_handler, lambda c: c.data == 'passwords_menu', state='*')
    dp.register_callback_query_handler(passwords_generate_handler, lambda c: c.data == 'passwords_generate', state='*')
    dp.register_callback_query_handler(passwords_lock_handler, lambda c: c.data == 'passwords_lock', state='*')
    dp.register_callback_query_handler(passwords_toggle_category_handler, lambda c: c.data.startswith('pwd_lock:'), state='*')
    dp.register_callback_query_handler(passwords_view_users_handler, lambda c: c.data == 'passwords_view_users', state='*')
    dp.register_callback_query_handler(passwords_view_user_detail_handler, lambda c: c.data.startswith('pwd_user:'), state='*')
    dp.register_callback_query_handler(passwords_delete_user_password_handler, lambda c: c.data.startswith('pwdUdel:'), state='*')
    dp.register_callback_query_handler(passwords_change_user_password_handler, lambda c: c.data.startswith('pwdUchg:'), state='*')
    dp.register_message_handler(
        passwords_generate_message_handler,
        lambda m: isinstance(TgConfig.STATE.get(m.from_user.id), dict)
        and TgConfig.STATE[m.from_user.id].get('mode') == 'passwords_generate_count',
        state='*',
    )
    dp.register_message_handler(
        passwords_admin_change_message_handler,
        lambda m: isinstance(TgConfig.STATE.get(m.from_user.id), dict)
        and TgConfig.STATE[m.from_user.id].get('mode') == 'passwords_admin_change',
        state='*',
    )
