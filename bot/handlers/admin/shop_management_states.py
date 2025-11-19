import datetime
import os
import shutil

import secrets
from collections import Counter
from typing import Sequence, Tuple

from aiogram import Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.utils.exceptions import ChatNotFound

from bot.localization import t
from bot.database.methods import (
    add_values_to_item,
    check_category,
    check_item,
    check_role,
    check_value,
    select_item_values_amount,
    create_category,
    create_item,
    delete_category,
    delete_item,
    delete_only_items,
    get_all_categories,
    get_all_category_names,
    get_all_item_names,
    get_all_items,
    get_all_subcategories,
    get_category_parent,
    get_category_title,
    get_category_titles,
    get_item_info,
    get_user_count,
    get_user_language,
    select_admins,
    select_all_operations,
    select_all_orders,
    select_bought_item,
    select_count_bought_items,
    select_count_categories,
    select_count_goods,
    select_count_items,
    select_today_operations,
    select_today_orders,
    select_today_users,
    select_users_balance,
    update_category,
    update_item,
    set_category_options,
    create_promocode,
    delete_promocode,
    get_promocode,
    get_promocode_items,
    get_all_promocodes,
    update_promocode,
    set_promocode_items,
)
from bot.utils import generate_internal_name, display_name
from bot.utils.stock_notify import notify_restock
from bot.utils.media import write_media_meta


from bot.utils.files import cleanup_item_file, get_next_file_path
from bot.database.models import Permission
from bot.handlers.other import get_bot_user_ids
from bot.keyboards import (
    shop_management,
    goods_management,
    categories_management,
    back,
    item_management,
    question_buttons,
    promo_codes_management,
    promo_expiry_keyboard,
    promo_codes_list,
    promo_manage_actions,
    catalog_editor_menu,
)
from bot.logger_mesh import logger
from bot.misc import TgConfig, EnvKeys


MAX_SELECTION_DEPTH = 32


def _get_lang(user_id: int) -> str:
    return get_user_language(user_id) or 'en'


async def shop_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('⛩️ Parduotuvės valdymo meniu',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=shop_management(role))
        return
    await call.answer('Nepakanka teisių')


async def logs_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    file_path = 'bot.log'
    if role & Permission.SHOP_MANAGE:
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            with open(file_path, 'rb') as document:
                await bot.send_document(chat_id=call.message.chat.id,
                                        document=document)
                return
        else:
            await call.answer(text="❗️ Kolkas nėra logų")
            return
    await call.answer('Nepakanka teisių')


async def goods_management_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('🛒 Prekių valdymo meniu',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=goods_management())
        return
    await call.answer('Nepakanka teisių')


async def promo_management_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('🏷 Promo codes menu',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=promo_codes_management())
        return
    await call.answer('Nepakanka teisių')


