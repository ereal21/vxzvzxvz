from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from bot.database.methods import check_role, check_user_by_username, set_role
from bot.database.models import Permission
from bot.keyboards import back
from bot.misc import TgConfig
from bot.handlers.other import get_bot_user_ids

ASSISTANT_ROLE_ID = 4

async def assistant_management_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.OWN):
        await call.answer('Nepakanka teisių')
        return
    TgConfig.STATE[user_id] = None
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('➕ Pridėti asistentą', callback_data='assistant_add'))
    markup.add(InlineKeyboardButton('➖ Pašalinti asistentą', callback_data='assistant_remove'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console'))
    await bot.edit_message_text('Pasirinkite veiksmą:', chat_id=call.message.chat.id,
                                message_id=call.message.message_id, reply_markup=markup)

async def assistant_add_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'assistant_add_username'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text('Siųskite asistento vartotojo vardą:', chat_id=call.message.chat.id,
                                message_id=call.message.message_id, reply_markup=back('assistant_management'))

async def assistant_remove_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'assistant_remove_username'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text('Siųskite pašalinamo vartotojo vardą:', chat_id=call.message.chat.id,
                                message_id=call.message.message_id, reply_markup=back('assistant_management'))

async def process_assistant_username(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    state = TgConfig.STATE.get(user_id)
    if state not in {'assistant_add_username', 'assistant_remove_username'}:
        return
    username = message.text.lstrip('@')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = None
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    user = check_user_by_username(username)
    if not user:
        await bot.edit_message_text('❌ Vartotojas nerastas', chat_id=message.chat.id,
                                    message_id=message_id, reply_markup=back('assistant_management'))
        return
    if state == 'assistant_add_username':
        set_role(user.telegram_id, ASSISTANT_ROLE_ID)
        await bot.edit_message_text('✅ Asistentas priskirtas', chat_id=message.chat.id,
                                    message_id=message_id, reply_markup=back('assistant_management'))
    else:
        set_role(user.telegram_id, 1)
        await bot.edit_message_text('✅ Asistentas pašalintas', chat_id=message.chat.id,
                                    message_id=message_id, reply_markup=back('assistant_management'))


def register_assistant_management(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(assistant_management_callback,
                                       lambda c: c.data == 'assistant_management')
    dp.register_callback_query_handler(assistant_add_callback,
                                       lambda c: c.data == 'assistant_add')
    dp.register_callback_query_handler(assistant_remove_callback,
                                       lambda c: c.data == 'assistant_remove')
    dp.register_message_handler(
        process_assistant_username,
        lambda m: TgConfig.STATE.get(m.from_user.id) in (
            'assistant_add_username',
            'assistant_remove_username',
        ),
    )
