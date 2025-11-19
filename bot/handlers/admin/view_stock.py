import os
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, InputFile, InputMediaPhoto, InputMediaVideo

from bot.database.methods import (
    check_role,
    get_all_category_names,
    get_all_subcategories,
    get_all_item_names,
    get_category_parent,
    get_item_values,
    get_item_value_by_id,
    buy_item,
    select_item_values_amount,
    get_item_info,
)
from bot.database.models import Permission
from bot.handlers.other import get_bot_user_ids
from bot.keyboards import (
    stock_categories_list,
    stock_goods_list,
    stock_values_list,
    stock_value_actions,
)
from bot.misc import TgConfig
from bot.utils import display_name
from bot.utils.files import cleanup_item_file
from bot.utils.media import load_media_bundle


async def view_stock_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    role = check_role(user_id)
    if role & Permission.OWN:
        root_cb = 'information' if call.data == 'view_stock' else 'shop_management'
        TgConfig.STATE[f'{user_id}_stock_root'] = root_cb
        categories = get_all_category_names()
        lines = ['📋 Atsargų sąrašas']
        for category in categories:
            lines.append(f"\n<b>{category}</b>")
            for sub in get_all_subcategories(category):
                lines.append(f"  {sub}")
                for item in get_all_item_names(sub):
                    info = get_item_info(item)
                    count = select_item_values_amount(item)
                    lines.append(f"    • {display_name(item)} ({info['price']:.2f}€, {count})")
            for item in get_all_item_names(category):
                info = get_item_info(item)
                count = select_item_values_amount(item)
                lines.append(f"  • {display_name(item)} ({info['price']:.2f}€, {count})")
        text = '\n'.join(lines)
        await bot.send_message(call.message.chat.id, text, parse_mode='HTML')
        await bot.edit_message_text(
            '📦 Pasirinkite kategoriją',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=stock_categories_list(categories, None, root_cb),
        )
        return
    await call.answer('Nepakanka teisių')


async def view_stock_category_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not role & Permission.OWN:
        await call.answer('Nepakanka teisių')
        return
    category = call.data.split(':', 1)[1]
    subs = get_all_subcategories(category)
    if subs:
        parent = get_category_parent(category)
        root_cb = TgConfig.STATE.get(f'{user_id}_stock_root', 'console')
        await bot.edit_message_text(
            '📂 Pasirinkite kategoriją',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=stock_categories_list(subs, parent, root_cb),
        )
        return
    items = get_all_item_names(category)
    if items:
        root_cb = TgConfig.STATE.get(f'{user_id}_stock_root', 'console')
        await bot.edit_message_text(
            '🏷 Pasirinkite prekę',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=stock_goods_list(items, category, root_cb),
        )
        return
    await call.answer('Nėra prekių')


async def view_stock_item_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not role & Permission.OWN:
        await call.answer('Nepakanka teisių')
        return
    _, item_name, category = call.data.split(':', 2)
    values = get_item_values(item_name)
    if values:
        await bot.edit_message_text(
            f'📦 {display_name(item_name)} atsargos',
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=stock_values_list(values, item_name, category),
        )
        return
    await call.answer('Nėra atsargų')


async def view_stock_value_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not role & Permission.OWN:
        await call.answer('Nepakanka teisių')
        return
    _, value_id, item_name, category = call.data.split(':', 3)
    value_id = int(value_id)
    value = get_item_value_by_id(value_id)
    if not value:
        await call.answer('Nerasta')
        return
    attachments, desc = load_media_bundle(value['value'])
    if attachments:
        if len(attachments) == 1:
            path = attachments[0]
            with open(path, 'rb') as doc:
                if path.lower().endswith('.mp4'):
                    await bot.send_video(user_id, doc, caption=desc or None)
                else:
                    await bot.send_photo(user_id, doc, caption=desc or None)
        else:
            media_group = []
            for idx, path in enumerate(attachments):
                media_kwargs = {
                    'media': InputFile(path),
                    'caption': desc if idx == 0 and desc else None,
                }
                if path.lower().endswith('.mp4'):
                    media_group.append(InputMediaVideo(**media_kwargs))
                else:
                    media_group.append(InputMediaPhoto(**media_kwargs))
            await bot.send_media_group(user_id, media_group)
    else:
        await bot.send_message(user_id, value['value'])
    await bot.edit_message_text(
        f'ID {value_id}',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=stock_value_actions(value_id, item_name, category),
    )


async def view_stock_delete_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    role = check_role(user_id)
    if not role & Permission.OWN:
        await call.answer('Nepakanka teisių')
        return
    _, value_id, item_name, category = call.data.split(':', 3)
    value_id = int(value_id)
    value = get_item_value_by_id(value_id)
    if value and value['value']:
        attachments, _ = load_media_bundle(value['value'])
        if attachments:
            for path in attachments:
                cleanup_item_file(path)
        meta_path = f"{value['value']}.meta.json"
        if os.path.isfile(meta_path):
            os.remove(meta_path)
        elif os.path.isfile(value['value']):
            os.remove(value['value'])
    buy_item(value_id)
    values = get_item_values(item_name)
    await bot.edit_message_text(
        '✅ Atsargos ištrintos',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=stock_values_list(values, item_name, category),
    )


def register_view_stock(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(
        view_stock_callback_handler, lambda c: c.data in ('view_stock', 'manage_stock')
    )
    dp.register_callback_query_handler(
        view_stock_category_handler,
        lambda c: c.data.startswith('stock_cat:'),
        state='*',
    )
    dp.register_callback_query_handler(
        view_stock_item_handler,
        lambda c: c.data.startswith('stock_item:'),
        state='*',
    )
    dp.register_callback_query_handler(
        view_stock_value_handler,
        lambda c: c.data.startswith('stock_val:'),
        state='*',
    )
    dp.register_callback_query_handler(
        view_stock_delete_handler,
        lambda c: c.data.startswith('stock_del:'),
        state='*',
    )