async def create_promo_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'promo_create_code'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text('Enter promo code:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back('promo_management'))


async def promo_code_receive_code(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'promo_create_code':
        return
    code = message.text.strip()
    TgConfig.STATE[f'{user_id}_promo_code'] = code
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = 'promo_create_discount'
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    await bot.edit_message_text('Enter discount percent:',
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=back('promo_management'))


async def promo_code_receive_discount(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'promo_create_discount':
        return
    discount = int(message.text.strip())
    TgConfig.STATE[f'{user_id}_promo_discount'] = discount
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = 'promo_create_expiry_type'
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    await bot.edit_message_text('Choose expiry type:',
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=promo_expiry_keyboard('promo_management'))


async def promo_create_expiry_type_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_create_expiry_type':
        return
    unit = call.data[len('promo_expiry_'):]
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    if unit == 'none':
        code = TgConfig.STATE.get(f'{user_id}_promo_code')
        discount = TgConfig.STATE.get(f'{user_id}_promo_discount')
        create_promocode(code, discount, None)
        TgConfig.STATE[user_id] = None
        await bot.edit_message_text('✅ Promo code created',
                                    chat_id=call.message.chat.id,
                                    message_id=message_id,
                                    reply_markup=back('promo_management'))
        admin_info = await bot.get_chat(user_id)
        logger.info(f"User {user_id} ({admin_info.first_name}) created promo code {code}")
        return
    TgConfig.STATE[f'{user_id}_promo_expiry_unit'] = unit
    TgConfig.STATE[user_id] = 'promo_create_expiry_number'
    await bot.edit_message_text(f'Enter number of {unit}:',
                                chat_id=call.message.chat.id,
                                message_id=message_id,
                                reply_markup=back('promo_management'))


async def promo_code_receive_expiry_number(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'promo_create_expiry_number':
        return
    number = int(message.text.strip())
    unit = TgConfig.STATE.get(f'{user_id}_promo_expiry_unit')
    code = TgConfig.STATE.get(f'{user_id}_promo_code')
    discount = TgConfig.STATE.get(f'{user_id}_promo_discount')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if number <= 0:
        expiry = None
    else:
        days = {'days': number, 'weeks': number * 7, 'months': number * 30}[unit]
        expiry_date = datetime.date.today() + datetime.timedelta(days=days)
        expiry = expiry_date.strftime('%Y-%m-%d')
    create_promocode(code, discount, expiry)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_promo_expiry_unit', None)
    await bot.edit_message_text('✅ Promo code created',
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=back('promo_management'))
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) created promo code {code}")


async def delete_promo_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    codes = [p.code for p in get_all_promocodes()]
    if codes:
        await bot.edit_message_text('Select promo code to delete:',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=promo_codes_list(codes, 'delete_promo_code', 'promo_management'))
    else:
        await call.answer('No promo codes available', show_alert=True)


async def promo_code_delete_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    code = call.data[len('delete_promo_code_'):]
    delete_promocode(code)
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) deleted promo code {code}")
    codes = [p.code for p in get_all_promocodes()]
    if codes:
        await bot.edit_message_text('Select promo code to delete:',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=promo_codes_list(codes, 'delete_promo_code', 'promo_management'))
    else:
        await bot.edit_message_text('✅ Promo code deleted',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('promo_management'))


async def manage_promo_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    codes = [p.code for p in get_all_promocodes()]
    if codes:
        await bot.edit_message_text('Select promo code:',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=promo_codes_list(codes, 'manage_promo_code', 'promo_management'))
    else:
        await call.answer('No promo codes available', show_alert=True)


def _promo_summary_text(code: str, info: dict | None = None) -> str:
    data = info if info is not None else get_promocode(code)
    if not data:
        return f'Promo code: {code}'
    expiry = data['expires_at'] or 'No expiry'
    assigned = data.get('items') or []
    if assigned:
        items_text = '\n'.join(f'• {display_name(name)}' for name in assigned)
        applies = f'Applies to:\n{items_text}'
    else:
        applies = 'Applies to: all items'
    return (
        f'Promo code: {code}\n'
        f'Discount: {data["discount"]}%\n'
        f'Expiry: {expiry}\n'
        f'{applies}'
    )


async def promo_manage_select_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    code = call.data[len('manage_promo_code_'):]
    info = get_promocode(code)
    text = _promo_summary_text(code, info)
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=promo_manage_actions(code),
    )


async def promo_manage_discount_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    code = call.data[len('promo_manage_discount_'):]
    TgConfig.STATE[user_id] = 'promo_manage_discount'
    TgConfig.STATE[f'{user_id}_promo_manage_code'] = code
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text('Enter new discount percent:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back(f'manage_promo_code_{code}'))


async def promo_manage_receive_discount(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'promo_manage_discount':
        return
    code = TgConfig.STATE.get(f'{user_id}_promo_manage_code')
    new_discount = int(message.text.strip())
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    update_promocode(code, discount=new_discount)
    TgConfig.STATE[user_id] = None
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) updated promo code {code} discount to {new_discount}")
    await bot.edit_message_text('✅ Discount updated',
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=promo_manage_actions(code))


async def promo_manage_expiry_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    code = call.data[len('promo_manage_expiry_'):]
    TgConfig.STATE[user_id] = 'promo_manage_expiry_type'
    TgConfig.STATE[f'{user_id}_promo_manage_code'] = code
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text('Choose expiry type:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=promo_expiry_keyboard(f'manage_promo_code_{code}'))


async def promo_manage_expiry_type_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_manage_expiry_type':
        return
    unit = call.data[len('promo_expiry_'):]
    code = TgConfig.STATE.get(f'{user_id}_promo_manage_code')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    if unit == 'none':
        update_promocode(code, expires_at=None)
        TgConfig.STATE[user_id] = None
        admin_info = await bot.get_chat(user_id)
        logger.info(f"User {user_id} ({admin_info.first_name}) updated promo code {code} expiry")
        await bot.edit_message_text('✅ Expiry updated',
                                    chat_id=call.message.chat.id,
                                    message_id=message_id,
                                    reply_markup=promo_manage_actions(code))
        return
    TgConfig.STATE[f'{user_id}_promo_expiry_unit'] = unit
    TgConfig.STATE[user_id] = 'promo_manage_expiry_number'
    await bot.edit_message_text(f'Enter number of {unit}:',
                                chat_id=call.message.chat.id,
                                message_id=message_id,
                                reply_markup=back(f'manage_promo_code_{code}'))


async def promo_manage_items_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    code = call.data[len('promo_manage_items_'):]
    TgConfig.STATE[user_id] = 'promo_manage_items'
    TgConfig.STATE[f'{user_id}_promo_manage_code'] = code
    TgConfig.STATE[f'{user_id}_promo_items_selected'] = set(get_promocode_items(code))
    TgConfig.STATE[f'{user_id}_promo_items_nav'] = []
    TgConfig.STATE[f'{user_id}_promo_items_current'] = None
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await call.answer()
    await show_promo_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def show_promo_item_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    if TgConfig.STATE.get(user_id) != 'promo_manage_items':
        return
    code = TgConfig.STATE.get(f'{user_id}_promo_manage_code', '')
    selected: set[str] = set(TgConfig.STATE.get(f'{user_id}_promo_items_selected', set()))
    current = TgConfig.STATE.get(f'{user_id}_promo_items_current')
    nav_stack: list[str] = list(TgConfig.STATE.get(f'{user_id}_promo_items_nav', []))
    categories = _get_hierarchy_children(current)
    titles = get_category_titles(categories)
    items = sorted(get_all_item_names(current)) if current is not None else []
    markup = InlineKeyboardMarkup(row_width=1)
    for name in categories:
        label = titles.get(name, _category_label(name))
        markup.add(InlineKeyboardButton(f'📁 {label}', callback_data=f'promoitem_open_{name}'))
    for item in items:
        marker = '✅' if item in selected else '▫️'
        markup.add(InlineKeyboardButton(f'{marker} {display_name(item)}', callback_data=f'promoitem_toggle_{item}'))
    if nav_stack:
        markup.add(InlineKeyboardButton('🔼 Up', callback_data='promoitem_back'))
    markup.row(
        InlineKeyboardButton('✅ Done', callback_data='promoitem_done'),
        InlineKeyboardButton('🧹 Clear', callback_data='promoitem_clear'),
    )
    markup.add(InlineKeyboardButton('🔙 Cancel', callback_data='promoitem_cancel'))
    if current is None:
        text = f'Select a category to choose items for promo {code}:'
    else:
        path = ' / '.join(_category_label(part) for part in nav_stack + [current])
        text = f'Select items in {path} for promo {code}:'
    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def promo_item_open(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_manage_items':
        return
    target = call.data[len('promoitem_open_'):]
    current = TgConfig.STATE.get(f'{user_id}_promo_items_current')
    lang = _get_lang(user_id)
    if target not in _get_hierarchy_children(current):
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    nav_stack: list[str] = list(TgConfig.STATE.get(f'{user_id}_promo_items_nav', []))
    if current is not None:
        if len(nav_stack) >= MAX_SELECTION_DEPTH:
            await call.answer(t(lang, 'multi_select_depth_limit'), show_alert=True)
            return
        nav_stack.append(current)
    TgConfig.STATE[f'{user_id}_promo_items_nav'] = nav_stack
    TgConfig.STATE[f'{user_id}_promo_items_current'] = target
    await call.answer()
    await show_promo_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def promo_item_back(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_manage_items':
        return
    nav_stack: list[str] = list(TgConfig.STATE.get(f'{user_id}_promo_items_nav', []))
    current = nav_stack.pop() if nav_stack else None
    TgConfig.STATE[f'{user_id}_promo_items_nav'] = nav_stack
    TgConfig.STATE[f'{user_id}_promo_items_current'] = current
    await call.answer()
    await show_promo_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def promo_item_toggle(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_manage_items':
        return
    item_name = call.data[len('promoitem_toggle_'):]
    current = TgConfig.STATE.get(f'{user_id}_promo_items_current')
    lang = _get_lang(user_id)
    if current is None:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    valid_items = set(get_all_item_names(current))
    if item_name not in valid_items:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    selected: set[str] = set(TgConfig.STATE.get(f'{user_id}_promo_items_selected', set()))
    if item_name in selected:
        selected.remove(item_name)
    else:
        selected.add(item_name)
    TgConfig.STATE[f'{user_id}_promo_items_selected'] = selected
    await call.answer()
    await show_promo_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def promo_item_clear(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_manage_items':
        return
    TgConfig.STATE[f'{user_id}_promo_items_selected'] = set()
    await call.answer('Selection cleared')
    await show_promo_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def promo_item_done(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_manage_items':
        return
    code = TgConfig.STATE.get(f'{user_id}_promo_manage_code')
    selected: set[str] = set(TgConfig.STATE.get(f'{user_id}_promo_items_selected', set()))
    set_promocode_items(code, sorted(selected))
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_promo_items_selected', None)
    TgConfig.STATE.pop(f'{user_id}_promo_items_nav', None)
    TgConfig.STATE.pop(f'{user_id}_promo_items_current', None)
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    admin_info = await bot.get_chat(user_id)
    logger.info(
        "User %s (%s) updated promo code %s items: %s",
        user_id,
        admin_info.first_name,
        code,
        ', '.join(sorted(selected)) or 'ALL',
    )
    await call.answer('Promo items updated')
    text = _promo_summary_text(code)
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=promo_manage_actions(code),
    )


async def promo_item_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'promo_manage_items':
        return
    code = TgConfig.STATE.get(f'{user_id}_promo_manage_code')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_promo_items_selected', None)
    TgConfig.STATE.pop(f'{user_id}_promo_items_nav', None)
    TgConfig.STATE.pop(f'{user_id}_promo_items_current', None)
    await call.answer()
    text = _promo_summary_text(code)
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=promo_manage_actions(code),
    )


async def promo_manage_receive_expiry_number(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'promo_manage_expiry_number':
        return
    number = int(message.text.strip())
    unit = TgConfig.STATE.get(f'{user_id}_promo_expiry_unit')
    code = TgConfig.STATE.get(f'{user_id}_promo_manage_code')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if number <= 0:
        expiry = None
    else:
        days = {'days': number, 'weeks': number * 7, 'months': number * 30}[unit]
        expiry_date = datetime.date.today() + datetime.timedelta(days=days)
        expiry = expiry_date.strftime('%Y-%m-%d')
    update_promocode(code, expires_at=expiry)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_promo_expiry_unit', None)
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) updated promo code {code} expiry")
    await bot.edit_message_text('✅ Expiry updated',
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=promo_manage_actions(code))


async def promo_manage_delete_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    code = call.data[len('promo_manage_delete_'):]
    delete_promocode(code)
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) deleted promo code {code}")
    codes = [p.code for p in get_all_promocodes()]
    if codes:
        await bot.edit_message_text('Select promo code:',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=promo_codes_list(codes, 'manage_promo_code', 'promo_management'))
    else:
        await bot.edit_message_text('✅ Promo code deleted',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('promo_management'))


def _assign_upload_markup() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton('❌ Cancel', callback_data='assign_photo_cancel'),
        InlineKeyboardButton('✅ Done', callback_data='assign_photo_done'),
    )
    return markup


def _assign_media_text(lang: str, item: str, path: str, uploaded: int) -> str:
    lines = [t(lang, 'assign_media_prompt', item=display_name(item))]
    if path:
        lines.append(t(lang, 'assign_current_path', path=path))
    lines.append(t(lang, 'assign_media_hint'))
    lines.append(t(lang, 'assign_media_progress', count=uploaded))
    return '\n'.join(lines)


async def _show_assign_menu(bot, chat_id: int, message_id: int, user_id: int, category: str | None) -> None:
    lang = _get_lang(user_id)
    if category is None:
        mains = _get_hierarchy_children(None)
        if not mains:
            await bot.edit_message_text(
                t(lang, 'assign_no_categories'),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=back('goods_management'),
            )
            return
        markup = InlineKeyboardMarkup(row_width=1)
        titles = get_category_titles(mains)
        for name in mains:
            label = titles.get(name, _category_label(name))
            markup.add(InlineKeyboardButton(f'📁 {label}', callback_data=f'assign_photo_main_{name}'))
        markup.add(InlineKeyboardButton(t(lang, 'back'), callback_data='goods_management'))
        await bot.edit_message_text(
            t(lang, 'assign_choose_main'),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
        return

    subcategories = get_all_subcategories(category)
    items = sorted(get_all_item_names(category))
    markup = InlineKeyboardMarkup(row_width=1)
    prefix = _assign_child_prefix(category)
    titles = get_category_titles(subcategories)
    for name in subcategories:
        label = titles.get(name, _category_label(name))
        markup.add(InlineKeyboardButton(f'📁 {label}', callback_data=f'{prefix}{name}'))
    for item in items:
        markup.add(
            InlineKeyboardButton(
                display_name(item),
                callback_data=f'assign_photo_item_{item}',
            )
        )
    if not subcategories and not items:
        markup.add(InlineKeyboardButton(t(lang, 'assign_empty_branch_button'), callback_data='assign_photo_empty'))
    parent = get_category_parent(category)
    if parent is None:
        back_data = 'assign_photos'
    elif get_category_parent(parent) is None:
        back_data = f'assign_photo_main_{parent}'
    else:
        back_data = f'assign_photo_sub_{parent}'
    markup.add(InlineKeyboardButton(t(lang, 'back'), callback_data=back_data))
    await bot.edit_message_text(
        t(lang, 'assign_choose_category', path=_format_assign_path(category)),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def assign_photos_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        await call.answer('Nepakanka teisių')
        return
    TgConfig.STATE[user_id] = None
    pending_paths = TgConfig.STATE.pop(f'{user_id}_stock_paths', [])
    for file_path in pending_paths:
        cleanup_item_file(file_path)
    TgConfig.STATE.pop(f'{user_id}_item', None)
    TgConfig.STATE.pop(f'{user_id}_assign_category', None)
    TgConfig.STATE.pop(f'{user_id}_message_id', None)
    await _show_assign_menu(bot, call.message.chat.id, call.message.message_id, user_id, None)


async def assign_photo_main_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        await call.answer('Nepakanka teisių')
        return
    main = call.data[len('assign_photo_main_'):]
    await _show_assign_menu(bot, call.message.chat.id, call.message.message_id, user_id, main)


async def assign_photo_category_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        await call.answer('Nepakanka teisių')
        return
    category = call.data[len('assign_photo_cat_'):]
    await _show_assign_menu(bot, call.message.chat.id, call.message.message_id, user_id, category)


async def assign_photo_subcategory_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        await call.answer('Nepakanka teisių')
        return
    category = call.data[len('assign_photo_sub_'):]
    await _show_assign_menu(bot, call.message.chat.id, call.message.message_id, user_id, category)


async def assign_photo_empty_handler(call: CallbackQuery):
    _, user_id = await get_bot_user_ids(call)
    lang = _get_lang(user_id)
    await call.answer(t(lang, 'assign_empty_branch'), show_alert=True)


async def assign_photo_item_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        await call.answer('Nepakanka teisių')
        return
    item = call.data[len('assign_photo_item_'):]
    info = get_item_info(item)
    category = info['category_name'] if info else None
    TgConfig.STATE[user_id] = 'assign_photo_collect_media'
    TgConfig.STATE[f'{user_id}_item'] = item
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    TgConfig.STATE[f'{user_id}_stock_paths'] = []
    TgConfig.STATE[f'{user_id}_assign_category'] = category
    lang = _get_lang(user_id)
    path = _format_assign_path(category)
    text = _assign_media_text(lang, item, path, 0)
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=_assign_upload_markup(),
    )


async def assign_photo_receive_media(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        return
    item = TgConfig.STATE.get(f'{user_id}_item')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    if not item:
        return
    preview_folder = os.path.join('assets', 'product_photos', item)
    os.makedirs(preview_folder, exist_ok=True)
    lang = _get_lang(user_id)
    if message.photo:
        file = message.photo[-1]
        ext = 'jpg'
    elif message.video:
        file = message.video
        ext = 'mp4'
    else:
        await bot.send_message(user_id, t(lang, 'assign_media_invalid'))
        return
    stock_path = get_next_file_path(item, ext)
    await file.download(destination_file=stock_path)
    stock_paths = TgConfig.STATE.get(f'{user_id}_stock_paths', [])
    stock_paths.append(stock_path)
    TgConfig.STATE[f'{user_id}_stock_paths'] = stock_paths
    category = TgConfig.STATE.get(f'{user_id}_assign_category')
    path = _format_assign_path(category)
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    text = _assign_media_text(lang, item, path, len(stock_paths))
    await bot.edit_message_text(
        text,
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=_assign_upload_markup(),
    )


async def assign_photo_done_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        await call.answer('Nepakanka teisių')
        return
    item = TgConfig.STATE.get(f'{user_id}_item')
    stock_paths = TgConfig.STATE.get(f'{user_id}_stock_paths') or []
    lang = _get_lang(user_id)
    if not item:
        await call.answer(t(lang, 'assign_no_categories'), show_alert=True)
        return
    if not stock_paths:
        await call.answer(t(lang, 'assign_done_no_media'), show_alert=True)
        return
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = 'assign_photo_wait_desc'
    await bot.edit_message_text(
        t(lang, 'assign_desc_prompt'),
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=back('assign_photos'),
    )


async def assign_photo_cancel_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        await call.answer('Nepakanka teisių')
        return
    category = TgConfig.STATE.pop(f'{user_id}_assign_category', None)
    stock_paths = TgConfig.STATE.pop(f'{user_id}_stock_paths', [])
    for file_path in stock_paths:
        cleanup_item_file(file_path)
    TgConfig.STATE.pop(f'{user_id}_item', None)
    TgConfig.STATE.pop(f'{user_id}_message_id', None)
    TgConfig.STATE[user_id] = None
    await _show_assign_menu(bot, call.message.chat.id, call.message.message_id, user_id, category)


async def assign_photo_receive_desc(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE or role & Permission.ASSIGN_PHOTOS):
        return
    item = TgConfig.STATE.get(f'{user_id}_item')
    stock_paths = [p for p in (TgConfig.STATE.get(f'{user_id}_stock_paths') or []) if os.path.isfile(p)]
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    if not item or not stock_paths:
        return
    preview_folder = os.path.join('assets', 'product_photos', item)
    with open(os.path.join(preview_folder, 'description.txt'), 'w') as f:
        f.write(message.text)
    was_empty = select_item_values_amount(item) == 0 and not check_value(item)

    # Keep the first uploaded media as the primary stock value but persist
    # every attachment in metadata so the purchaser receives the full bundle.
    primary_path = stock_paths[0]
    attachments: list[str] = []
    seen: set[str] = set()
    for path in stock_paths:
        if path in seen:
            continue
        attachments.append(path)
        seen.add(path)

    with open(f'{primary_path}.txt', 'w', encoding='utf-8') as f:
        f.write(message.text)
    write_media_meta(primary_path, attachments, message.text)
    add_values_to_item(item, primary_path, False)
    if was_empty:
        await notify_restock(bot, item)
    lang = _get_lang(user_id)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_stock_paths', None)
    TgConfig.STATE.pop(f'{user_id}_item', None)
    TgConfig.STATE.pop(f'{user_id}_assign_category', None)
    TgConfig.STATE.pop(f'{user_id}_message_id', None)
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    prompt = t(lang, 'assign_more')
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton(t(lang, 'yes'), callback_data=f'assign_photo_item_{item}'),
        InlineKeyboardButton(t(lang, 'no'), callback_data='assign_photos')
    )
    await bot.edit_message_text(prompt,
                                chat_id=message.chat.id,
                                message_id=message_id,
                                reply_markup=markup)

    owner_id = int(EnvKeys.OWNER_ID) if EnvKeys.OWNER_ID else None
    if owner_id:
        username = f'@{message.from_user.username}' if message.from_user.username else message.from_user.full_name
        info = get_item_info(item)
        category = info['category_name']
        parent = get_category_parent(category)
        if parent:
            category_name = parent
            subcategory = category
        else:
            category_name = category
            subcategory = '-'
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
        info_id = f'{user_id}_{int(now.timestamp())}'
        TgConfig.STATE[f'photo_info_{info_id}'] = {
            'username': username,
            'time': now.strftime("%Y-%m-%d %H:%M:%S"),
            'product': display_name(item),
            'category': category_name,
            'subcategory': subcategory,
            'description': message.text,
            'files': attachments,
        }
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton('Yes', callback_data=f'photo_info_{info_id}'))
        await bot.send_message(owner_id,
                               f'{username}, uploaded a photo to a ({display_name(item)}) in ({category_name}), ({subcategory}).',
                               reply_markup=markup)


async def photo_info_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    data_id = call.data[len('photo_info_'):]
    info = TgConfig.STATE.pop(f'photo_info_{data_id}', None)
    if not info:
        await call.answer('No data')
        return
    files = info.get('files') or [info.get('file')]
    files_text = '\n'.join(files) if files else '—'
    text = (
        f"{info['username']}\n"
        f"{info['time']}\n"
        f"Product: {info['product']}\n"
        f"Category: {info['category']} | {info['subcategory']}\n"
        f"Description: {info['description']}\n"
        f"Files:\n{files_text}"
    )
    await bot.edit_message_text(text,
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id)
    preview_file = files[0] if files else None
    if preview_file:
        try:
            await bot.send_photo(call.message.chat.id, InputFile(preview_file))
        except Exception:
            pass


async def categories_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('🧾 Kategorijų valdymo meniu',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=categories_management())
        return
    await call.answer('Nepakanka teisių')


async def add_main_category_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'add_main_category'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('Enter main category name',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back("categories_management"))
        return
    await call.answer('Nepakanka teisių')


async def add_category_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await start_category_parent_selection(
            bot,
            call.message.chat.id,
            call.message.message_id,
            user_id,
        )
        return
    await call.answer('Nepakanka teisių')


async def add_subcategory_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await start_subcategory_parent_selection(
            bot,
            call.message.chat.id,
            call.message.message_id,
            user_id,
        )
        return
    await call.answer('Nepakanka teisių')


async def statistics_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        await bot.edit_message_text('Shop statistics:\n'
                                    '➖➖➖➖➖➖➖➖➖➖➖➖➖\n'
                                    '<b>◽USERS</b>\n'
                                    f'◾️Users in last 24h: {select_today_users(today)}\n'
                                    f'◾️Total administrators: {select_admins()}\n'
                                    f'◾️Total users: {get_user_count()}\n'
                                    '➖➖➖➖➖➖➖➖➖➖➖➖➖\n'
                                    '◽<b>FUNDS</b>\n'
                                    f'◾Sales in 24h: {select_today_orders(today)}€\n'
                                    f'◾Items sold for: {select_all_orders()}€\n'
                                    f'◾Top-ups in 24h: {select_today_operations(today)}€\n'
                                    f'◾Funds in system: {select_users_balance()}€\n'
                                    f'◾Total topped up: {select_all_operations()}€\n'
                                    '➖➖➖➖➖➖➖➖➖➖➖➖➖\n'
                                    '◽<b>OTHER</b>\n'
                                    f'◾Items: {select_count_items()}pcs.\n'
                                    f'◾Positions: {select_count_goods()}pcs.\n'
                                    f'◾Categories: {select_count_categories()}pcs.\n'
                                    f'◾Items sold: {select_count_bought_items()}pcs.',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('shop_management'),
                                    parse_mode='HTML')
        return
    await call.answer('Nepakanka teisių')


async def process_main_category_for_add(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    msg = (message.text or '').strip()
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    if not msg:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='⚠️ Main category name cannot be empty.',
                                    reply_markup=back(_get_category_update_back(user_id)))
        TgConfig.STATE[user_id] = None
        return
    TgConfig.STATE[f'{user_id}_new_main_category'] = msg
    TgConfig.STATE[user_id] = 'add_main_category_discount'
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text='Let users use discounts in this main category?',
                                reply_markup=question_buttons('maincat_discount', 'categories_management'))


async def main_category_discount_decision(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_main_category_discount':
        return
    allow = call.data.endswith('_yes')
    TgConfig.STATE[f'{user_id}_new_main_category_discount'] = allow
    TgConfig.STATE[user_id] = 'add_main_category_referral'
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.edit_message_text(chat_id=call.message.chat.id,
                                message_id=message_id,
                                text='Award referral rewards in this main category?',
                                reply_markup=question_buttons('maincat_referral', 'categories_management'))


async def main_category_referral_decision(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_main_category_referral':
        return
    allow_referrals = call.data.endswith('_yes')
    name = TgConfig.STATE.pop(f'{user_id}_new_main_category', None)
    allow_discounts = TgConfig.STATE.pop(f'{user_id}_new_main_category_discount', True)
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = None
    if not name:
        return
    internal_name = generate_internal_name(name)
    create_category(
        internal_name,
        allow_discounts=allow_discounts,
        allow_referral_rewards=allow_referrals,
        title=name,
    )
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=message_id,
        text='Main category created.',
        reply_markup=back(_get_category_update_back(user_id)),
    )
    TgConfig.STATE.pop(f'{user_id}_category_update_back', None)
    admin_info = await bot.get_chat(user_id)
    logger.info(
        f"User {user_id} ({admin_info.first_name}) created new main category \"{name}\" (id {internal_name})"
    )


async def process_category_name(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'add_category_name':
        return
    queue: list[str] = TgConfig.STATE.get(f'{user_id}_category_queue', [])
    index = TgConfig.STATE.get(f'{user_id}_category_index', 0)
    created: list[tuple[str, str]] = TgConfig.STATE.get(f'{user_id}_category_created', [])
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    name = message.text.strip()
    parent = queue[index]
    if not name:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text='⚠️ Category name cannot be empty. Try again.',
            reply_markup=back(_get_category_update_back(user_id)),
        )
        return
    internal_name = generate_internal_name(name)
    create_category(internal_name, parent, title=name)
    admin_info = await bot.get_chat(user_id)
    logger.info(
        "User %s (%s) created category \"%s\" (id %s) under \"%s\"",
        user_id,
        admin_info.first_name,
        name,
        internal_name,
        parent,
    )
    created.append((internal_name, parent, name))
    index += 1
    if index < len(queue):
        TgConfig.STATE[f'{user_id}_category_created'] = created
        TgConfig.STATE[f'{user_id}_category_index'] = index
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text=f'Enter category name for "{_category_label(queue[index])}" ({index + 1}/{len(queue)}):',
            reply_markup=back(_get_category_update_back(user_id)),
        )
        return
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_category_selection', None)
    TgConfig.STATE.pop(f'{user_id}_category_queue', None)
    TgConfig.STATE.pop(f'{user_id}_category_index', None)
    TgConfig.STATE.pop(f'{user_id}_category_created', None)
    summary_lines = []
    for internal, parent, display in created:
        summary_lines.append(f'• {display} → {_category_label(parent)}')
    summary = '\n'.join(summary_lines)
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=message_id,
        text=f'Categories created:\n{summary}',
        reply_markup=back(_get_category_update_back(user_id)),
    )
    TgConfig.STATE.pop(f'{user_id}_category_update_back', None)


async def process_subcategory_name(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'add_subcategory_name':
        return
    queue: list[str] = TgConfig.STATE.get(f'{user_id}_subcategory_queue', [])
    index = TgConfig.STATE.get(f'{user_id}_subcategory_index', 0)
    created: list[tuple[str, str]] = TgConfig.STATE.get(f'{user_id}_subcategory_created', [])
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    name = message.text.strip()
    parent = queue[index]
    if not name:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text='⚠️ Subcategory name cannot be empty. Try again.',
            reply_markup=back(_get_category_update_back(user_id)),
        )
        return
    internal_name = generate_internal_name(name)
    create_category(internal_name, parent, title=name)
    admin_info = await bot.get_chat(user_id)
    logger.info(
        "User %s (%s) created subcategory \"%s\" (id %s) under \"%s\"",
        user_id,
        admin_info.first_name,
        name,
        internal_name,
        parent,
    )
    created.append((internal_name, parent, name))
    index += 1
    if index < len(queue):
        TgConfig.STATE[f'{user_id}_subcategory_created'] = created
        TgConfig.STATE[f'{user_id}_subcategory_index'] = index
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text=f'Enter subcategory name for "{_category_label(queue[index])}" ({index + 1}/{len(queue)}):',
            reply_markup=back(_get_category_update_back(user_id)),
        )
        return
    TgConfig.STATE[user_id] = None
    for key in (
        f'{user_id}_sub_parent_selection',
        f'{user_id}_sub_nav',
        f'{user_id}_sub_current',
        f'{user_id}_subcategory_queue',
        f'{user_id}_subcategory_index',
        f'{user_id}_subcategory_created',
    ):
        TgConfig.STATE.pop(key, None)
    summary_lines = []
    for internal, parent, display in created:
        summary_lines.append(f'• {display} → {_category_label(parent)}')
    summary = '\n'.join(summary_lines)
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=message_id,
        text=f'Subcategories created:\n{summary}',
        reply_markup=back(_get_category_update_back(user_id)),
    )
    TgConfig.STATE.pop(f'{user_id}_category_update_back', None)


