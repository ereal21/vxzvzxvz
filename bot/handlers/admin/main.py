from aiogram import Dispatcher
from aiogram.types import CallbackQuery

from bot.keyboards import console, back, information_menu
from bot.database.methods import check_role, get_user_language
from bot.database.models import Permission
from bot.localization import t
from bot.misc import TgConfig

from bot.handlers.admin.broadcast import register_mailing
from bot.handlers.admin.shop_management_states import register_shop_management
from bot.handlers.admin.user_management_states import register_user_management
from bot.handlers.admin.assistant_management_states import register_assistant_management
from bot.handlers.admin.owner_management_states import register_owner_management
from bot.handlers.admin.view_stock import register_view_stock
from bot.handlers.admin.purchases import register_purchases
from bot.handlers.admin.miscs import register_miscs
from bot.handlers.admin.passwords import register_passwords
from bot.handlers.admin.reseller_management_states import register_reseller_management
from bot.handlers.other import get_bot_user_ids


async def console_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role != Permission.USE:
        await bot.edit_message_text('⛩️ Administratoriaus meniu',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=console(role))
        return
    await call.answer('Nepakanka teisių')


async def admin_help_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    user_lang = get_user_language(user_id) or 'en'
    assistant_role = Permission.USE | Permission.ASSIGN_PHOTOS
    key = 'assistant_help_info' if role == assistant_role else 'admin_help_info'
    text = t(user_lang, key)
    await bot.edit_message_text(text,
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back('console'))


async def information_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role != Permission.USE:
        await bot.edit_message_text('ℹ️ Informacijos meniu',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=information_menu(role))
        return
    await call.answer('Nepakanka teisių')


def register_admin_handlers(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(console_callback_handler,
                                       lambda c: c.data == 'console',
                                       state='*')
    dp.register_callback_query_handler(admin_help_callback_handler,
                                       lambda c: c.data == 'admin_help',
                                       state='*')
    dp.register_callback_query_handler(information_callback_handler,
                                       lambda c: c.data == 'information',
                                       state='*')

    register_mailing(dp)
    register_shop_management(dp)
    register_user_management(dp)
    register_assistant_management(dp)
    register_owner_management(dp)
    register_view_stock(dp)
    register_purchases(dp)
    register_reseller_management(dp)
    register_miscs(dp)
    register_passwords(dp)
