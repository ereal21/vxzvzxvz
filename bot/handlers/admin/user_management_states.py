import datetime

from aiogram import Dispatcher
from aiogram.types import Message, CallbackQuery
from aiogram.utils.exceptions import BotBlocked

from bot.keyboards import back, user_manage_check, user_management, user_items_list, close
from bot.database.methods import check_role, check_user, check_user_by_username, select_user_operations, select_user_items, \
    check_role_name_by_id, check_user_referrals, select_bought_items, set_role, create_operation, update_balance, \
    bought_items_list
from bot.misc import TgConfig
from bot.database.models import Permission
from bot.handlers.other import get_bot_user_ids
from bot.logger_mesh import logger

async def user_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    TgConfig.STATE[user_id] = 'user_username_for_check'
    role = check_role(user_id)
    if role & Permission.USERS_MANAGE:
        await bot.edit_message_text('👤 Enter the user username to view or edit their data',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('console'))
        return
    await call.answer('Insufficient permissions')


async def check_user_data(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    msg = message.text.lstrip('@')
    TgConfig.STATE[user_id] = None
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    user = check_user_by_username(msg)
    if not user:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='❌ User not found',
                                    reply_markup=back('console'))
        return
    user_info = await bot.get_chat(user.telegram_id)
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text=f"Are you sure you want to view the profile of user @{user_info.username}?",
                                parse_mode='HTML',
                                reply_markup=user_manage_check(user.telegram_id))



async def user_profile_view(call: CallbackQuery):
    user_id = call.data[11:]
    bot, admin_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE[f'{admin_id}_user_data'] = user_id
    user = check_user(user_id)
    admin_permissions = check_role(admin_id)
    user_permissions = check_role(user_id)
    user_info = await bot.get_chat(user_id)
    operations = select_user_operations(user_id)
    overall_balance = 0
    if operations:
        for i in operations:
            overall_balance += i
    items = select_user_items(user_id)
    role = check_role_name_by_id(user.role_id)
    referrals = check_user_referrals(user.telegram_id)
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            f"👤 <b>Profile</b> — {user_info.first_name}\n\n"
            f"👤 <b>Username</b> — @{user_info.username}\n"
            f"🆔 <b>ID</b> — <code>{user_id}</code>\n"
            f"💳 <b>Balance</b> — <code>{user.balance}</code> €\n"
            f"💵 <b>Total topped up</b> — <code>{overall_balance}</code> €\n"
            f"📦 <b>Items purchased</b> — {items} pcs\n\n"
            f"👤 <b>Referral</b> — <code>{user.referral_id}</code>\n"
            f"👥 <b>User's referrals</b> — {referrals}\n"
            f"🎛 <b>Role</b> — {role}\n"
            f"🕢 <b>Registration date</b> — <code>{user.registration_date}</code>\n"
        ),
        parse_mode='HTML',
        reply_markup=user_management(
            admin_permissions, user_permissions, Permission.ADMINS_MANAGE, items, user_id
        )
    )

async def user_items_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    user_data = call.data[11:]
    role = check_role(user_id)
    if role & Permission.ADMINS_MANAGE:
        TgConfig.STATE[f'{user_id}_back'] = f'user-items_{user_data}'
        bought_goods = select_bought_items(user_data)
        goods = bought_items_list(user_id)
        max_index = len(goods) // 10
        if len(goods) % 10 == 0:
            max_index -= 1
        keyboard = user_items_list(bought_goods, user_data, f'check-user_{user_data}',
                                   f'user-items_{user_data}', 0, max_index)
        await bot.edit_message_text(
            'User’s items:',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard
        )
        return
    await call.answer('Not enough permissions')