async def delete_category_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE):
        await call.answer('Nepakanka teisių')
        return
    categories = get_all_category_names()
    markup = InlineKeyboardMarkup()
    for cat in categories:
        markup.add(InlineKeyboardButton(cat, callback_data=f'delete_cat_{cat}'))
    markup.add(InlineKeyboardButton('🔙 Back', callback_data='categories_management'))
    await bot.edit_message_text('Select category to delete:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def delete_category_choose_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    category = call.data[len('delete_cat_'):]
    subcats = get_all_subcategories(category)
    markup = InlineKeyboardMarkup()
    for sub in subcats:
        markup.add(InlineKeyboardButton(sub, callback_data=f'delete_cat_{sub}'))
    markup.add(InlineKeyboardButton(f'🗑️ Delete {category}', callback_data=f'delete_cat_confirm_{category}'))
    back_parent = get_category_parent(category)
    back_data = 'delete_category' if back_parent is None else f'delete_cat_{back_parent}'
    markup.add(InlineKeyboardButton('🔙 Back', callback_data=back_data))
    await bot.edit_message_text('Choose subcategory or delete:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def delete_category_confirm_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    category = call.data[len('delete_cat_confirm_'):]
    delete_category(category)
    await bot.edit_message_text('✅ Category deleted',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back(_get_category_update_back(user_id)))
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) deleted category \"{category}\"")


def _clear_update_category_selection_state(user_id: int) -> None:
    TgConfig.STATE.pop(f'{user_id}_category_nav', None)
    TgConfig.STATE.pop(f'{user_id}_category_current', None)


