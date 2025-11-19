import os
from aiogram import Dispatcher
from aiogram.types import CallbackQuery

from aiogram.types import InputFile, InputMediaPhoto, InputMediaVideo

from bot.database.methods import (
    get_purchase_dates,
    get_purchases_by_date,
    select_bought_item,
    check_user,
    get_item_info,
    get_category_parent,
)
from bot.handlers.other import get_bot_user_ids
from bot.keyboards import (
    purchases_dates_list,
    purchases_list,
    purchase_info_menu,
)
from bot.misc import TgConfig
from bot.utils.media import load_media_bundle


async def pirkimai_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    dates = get_purchase_dates()
    await bot.edit_message_text(
        '📅 Pasirinkite datą',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=purchases_dates_list(dates),
    )


async def purchases_date_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    date = call.data[len('purchases_date_'):]
    purchases = get_purchases_by_date(date)
    await bot.edit_message_text(
        f'📦 Pirkimai {date}',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=purchases_list(purchases, date),
    )


async def purchase_info_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    _, purchase_id, date = call.data.split('_', 2)
    purchase_id_int = int(purchase_id)
    purchase = select_bought_item(purchase_id_int)
    if not purchase:
        await call.answer('Not found', show_alert=True)
        return
    buyer = check_user(purchase['buyer_id'])
    username = f'@{buyer.username}' if buyer and buyer.username else str(purchase['buyer_id'])
    item_info = get_item_info(purchase['item_name'])
    parent_cat = get_category_parent(item_info['category_name'])
    path_guess = purchase['value']
    attachments, desc = load_media_bundle(path_guess)
    sold_path = attachments[0] if attachments else os.path.join(os.path.dirname(path_guess), 'Sold', os.path.basename(path_guess))
    text = (
        f"User {username}\n"
        f"Time: {purchase['bought_datetime']} GMT+3\n"
        f"Product: {purchase['item_name']} ({purchase['price']}€)\n"
        f"Crypto: N/A\n"
        f"Category: {parent_cat or '-'} / {item_info['category_name']}\n"
        f"Description: {desc or '-'}\n"
        f"File: {sold_path}"
    )
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=purchase_info_menu(purchase_id_int, date),
    )


async def view_purchase_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    purchase_id = call.data[len('view_purchase_'):]
    purchase = select_bought_item(int(purchase_id))
    if not purchase:
        await call.answer('Not found', show_alert=True)
        return
    path = purchase['value']
    attachments, desc = load_media_bundle(path)
    if attachments:
        if len(attachments) == 1:
            media_path = attachments[0]
            with open(media_path, 'rb') as media:
                if media_path.endswith('.mp4'):
                    await bot.send_video(user_id, media, caption=desc or None)
                else:
                    await bot.send_photo(user_id, media, caption=desc or None)
        else:
            media_group = []
            for idx, media_path in enumerate(attachments):
                media_kwargs = {
                    'media': InputFile(media_path),
                    'caption': desc if idx == 0 and desc else None,
                }
                if media_path.endswith('.mp4'):
                    media_group.append(InputMediaVideo(**media_kwargs))
                else:
                    media_group.append(InputMediaPhoto(**media_kwargs))
            await bot.send_media_group(user_id, media_group)
    else:
        await bot.send_message(user_id, purchase['value'])
    await call.answer()


def register_purchases(dp: Dispatcher) -> None:
    dp.register_callback_query_handler(pirkimai_callback_handler, lambda c: c.data == 'pirkimai', state='*')
    dp.register_callback_query_handler(purchases_date_callback_handler, lambda c: c.data.startswith('purchases_date_'), state='*')
    dp.register_callback_query_handler(purchase_info_callback_handler, lambda c: c.data.startswith('purchase_'), state='*')
    dp.register_callback_query_handler(view_purchase_handler, lambda c: c.data.startswith('view_purchase_'), state='*')
