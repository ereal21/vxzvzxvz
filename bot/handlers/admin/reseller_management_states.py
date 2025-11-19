from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from bot.database.methods import (
    check_role, check_user_by_username, create_reseller, delete_reseller,
    get_resellers, set_reseller_price, get_all_category_names,
    get_all_subcategories, get_all_item_names, get_category_parent,
    check_user, is_reseller
)
from bot.database.models import Permission
from bot.keyboards import back, resellers_management, resellers_list
from bot.misc import TgConfig
from bot.handlers.other import get_bot_user_ids
from bot.utils import display_name


async def resellers_management_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE):
        await call.answer('Nepakanka teisių')
        return
    TgConfig.STATE[user_id] = None
    await bot.edit_message_text('🤝 Resellerių meniu',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=resellers_management())


async def reseller_add_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'reseller_add_username'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text('Įveskite vartotojo vardą:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back('resellers_management'))


async def reseller_add_receive(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'reseller_add_username':
        return
    username = message.text.lstrip('@')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    user = check_user_by_username(username)
    if not user:
        await bot.edit_message_text('❌ Vartotojas nerastas',
                                    chat_id=message.chat.id,
                                    message_id=message_id,
                                    reply_markup=back('resellers_management'))
        return
    if is_reseller(user.telegram_id):
        await bot.edit_message_text('⚠️ Vartotojas jau yra reselleris',
                                    chat_id=message.chat.id,
                                    message_id=message_id,
                                    reply_markup=back('resellers_management'))
        return
    create_reseller(user.telegram_id)
    TgConfig.STATE[user_id] = None
    await bot.edit_message_text('✅ Reselleris pridėtas',
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=back('resellers_management'))


async def reseller_remove_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    res = get_resellers()
    if not res:
        await bot.edit_message_text('❌ Nėra resellerių',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('resellers_management'))
        return
    await bot.edit_message_text('Pasirinkite resellerį:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=resellers_list(res, 'reseller_remove', 'resellers_management'))


async def reseller_remove_select(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    rid = int(call.data[len('reseller_remove_'):])
    user = check_user(rid)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('✅ Taip', callback_data=f'reseller_remove_confirm_{rid}'))
    markup.add(InlineKeyboardButton('🔙 Ne', callback_data='reseller_remove'))
    name = f'@{user.username}' if user and user.username else str(rid)
    await bot.edit_message_text(
        f'Ar tikrai pašalinti {name} iš resellerių sąrašo?',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def reseller_remove_confirm(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    rid = int(call.data[len('reseller_remove_confirm_'):])
    delete_reseller(rid)
    await bot.edit_message_text(
        '✅ Reselleris pašalintas. Jam nebetaikoma resellerio kaina',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('resellers_management'))


async def reseller_price_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if not get_resellers():
        await bot.edit_message_text('❌ Nėra resellerių',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('resellers_management'))
        return
    mains = get_all_category_names()
    markup = InlineKeyboardMarkup()
    for main in mains:
        markup.add(InlineKeyboardButton(main, callback_data=f'reseller_price_main_{main}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='resellers_management'))
    await bot.edit_message_text('Pasirinkite pagrindinę kategoriją:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def reseller_price_main(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    main = call.data[len('reseller_price_main_'):]
    categories = get_all_subcategories(main)
    if categories:
        markup = InlineKeyboardMarkup()
        for cat in categories:
            markup.add(InlineKeyboardButton(cat, callback_data=f'reseller_price_cat_{cat}'))
        markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='reseller_prices'))
        await bot.edit_message_text('Pasirinkite kategoriją:',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=markup)
        return
    items = get_all_item_names(main)
    if not items:
        await bot.edit_message_text('❌ Šioje kategorijoje nėra prekių',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('reseller_prices'))
        return
    markup = InlineKeyboardMarkup()
    for item in items:
        markup.add(InlineKeyboardButton(display_name(item), callback_data=f'reseller_price_item_{item}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='reseller_prices'))
    await bot.edit_message_text('Pasirinkite prekę:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def reseller_price_cat(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    category = call.data[len('reseller_price_cat_'):]
    subs = get_all_subcategories(category)
    if subs:
        markup = InlineKeyboardMarkup()
        for sub in subs:
            markup.add(InlineKeyboardButton(sub, callback_data=f'reseller_price_sub_{sub}'))
        back_main = get_category_parent(category)
        markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=f'reseller_price_main_{back_main}'))
        await bot.edit_message_text('Pasirinkite subkategoriją:',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=markup)
        return
    items = get_all_item_names(category)
    if not items:
        back_main = get_category_parent(category)
        await bot.edit_message_text('❌ Šioje kategorijoje nėra prekių',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back(f'reseller_price_main_{back_main}'))
        return
    markup = InlineKeyboardMarkup()
    for item in items:
        markup.add(InlineKeyboardButton(display_name(item), callback_data=f'reseller_price_item_{item}'))
    back_main = get_category_parent(category)
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=f'reseller_price_main_{back_main}'))
    await bot.edit_message_text('Pasirinkite prekę:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def reseller_price_sub(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    sub = call.data[len('reseller_price_sub_'):]
    items = get_all_item_names(sub)
    if not items:
        parent = get_category_parent(sub)
        await bot.edit_message_text('❌ Šioje kategorijoje nėra prekių',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back(f'reseller_price_cat_{parent}'))
        return
    markup = InlineKeyboardMarkup()
    for item in items:
        markup.add(InlineKeyboardButton(display_name(item), callback_data=f'reseller_price_item_{item}'))
    parent = get_category_parent(sub)
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=f'reseller_price_cat_{parent}'))
    await bot.edit_message_text('Pasirinkite prekę:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def reseller_price_item(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    item = call.data[len('reseller_price_item_'):]
    TgConfig.STATE[user_id] = 'reseller_price_wait'
    TgConfig.STATE[f'{user_id}_item'] = item
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text('Įveskite kainą:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back('reseller_prices'))


async def reseller_price_receive(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'reseller_price_wait':
        return
    price_text = message.text.strip()
    item = TgConfig.STATE.get(f'{user_id}_item')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if not price_text.isdigit():
        await bot.edit_message_text('⚠️ Neteisinga kaina',
                                    chat_id=message.chat.id,
                                    message_id=message_id,
                                    reply_markup=back('reseller_prices'))
        return
    set_reseller_price(None, item, int(price_text))
    mains = get_all_category_names()
    markup = InlineKeyboardMarkup()
    for main in mains:
        markup.add(InlineKeyboardButton(main, callback_data=f'reseller_price_main_{main}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='resellers_management'))
    TgConfig.STATE[user_id] = None
    await bot.edit_message_text('✅ Kaina nustatyta. Pasirinkite pagrindinę kategoriją:',
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=markup)


def register_reseller_management(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(resellers_management_callback,
                                       lambda c: c.data == 'resellers_management')
    dp.register_callback_query_handler(reseller_add_callback,
                                       lambda c: c.data == 'reseller_add')
    dp.register_callback_query_handler(reseller_remove_callback,
                                       lambda c: c.data == 'reseller_remove')
    dp.register_callback_query_handler(reseller_remove_select,
                                       lambda c: c.data.startswith('reseller_remove_') and not c.data.startswith('reseller_remove_confirm_'))
    dp.register_callback_query_handler(reseller_remove_confirm,
                                       lambda c: c.data.startswith('reseller_remove_confirm_'))
    dp.register_callback_query_handler(reseller_price_callback,
                                       lambda c: c.data == 'reseller_prices')
    dp.register_callback_query_handler(reseller_price_main,
                                       lambda c: c.data.startswith('reseller_price_main_'))
    dp.register_callback_query_handler(reseller_price_cat,
                                       lambda c: c.data.startswith('reseller_price_cat_'))
    dp.register_callback_query_handler(reseller_price_sub,
                                       lambda c: c.data.startswith('reseller_price_sub_'))
    dp.register_callback_query_handler(reseller_price_item,
                                       lambda c: c.data.startswith('reseller_price_item_'))
    dp.register_message_handler(reseller_add_receive,
                                lambda m: TgConfig.STATE.get(m.from_user.id) == 'reseller_add_username')
    dp.register_message_handler(reseller_price_receive,
                                lambda m: TgConfig.STATE.get(m.from_user.id) == 'reseller_price_wait')