async def update_category_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if f'{user_id}_category_update_back' not in TgConfig.STATE:
        TgConfig.STATE[f'{user_id}_category_update_back'] = 'categories_management'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE):
        await call.answer('Nepakanka teisių')
        return
    lang = _get_lang(user_id)
    TgConfig.STATE[user_id] = 'update_category_select'
    TgConfig.STATE[f'{user_id}_category_nav'] = []
    TgConfig.STATE[f'{user_id}_category_current'] = None
    roots = _get_hierarchy_children(None)
    if not roots:
        TgConfig.STATE[user_id] = None
        await bot.edit_message_text(
            t(lang, 'catalog_no_categories_available'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=back(_get_category_update_back(user_id)),
        )
        _clear_update_category_selection_state(user_id)
        return
    await show_update_category_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def show_update_category_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    if TgConfig.STATE.get(user_id) != 'update_category_select':
        return
    lang = _get_lang(user_id)
    current = TgConfig.STATE.get(f'{user_id}_category_current')
    nav = TgConfig.STATE.get(f'{user_id}_category_nav', [])
    categories = _get_hierarchy_children(current)
    markup = InlineKeyboardMarkup(row_width=1)
    for name in categories:
        buttons = [InlineKeyboardButton(_category_label(name), callback_data=f'updatecat_pick_{name}')]
        if _category_has_children(name):
            buttons.append(InlineKeyboardButton('➡️', callback_data=f'updatecat_open_{name}'))
        markup.row(*buttons)
    if not categories:
        markup.add(InlineKeyboardButton(t(lang, 'catalog_update_branch_empty_button'), callback_data='updatecat_empty'))
    if nav:
        markup.add(InlineKeyboardButton(t(lang, 'multi_select_up'), callback_data='updatecat_back'))
    markup.add(InlineKeyboardButton(t(lang, 'action_cancel'), callback_data='updatecat_cancel'))
    if current is None:
        text = t(lang, 'catalog_update_select_root')
    else:
        text = t(lang, 'catalog_update_select_branch', path=_format_assign_path(current))
    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def update_category_selection_open(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_category_select':
        return
    target = call.data[len('updatecat_open_'):]
    current = TgConfig.STATE.get(f'{user_id}_category_current')
    lang = _get_lang(user_id)
    valid = set(_get_hierarchy_children(current))
    if target not in valid:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    nav: list[str] = TgConfig.STATE.get(f'{user_id}_category_nav', [])
    if current is not None:
        if len(nav) >= MAX_SELECTION_DEPTH:
            await call.answer(t(lang, 'multi_select_depth_limit'), show_alert=True)
            return
        nav.append(current)
    TgConfig.STATE[f'{user_id}_category_nav'] = nav
    TgConfig.STATE[f'{user_id}_category_current'] = target
    await show_update_category_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def update_category_selection_back(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_category_select':
        return
    nav: list[str] = TgConfig.STATE.get(f'{user_id}_category_nav', [])
    new_current = nav.pop() if nav else None
    TgConfig.STATE[f'{user_id}_category_nav'] = nav
    TgConfig.STATE[f'{user_id}_category_current'] = new_current
    await show_update_category_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def update_category_selection_empty(call: CallbackQuery):
    _, user_id = await get_bot_user_ids(call)
    lang = _get_lang(user_id)
    await call.answer(t(lang, 'catalog_update_branch_empty'), show_alert=True)


async def update_category_selection_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_category_select':
        return
    _clear_update_category_selection_state(user_id)
    TgConfig.STATE[user_id] = None
    lang = _get_lang(user_id)
    await bot.edit_message_text(
        t(lang, 'catalog_category_update_cancelled'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back(_get_category_update_back(user_id)),
    )


async def update_category_selection_pick(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_category_select':
        return
    target = call.data[len('updatecat_pick_'):]
    current = TgConfig.STATE.get(f'{user_id}_category_current')
    lang = _get_lang(user_id)
    valid = set(_get_hierarchy_children(current))
    if target not in valid:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    TgConfig.STATE[user_id] = 'update_category_name'
    TgConfig.STATE[f'{user_id}_check_category'] = target
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await bot.edit_message_text(
        t(lang, 'catalog_category_rename_prompt', name=_category_label(target)),
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=back('update_category_select'),
    )


async def update_category_selection_resume(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_category_name':
        return
    TgConfig.STATE[user_id] = 'update_category_select'
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await show_update_category_selection(bot, call.message.chat.id, message_id, user_id)


async def check_category_name_for_update(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'update_category_name':
        return
    category = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    old_name = TgConfig.STATE.get(f'{user_id}_check_category')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if not old_name:
        TgConfig.STATE[user_id] = None
        return
    update_category(old_name, category)
    TgConfig.STATE[user_id] = None
    _clear_update_category_selection_state(user_id)
    lang = _get_lang(user_id)
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=message_id,
        text=t(
            lang,
            'catalog_category_updated',
            old=_category_label(old_name),
            new=category,
        ),
        reply_markup=back(_get_category_update_back(user_id)),
    )
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) "
                f'changed category "{old_name}" to "{category}"')
    TgConfig.STATE.pop(f'{user_id}_category_update_back', None)
    TgConfig.STATE.pop(f'{user_id}_check_category', None)


async def goods_settings_menu_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('🛒 Pasirinkite veiksmą šiai prekei',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=item_management())
        return
    await call.answer('Nepakanka teisių')


async def add_item_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    TgConfig.STATE[f'{user_id}_item_update_back'] = 'item-management'
    TgConfig.STATE[user_id] = 'create_item_name'
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('🏷️ Įveskite prekės pavadinimą',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back('item-management'))
        return
    await call.answer('Nepakanka teisių')


async def check_item_name_for_add(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    item_name = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    item = check_item(item_name)
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if item:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='❌ Item cannot be created (already exists)',
                                    reply_markup=back('item-management'))
        return
    TgConfig.STATE[user_id] = 'create_item_description_choice'
    TgConfig.STATE[f'{user_id}_name'] = message.text
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton('✅ Yes', callback_data='add_item_desc_yes'),
        InlineKeyboardButton('❌ No', callback_data='add_item_desc_no')
    )
    markup.add(InlineKeyboardButton('🔙 Back', callback_data='item-management'))
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text='Add description for item?',
                                reply_markup=markup)


async def add_item_desc_yes(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'create_item_description'
    await bot.edit_message_text('Enter description for item:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back('item-management'))


async def add_item_desc_no(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_description'] = ''
    TgConfig.STATE[user_id] = 'create_item_price'
    await bot.edit_message_text('Enter price for item:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back('item-management'))


async def add_item_description(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    TgConfig.STATE[f'{user_id}_description'] = message.text
    TgConfig.STATE[user_id] = 'create_item_price'
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text='Enter price for item:',
                                reply_markup=back('item-management'))


async def add_item_price(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    if not message.text.isdigit():
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='⚠️ Invalid price value.',
                                    reply_markup=back('item-management'))
        return
    TgConfig.STATE[f'{user_id}_price'] = message.text
    TgConfig.STATE[user_id] = 'create_item_preview'
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text='Do you want to add a preview photo?',
                                reply_markup=question_buttons('add_preview', 'item-management'))


async def add_preview_yes(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_preview':
        return
    TgConfig.STATE[user_id] = 'create_item_photo'
    await bot.edit_message_text('Send preview photo for item:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back('item-management'))


async def add_preview_no(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_preview':
        return
    TgConfig.STATE[user_id] = None
    await start_item_destination_selection(
        bot,
        call.message.chat.id,
        call.message.message_id,
        user_id,
    )


async def add_item_preview_photo(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'create_item_photo':
        return
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if not message.photo:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='❌ Send a photo',
                                    reply_markup=back('item-management'))
        return
    file = message.photo[-1]
    temp_folder = os.path.join('assets', 'temp_previews')
    os.makedirs(temp_folder, exist_ok=True)
    temp_path = os.path.join(temp_folder, f'{user_id}.jpg')
    await file.download(destination_file=temp_path)
    TgConfig.STATE[f'{user_id}_preview_path'] = temp_path
    TgConfig.STATE[user_id] = None
    await start_item_destination_selection(bot, message.chat.id, message_id, user_id)


def _get_hierarchy_children(parent: str | None) -> list[str]:
    if parent is None:
        return get_all_category_names()
    return get_all_subcategories(parent)


def _category_has_children(category: str) -> bool:
    return bool(get_all_subcategories(category))


def _build_category_path(category: str | None) -> list[str]:
    if category is None:
        return []
    path: list[str] = []
    current = category
    while current is not None:
        path.append(current)
        current = get_category_parent(current)
    return list(reversed(path))


def _format_selection_button(
    name: str,
    selected: set[str],
    titles: dict[str, str] | None = None,
) -> str:
    marker = '✅' if name in selected else '▫️'
    label = (titles or {}).get(name, _category_label(name))
    return f'{marker} {label}'


def _compose_category_path(nav_stack: Sequence[str], current: str | None, name: str) -> Tuple[str, ...]:
    parts = list(nav_stack)
    if current:
        parts.append(current)
    parts.append(name)
    return tuple(parts)


def _category_label(name: str | None) -> str:
    if not name:
        return ''
    return get_category_title(name)


def _format_path_selection_button(
    name: str,
    selected: set[Tuple[str, ...]],
    path: Tuple[str, ...],
    duplicates: set[str],
    titles: dict[str, str] | None = None,
) -> str:
    marker = '✅' if path in selected else '▫️'
    label = (titles or {}).get(name, _category_label(name))
    if name in duplicates and len(path) > 1:
        context = ' / '.join(_category_label(part) for part in path[:-1])
        return f'{marker} {label} ({context})'
    return f'{marker} {label}'


def _format_assign_path(category: str | Sequence[str] | None) -> str:
    if category is None:
        return ''
    if isinstance(category, (list, tuple)):
        return ' / '.join(_category_label(part) for part in category)
    path = _build_category_path(category)
    return ' / '.join(_category_label(part) for part in path)


def _assign_child_prefix(category: str | None) -> str:
    parent = get_category_parent(category) if category else None
    return 'assign_photo_cat_' if parent is None else 'assign_photo_sub_'


def _clear_update_item_selection_state(user_id: int) -> None:
    TgConfig.STATE.pop(f'{user_id}_update_nav', None)
    TgConfig.STATE.pop(f'{user_id}_update_current', None)


def _reset_item_destination_tokens(user_id: int) -> None:
    TgConfig.STATE[f'{user_id}_item_token_store'] = {}


def _register_item_destination_token(
    user_id: int,
    path: Tuple[str, ...],
    token_store: dict[str, Tuple[str, ...]],
    reverse_store: dict[Tuple[str, ...], str],
) -> str:
    """Return a short-lived token for the given category path."""
    if path in reverse_store:
        return reverse_store[path]
    while True:
        candidate = secrets.token_urlsafe(6)
        if (
            candidate not in token_store
            and len(f'itemdest_toggle_{candidate}') <= 64
            and len(f'itemdest_open_{candidate}') <= 64
        ):
            token_store[candidate] = path
            reverse_store[path] = candidate
            return candidate


def _resolve_item_destination_token(user_id: int, token: str) -> Tuple[str, ...] | None:
    store: dict[str, Tuple[str, ...]] = TgConfig.STATE.get(f'{user_id}_item_token_store', {})
    return store.get(token)


async def start_item_destination_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    TgConfig.STATE[user_id] = 'create_item_destinations'
    TgConfig.STATE[f'{user_id}_item_destinations'] = set()
    TgConfig.STATE[f'{user_id}_item_nav'] = []
    TgConfig.STATE[f'{user_id}_item_current'] = None
    _reset_item_destination_tokens(user_id)
    await show_item_destination_selection(bot, chat_id, message_id, user_id)


async def show_item_destination_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    selected: set[Tuple[str, ...]] = set(TgConfig.STATE.get(f'{user_id}_item_destinations', set()))
    current_parent = TgConfig.STATE.get(f'{user_id}_item_current')
    nav_stack: list[str] = list(TgConfig.STATE.get(f'{user_id}_item_nav', []))
    options = _get_hierarchy_children(current_parent)
    lang = _get_lang(user_id)
    markup = InlineKeyboardMarkup(row_width=2)
    titles = get_category_titles(options)
    label_counts = Counter(titles.get(name, _category_label(name)) for name in options)
    duplicates = {
        name for name in options if label_counts[titles.get(name, _category_label(name))] > 1
    }
    token_store: dict[str, Tuple[str, ...]] = {}
    reverse_store: dict[Tuple[str, ...], str] = {}
    for name in options:
        path = _compose_category_path(nav_stack, current_parent, name)
        token = _register_item_destination_token(user_id, path, token_store, reverse_store)
        buttons = [
            InlineKeyboardButton(
                _format_path_selection_button(name, selected, path, duplicates, titles),
                callback_data=f'itemdest_toggle_{token}',
            )
        ]
        if _category_has_children(name):
            buttons.append(InlineKeyboardButton('➡️', callback_data=f'itemdest_open_{token}'))
        markup.row(*buttons)
    TgConfig.STATE[f'{user_id}_item_token_store'] = token_store
    if not options:
        markup.add(InlineKeyboardButton(t(lang, 'multi_select_empty'), callback_data='itemdest_empty'))
    if current_parent is not None:
        markup.add(InlineKeyboardButton(t(lang, 'multi_select_up'), callback_data='itemdest_back'))
    markup.row(
        InlineKeyboardButton(t(lang, 'action_done'), callback_data='itemdest_done'),
        InlineKeyboardButton(t(lang, 'action_clear'), callback_data='itemdest_clear'),
    )
    markup.add(InlineKeyboardButton(t(lang, 'action_cancel'), callback_data='itemdest_cancel'))
    if current_parent:
        path = ' / '.join(_category_label(part) for part in nav_stack + [current_parent])
        text = t(lang, 'catalog_select_subcategories_path', path=path)
    else:
        text = t(lang, 'catalog_select_subcategories')
    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def item_destination_empty(call: CallbackQuery):
    _, user_id = await get_bot_user_ids(call)
    lang = _get_lang(user_id)
    await call.answer(t(lang, 'multi_select_no_children'), show_alert=True)


async def item_destination_toggle(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destinations':
        return
    token = call.data[len('itemdest_toggle_'):]
    path = _resolve_item_destination_token(user_id, token)
    lang = _get_lang(user_id)
    current_parent = TgConfig.STATE.get(f'{user_id}_item_current')
    nav_stack: list[str] = list(TgConfig.STATE.get(f'{user_id}_item_nav', []))
    if path is None:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    expected_parent = nav_stack + ([current_parent] if current_parent else [])
    if list(path[:-1]) != expected_parent:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    valid_options = {
        _compose_category_path(nav_stack, current_parent, name)
        for name in _get_hierarchy_children(current_parent)
    }
    if path not in valid_options:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    selected: set[Tuple[str, ...]] = set(TgConfig.STATE.get(f'{user_id}_item_destinations', set()))
    if path in selected:
        selected.remove(path)
    else:
        selected.add(path)
    TgConfig.STATE[f'{user_id}_item_destinations'] = selected
    await show_item_destination_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def item_destination_open(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destinations':
        return
    token = call.data[len('itemdest_open_'):]
    path = _resolve_item_destination_token(user_id, token)
    current = TgConfig.STATE.get(f'{user_id}_item_current')
    nav_stack: list[str] = list(TgConfig.STATE.get(f'{user_id}_item_nav', []))
    lang = _get_lang(user_id)
    if path is None:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    expected_parent = nav_stack + ([current] if current else [])
    valid_options = {
        _compose_category_path(nav_stack, current, name)
        for name in _get_hierarchy_children(current)
    }
    if list(path[:-1]) != expected_parent or path not in valid_options:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    if current is not None:
        if len(nav_stack) >= MAX_SELECTION_DEPTH:
            await call.answer(t(lang, 'multi_select_depth_limit'), show_alert=True)
            return
        nav_stack.append(current)
    TgConfig.STATE[f'{user_id}_item_nav'] = nav_stack
    TgConfig.STATE[f'{user_id}_item_current'] = path[-1]
    await show_item_destination_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def item_destination_back(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destinations':
        return
    nav_stack: list[str] = TgConfig.STATE.get(f'{user_id}_item_nav', [])
    new_current = nav_stack.pop() if nav_stack else None
    TgConfig.STATE[f'{user_id}_item_nav'] = nav_stack
    TgConfig.STATE[f'{user_id}_item_current'] = new_current
    await show_item_destination_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def item_destination_clear(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destinations':
        return
    TgConfig.STATE[f'{user_id}_item_destinations'] = set()
    await show_item_destination_selection(bot, call.message.chat.id, call.message.message_id, user_id)


def _cleanup_item_creation_state(user_id: int, keep_preview: bool = False) -> None:
    TgConfig.STATE.pop(f'{user_id}_item_destinations', None)
    TgConfig.STATE.pop(f'{user_id}_item_nav', None)
    TgConfig.STATE.pop(f'{user_id}_item_current', None)
    TgConfig.STATE.pop(f'{user_id}_item_destination_order', None)
    TgConfig.STATE.pop(f'{user_id}_item_destination_idx', None)
    TgConfig.STATE.pop(f'{user_id}_item_destination_names', None)
    TgConfig.STATE.pop(f'{user_id}_item_token_store', None)
    TgConfig.STATE.pop(f'{user_id}_message_id', None)
    for key in ('name', 'description', 'price'):
        TgConfig.STATE.pop(f'{user_id}_{key}', None)
    preview = TgConfig.STATE.pop(f'{user_id}_preview_path', None)
    if preview and os.path.isfile(preview) and not keep_preview:
        os.remove(preview)


async def item_destination_done(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destinations':
        return
    selected: set[Tuple[str, ...]] = set(TgConfig.STATE.get(f'{user_id}_item_destinations', set()))
    lang = _get_lang(user_id)
    if not selected:
        await call.answer(t(lang, 'multi_select_need_category'), show_alert=True)
        return
    destinations = sorted(selected)
    TgConfig.STATE[f'{user_id}_item_destination_order'] = destinations
    TgConfig.STATE[f'{user_id}_item_destination_idx'] = 0
    TgConfig.STATE[f'{user_id}_item_destination_names'] = {}
    TgConfig.STATE[user_id] = 'create_item_destination_names'
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await _prompt_next_destination_name(
        bot,
        call.message.chat.id,
        message_id,
        user_id,
    )


async def _prompt_next_destination_name(bot, chat_id: int, message_id: int, user_id: int) -> None:
    destinations: list[Tuple[str, ...]] = TgConfig.STATE.get(f'{user_id}_item_destination_order', [])
    index = TgConfig.STATE.get(f'{user_id}_item_destination_idx', 0)
    lang = _get_lang(user_id)
    total = len(destinations)
    if index >= total:
        await _finalize_item_creation(bot, chat_id, message_id, user_id)
        return
    category = destinations[index]
    path = _format_assign_path(category)
    base_name = TgConfig.STATE.get(f'{user_id}_name', '')
    prompt = t(
        lang,
        'catalog_item_name_for_destination',
        path=path,
        index=index + 1,
        total=total,
    )
    markup = InlineKeyboardMarkup(row_width=1)
    if base_name:
        prompt += f"\n{t(lang, 'catalog_item_name_hint', name=base_name)}"
        markup.add(
            InlineKeyboardButton(
                t(lang, 'catalog_item_name_keep', name=base_name),
                callback_data='itemdest_name_default',
            )
        )
    markup.add(InlineKeyboardButton(t(lang, 'action_cancel'), callback_data='itemdest_names_cancel'))
    await bot.edit_message_text(
        prompt,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def _finalize_item_creation(bot, chat_id: int, message_id: int, user_id: int) -> None:
    destinations: list[Tuple[str, ...]] = TgConfig.STATE.get(f'{user_id}_item_destination_order', [])
    names: dict[Tuple[str, ...], str] = TgConfig.STATE.get(f'{user_id}_item_destination_names', {})
    base_name = TgConfig.STATE.get(f'{user_id}_name', '')
    description = TgConfig.STATE.get(f'{user_id}_description', '')
    price = TgConfig.STATE.get(f'{user_id}_price')
    preview_src = TgConfig.STATE.get(f'{user_id}_preview_path')
    admin_info = await bot.get_chat(user_id)
    created: list[tuple[str, Tuple[str, ...]]] = []
    for category in destinations:
        title = names.get(category, base_name) or base_name
        internal_name = generate_internal_name(title)
        preview_folder = os.path.join('assets', 'product_photos', internal_name)
        os.makedirs(preview_folder, exist_ok=True)
        if preview_src and os.path.isfile(preview_src):
            ext = os.path.splitext(preview_src)[1]
            shutil.copy(preview_src, os.path.join(preview_folder, f'preview{ext}'))
            shutil.copy(
                preview_src,
                os.path.join(preview_folder, os.path.basename(preview_src)),
            )
        create_item(internal_name, description, price, category[-1], None)
        created.append((internal_name, category))
        logger.info(
            "User %s (%s) created new item \"%s\" in category \"%s\"",
            user_id,
            admin_info.first_name,
            internal_name,
            _format_assign_path(category),
        )
    _cleanup_item_creation_state(user_id)
    TgConfig.STATE[user_id] = None
    if preview_src and os.path.isfile(preview_src):
        os.remove(preview_src)
    lang = _get_lang(user_id)
    summary_lines = []
    for name, category in created:
        path = _format_assign_path(category)
        summary_lines.append(f'• {display_name(name)} → {path}')
    summary = '\n'.join(summary_lines)
    await bot.edit_message_text(
        t(lang, 'catalog_items_created', summary=summary),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=back('item-management'),
    )


async def item_destination_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destinations':
        return
    _cleanup_item_creation_state(user_id)
    TgConfig.STATE[user_id] = None
    lang = _get_lang(user_id)
    await call.answer()
    await bot.edit_message_text(
        t(lang, 'catalog_item_creation_cancelled'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('item-management'),
    )


async def item_destination_names_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destination_names':
        return
    _cleanup_item_creation_state(user_id)
    TgConfig.STATE[user_id] = None
    lang = _get_lang(user_id)
    await call.answer()
    await bot.edit_message_text(
        t(lang, 'catalog_item_creation_cancelled'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('item-management'),
    )


async def item_destination_name_default(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'create_item_destination_names':
        return
    base_name = (TgConfig.STATE.get(f'{user_id}_name') or '').strip()
    lang = _get_lang(user_id)
    if not base_name:
        await call.answer(t(lang, 'catalog_item_name_invalid'), show_alert=True)
        return
    destinations: list[Tuple[str, ...]] = TgConfig.STATE.get(f'{user_id}_item_destination_order', [])
    index = TgConfig.STATE.get(f'{user_id}_item_destination_idx', 0)
    if index >= len(destinations):
        await call.answer()
        return
    names: dict[Tuple[str, ...], str] = TgConfig.STATE.get(f'{user_id}_item_destination_names', {})
    category = destinations[index]
    names[category] = base_name
    TgConfig.STATE[f'{user_id}_item_destination_names'] = names
    TgConfig.STATE[f'{user_id}_item_destination_idx'] = index + 1
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await _prompt_next_destination_name(bot, call.message.chat.id, message_id, user_id)
    await call.answer()


async def process_item_destination_name(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'create_item_destination_names':
        return
    lang = _get_lang(user_id)
    text = (message.text or '').strip()
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if not text:
        await bot.send_message(user_id, t(lang, 'catalog_item_name_invalid'))
        return
    destinations: list[Tuple[str, ...]] = TgConfig.STATE.get(f'{user_id}_item_destination_order', [])
    index = TgConfig.STATE.get(f'{user_id}_item_destination_idx', 0)
    if index >= len(destinations):
        await _prompt_next_destination_name(
            bot,
            message.chat.id,
            TgConfig.STATE.get(f'{user_id}_message_id', message.message_id),
            user_id,
        )
        return
    names: dict[Tuple[str, ...], str] = TgConfig.STATE.get(f'{user_id}_item_destination_names', {})
    category = destinations[index]
    names[category] = text
    TgConfig.STATE[f'{user_id}_item_destination_names'] = names
    TgConfig.STATE[f'{user_id}_item_destination_idx'] = index + 1
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', message.message_id)
    await _prompt_next_destination_name(bot, message.chat.id, message_id, user_id)


def _get_item_update_back(user_id: int) -> str:
    return TgConfig.STATE.get(f'{user_id}_item_update_back', 'goods_management')


def _get_category_update_back(user_id: int) -> str:
    return TgConfig.STATE.get(f'{user_id}_category_update_back', 'categories_management')


async def start_category_parent_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    mains = sorted(get_all_category_names())
    lang = _get_lang(user_id)
    if not mains:
        TgConfig.STATE[user_id] = None
        await bot.edit_message_text(
            t(lang, 'catalog_no_main_categories'),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=back(_get_category_update_back(user_id)),
        )
        return
    TgConfig.STATE[user_id] = 'add_category_select_parents'
    TgConfig.STATE[f'{user_id}_category_selection'] = set()
    await show_category_parent_selection(bot, chat_id, message_id, user_id)


async def show_category_parent_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    selected: set[str] = TgConfig.STATE.get(f'{user_id}_category_selection', set())
    mains = get_all_category_names()
    lang = _get_lang(user_id)
    markup = InlineKeyboardMarkup(row_width=2)
    titles = get_category_titles(mains)
    for name in mains:
        markup.add(
            InlineKeyboardButton(
                _format_selection_button(name, selected, titles),
                callback_data=f'catparent_toggle_{name}',
            )
        )
    markup.row(
        InlineKeyboardButton(t(lang, 'action_done'), callback_data='catparent_done'),
        InlineKeyboardButton(t(lang, 'action_clear'), callback_data='catparent_clear'),
    )
    markup.add(InlineKeyboardButton(t(lang, 'action_cancel'), callback_data='catparent_cancel'))
    await bot.edit_message_text(
        t(lang, 'catalog_select_main_categories'),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def category_parent_toggle(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_category_select_parents':
        return
    parent = call.data[len('catparent_toggle_'):]
    lang = _get_lang(user_id)
    valid_options = set(get_all_category_names())
    if parent not in valid_options:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    selected: set[str] = TgConfig.STATE.get(f'{user_id}_category_selection', set())
    if parent in selected:
        selected.remove(parent)
    else:
        selected.add(parent)
    TgConfig.STATE[f'{user_id}_category_selection'] = selected
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await show_category_parent_selection(bot, call.message.chat.id, message_id, user_id)


async def category_parent_clear(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_category_select_parents':
        return
    TgConfig.STATE[f'{user_id}_category_selection'] = set()
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await show_category_parent_selection(bot, call.message.chat.id, message_id, user_id)


async def category_parent_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_category_select_parents':
        return
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_category_selection', None)
    lang = _get_lang(user_id)
    await bot.edit_message_text(
        t(lang, 'catalog_category_creation_cancelled'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back(_get_category_update_back(user_id)),
    )


async def category_parent_done(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_category_select_parents':
        return
    selected: set[str] = TgConfig.STATE.get(f'{user_id}_category_selection', set())
    lang = _get_lang(user_id)
    if not selected:
        await call.answer(t(lang, 'catalog_need_main_category'), show_alert=True)
        return
    queue = sorted(selected, key=_category_label)
    TgConfig.STATE[f'{user_id}_category_queue'] = queue
    TgConfig.STATE[f'{user_id}_category_index'] = 0
    TgConfig.STATE[f'{user_id}_category_created'] = []
    TgConfig.STATE[user_id] = 'add_category_name'
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await bot.edit_message_text(
        t(
            lang,
            'catalog_category_name_prompt',
            parent=_category_label(queue[0]),
            index=1,
            total=len(queue),
        ),
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=back(_get_category_update_back(user_id)),
    )


async def start_subcategory_parent_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    roots = _get_hierarchy_children(None)
    lang = _get_lang(user_id)
    if not roots:
        TgConfig.STATE[user_id] = None
        await bot.edit_message_text(
            t(lang, 'catalog_no_categories_available'),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=back(_get_category_update_back(user_id)),
        )
        return
    TgConfig.STATE[user_id] = 'add_subcategory_select_parents'
    TgConfig.STATE[f'{user_id}_sub_parent_selection'] = set()
    TgConfig.STATE[f'{user_id}_sub_nav'] = []
    TgConfig.STATE[f'{user_id}_sub_current'] = None
    await show_subcategory_parent_selection(bot, chat_id, message_id, user_id)


async def show_subcategory_parent_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    selected: set[str] = TgConfig.STATE.get(f'{user_id}_sub_parent_selection', set())
    current_parent = TgConfig.STATE.get(f'{user_id}_sub_current')
    nav_stack: list[str] = TgConfig.STATE.get(f'{user_id}_sub_nav', [])
    options = _get_hierarchy_children(current_parent)
    lang = _get_lang(user_id)
    markup = InlineKeyboardMarkup(row_width=2)
    titles = get_category_titles(options)
    for name in options:
        buttons = [
            InlineKeyboardButton(
                _format_selection_button(name, selected, titles),
                callback_data=f'subparent_toggle_{name}',
            )
        ]
        if _category_has_children(name):
            buttons.append(InlineKeyboardButton('➡️', callback_data=f'subparent_open_{name}'))
        markup.row(*buttons)
    if not options:
        markup.add(InlineKeyboardButton(t(lang, 'multi_select_empty'), callback_data='subparent_empty'))
    if current_parent is not None:
        markup.add(InlineKeyboardButton(t(lang, 'multi_select_up'), callback_data='subparent_back'))
    markup.row(
        InlineKeyboardButton(t(lang, 'action_done'), callback_data='subparent_done'),
        InlineKeyboardButton(t(lang, 'action_clear'), callback_data='subparent_clear'),
    )
    markup.add(InlineKeyboardButton(t(lang, 'action_cancel'), callback_data='subparent_cancel'))
    if current_parent:
        path = ' / '.join(_category_label(part) for part in nav_stack + [current_parent])
        text = t(lang, 'catalog_select_parents_path', path=path)
    else:
        text = t(lang, 'catalog_select_parents')
    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def subcategory_parent_empty(call: CallbackQuery):
    _, user_id = await get_bot_user_ids(call)
    lang = _get_lang(user_id)
    await call.answer(t(lang, 'multi_select_no_children'), show_alert=True)


async def subcategory_parent_toggle(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_subcategory_select_parents':
        return
    target = call.data[len('subparent_toggle_'):]
    lang = _get_lang(user_id)
    current = TgConfig.STATE.get(f'{user_id}_sub_current')
    valid_options = set(_get_hierarchy_children(current))
    if target not in valid_options:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    selected: set[str] = TgConfig.STATE.get(f'{user_id}_sub_parent_selection', set())
    if target in selected:
        selected.remove(target)
    else:
        selected.add(target)
    TgConfig.STATE[f'{user_id}_sub_parent_selection'] = selected
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await show_subcategory_parent_selection(bot, call.message.chat.id, message_id, user_id)


async def subcategory_parent_open(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_subcategory_select_parents':
        return
    target = call.data[len('subparent_open_'):]
    current = TgConfig.STATE.get(f'{user_id}_sub_current')
    nav_stack: list[str] = TgConfig.STATE.get(f'{user_id}_sub_nav', [])
    lang = _get_lang(user_id)
    valid_options = set(_get_hierarchy_children(current))
    if target not in valid_options:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    if current is not None:
        if len(nav_stack) >= MAX_SELECTION_DEPTH:
            await call.answer(t(lang, 'multi_select_depth_limit'), show_alert=True)
            return
        nav_stack.append(current)
    TgConfig.STATE[f'{user_id}_sub_nav'] = nav_stack
    TgConfig.STATE[f'{user_id}_sub_current'] = target
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await show_subcategory_parent_selection(bot, call.message.chat.id, message_id, user_id)


async def subcategory_parent_back(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_subcategory_select_parents':
        return
    nav_stack: list[str] = TgConfig.STATE.get(f'{user_id}_sub_nav', [])
    new_current = nav_stack.pop() if nav_stack else None
    TgConfig.STATE[f'{user_id}_sub_nav'] = nav_stack
    TgConfig.STATE[f'{user_id}_sub_current'] = new_current
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await show_subcategory_parent_selection(bot, call.message.chat.id, message_id, user_id)


async def subcategory_parent_clear(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_subcategory_select_parents':
        return
    TgConfig.STATE[f'{user_id}_sub_parent_selection'] = set()
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await show_subcategory_parent_selection(bot, call.message.chat.id, message_id, user_id)


async def subcategory_parent_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_subcategory_select_parents':
        return
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_sub_parent_selection', None)
    TgConfig.STATE.pop(f'{user_id}_sub_nav', None)
    TgConfig.STATE.pop(f'{user_id}_sub_current', None)
    lang = _get_lang(user_id)
    await bot.edit_message_text(
        t(lang, 'catalog_subcategory_creation_cancelled'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back(_get_category_update_back(user_id)),
    )


async def subcategory_parent_done(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'add_subcategory_select_parents':
        return
    selected: set[str] = TgConfig.STATE.get(f'{user_id}_sub_parent_selection', set())
    lang = _get_lang(user_id)
    if not selected:
        await call.answer(t(lang, 'multi_select_need_category'), show_alert=True)
        return
    queue = sorted(selected, key=_category_label)
    TgConfig.STATE[f'{user_id}_subcategory_queue'] = queue
    TgConfig.STATE[f'{user_id}_subcategory_index'] = 0
    TgConfig.STATE[f'{user_id}_subcategory_created'] = []
    TgConfig.STATE[user_id] = 'add_subcategory_name'
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    await bot.edit_message_text(
        t(
            lang,
            'catalog_subcategory_name_prompt',
            parent=_category_label(queue[0]),
            index=1,
            total=len(queue),
        ),
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=back(_get_category_update_back(user_id)),
    )
async def catalog_editor_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    lang = _get_lang(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text(
            t(lang, 'catalog_editor_menu_title'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=catalog_editor_menu(lang),
        )
        return
    await call.answer(t(lang, 'insufficient_rights'))


async def catalog_edit_main_start(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    mains = sorted(get_all_category_names())
    lang = _get_lang(user_id)
    if not mains:
        await bot.edit_message_text(
            t(lang, 'catalog_no_main_categories'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=back('catalog_editor'),
        )
        return
    markup = InlineKeyboardMarkup()
    titles = get_category_titles(mains)
    for name in mains:
        label = titles.get(name, _category_label(name))
        markup.add(InlineKeyboardButton(label, callback_data=f'catalog_main_select_{name}'))
    markup.add(InlineKeyboardButton(t(lang, 'back'), callback_data='catalog_editor'))
    await bot.edit_message_text(
        t(lang, 'catalog_select_main_prompt'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )


def _get_main_category_info(name: str) -> dict | None:
    return check_category(name)


async def _show_main_category_actions(bot, chat_id: int, message_id: int, user_id: int, name: str) -> None:
    category = _get_main_category_info(name)
    lang = _get_lang(user_id)
    if not category:
        await bot.edit_message_text(
            t(lang, 'catalog_main_not_found'),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=catalog_editor_menu(lang),
        )
        return
    discounts = t(lang, 'state_enabled') if category['allow_discounts'] else t(lang, 'state_disabled')
    referrals = t(lang, 'state_enabled') if category['allow_referral_rewards'] else t(lang, 'state_disabled')
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(t(lang, 'catalog_action_rename'), callback_data='catalog_main_rename'))
    markup.add(
        InlineKeyboardButton(
            t(lang, 'catalog_action_toggle_discount', state=discounts),
            callback_data='catalog_main_toggle_discount',
        )
    )
    markup.add(
        InlineKeyboardButton(
            t(lang, 'catalog_action_toggle_referral', state=referrals),
            callback_data='catalog_main_toggle_referral',
        )
    )
    markup.add(InlineKeyboardButton(t(lang, 'back'), callback_data='catalog_edit_main'))
    await bot.edit_message_text(
        t(lang, 'catalog_main_info', name=_category_label(name)),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def catalog_edit_main_select(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    name = call.data[len('catalog_main_select_'):]
    TgConfig.STATE[f'{user_id}_catalog_main'] = name
    await call.answer()
    await _show_main_category_actions(bot, call.message.chat.id, call.message.message_id, user_id, name)


async def catalog_main_rename_prompt(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    name = TgConfig.STATE.get(f'{user_id}_catalog_main')
    lang = _get_lang(user_id)
    if not name:
        await call.answer(t(lang, 'catalog_select_category_first'), show_alert=True)
        return
    TgConfig.STATE[user_id] = 'catalog_main_rename'
    await bot.edit_message_text(
        t(lang, 'catalog_main_rename_prompt', name=_category_label(name)),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('catalog_edit_main'),
    )


async def catalog_main_apply_toggle(call: CallbackQuery, field: str) -> None:
    bot, user_id = await get_bot_user_ids(call)
    name = TgConfig.STATE.get(f'{user_id}_catalog_main')
    lang = _get_lang(user_id)
    if not name:
        await call.answer(t(lang, 'catalog_select_category_first'), show_alert=True)
        return
    category = _get_main_category_info(name)
    if not category:
        await call.answer(t(lang, 'catalog_main_not_found'), show_alert=True)
        return
    if field == 'discount':
        set_category_options(name, allow_discounts=not category['allow_discounts'])
    else:
        set_category_options(name, allow_referral_rewards=not category['allow_referral_rewards'])
    admin_info = await bot.get_chat(user_id)
    logger.info(
        "User %s (%s) toggled %s for main category %s",
        user_id,
        admin_info.first_name,
        field,
        name,
    )
    await call.answer(t(lang, 'catalog_status_updated'), show_alert=False)
    await _show_main_category_actions(bot, call.message.chat.id, call.message.message_id, user_id, name)


async def catalog_main_toggle_discount(call: CallbackQuery):
    await catalog_main_apply_toggle(call, 'discount')


async def catalog_main_toggle_referral(call: CallbackQuery):
    await catalog_main_apply_toggle(call, 'referral')


async def catalog_main_rename(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'catalog_main_rename':
        return
    new_name = message.text.strip()
    old_name = TgConfig.STATE.get(f'{user_id}_catalog_main')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    lang = _get_lang(user_id)
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if not new_name:
        await bot.edit_message_text(
            t(lang, 'catalog_name_empty'),
            chat_id=message.chat.id,
            message_id=message_id,
            reply_markup=back('catalog_edit_main'),
        )
        return
    TgConfig.STATE[user_id] = None
    update_category(old_name, new_name)
    TgConfig.STATE[f'{user_id}_catalog_main'] = old_name
    admin_info = await bot.get_chat(user_id)
    logger.info(
        "User %s (%s) renamed main category %s to %s",
        user_id,
        admin_info.first_name,
        old_name,
        new_name,
    )
    await _show_main_category_actions(bot, message.chat.id, message_id, user_id, old_name)





async def catalog_edit_category_start(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_category_update_back'] = 'catalog_editor'
    await call.answer()
    await update_category_callback_handler(call)


async def catalog_edit_item_start(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_item_update_back'] = 'catalog_editor'
    await call.answer()
    await update_item_callback_handler(call)


async def update_item_amount_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    TgConfig.STATE[user_id] = 'update_amount_of_item'
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text('🏷️ Įveskite prekės pavadinimą',
                                    chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    reply_markup=back(_get_item_update_back(user_id)))
        return
    await call.answer('Nepakanka teisių')


async def check_item_name_for_amount_upd(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    item_name = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    item = check_item(item_name)
    if not item:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='❌ Товар не может быть добавлен (Такой позиции не существует)',
                                    reply_markup=back(_get_item_update_back(user_id)))
    else:
        if check_value(item_name) is False:
            TgConfig.STATE[user_id] = 'add_new_amount'
            TgConfig.STATE[f'{user_id}_name'] = message.text
            await bot.edit_message_text(chat_id=message.chat.id,
                                        message_id=message_id,
                                        text='Send folder path with product files or list values separated by ;:',
                                        reply_markup=back(_get_item_update_back(user_id)))
        else:
            await bot.edit_message_text(chat_id=message.chat.id,
                                        message_id=message_id,
                                        text='❌ Товар не может быть добавлен (У данной позиции бесконечный товар)',
                                        reply_markup=back(_get_item_update_back(user_id)))


async def updating_item_amount(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if message.photo:
        file_path = get_next_file_path(TgConfig.STATE.get(f'{user_id}_name'))
        file_name = f"{TgConfig.STATE.get(f'{user_id}_name')}_{int(datetime.datetime.now().timestamp())}.jpg"
        file_path = os.path.join('assets', 'uploads', file_name)
        await message.photo[-1].download(destination_file=file_path)
        values_list = [file_path]
    else:
        if os.path.isdir(message.text):
            folder = message.text
            values_list = [os.path.join(folder, f) for f in os.listdir(folder)]
        else:
            values_list = message.text.split(';')
    TgConfig.STATE[user_id] = None
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    item_name = TgConfig.STATE.get(f'{user_id}_name')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    was_empty = select_item_values_amount(item_name) == 0 and not check_value(item_name)
    for i in values_list:
        add_values_to_item(item_name, i, False)
    if was_empty:
        await notify_restock(bot, item_name)
    group_id = TgConfig.GROUP_ID if TgConfig.GROUP_ID != -988765433 else None
    if group_id:
        try:
            await bot.send_message(
                chat_id=group_id,
                text=f'🎁 Upload\n🏷️ Item: <b>{item_name}</b>',
                parse_mode='HTML'
            )
        except ChatNotFound:
            pass
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text='✅ Товар добавлен',
                                reply_markup=back(_get_item_update_back(user_id)))
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) "
                f'добавил товары к позиции "{item_name}" в количестве {len(values_list)} шт')


async def update_item_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if f'{user_id}_item_update_back' not in TgConfig.STATE:
        TgConfig.STATE[f'{user_id}_item_update_back'] = 'goods_management'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE):
        await call.answer('Nepakanka teisių')
        return
    lang = _get_lang(user_id)
    TgConfig.STATE[user_id] = 'update_item_select'
    TgConfig.STATE[f'{user_id}_update_nav'] = []
    TgConfig.STATE[f'{user_id}_update_current'] = None
    categories = _get_hierarchy_children(None)
    if not categories:
        TgConfig.STATE[user_id] = None
        await bot.edit_message_text(
            t(lang, 'catalog_no_categories_available'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=back(_get_item_update_back(user_id)),
        )
        _clear_update_item_selection_state(user_id)
        return
    await show_update_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def show_update_item_selection(bot, chat_id: int, message_id: int, user_id: int) -> None:
    if TgConfig.STATE.get(user_id) != 'update_item_select':
        return
    lang = _get_lang(user_id)
    current = TgConfig.STATE.get(f'{user_id}_update_current')
    nav = TgConfig.STATE.get(f'{user_id}_update_nav', [])
    categories = _get_hierarchy_children(current)
    items = sorted(get_all_item_names(current)) if current is not None else []
    markup = InlineKeyboardMarkup(row_width=1)
    titles = get_category_titles(categories)
    for name in categories:
        label = titles.get(name, _category_label(name))
        markup.add(InlineKeyboardButton(f'📁 {label}', callback_data=f'updateitem_open_{name}'))
    if current is not None:
        for item in items:
            markup.add(
                InlineKeyboardButton(
                    display_name(item),
                    callback_data=f'updateitem_pick_{item}',
                )
            )
    if not categories and not items:
        markup.add(InlineKeyboardButton(t(lang, 'catalog_update_branch_empty_button'), callback_data='updateitem_empty'))
    if nav:
        markup.add(InlineKeyboardButton(t(lang, 'multi_select_up'), callback_data='updateitem_back'))
    markup.add(InlineKeyboardButton(t(lang, 'action_cancel'), callback_data='updateitem_cancel'))
    if current is None:
        text = t(lang, 'catalog_update_select_root')
    else:
        text = t(lang, 'catalog_update_select_branch', path=_format_assign_path(current))
    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
    )


async def update_item_selection_open(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_item_select':
        return
    target = call.data[len('updateitem_open_'):]
    current = TgConfig.STATE.get(f'{user_id}_update_current')
    lang = _get_lang(user_id)
    valid = set(_get_hierarchy_children(current))
    if target not in valid:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    nav: list[str] = TgConfig.STATE.get(f'{user_id}_update_nav', [])
    if current is not None:
        if len(nav) >= MAX_SELECTION_DEPTH:
            await call.answer(t(lang, 'multi_select_depth_limit'), show_alert=True)
            return
        nav.append(current)
    TgConfig.STATE[f'{user_id}_update_nav'] = nav
    TgConfig.STATE[f'{user_id}_update_current'] = target
    await show_update_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def update_item_selection_back(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_item_select':
        return
    nav: list[str] = TgConfig.STATE.get(f'{user_id}_update_nav', [])
    new_current = nav.pop() if nav else None
    TgConfig.STATE[f'{user_id}_update_nav'] = nav
    TgConfig.STATE[f'{user_id}_update_current'] = new_current
    await show_update_item_selection(bot, call.message.chat.id, call.message.message_id, user_id)


async def update_item_selection_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_item_select':
        return
    _clear_update_item_selection_state(user_id)
    TgConfig.STATE[user_id] = None
    lang = _get_lang(user_id)
    await bot.edit_message_text(
        t(lang, 'catalog_item_update_cancelled'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back(_get_item_update_back(user_id)),
    )


async def update_item_selection_empty(call: CallbackQuery):
    _, user_id = await get_bot_user_ids(call)
    lang = _get_lang(user_id)
    await call.answer(t(lang, 'catalog_update_branch_empty'), show_alert=True)


async def update_item_selection_pick(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_item_select':
        return
    item = call.data[len('updateitem_pick_'):]
    current = TgConfig.STATE.get(f'{user_id}_update_current')
    lang = _get_lang(user_id)
    if current is None:
        await call.answer(t(lang, 'catalog_select_category_first'), show_alert=True)
        return
    valid = set(get_all_item_names(current))
    if item not in valid:
        await call.answer(t(lang, 'multi_select_target_missing'), show_alert=True)
        return
    TgConfig.STATE[f'{user_id}_old_name'] = item
    TgConfig.STATE[f'{user_id}_category'] = current
    TgConfig.STATE[user_id] = 'update_item_name'
    _clear_update_item_selection_state(user_id)
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.edit_message_text(
        t(lang, 'catalog_update_name_prompt', name=display_name(item)),
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=back(_get_item_update_back(user_id)),
    )


async def check_item_name_for_update(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    item_name = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    item = check_item(item_name)
    if not item:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='❌ Item cannot be changed (does not exist)',
                                    reply_markup=back(_get_item_update_back(user_id)))
        return
    TgConfig.STATE[user_id] = 'update_item_name'
    TgConfig.STATE[f'{user_id}_old_name'] = message.text
    TgConfig.STATE[f'{user_id}_category'] = item['category_name']
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text='Введите новое имя для позиции:',
                                reply_markup=back(_get_item_update_back(user_id)))


async def update_item_name(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    TgConfig.STATE[f'{user_id}_name'] = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = 'update_item_description'
    lang = _get_lang(user_id)
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text=t(lang, 'catalog_update_description_prompt', name=message.text),
                                reply_markup=back(_get_item_update_back(user_id)))


async def update_item_description(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    TgConfig.STATE[f'{user_id}_description'] = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = 'update_item_price'
    lang = _get_lang(user_id)
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    name = TgConfig.STATE.get(f'{user_id}_name', '')
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text=t(lang, 'catalog_update_price_prompt', name=name),
                                reply_markup=back(_get_item_update_back(user_id)))


async def update_item_price(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    TgConfig.STATE[user_id] = None
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    lang = _get_lang(user_id)
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    if not message.text.isdigit():
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text=t(lang, 'catalog_invalid_price'),
                                    reply_markup=back(_get_item_update_back(user_id)))
        return
    TgConfig.STATE[f'{user_id}_price'] = message.text
    item_old_name = TgConfig.STATE.get(f'{user_id}_old_name')
    if check_value(item_old_name) is False:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='Do you want to make unlimited goods?',
                                    reply_markup=question_buttons('change_make_infinity', _get_item_update_back(user_id)))
    else:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text='Do you want to disable unlimited goods?',
                                    reply_markup=question_buttons('change_deny_infinity', _get_item_update_back(user_id)))


async def _offer_preview_update(bot, chat_id: int, message_id: int, user_id: int, item_name: str) -> None:
    lang = _get_lang(user_id)
    TgConfig.STATE[user_id] = 'update_item_preview_choice'
    TgConfig.STATE[f'{user_id}_preview_item'] = item_name
    TgConfig.STATE[f'{user_id}_message_id'] = message_id
    text = t(lang, 'catalog_update_preview_prompt', name=display_name(item_name))
    markup = question_buttons('update_preview', _get_item_update_back(user_id))
    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=markup,
        parse_mode='HTML',
    )


async def _finalize_item_update(
    bot,
    chat_id: int,
    message_id: int,
    user_id: int,
    old_name: str,
    new_name: str,
    description: str,
    price: str,
    category: str,
) -> None:
    lang = _get_lang(user_id)
    item_data = check_item(old_name)
    delivery_desc = item_data.get('delivery_description') if item_data else None
    update_item(old_name, new_name, description, price, category, delivery_desc)
    if old_name != new_name:
        old_folder = os.path.join('assets', 'product_photos', old_name)
        new_folder = os.path.join('assets', 'product_photos', new_name)
        if os.path.isdir(old_folder):
            try:
                if os.path.isdir(new_folder):
                    shutil.rmtree(new_folder)
                shutil.move(old_folder, new_folder)
            except Exception as exc:
                logger.error('Failed to move preview folder %s → %s: %s', old_folder, new_folder, exc)
    admin_info = await bot.get_chat(user_id)
    logger.info(
        "User %s (%s) updated item \"%s\" → \"%s\"",
        user_id,
        admin_info.first_name,
        old_name,
        new_name,
    )
    await _offer_preview_update(bot, chat_id, message_id, user_id, new_name)


async def update_item_preview_yes(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_item_preview_choice':
        return
    item_name = TgConfig.STATE.get(f'{user_id}_preview_item')
    if not item_name:
        TgConfig.STATE[user_id] = None
        return
    lang = _get_lang(user_id)
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    TgConfig.STATE[user_id] = 'update_item_preview_wait'
    text = t(lang, 'catalog_update_preview_send', name=display_name(item_name))
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=back(_get_item_update_back(user_id)),
        parse_mode='HTML',
    )
    await call.answer()


async def update_item_preview_no(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'update_item_preview_choice':
        return
    lang = _get_lang(user_id)
    message_id = TgConfig.STATE.get(f'{user_id}_message_id', call.message.message_id)
    back_target = _get_item_update_back(user_id)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_preview_item', None)
    TgConfig.STATE.pop(f'{user_id}_item_update_back', None)
    TgConfig.STATE.pop(f'{user_id}_message_id', None)
    await bot.edit_message_text(
        t(lang, 'catalog_item_update_complete'),
        chat_id=call.message.chat.id,
        message_id=message_id,
        reply_markup=back(back_target),
    )
    await call.answer()


async def update_item_preview_photo(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'update_item_preview_wait':
        return
    item_name = TgConfig.STATE.get(f'{user_id}_preview_item')
    lang = _get_lang(user_id)
    if not message.photo or not item_name:
        await bot.send_message(user_id, t(lang, 'catalog_update_preview_invalid'))
        return
    folder = os.path.join('assets', 'product_photos', item_name)
    os.makedirs(folder, exist_ok=True)
    for ext in ('jpg', 'jpeg', 'png', 'webp', 'mp4'):
        candidate = os.path.join(folder, f'preview.{ext}')
        if os.path.isfile(candidate):
            os.remove(candidate)
    destination = os.path.join(folder, 'preview.jpg')
    await message.photo[-1].download(destination_file=destination)
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    back_target = _get_item_update_back(user_id)
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_preview_item', None)
    TgConfig.STATE.pop(f'{user_id}_item_update_back', None)
    TgConfig.STATE.pop(f'{user_id}_message_id', None)
    response = t(lang, 'catalog_update_preview_saved')
    markup = back(back_target)
    if message_id:
        try:
            await bot.edit_message_text(response, chat_id=message.chat.id, message_id=message_id, reply_markup=markup)
        except Exception:
            await bot.send_message(message.chat.id, response, reply_markup=markup)
    else:
        await bot.send_message(message.chat.id, response, reply_markup=markup)
    admin_info = await bot.get_chat(user_id)
    logger.info(
        "User %s (%s) updated preview for \"%s\"",
        user_id,
        admin_info.first_name,
        item_name,
    )


async def update_item_process(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    answer = call.data.split('_')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    item_old_name = TgConfig.STATE.get(f'{user_id}_old_name')
    item_new_name = TgConfig.STATE.get(f'{user_id}_name')
    item_description = TgConfig.STATE.get(f'{user_id}_description')
    category = TgConfig.STATE.get(f'{user_id}_category')
    price = TgConfig.STATE.get(f'{user_id}_price')
    if answer[3] == 'no':
        TgConfig.STATE[user_id] = None
        await _finalize_item_update(
            bot,
            call.message.chat.id,
            message_id,
            user_id,
            item_old_name,
            item_new_name,
            item_description,
            price,
            category,
        )
    else:
        if answer[1] == 'make':
            await bot.edit_message_text(chat_id=call.message.chat.id,
                                        message_id=message_id,
                                        text='Enter item value:',
                                        reply_markup=back(_get_item_update_back(user_id)))
            TgConfig.STATE[f'{user_id}_change'] = 'make'
        elif answer[1] == 'deny':
            await bot.edit_message_text(chat_id=call.message.chat.id,
                                        message_id=message_id,
                                        text='Send folder path with product files or list values separated by ;:',
                                        reply_markup=back(_get_item_update_back(user_id)))
            TgConfig.STATE[f'{user_id}_change'] = 'deny'
    TgConfig.STATE[user_id] = 'apply_change'


async def update_item_infinity(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if message.photo:
        file_path = get_next_file_path(TgConfig.STATE.get(f'{user_id}_old_name'))
        file_name = f"{TgConfig.STATE.get(f'{user_id}_old_name')}_{int(datetime.datetime.now().timestamp())}.jpg"
        file_path = os.path.join('assets', 'uploads', file_name)
        await message.photo[-1].download(destination_file=file_path)
        msg = file_path
    else:
        msg = message.text
    change = TgConfig.STATE[f'{user_id}_change']
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    item_old_name = TgConfig.STATE.get(f'{user_id}_old_name')
    item_new_name = TgConfig.STATE.get(f'{user_id}_name')
    item_description = TgConfig.STATE.get(f'{user_id}_description')
    category = TgConfig.STATE.get(f'{user_id}_category')
    price = TgConfig.STATE.get(f'{user_id}_price')
    await bot.delete_message(chat_id=message.chat.id,
                             message_id=message.message_id)
    was_empty = select_item_values_amount(item_old_name) == 0 and not check_value(item_old_name)
    if change == 'make':
        delete_only_items(item_old_name)
        add_values_to_item(item_old_name, msg, False)
        if was_empty:
            await notify_restock(bot, item_old_name)
    elif change == 'deny':
        delete_only_items(item_old_name)
        if os.path.isdir(msg):
            values_list = [os.path.join(msg, f) for f in os.listdir(msg)]
        else:
            values_list = msg.split(';')
        for i in values_list:
            add_values_to_item(item_old_name, i, False)
        if was_empty:
            await notify_restock(bot, item_old_name)
    TgConfig.STATE[user_id] = None
    await _finalize_item_update(
        bot,
        message.chat.id,
        message_id,
        user_id,
        item_old_name,
        item_new_name,
        item_description,
        price,
        category,
    )


async def delete_item_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if not (role & Permission.SHOP_MANAGE):
        await call.answer('Nepakanka teisių')
        return
    categories = get_all_category_names()
    markup = InlineKeyboardMarkup()
    for cat in categories:
        markup.add(InlineKeyboardButton(cat, callback_data=f'delete_item_cat_{cat}'))
    markup.add(InlineKeyboardButton('🔙 Back', callback_data='goods_management'))
    await bot.edit_message_text('Choose category:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def delete_item_category_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    category = call.data[len('delete_item_cat_'):]
    subcats = get_all_subcategories(category)
    items = get_all_item_names(category)
    markup = InlineKeyboardMarkup()
    for sub in subcats:
        markup.add(InlineKeyboardButton(sub, callback_data=f'delete_item_cat_{sub}'))
    for item in items:
        markup.add(InlineKeyboardButton(display_name(item), callback_data=f'delete_item_item_{item}'))
    back_parent = get_category_parent(category)
    back_data = 'delete_item' if back_parent is None else f'delete_item_cat_{back_parent}'
    markup.add(InlineKeyboardButton('🔙 Back', callback_data=back_data))
    await bot.edit_message_text('Choose subcategory or item to delete:',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def delete_item_item_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    item_name = call.data[len('delete_item_item_'):]
    delete_item(item_name)
    await bot.edit_message_text('✅ Item deleted',
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=back(_get_item_update_back(user_id)))
    admin_info = await bot.get_chat(user_id)
    logger.info(f"User {user_id} ({admin_info.first_name}) удалил позицию \"{item_name}\"")


async def show_bought_item_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'show_item'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    role = check_role(user_id)
    if role & Permission.SHOP_MANAGE:
        await bot.edit_message_text(
            '🔍 Enter the unique ID of the purchased item',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=back(_get_item_update_back(user_id)))
        return
    await call.answer('Nepakanka teisių')


async def process_item_show(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    msg = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = None
    item = select_bought_item(msg)
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if item:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text=f'<b>Item</b>: <code>{item["item_name"]}</code>\n'
                 f'<b>Price</b>: <code>{item["price"]}</code>€\n'
                 f'<b>Purchase date</b>: <code>{item["bought_datetime"]}</code>\n'
                 f'<b>Buyer</b>: <code>{item["buyer_id"]}</code>\n'
                 f'<b>Unique operation ID</b>: <code>{item["unique_id"]}</code>\n'
                 f'<b>Value</b>:\n<code>{item["value"]}</code>',
            parse_mode='HTML',
            reply_markup=back('show_bought_item')
        )
        return
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=message_id,
        text='❌ Item with the specified unique ID was not found',
        reply_markup=back('show_bought_item')
    )



def register_shop_management(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(statistics_callback_handler,
                                       lambda c: c.data == 'statistics')
    dp.register_callback_query_handler(goods_settings_menu_callback_handler,
                                       lambda c: c.data == 'item-management')
    dp.register_callback_query_handler(add_item_callback_handler,
                                       lambda c: c.data == 'add_item')
    dp.register_callback_query_handler(update_item_amount_callback_handler,
                                       lambda c: c.data == 'update_item_amount')
    dp.register_callback_query_handler(update_item_callback_handler,
                                       lambda c: c.data == 'update_item')
    dp.register_callback_query_handler(update_item_selection_open,
                                       lambda c: c.data.startswith('updateitem_open_'))
    dp.register_callback_query_handler(update_item_selection_back,
                                       lambda c: c.data == 'updateitem_back')
    dp.register_callback_query_handler(update_item_selection_cancel,
                                       lambda c: c.data == 'updateitem_cancel')
    dp.register_callback_query_handler(update_item_selection_pick,
                                       lambda c: c.data.startswith('updateitem_pick_'))
    dp.register_callback_query_handler(update_item_selection_empty,
                                       lambda c: c.data == 'updateitem_empty')
    dp.register_callback_query_handler(update_item_preview_yes,
                                       lambda c: c.data == 'update_preview_yes')
    dp.register_callback_query_handler(update_item_preview_no,
                                       lambda c: c.data == 'update_preview_no')
    dp.register_callback_query_handler(update_category_selection_open,
                                       lambda c: c.data.startswith('updatecat_open_'))
    dp.register_callback_query_handler(update_category_selection_back,
                                       lambda c: c.data == 'updatecat_back')
    dp.register_callback_query_handler(update_category_selection_cancel,
                                       lambda c: c.data == 'updatecat_cancel')
    dp.register_callback_query_handler(update_category_selection_pick,
                                       lambda c: c.data.startswith('updatecat_pick_'))
    dp.register_callback_query_handler(update_category_selection_empty,
                                       lambda c: c.data == 'updatecat_empty')
    dp.register_callback_query_handler(update_category_selection_resume,
                                       lambda c: c.data == 'update_category_select')
    dp.register_callback_query_handler(delete_item_callback_handler,
                                       lambda c: c.data == 'delete_item')
    dp.register_callback_query_handler(delete_item_category_handler,
                                       lambda c: c.data.startswith('delete_item_cat_'))
    dp.register_callback_query_handler(delete_item_item_handler,
                                       lambda c: c.data.startswith('delete_item_item_'))
    dp.register_callback_query_handler(show_bought_item_callback_handler,
                                       lambda c: c.data == 'show_bought_item')
    dp.register_callback_query_handler(assign_photos_callback_handler,
                                       lambda c: c.data == 'assign_photos')
    dp.register_callback_query_handler(assign_photo_main_handler,
                                       lambda c: c.data.startswith('assign_photo_main_'))
    dp.register_callback_query_handler(assign_photo_category_handler,
                                       lambda c: c.data.startswith('assign_photo_cat_'))
    dp.register_callback_query_handler(assign_photo_subcategory_handler,
                                       lambda c: c.data.startswith('assign_photo_sub_'))
    dp.register_callback_query_handler(assign_photo_empty_handler,
                                       lambda c: c.data == 'assign_photo_empty')
    dp.register_callback_query_handler(assign_photo_item_handler,
                                       lambda c: c.data.startswith('assign_photo_item_'))
    dp.register_callback_query_handler(assign_photo_done_handler,
                                       lambda c: c.data == 'assign_photo_done')
    dp.register_callback_query_handler(assign_photo_cancel_handler,
                                       lambda c: c.data == 'assign_photo_cancel')
    dp.register_callback_query_handler(photo_info_callback_handler,
                                       lambda c: c.data.startswith('photo_info_'))
    dp.register_callback_query_handler(shop_callback_handler,
                                       lambda c: c.data == 'shop_management')
    dp.register_callback_query_handler(logs_callback_handler,
                                       lambda c: c.data == 'show_logs')
    dp.register_callback_query_handler(goods_management_callback_handler,
                                       lambda c: c.data == 'goods_management')
    dp.register_callback_query_handler(promo_management_callback_handler,
                                       lambda c: c.data == 'promo_management')
    dp.register_callback_query_handler(categories_callback_handler,
                                       lambda c: c.data == 'categories_management')
    dp.register_callback_query_handler(add_main_category_callback_handler,
                                       lambda c: c.data == 'add_main_category')
    dp.register_callback_query_handler(add_category_callback_handler,
                                       lambda c: c.data == 'add_category')
    dp.register_callback_query_handler(add_subcategory_callback_handler,
                                       lambda c: c.data == 'add_subcategory')
    dp.register_callback_query_handler(catalog_editor_callback_handler,
                                       lambda c: c.data == 'catalog_editor')
    dp.register_callback_query_handler(catalog_edit_main_start,
                                       lambda c: c.data == 'catalog_edit_main')
    dp.register_callback_query_handler(catalog_edit_main_select,
                                       lambda c: c.data.startswith('catalog_main_select_'))
    dp.register_callback_query_handler(catalog_main_rename_prompt,
                                       lambda c: c.data == 'catalog_main_rename')
    dp.register_callback_query_handler(catalog_main_toggle_discount,
                                       lambda c: c.data == 'catalog_main_toggle_discount')
    dp.register_callback_query_handler(catalog_main_toggle_referral,
                                       lambda c: c.data == 'catalog_main_toggle_referral')
    dp.register_callback_query_handler(catalog_edit_category_start,
                                       lambda c: c.data == 'catalog_edit_category')
    dp.register_callback_query_handler(catalog_edit_item_start,
                                       lambda c: c.data == 'catalog_edit_item')
    dp.register_callback_query_handler(category_parent_toggle,
                                       lambda c: c.data.startswith('catparent_toggle_'))
    dp.register_callback_query_handler(category_parent_clear,
                                       lambda c: c.data == 'catparent_clear')
    dp.register_callback_query_handler(category_parent_cancel,
                                       lambda c: c.data == 'catparent_cancel')
    dp.register_callback_query_handler(category_parent_done,
                                       lambda c: c.data == 'catparent_done')
    dp.register_callback_query_handler(subcategory_parent_empty,
                                       lambda c: c.data == 'subparent_empty')
    dp.register_callback_query_handler(subcategory_parent_toggle,
                                       lambda c: c.data.startswith('subparent_toggle_'))
    dp.register_callback_query_handler(subcategory_parent_open,
                                       lambda c: c.data.startswith('subparent_open_'))
    dp.register_callback_query_handler(subcategory_parent_back,
                                       lambda c: c.data == 'subparent_back')
    dp.register_callback_query_handler(subcategory_parent_clear,
                                       lambda c: c.data == 'subparent_clear')
    dp.register_callback_query_handler(subcategory_parent_cancel,
                                       lambda c: c.data == 'subparent_cancel')
    dp.register_callback_query_handler(subcategory_parent_done,
                                       lambda c: c.data == 'subparent_done')
    dp.register_callback_query_handler(item_destination_empty,
                                       lambda c: c.data == 'itemdest_empty')
    dp.register_callback_query_handler(item_destination_toggle,
                                       lambda c: c.data.startswith('itemdest_toggle_'))
    dp.register_callback_query_handler(item_destination_open,
                                       lambda c: c.data.startswith('itemdest_open_'))
    dp.register_callback_query_handler(item_destination_back,
                                       lambda c: c.data == 'itemdest_back')
    dp.register_callback_query_handler(item_destination_clear,
                                       lambda c: c.data == 'itemdest_clear')
    dp.register_callback_query_handler(item_destination_cancel,
                                       lambda c: c.data == 'itemdest_cancel')
    dp.register_callback_query_handler(item_destination_done,
                                       lambda c: c.data == 'itemdest_done')
    dp.register_callback_query_handler(item_destination_names_cancel,
                                       lambda c: c.data == 'itemdest_names_cancel')
    dp.register_callback_query_handler(item_destination_name_default,
                                       lambda c: c.data == 'itemdest_name_default')
    dp.register_callback_query_handler(add_item_desc_yes,
                                       lambda c: c.data == 'add_item_desc_yes')
    dp.register_callback_query_handler(add_item_desc_no,
                                       lambda c: c.data == 'add_item_desc_no')
    dp.register_callback_query_handler(delete_category_callback_handler,
                                       lambda c: c.data == 'delete_category')
    dp.register_callback_query_handler(delete_category_confirm_handler,
                                       lambda c: c.data.startswith('delete_cat_confirm_'))
    dp.register_callback_query_handler(delete_category_choose_handler,
                                       lambda c: c.data.startswith('delete_cat_') and not c.data.startswith('delete_cat_confirm_'))
    dp.register_callback_query_handler(update_category_callback_handler,
                                       lambda c: c.data == 'update_category')
    dp.register_callback_query_handler(create_promo_callback_handler,
                                       lambda c: c.data == 'create_promo')
    dp.register_callback_query_handler(delete_promo_callback_handler,
                                       lambda c: c.data == 'delete_promo')
    dp.register_callback_query_handler(manage_promo_callback_handler,
                                       lambda c: c.data == 'manage_promo')
    dp.register_callback_query_handler(promo_code_delete_callback_handler,
                                       lambda c: c.data.startswith('delete_promo_code_'))
    dp.register_callback_query_handler(promo_manage_select_handler,
                                       lambda c: c.data.startswith('manage_promo_code_'))
    dp.register_callback_query_handler(promo_manage_discount_handler,
                                       lambda c: c.data.startswith('promo_manage_discount_'))
    dp.register_callback_query_handler(promo_manage_expiry_handler,
                                       lambda c: c.data.startswith('promo_manage_expiry_'))
    dp.register_callback_query_handler(promo_manage_items_handler,
                                       lambda c: c.data.startswith('promo_manage_items_'))
    dp.register_callback_query_handler(promo_manage_delete_handler,
                                       lambda c: c.data.startswith('promo_manage_delete_'))
    dp.register_callback_query_handler(promo_create_expiry_type_handler,
                                       lambda c: c.data.startswith('promo_expiry_') and TgConfig.STATE.get(c.from_user.id) == 'promo_create_expiry_type')
    dp.register_callback_query_handler(promo_manage_expiry_type_handler,
                                       lambda c: c.data.startswith('promo_expiry_') and TgConfig.STATE.get(c.from_user.id) == 'promo_manage_expiry_type')
    dp.register_callback_query_handler(promo_item_open,
                                       lambda c: c.data.startswith('promoitem_open_'))
    dp.register_callback_query_handler(promo_item_toggle,
                                       lambda c: c.data.startswith('promoitem_toggle_'))
    dp.register_callback_query_handler(promo_item_back,
                                       lambda c: c.data == 'promoitem_back')
    dp.register_callback_query_handler(promo_item_clear,
                                       lambda c: c.data == 'promoitem_clear')
    dp.register_callback_query_handler(promo_item_done,
                                       lambda c: c.data == 'promoitem_done')
    dp.register_callback_query_handler(promo_item_cancel,
                                       lambda c: c.data == 'promoitem_cancel')

    dp.register_callback_query_handler(main_category_discount_decision,
                                       lambda c: c.data.startswith('maincat_discount_') and TgConfig.STATE.get(c.from_user.id) == 'add_main_category_discount')

    dp.register_callback_query_handler(main_category_referral_decision,
                                       lambda c: c.data.startswith('maincat_referral_') and TgConfig.STATE.get(c.from_user.id) == 'add_main_category_referral')

    dp.register_callback_query_handler(add_preview_yes,
                                       lambda c: c.data == 'add_preview_yes' and TgConfig.STATE.get(c.from_user.id) == 'create_item_preview')
    dp.register_callback_query_handler(add_preview_no,
                                       lambda c: c.data == 'add_preview_no' and TgConfig.STATE.get(c.from_user.id) == 'create_item_preview')

    dp.register_message_handler(check_item_name_for_amount_upd,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'update_amount_of_item')
    dp.register_message_handler(updating_item_amount,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'add_new_amount')
    dp.register_message_handler(check_item_name_for_add,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'create_item_name')
    dp.register_message_handler(add_item_description,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'create_item_description')
    dp.register_message_handler(add_item_price,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'create_item_price')
    dp.register_message_handler(add_item_preview_photo,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'create_item_photo',
                                content_types=['photo', 'text'])
    dp.register_message_handler(assign_photo_receive_media,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'assign_photo_collect_media',
                                content_types=['photo', 'video'])
    dp.register_message_handler(assign_photo_receive_desc,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'assign_photo_wait_desc',
                                content_types=['text'])
    dp.register_message_handler(check_item_name_for_update,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'check_item_name')
    dp.register_message_handler(update_item_name,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'update_item_name')
    dp.register_message_handler(update_item_description,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'update_item_description')
    dp.register_message_handler(update_item_price,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'update_item_price')
    dp.register_message_handler(update_item_preview_photo,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'update_item_preview_wait',
                                content_types=['photo'])
    dp.register_message_handler(process_item_show,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'show_item')
    dp.register_message_handler(process_main_category_for_add,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'add_main_category')
    dp.register_message_handler(catalog_main_rename,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'catalog_main_rename')
    dp.register_message_handler(process_category_name,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'add_category_name')
    dp.register_message_handler(process_subcategory_name,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'add_subcategory_name')
    dp.register_message_handler(process_item_destination_name,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'create_item_destination_names')
    dp.register_message_handler(check_category_name_for_update,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'update_category_name')
    dp.register_message_handler(update_item_infinity,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'apply_change')
    dp.register_message_handler(promo_code_receive_code,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'promo_create_code')
    dp.register_message_handler(promo_code_receive_discount,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'promo_create_discount')
    dp.register_message_handler(promo_code_receive_expiry_number,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'promo_create_expiry_number')
    dp.register_message_handler(promo_manage_receive_discount,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'promo_manage_discount')
    dp.register_message_handler(promo_manage_receive_expiry_number,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'promo_manage_expiry_number')

    dp.register_callback_query_handler(update_item_process,
                                       lambda c: c.data.startswith('change_'))
