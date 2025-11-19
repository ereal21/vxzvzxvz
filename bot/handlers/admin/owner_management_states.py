from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Message

from bot.database.methods import check_role, check_user_by_username, set_role, get_role_id_by_name
from bot.database.models import Permission
from bot.handlers.other import get_bot_user_ids
from bot.keyboards import back
from bot.misc import TgConfig


async def owner_management_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.OWN):
        await call.answer('Nepakanka teisių')
        return
    TgConfig.STATE[user_id] = 'owner_assign_username'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text(
        'Įveskite vartotojo vardą, kuriam norite suteikti savininko rolę:',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('console'),
    )


async def process_owner_username(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'owner_assign_username':
        return
    username = (message.text or '').strip().lstrip('@')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    message_id = TgConfig.STATE.pop(f'{user_id}_message_id', message.message_id)
    TgConfig.STATE[user_id] = None

    if not username:
        await bot.edit_message_text(
            '❌ Vartotojo vardas negali būti tuščias.',
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=back('console'),
        )
        return

    user = check_user_by_username(username)
    if not user:
        await bot.edit_message_text(
            '❌ Vartotojas nerastas.',
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=back('console'),
        )
        return

    owner_role_id = get_role_id_by_name('OWNER')
    if owner_role_id is None:
        await bot.edit_message_text(
            '⚠️ Nepavyko rasti savininko rolės konfigūracijoje.',
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=back('console'),
        )
        return

    set_role(user.telegram_id, owner_role_id)
    await bot.edit_message_text(
        f'✅ @{username} suteikta savininko rolė.',
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=back('console'),
    )


def register_owner_management(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(owner_management_callback, lambda c: c.data == 'owner_management')
    dp.register_message_handler(
        process_owner_username,
        lambda m: TgConfig.STATE.get(m.from_user.id) == 'owner_assign_username',
    )