async def process_admin_for_purpose(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    user_data = call.data[10:]
    user_info = await bot.get_chat(user_data)
    role = check_role(user_id)
    if role & Permission.ADMINS_MANAGE:
        set_role(user_data, 2)
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f'✅ User {user_info.first_name} has been assigned the ADMINISTRATOR role.',
            reply_markup=back(f'check-user_{user_data}')
        )
        try:
            await bot.send_message(
                chat_id=user_data,
                text='✅ You have been assigned the ADMINISTRATOR role in the bot.',
                reply_markup=close()
            )
        except BotBlocked:
            pass
        admin_info = await bot.get_chat(user_id)
        logger.info(
            f"User {user_id} ({admin_info.first_name}) "
            f"assigned user {user_data} ({user_info.first_name}) as administrator"
        )
        return
    await call.answer('Not enough permissions')

async def process_admin_for_remove(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    user_data = call.data[13:]
    user_info = await bot.get_chat(user_data)
    role = check_role(user_id)
    if role & Permission.ADMINS_MANAGE:
        set_role(user_data, 1)
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f'✅ ADMINISTRATOR role has been revoked from user {user_info.first_name}.',
            reply_markup=back(f'check-user_{user_data}')
        )
        try:
            await bot.send_message(
                chat_id=user_data,
                text='❌ Your ADMINISTRATOR role has been revoked in the bot.',
                reply_markup=close()
            )
        except BotBlocked:
            pass
        admin_info = await bot.get_chat(user_id)
        logger.info(
            f"User {user_id} ({admin_info.first_name}) "
            f"revoked administrator role from user {user_data} ({user_info.first_name})"
        )
        return
    await call.answer('Not enough permissions')

async def replenish_user_balance_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    user_data = call.data[18:]
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    TgConfig.STATE[user_id] = 'process_replenish_user_balance'
    role = check_role(user_id)
    if role & Permission.USERS_MANAGE:
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text='💰 Enter the amount to replenish:',
            reply_markup=back(f'check-user_{user_data}')
        )
        return
    await call.answer('Not enough permissions')

async def process_replenish_user_balance(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    msg = message.text
    TgConfig.STATE[user_id] = None
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    user_data = TgConfig.STATE.get(f'{user_id}_user_data')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if not message.text.isdigit() or int(message.text) < 10 or int(message.text) > 10000:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text="❌ Invalid top-up amount. "
                 "The amount must be a number not less than 10€ and not more than 10,000€.",
            reply_markup=back(f'check-user_{user_data}')
        )
        return
    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
    create_operation(user_data, msg, formatted_time)
    update_balance(user_data, msg)
    user_info = await bot.get_chat(user_data)
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=message_id,
        text=f'✅ The balance of user {user_info.first_name} has been replenished by {msg}€.',
        reply_markup=back(f'check-user_{user_data}')
    )
    admin_info = await bot.get_chat(user_id)
    logger.info(
        f"User {user_id} ({admin_info.first_name}) "
        f"replenished the balance of user {user_data} ({user_info.first_name}) by {msg}€"
    )
    try:
        await bot.send_message(
            chat_id=user_data,
            text=f'✅ Your balance has been replenished by {msg}€.',
            reply_markup=close()
        )
    except BotBlocked:
        pass


def register_user_management(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(user_callback_handler,
                                       lambda c: c.data == 'user_management')

    dp.register_message_handler(process_replenish_user_balance,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'process_replenish_user_balance')
    dp.register_message_handler(check_user_data,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'user_username_for_check')

    dp.register_callback_query_handler(process_admin_for_remove,
                                       lambda c: c.data.startswith('remove-admin_'))
    dp.register_callback_query_handler(process_admin_for_purpose,
                                       lambda c: c.data.startswith('set-admin_'))
    dp.register_callback_query_handler(replenish_user_balance_callback_handler,
                                       lambda c: c.data.startswith('fill-user-balance_'))
    dp.register_callback_query_handler(user_profile_view,
                                       lambda c: c.data.startswith('check-user_'))
    dp.register_callback_query_handler(user_items_callback_handler,
                                       lambda c: c.data.startswith('user-items_'))
