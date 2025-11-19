import asyncio
import datetime
import os
import random
import shutil
import time
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from urllib.parse import urlparse
import html
import base64

import qrcode

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import contextlib


from aiogram import Dispatcher
from aiogram.types import (
    Message,
    CallbackQuery,
    ChatType,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)
from aiogram.utils.exceptions import (
    MessageNotModified,
    MessageCantBeEdited,
    MessageCantBeDeleted,
    MessageToDeleteNotFound,
    MessageToEditNotFound,
)

from bot.database.methods import (
    get_role_id_by_name, create_user, check_role, check_user,
    get_all_categories, get_all_items, select_bought_items, get_bought_item_info, get_item_info,
    select_item_values_amount, get_user_balance, get_item_value, buy_item, add_bought_item, buy_item_for_balance,
    select_user_operations, select_user_items, start_operation,
    select_unfinished_operations, get_user_referral, finish_operation, update_balance, create_operation,
    bought_items_list, check_value, get_subcategories, get_category_parent, get_user_language, update_user_language,
    get_unfinished_operation, get_user_unfinished_operation, get_promocode, add_values_to_item, get_user_tickets, update_lottery_tickets,
    can_use_discount, can_get_referral_reward,
    get_category_title, get_category_titles,
    has_user_achievement, get_achievement_users, grant_achievement, get_user_count,
    get_out_of_stock_categories, get_out_of_stock_subcategories, get_out_of_stock_items,
    has_stock_notification, add_stock_notification, check_user_by_username, check_user_referrals,
    sum_referral_operations, add_item_to_cart, get_cart_items_with_prices,
    remove_cart_item, clear_cart,
    is_category_locked, get_user_category_password, get_generated_password,
)
from bot.database.methods.update import (
    process_purchase_streak,
    set_cart_quantity,
    upsert_user_category_password,
    mark_generated_password_used,
    set_user_category_password_ack,
    set_role,
)
from bot.handlers.other import get_bot_user_ids, get_bot_info
from bot.keyboards import (
    main_menu, categories_list, goods_list, subcategories_list, user_items_list, back, item_info,
    profile, rules, payment_menu, close, crypto_choice, crypto_invoice_menu, blackjack_controls,
    blackjack_bet_input_menu, blackjack_end_menu, blackjack_history_menu, feedback_menu,
    confirm_purchase_menu, games_menu,
    achievements_menu,
    crypto_choice_purchase, notify_categories_list, notify_subcategories_list, notify_goods_list,
    cart_overview_keyboard, empty_cart_keyboard, cart_manage_keyboard, cart_payment_choice,
    category_password_options, category_password_continue_keyboard,
)

from bot.localization import t
from bot.logger_mesh import logger
from bot.misc import TgConfig, EnvKeys
from bot.misc.payment import quick_pay, check_payment_status
from bot.misc.nowpayments import create_payment, check_payment
from bot.utils import display_name
from bot.utils.stock_notify import notify_restock
from bot.utils.media import load_media_bundle, move_media_to_sold
from bot.utils.reservations import add_reservation, remove_reservation, reservation_eta_minutes
from bot.utils.notifications import notify_owner_of_purchase
from bot.utils.level import get_level_info
from bot.utils.files import cleanup_item_file


def _reservation_or_stock_notice(item_name: str, lang: str) -> str:
    eta = reservation_eta_minutes(item_name)
    if eta:
        return t(lang, 'item_reserved_notice', minutes=eta)
    return '❌ Item out of stock'


def build_menu_text(user_obj, balance: float, purchases: int, streak: int, lang: str) -> str:
    """Return main menu text with loyalty status and streak."""
    mention = f"<a href='tg://user?id={user_obj.id}'>{html.escape(user_obj.full_name)}</a>"
    level_name, _, _ = get_level_info(purchases, lang)
    status = f"👤 Status: {level_name}"
    streak_line = t(lang, 'streak', days=streak)
    return (
        f"{t(lang, 'hello', user=mention)}\n"
        f"{t(lang, 'balance', balance=f'{balance:.2f}')}\n"
        f"{t(lang, 'total_purchases', count=purchases)}\n"
        f"{status}\n"
        f"{streak_line}\n\n"
        f"{t(lang, 'note')}"
    )


async def _send_media_bundle(bot, chat_id: int, attachments: list[str], caption: str, parse_mode: str = 'HTML'):
    if not attachments:
        await bot.send_message(chat_id, caption, parse_mode=parse_mode)
        return

    def _media_type(path: str) -> str:
        lowered = path.lower()
        if lowered.endswith(('.mp4', '.mov', '.mkv', '.avi')):
            return 'video'
        if lowered.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            return 'photo'
        return 'document'

    async def _send_single(path: str, caption_here: str | None) -> None:
        if not os.path.isfile(path):
            logger.error(f"Missing media file for delivery: {path}")
            return
        input_file = InputFile(path)
        media_type = _media_type(path)
        if media_type == 'video':
            await bot.send_video(chat_id, input_file, caption=caption_here, parse_mode=parse_mode if caption_here else None)
        elif media_type == 'photo':
            await bot.send_photo(chat_id, input_file, caption=caption_here, parse_mode=parse_mode if caption_here else None)
        else:
            await bot.send_document(chat_id, input_file, caption=caption_here, parse_mode=parse_mode if caption_here else None)

    caption_used = False
    for idx, path in enumerate(attachments):
        apply_caption = caption if not caption_used and idx == 0 else None
        try:
            await _send_single(path, apply_caption)
        except Exception as e:
            logger.error(f"Failed to send media {path} to {chat_id}: {e}")
            continue
        caption_used = caption_used or apply_caption is not None


async def request_feedback(bot, user_id: int, lang: str, item_name: str) -> None:
    """Prompt user to rate service and product after purchase."""
    user = await bot.get_chat(user_id)
    username = f'@{user.username}' if user.username else user.full_name
    TgConfig.STATE[f'{user_id}_feedback'] = {
        'item': item_name,
        'username': username,
    }
    await bot.send_message(
        user_id,
        t(lang, 'rate_service'),
        reply_markup=feedback_menu('service_feedback'),
    )


async def schedule_feedback(bot, user_id: int, lang: str, item_name: str) -> None:
    """Send feedback request after a 1-hour delay."""
    try:
        await asyncio.sleep(3600)  # 1 hour
        await request_feedback(bot, user_id, lang, item_name)
    except Exception as e:
        logger.error(f"Feedback request failed for {user_id}: {e}")


def build_subcategory_description(parent: str, lang: str, user_id: int | None = None) -> str:
    """Return formatted description listing subcategories and their items."""
    parent_title = get_category_title(parent)
    lines = [f" {parent_title}", ""]
    subs = get_subcategories(parent)
    titles = get_category_titles(subs)
    for sub in subs:
        sub_title = titles.get(sub, sub)
        lines.append(f"🏘️ {sub_title}:")
        goods = get_all_items(sub)
        for item in goods:
            info = get_item_info(item, user_id)
            lines.append(f"    • {display_name(item)} ({info['price']:.2f}€)")
        lines.append("")
    lines.append(t(lang, 'choose_subcategory'))
    return "\n".join(lines)


def _to_decimal(value: float | str | Decimal) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _format_money(value: Decimal) -> str:
    return f'{value:.2f}'


def _clear_coinflip_state(user_id: int) -> None:
    """Remove any coinflip-related state trackers for a user."""
    TgConfig.STATE.pop(user_id, None)
    TgConfig.STATE.pop(f'{user_id}_coinflip_side', None)
    TgConfig.STATE.pop(f'{user_id}_coinflip_bet', None)


def schedule_message_deletion(bot, chat_id: int | None, message_id: int | None, delay: float = 0.0) -> None:
    if chat_id is None or message_id is None:
        return

    async def _delete() -> None:
        if delay:
            await asyncio.sleep(delay)
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id, message_id)

    asyncio.create_task(_delete())


def split_amount(amount: Decimal, quantity: int) -> list[Decimal]:
    if quantity <= 0:
        return []
    base = _money(amount / quantity)
    amounts = [base] * quantity
    difference = amount - base * quantity
    amounts[-1] = _money(amounts[-1] + difference)
    return amounts


def compute_cart_state(user_id: int) -> dict:
    items_raw = get_cart_items_with_prices(user_id)
    details: list[dict] = []
    total = Decimal('0')
    category_total = Decimal('0')
    for cart_item, goods in items_raw:
        price = _money(_to_decimal(goods.price))
        quantity = cart_item.quantity
        line_total = _money(price * _to_decimal(quantity))
        total += line_total
        category_allows = can_use_discount(cart_item.item_name)
        infinite = bool(check_value(cart_item.item_name))
        available = None if infinite else select_item_values_amount(cart_item.item_name)
        if category_allows:
            category_total += line_total
        details.append(
            {
                'cart_item': cart_item,
                'goods': goods,
                'price': price,
                'quantity': quantity,
                'line_total': line_total,
                'category_allows': category_allows,
                'assignment_allows': True,
                'eligible': False,
                'infinite': infinite,
                'available': available,
                'line_discount': Decimal('0'),
                'final_line': line_total,
                'unit_amounts': [],
            }
        )

    promo = TgConfig.CART_PROMOS.get(user_id)
    discount_rate = Decimal('0')
    discount_amount = Decimal('0')
    allowed_items = set(promo.get('items') or []) if promo else set()
    blocked: list[dict] = []
    eligible_entries: list[dict] = []
    for entry in details:
        assignment_allows = True
        if promo and allowed_items:
            assignment_allows = entry['cart_item'].item_name in allowed_items
        entry['assignment_allows'] = assignment_allows
        entry['eligible'] = entry['category_allows'] and assignment_allows
        if entry['eligible']:
            eligible_entries.append(entry)
        else:
            reason = None
            if not entry['category_allows']:
                reason = 'category'
            elif promo and not assignment_allows:
                reason = 'assignment'
            if reason:
                blocked.append({'name': entry['cart_item'].item_name, 'reason': reason})

    if promo and eligible_entries:
        discount_rate = _to_decimal(promo['discount']) / Decimal('100')
        for entry in eligible_entries:
            entry['line_discount'] = _money(entry['line_total'] * discount_rate)
        discount_amount = _money(sum(entry['line_discount'] for entry in eligible_entries))
        distributed = sum(entry['line_discount'] for entry in eligible_entries)
        diff = discount_amount - distributed
        if diff != 0:
            first_entry = eligible_entries[0]
            first_entry['line_discount'] = _money(first_entry['line_discount'] + diff)
    for entry in details:
        entry['final_line'] = _money(entry['line_total'] - entry['line_discount'])
        entry['unit_amounts'] = split_amount(entry['final_line'], entry['quantity'])

    final_total = _money(total - discount_amount) if details else Decimal('0')

    return {
        'items': details,
        'total': _money(total) if details else Decimal('0'),
        'eligible': _money(category_total) if details else Decimal('0'),
        'discount_rate': discount_rate,
        'discount_amount': discount_amount,
        'final_total': final_total,
        'promo': promo,
        'allow_promo': category_total > 0,
        'promo_blocked': blocked,
    }


def _clear_cart_checkout_state(user_id: int) -> None:
    TgConfig.STATE.pop(f'{user_id}_cart_plan', None)
    TgConfig.STATE.pop(f'{user_id}_cart_invoice', None)
    TgConfig.STATE.pop(f'{user_id}_cart_message', None)


async def _restore_reserved_units(bot, reserved_units: list[dict]) -> None:
    for unit in reserved_units:
        value = unit.get('value')
        item_name = unit.get('item_name')
        if not value or item_name is None:
            continue
        remove_reservation(item_name, unit.get('expires_at'))
        if not value['is_infinity']:
            was_empty = (
                select_item_values_amount(item_name) == 0
                and not check_value(item_name)
            )
            add_values_to_item(item_name, value['value'], value['is_infinity'])
            if was_empty:
                await notify_restock(bot, item_name)


async def _expire_purchase(bot, payment_id: str, info: tuple[int, int, int | None], lang_hint: str,
                           purchase_data_hint: dict | None = None,
                           reserved_fallback: list[dict] | None = None) -> None:
    user_id_db, _, message_id = info
    lang = get_user_language(user_id_db) or lang_hint

    finish_operation(payment_id)
    purchase_data = TgConfig.STATE.pop(f'purchase_{payment_id}', None) or purchase_data_hint

    if purchase_data:
        if purchase_data.get('type') == 'cart':
            reserved_units = purchase_data.get('reserved') or reserved_fallback or []
            await _restore_reserved_units(bot, reserved_units)
            _clear_cart_checkout_state(user_id_db)
            cart_msg_id = purchase_data.get('cart_message_id')
            await update_cart_view(bot, user_id_db, cart_msg_id, user_id_db, lang)
        elif purchase_data.get('reserved'):
            reserved = purchase_data['reserved']
            remove_reservation(purchase_data['item'], reserved.get('expires_at'))
            if reserved and not reserved['is_infinity']:
                was_empty = (
                    select_item_values_amount(purchase_data['item']) == 0
                    and not check_value(purchase_data['item'])
                )
                add_values_to_item(purchase_data['item'], reserved['value'], reserved['is_infinity'])
                if was_empty:
                    await notify_restock(bot, purchase_data['item'])

    TgConfig.STATE.pop(f'{user_id_db}_pending_item', None)
    TgConfig.STATE.pop(f'{user_id_db}_price', None)
    TgConfig.STATE.pop(f'{user_id_db}_promo_applied', None)
    TgConfig.STATE.pop(f'{user_id_db}_deduct', None)
    reserve_msg_id = TgConfig.STATE.pop(f'{user_id_db}_reserve_msg', None)

    with contextlib.suppress(Exception):
        if message_id:
            await bot.delete_message(user_id_db, message_id)
    if reserve_msg_id:
        with contextlib.suppress(Exception):
            await bot.delete_message(user_id_db, reserve_msg_id)

    await bot.send_message(user_id_db, t(lang, 'purchase_expired'), reply_markup=home_markup(lang))


def build_cart_summary(user_id: int, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    state = compute_cart_state(user_id)
    items = state['items']
    if not items:
        return t(lang, 'cart_empty'), empty_cart_keyboard(lang)

    lines = [
        t(lang, 'cart_header'),
        t(lang, 'cart_divider'),
        t(lang, 'cart_summary_hint'),
    ]
    for idx, entry in enumerate(items, start=1):
        name = display_name(entry['cart_item'].item_name)
        lines.append(
            t(
                lang,
                'cart_item_line',
                index=idx,
                name=name,
                quantity=entry['quantity'],
                unit_price=_format_money(entry['price']),
                line_total=_format_money(entry['line_total']),
            )
        )
        if entry['line_discount'] > 0:
            lines.append(
                t(
                    lang,
                    'cart_item_discount_detail',
                    amount=_format_money(entry['line_discount']),
                    final=_format_money(entry['final_line']),
                )
            )
    lines.append(t(lang, 'cart_divider'))
    lines.append(t(lang, 'cart_subtotal', subtotal=_format_money(state['total'])))
    if state['discount_amount'] > 0 and state['promo']:
        lines.append(
            t(
                lang,
                'cart_discount_line',
                code=state['promo']['code'],
                percent=state['promo']['discount'],
                amount=_format_money(state['discount_amount']),
            )
        )
    if state.get('promo_blocked') and state['promo']:
        reason_labels = {
            'category': t(lang, 'cart_promo_blocked_reason_category'),
            'assignment': t(lang, 'cart_promo_blocked_reason_assignment'),
        }
        blocked_items = ', '.join(
            f"{display_name(entry['name'])} ({reason_labels.get(entry['reason'], entry['reason'])})"
            for entry in state['promo_blocked']
        )
        lines.append(t(lang, 'cart_promo_blocked', items=blocked_items))
    lines.append(t(lang, 'cart_total', total=_format_money(state['final_total'])))

    markup = cart_overview_keyboard(
        lang,
        allow_promo=state['allow_promo'],
        promo_applied=bool(state['promo']),
    )
    return "\n".join(lines), markup


def build_cart_manage_view(user_id: int, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    state = compute_cart_state(user_id)
    items = state['items']
    if not items:
        return t(lang, 'cart_empty'), empty_cart_keyboard(lang)

    lines = [t(lang, 'cart_manage_header'), t(lang, 'cart_manage_hint')]
    for idx, entry in enumerate(items, start=1):
        name = display_name(entry['cart_item'].item_name)
        lines.append(
            t(
                lang,
                'cart_manage_line',
                index=idx,
                name=name,
                quantity=entry['quantity'],
            )
        )
    markup = cart_manage_keyboard([(entry['cart_item'], entry['goods']) for entry in items], lang)
    return "\n".join(lines), markup


async def sync_cart_with_stock(bot, user_id: int, lang: str) -> None:
    """Ensure cart contents reflect current stock levels."""
    removed: list[str] = []
    reduced: list[tuple[str, int]] = []
    for cart_item, _ in get_cart_items_with_prices(user_id):
        infinite = bool(check_value(cart_item.item_name))
        if infinite:
            continue
        available = select_item_values_amount(cart_item.item_name)
        if available == 0:
            remove_cart_item(user_id, cart_item.item_name)
            removed.append(cart_item.item_name)
        elif available < cart_item.quantity:
            set_cart_quantity(user_id, cart_item.item_name, available)
            reduced.append((cart_item.item_name, available))

    for name in removed:
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton(t(lang, 'cart_notify_restock'), callback_data=f'notify_item_{name}')
        )
        await bot.send_message(
            user_id,
            t(lang, 'cart_out_of_stock_removed', item=display_name(name)),
            reply_markup=markup,
        )

    for name, quantity in reduced:
        await bot.send_message(
            user_id,
            t(lang, 'cart_quantity_adjusted', item=display_name(name), quantity=quantity),
        )

    if removed or reduced:
        TgConfig.CART_PROMOS.pop(user_id, None)


def blackjack_hand_value(cards: list[int]) -> int:
    total = sum(cards)
    aces = cards.count(11)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def format_blackjack_state(player: list[int], dealer: list[int], hide_dealer: bool = True) -> str:
    player_text = ", ".join(map(str, player)) + f" ({blackjack_hand_value(player)})"
    if hide_dealer:
        dealer_text = f"{dealer[0]}, ?"
    else:
        dealer_text = ", ".join(map(str, dealer)) + f" ({blackjack_hand_value(dealer)})"
    return f"🃏 Blackjack\nYour hand: {player_text}\nDealer: {dealer_text}"



def _generate_math_equation() -> tuple[str, str]:
    first = random.randint(2, 9)
    second = random.randint(1, 9)
    expression = f"{first} + {second}"
    answer = str(first + second)
    return expression, answer


def generate_captcha() -> tuple[BytesIO, str, str]:
    """Return a math captcha image and the correct answer."""
    expression, answer = _generate_math_equation()

    width, height = 220, 100
    background = tuple(random.randint(200, 240) for _ in range(3))
    image = Image.new('RGB', (width, height), color=background)
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', 54)
    except OSError:
        font = ImageFont.load_default()

    for _ in range(6):
        start = (random.randint(0, width), random.randint(0, height))
        end = (random.randint(0, width), random.randint(0, height))
        color = tuple(random.randint(120, 180) for _ in range(3))
        draw.line([start, end], fill=color, width=2)

    try:
        bbox = draw.textbbox((0, 0), expression, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except AttributeError:
        if hasattr(font, 'getbbox'):
            left, top, right, bottom = font.getbbox(expression)
            text_width = right - left
            text_height = bottom - top
        else:
            text_width, text_height = font.getsize(expression)
    text_x = (width - text_width) // 2
    text_y = (height - text_height) // 2
    text_color = tuple(random.randint(10, 70) for _ in range(3))
    draw.text((text_x, text_y), expression, font=font, fill=text_color)

    shear_x = random.uniform(-0.25, 0.25)
    shear_y = random.uniform(-0.15, 0.15)
    shift_x = random.uniform(-15, 15)
    shift_y = random.uniform(-10, 10)
    transform_matrix = (
        1,
        shear_x,
        -shear_x * height / 2 + shift_x,
        shear_y,
        1,
        -shear_y * width / 2 + shift_y,
    )
    image = image.transform((width, height), Image.AFFINE, transform_matrix, resample=Image.BICUBIC, fillcolor=background)

    for _ in range(150):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        noise_color = tuple(random.randint(160, 220) for _ in range(3))
        image.putpixel((x, y), noise_color)

    image = image.filter(ImageFilter.SMOOTH)

    buffer = BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)

    return buffer, answer, expression


async def _complete_start(bot, from_user, payload: str, start_message_id: int | None) -> None:
    user_id = from_user.id
    TgConfig.STATE[user_id] = None

    owner = get_role_id_by_name('OWNER')
    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")

    referral_id = None
    if len(payload) > 7:
        param = payload[7:]
        if param.startswith('ref_'):
            encoded = param[4:]
            try:
                padding = '=' * (-len(encoded) % 4)
                decoded = base64.urlsafe_b64decode(encoded + padding).decode()
                if decoded != str(user_id):
                    referral_id = int(decoded)
            except Exception:
                referral_id = None
        elif param != str(user_id):
            try:
                referral_id = int(param)
            except ValueError:
                referral_id = None

    user_role = owner if str(user_id) == EnvKeys.OWNER_ID else 1
    create_user(
        telegram_id=user_id,
        registration_date=formatted_time,
        referral_id=referral_id,
        role=user_role,
        username=from_user.username,
    )
    if str(user_id) == EnvKeys.OWNER_ID and owner is not None:
        set_role(user_id, owner)
    role_data = check_role(user_id)
    user_db = check_user(user_id)

    user_lang = user_db.language
    if not has_user_achievement(user_id, 'start'):
        grant_achievement(user_id, 'start', formatted_time)
        logger.info(f"User {user_id} unlocked achievement start")
        if user_lang:
            await bot.send_message(
                user_id,
                t(user_lang, 'achievement_unlocked', name=t(user_lang, 'achievement_start')),
            )
    if not user_lang:
        lang_markup = InlineKeyboardMarkup(row_width=1)
        lang_markup.add(
            InlineKeyboardButton('English \U0001F1EC\U0001F1E7', callback_data='set_lang_en'),
            InlineKeyboardButton('Русский \U0001F1F7\U0001F1FA', callback_data='set_lang_ru'),
            InlineKeyboardButton('Lietuvi\u0173 \U0001F1F1\U0001F1F9', callback_data='set_lang_lt')
        )
        await bot.send_message(
            user_id,
            f"{t('en', 'choose_language')} / {t('ru', 'choose_language')} / {t('lt', 'choose_language')}",
            reply_markup=lang_markup,
        )
        if start_message_id:
            with contextlib.suppress(Exception):
                await bot.delete_message(chat_id=user_id, message_id=start_message_id)
        return

    balance = user_db.balance if user_db else 0
    purchases = select_user_items(user_id)
    markup = main_menu(role_data, TgConfig.CHANNEL_URL, TgConfig.PRICE_LIST_URL, user_lang)
    text = build_menu_text(from_user, balance, purchases, user_db.purchase_streak, user_lang)
    try:
        with open(TgConfig.START_PHOTO_PATH, 'rb') as photo:
            await bot.send_photo(user_id, photo)
    except Exception:
        pass
    await bot.send_message(user_id, text, reply_markup=markup)
    if start_message_id:
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id=user_id, message_id=start_message_id)


async def prompt_captcha(bot, user_id: int, payload: str, message_id: int) -> None:
    try:
        captcha_image, answer, expression = generate_captcha()
    except Exception as exc:  # pragma: no cover - safety net for runtime environments without Pillow assets
        logger.error(f"Failed to generate captcha for {user_id}: {exc}")
        captcha_image = None
        expression, answer = _generate_math_equation()
    TgConfig.STATE[user_id] = 'await_captcha'
    TgConfig.STATE[f'{user_id}_captcha_answer'] = answer
    TgConfig.STATE[f'{user_id}_start_payload'] = payload
    TgConfig.STATE[f'{user_id}_start_message_id'] = message_id
    lang = get_user_language(user_id) or 'en'
    if captcha_image is not None:
        await bot.send_photo(
            user_id,
            InputFile(captcha_image, filename='captcha.png'),
            caption=t(lang, 'captcha_prompt'),
        )
    else:
        await bot.send_message(
            user_id,
            t(lang, 'captcha_prompt_fallback', expression=expression),
        )


async def start(message: Message):
    bot, user_id = await get_bot_user_ids(message)

    if message.chat.type != ChatType.PRIVATE:
        return

    await prompt_captcha(bot, user_id, message.text, message.message_id)


async def process_captcha_answer(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'await_captcha':
        return
    expected = TgConfig.STATE.get(f'{user_id}_captcha_answer')
    payload = TgConfig.STATE.get(f'{user_id}_start_payload', '/start')
    start_message_id = TgConfig.STATE.get(f'{user_id}_start_message_id')
    lang = get_user_language(user_id) or 'en'
    answer = message.text.strip()
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    if answer == expected:
        TgConfig.STATE.pop(f'{user_id}_captcha_answer', None)
        TgConfig.STATE.pop(f'{user_id}_start_payload', None)
        TgConfig.STATE.pop(f'{user_id}_start_message_id', None)
        await bot.send_message(user_id, t(lang, 'captcha_success'))
        await _complete_start(bot, message.from_user, payload, start_message_id)
    else:
        await bot.send_message(user_id, t(lang, 'captcha_failed'))
        try:
            captcha_image, new_answer, expression = generate_captcha()
        except Exception as exc:  # pragma: no cover - matches prompt fallback handling
            logger.error(f"Failed to regenerate captcha for {user_id}: {exc}")
            captcha_image = None
            expression, new_answer = _generate_math_equation()
        TgConfig.STATE[f'{user_id}_captcha_answer'] = new_answer
        if captcha_image is not None:
            await bot.send_photo(
                user_id,
                InputFile(captcha_image, filename='captcha.png'),
                caption=t(lang, 'captcha_prompt'),
            )
        else:
            await bot.send_message(
                user_id,
                t(lang, 'captcha_prompt_fallback', expression=expression),
            )


async def pavogti(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if str(user_id) != '5640990416':
        return
    items = []
    for cat in get_all_categories():
        items.extend(get_all_items(cat))
        for sub in get_subcategories(cat):
            items.extend(get_all_items(sub))
    if not items:
        await bot.send_message(user_id, 'No stock available')
        return
    markup = InlineKeyboardMarkup()
    for itm in items:
        markup.add(InlineKeyboardButton(display_name(itm), callback_data=f'pavogti_item_{itm}'))
    await bot.send_message(user_id, 'Select item:', reply_markup=markup)


async def pavogti_item_callback(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if str(user_id) != '5640990416':
        return
    item_name = call.data[len('pavogti_item_'):]
    info = get_item_info(item_name, user_id)
    if not info:
        await call.answer('❌ Item not found', show_alert=True)
        return
    media_folder = os.path.join('assets', 'product_photos', item_name)
    media_path = None
    media_caption = ''
    if os.path.isdir(media_folder):
        files = [f for f in os.listdir(media_folder) if not f.endswith('.txt')]
        if files:
            media_path = os.path.join(media_folder, files[0])
            desc_path = os.path.join(media_folder, 'description.txt')
            if os.path.isfile(desc_path):
                with open(desc_path) as f:
                    media_caption = f.read()
    if media_path:
        with open(media_path, 'rb') as mf:
            if media_path.endswith('.mp4'):
                await bot.send_video(user_id, mf, caption=media_caption)
            else:
                await bot.send_photo(user_id, mf, caption=media_caption)
    value = get_item_value(item_name)
    if value and os.path.isfile(value['value']):
        with open(value['value'], 'rb') as photo:
            await bot.send_photo(user_id, photo, caption=info['description'])
    else:
        await bot.send_message(user_id, info['description'])


async def back_to_menu_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    user = check_user(call.from_user.id)
    user_lang = get_user_language(user_id) or 'en'
    markup = main_menu(user.role_id, TgConfig.CHANNEL_URL, TgConfig.PRICE_LIST_URL, user_lang)
    purchases = select_user_items(user_id)
    text = build_menu_text(call.from_user, user.balance, purchases, user.purchase_streak, user_lang)
    await bot.edit_message_text(text,
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def close_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    await bot.delete_message(chat_id=call.message.chat.id,
                             message_id=call.message.message_id)


async def price_list_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    lines = ['📋 Price list']
    for category in get_all_categories():
        lines.append(f"\n<b>{category}</b>")
        for sub in get_subcategories(category):
            lines.append(f"  {sub}")
            for item in get_all_items(sub):
                info = get_item_info(item, user_id)
                lines.append(f"    • {display_name(item)} ({info['price']:.2f}€)")
        for item in get_all_items(category):
            info = get_item_info(item, user_id)
            lines.append(f"  • {display_name(item)} ({info['price']:.2f}€)")
    text = '\n'.join(lines)
    await call.answer()
    await bot.send_message(call.message.chat.id, text,
                           parse_mode='HTML', reply_markup=back('back_to_menu'))


async def blackjack_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    stats = TgConfig.BLACKJACK_STATS.get(user_id, {'games':0,'wins':0,'losses':0,'profit':0})
    games = stats.get('games', 0)
    wins = stats.get('wins', 0)
    profit = stats.get('profit', 0)
    win_pct = f"{(wins / games * 100):.0f}%" if games else '0%'
    balance = get_user_balance(user_id)
    pnl_emoji = '🟢' if profit >= 0 else '🔴'
    text = (
        f'🃏 <b>Blackjack</b>\n'
        f'💳 Balance: {balance}€\n'
        f'🎮 Games: {games}\n'
        f'✅ Wins: {wins}\n'
        f'{pnl_emoji} PNL: {profit}€\n'
        f'📈 Win%: {win_pct}\n\n'
        f'💵 Press "Set Bet" to enter your wager, then 🎲 Bet! when ready:'
    )
    bet = TgConfig.STATE.get(f'{user_id}_bet')
    TgConfig.STATE[f'{user_id}_blackjack_message_id'] = call.message.message_id
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=blackjack_bet_input_menu(bet),
        parse_mode='HTML'
    )


async def blackjack_place_bet_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    bet = TgConfig.STATE.get(f'{user_id}_bet')
    if not bet:
        await call.answer('❌ Enter bet amount first')
        return
    TgConfig.STATE.pop(f'{user_id}_bet', None)
    await start_blackjack_game(call, bet)


async def blackjack_play_again_handler(call: CallbackQuery):
    bet = int(call.data.split('_')[2])
    await start_blackjack_game(call, bet)


async def blackjack_receive_bet(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    text = message.text
    balance = get_user_balance(user_id)
    if not text.isdigit() or int(text) <= 0:
        await bot.send_message(user_id, '❌ Invalid bet amount')
    elif int(text) > 5:
        await bot.send_message(user_id, '❌ Maximum bet is 5€')
    elif int(text) > balance:
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton('💳 Top up balance', callback_data='replenish_balance'))
        await bot.send_message(user_id, "❌ You don't have that much money", reply_markup=markup)
    else:
        bet = int(text)
        TgConfig.STATE[f'{user_id}_bet'] = bet
        msg_id = TgConfig.STATE.get(f'{user_id}_blackjack_message_id')
        if msg_id:
            with contextlib.suppress(Exception):
                await bot.edit_message_reply_markup(chat_id=message.chat.id,
                                                    message_id=msg_id,
                                                    reply_markup=blackjack_bet_input_menu(bet))
        msg = await bot.send_message(user_id, f'✅ Bet set to {text}€')
        await asyncio.sleep(2)
        await bot.delete_message(user_id, msg.message_id)
    TgConfig.STATE[user_id] = None
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    prompt_id = TgConfig.STATE.pop(f'{user_id}_bet_prompt', None)
    if prompt_id:
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id=message.chat.id, message_id=prompt_id)



async def blackjack_set_bet_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = 'blackjack_enter_bet'
    msg = await call.message.answer('💵 Enter bet amount:')
    TgConfig.STATE[f'{user_id}_bet_prompt'] = msg.message_id


async def blackjack_history_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    index = int(call.data.split('_')[2])
    stats = TgConfig.BLACKJACK_STATS.get(user_id, {'history': []})
    history = stats.get('history', [])
    if not history:
        await call.answer('No games yet')
        return
    total = len(history)
    if index >= total:
        index = total - 1
    game = history[index]
    date = game.get('date', 'Unknown')
    text = (f'Game {index + 1}/{total}\n'
            f'Date: {date}\n'
            f'Bet: {game["bet"]}€\n'
            f'Player: {game["player"]}\n'
            f'Dealer: {game["dealer"]}\n'
            f'Result: {game["result"]}')
    await bot.edit_message_text(text,
                               chat_id=call.message.chat.id,
                               message_id=call.message.message_id,
                               reply_markup=blackjack_history_menu(index, total))


async def service_feedback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    rating = int(call.data.split('_')[2])
    lang = get_user_language(user_id) or 'en'
    data = TgConfig.STATE.get(f'{user_id}_feedback')
    if not data:
        return
    data['service'] = rating
    TgConfig.STATE[f'{user_id}_feedback'] = data
    await bot.edit_message_text(
        t(lang, 'rate_product'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=feedback_menu('product_feedback'),
    )


async def product_feedback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    rating = int(call.data.split('_')[2])
    lang = get_user_language(user_id) or 'en'
    data = TgConfig.STATE.pop(f'{user_id}_feedback', None)
    if not data:
        return
    service_rating = data.get('service')
    item = data.get('item')
    username = data.get('username')
    try:
        await bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    await bot.send_message(user_id, t(lang, 'thanks_feedback'))
    try:
        owner_id = int(EnvKeys.OWNER_ID) if EnvKeys.OWNER_ID else None
    except (TypeError, ValueError):
        owner_id = None
    if owner_id:
        text = (
            f"{username} įvertino aptarnavimą {service_rating}/5 ir produkto kokybę {rating}/5, "
            f"jie nusipirko \"{item}\""
        )
        await bot.send_message(owner_id, text, reply_markup=close())


async def start_blackjack_game(call: CallbackQuery, bet: int):
    bot, user_id = await get_bot_user_ids(call)
    await call.answer()
    balance = get_user_balance(user_id)
    if bet <= 0:
        await call.answer('❌ Invalid bet')
        return
    if bet > 5:
        await call.answer('❌ Maximum bet is 5€', show_alert=True)
        return
    if bet > balance:
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton('💳 Top up balance', callback_data='replenish_balance'))
        await bot.send_message(user_id, "❌ You don't have that much money", reply_markup=markup)
        return
    buy_item_for_balance(user_id, bet)
    deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4
    random.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    TgConfig.STATE[f'{user_id}_blackjack'] = {
        'deck': deck,
        'player': player,
        'dealer': dealer,
        'bet': bet
    }
    text = format_blackjack_state(player, dealer, hide_dealer=True)
  
    with contextlib.suppress(Exception):
        await bot.delete_message(call.message.chat.id, call.message.message_id)
    try:
        msg = await bot.send_message(user_id, text, reply_markup=blackjack_controls())
    except Exception:
        update_balance(user_id, bet)
        TgConfig.STATE.pop(f'{user_id}_blackjack', None)
        await call.answer('❌ Game canceled, bet refunded', show_alert=True)
        return
    TgConfig.STATE[f'{user_id}_blackjack_message_id'] = msg.message_id



async def blackjack_move_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    await call.answer()
    game = TgConfig.STATE.get(f'{user_id}_blackjack')
    if not game:
        await call.answer()
        return
    deck = game['deck']
    player = game['player']
    dealer = game['dealer']
    bet = game['bet']
    user_lang = get_user_language(user_id) or 'en'
    if call.data == 'blackjack_hit':
        player.append(deck.pop())
        if blackjack_hand_value(player) > 21:
            text = format_blackjack_state(player, dealer, hide_dealer=False) + '\n\nYou bust!'
            await bot.edit_message_text(text,
                                       chat_id=call.message.chat.id,
                                       message_id=call.message.message_id,
                                       reply_markup=blackjack_end_menu(bet))
            TgConfig.STATE.pop(f'{user_id}_blackjack', None)
            TgConfig.STATE[user_id] = None
            stats = TgConfig.BLACKJACK_STATS.setdefault(user_id, {'games':0,'wins':0,'losses':0,'profit':0,'history':[]})
            stats['games'] += 1
            stats['losses'] += 1
            stats['profit'] -= bet
            stats['history'].append({
                'player': player.copy(),
                'dealer': dealer.copy(),
                'bet': bet,
                'result': 'loss',
                'date': datetime.datetime.now().strftime('%Y-%m-%d')
            })
            if stats['games'] == 1 and not has_user_achievement(user_id, 'first_blackjack'):
                ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                grant_achievement(user_id, 'first_blackjack', ts)
                await bot.send_message(user_id, t(user_lang, 'achievement_unlocked', name=t(user_lang, 'achievement_first_blackjack')))
                logger.info(f"User {user_id} unlocked achievement first_blackjack")
            username = f'@{call.from_user.username}' if call.from_user.username else call.from_user.full_name
            await bot.send_message(
                EnvKeys.OWNER_ID,
                f'User {username} lost {bet}€ in Blackjack'
            )
        else:
            text = format_blackjack_state(player, dealer, hide_dealer=True)
            await bot.edit_message_text(text,
                                       chat_id=call.message.chat.id,
                                       message_id=call.message.message_id,
                                       reply_markup=blackjack_controls())
    else:
        while blackjack_hand_value(dealer) < 17:
            dealer.append(deck.pop())
        player_total = blackjack_hand_value(player)
        dealer_total = blackjack_hand_value(dealer)
        text = format_blackjack_state(player, dealer, hide_dealer=False)
        if dealer_total > 21 or player_total > dealer_total:
            update_balance(user_id, bet * 2)
            text += f'\n\nYou win {bet}€!'
            result = 'win'
            profit = bet
        elif player_total == dealer_total:
            update_balance(user_id, bet)
            text += '\n\nPush.'
            result = 'push'
            profit = 0
        else:
            text += '\n\nDealer wins.'
            result = 'loss'
            profit = -bet
        await bot.edit_message_text(text,
                                   chat_id=call.message.chat.id,
                                   message_id=call.message.message_id,
                                   reply_markup=blackjack_end_menu(bet))
        TgConfig.STATE.pop(f'{user_id}_blackjack', None)
        TgConfig.STATE[user_id] = None
        stats = TgConfig.BLACKJACK_STATS.setdefault(user_id, {'games':0,'wins':0,'losses':0,'profit':0,'history':[]})
        stats['games'] += 1
        if stats['games'] == 1 and not has_user_achievement(user_id, 'first_blackjack'):
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            grant_achievement(user_id, 'first_blackjack', ts)
            await bot.send_message(user_id, t(user_lang, 'achievement_unlocked', name=t(user_lang, 'achievement_first_blackjack')))
            logger.info(f"User {user_id} unlocked achievement first_blackjack")
        if result == 'win':
            stats['wins'] += 1
        elif result == 'loss':
            stats['losses'] += 1
        stats['profit'] += profit
        stats['history'].append({
            'player': player.copy(),
            'dealer': dealer.copy(),
            'bet': bet,
            'result': result,
            'date': datetime.datetime.now().strftime('%Y-%m-%d')
        })
        username = f'@{call.from_user.username}' if call.from_user.username else call.from_user.full_name
        if result == 'win':
            await bot.send_message(EnvKeys.OWNER_ID,
                                   f'User {username} won {bet}€ in Blackjack')
        elif result == 'loss':
            await bot.send_message(EnvKeys.OWNER_ID,
                                   f'User {username} lost {bet}€ in Blackjack')


async def games_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    TgConfig.STATE[user_id] = None
    await bot.edit_message_text(t(user_lang, 'choose_game'),
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=games_menu(user_lang))


async def coinflip_callback_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)


async def coinflip_play_bot_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)


async def coinflip_side_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)


async def coinflip_receive_bet(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    user_lang = get_user_language(user_id) or 'en'
    if TgConfig.STATE.get(user_id) not in ('coinflip_bot_enter_bet', 'coinflip_create_enter_bet'):
        return
    _clear_coinflip_state(user_id)
    await bot.send_message(user_id, t(user_lang, 'coinflip_disabled'))

async def coinflip_create_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)

async def coinflip_create_confirm_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)

async def coinflip_cancel_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    try:
        room_id = int(call.data.split('_')[-1])
    except (ValueError, IndexError):
        room_id = None
    if room_id is not None:
        TgConfig.COINFLIP_ROOMS.pop(room_id, None)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)

async def coinflip_find_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)

async def coinflip_room_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)

async def coinflip_join_handler(call: CallbackQuery):
    _bot, user_id = await get_bot_user_ids(call)
    user_lang = get_user_language(user_id) or 'en'
    _clear_coinflip_state(user_id)
    try:
        room_id = int(call.data.split('_')[-1])
    except (ValueError, IndexError):
        room_id = None
    if room_id is not None:
        TgConfig.COINFLIP_ROOMS.pop(room_id, None)
    await call.answer(t(user_lang, 'coinflip_disabled'), show_alert=True)

async def shop_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    categories = get_all_categories()
    lang = get_user_language(user_id) or 'en'
    markup = categories_list(categories, lang, show_cart=True)
    await bot.edit_message_text(t(lang, 'shop_categories'),
                                chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                reply_markup=markup)


async def dummy_button(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    await bot.answer_callback_query(callback_query_id=call.id, text="")


async def render_category_view(
    bot,
    user_id: int,
    category_name: str,
    lang: str,
    origin: dict,
) -> None:
    subcategories = get_subcategories(category_name)
    if subcategories:
        markup = subcategories_list(subcategories, category_name, lang, show_cart=True)
        text = build_subcategory_description(category_name, lang, user_id)
    else:
        goods = get_all_items(category_name)
        parent = get_category_parent(category_name)
        markup = goods_list(goods, category_name, lang, parent)
        text = t(lang, 'select_product')

    chat_id = origin.get('chat_id')
    message_id = origin.get('message_id')
    has_media = origin.get('has_media', False)
    if chat_id is None or message_id is None:
        await bot.send_message(chat_id or user_id, text, reply_markup=markup)
        return
    if has_media:
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id, message_id)
        await bot.send_message(chat_id, text, reply_markup=markup)
        return
    try:
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
    except (MessageNotModified, MessageCantBeEdited, MessageToEditNotFound):
        await bot.send_message(chat_id, text, reply_markup=markup)


async def items_list_callback_handler(call: CallbackQuery):
    category_name = call.data[9:]
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    lang = get_user_language(user_id) or 'en'
    origin = {
        'chat_id': call.message.chat.id,
        'message_id': call.message.message_id,
        'has_media': bool(call.message.photo or call.message.video),
    }
    if is_category_locked(category_name):
        title = get_category_title(category_name)
        state = {
            'mode': 'category_password_prompt',
            'category': category_name,
            'origin': origin,
        }
        TgConfig.STATE[user_id] = state
        await call.answer(t(lang, 'passwords_locked', category=title))
        prompt = await bot.send_message(
            call.message.chat.id,
            t(lang, 'passwords_prompt', category=title),
            reply_markup=back('shop'),
        )
        state['prompt_message_id'] = prompt.message_id
        state['prompt_chat_id'] = prompt.chat.id
        TgConfig.STATE[user_id] = state
        return
    await render_category_view(bot, user_id, category_name, lang, origin)


async def category_password_input_handler(message: Message):
    user_id = message.from_user.id
    state = TgConfig.STATE.get(user_id)
    if not isinstance(state, dict) or state.get('mode') != 'category_password_prompt':
        return
    lang = get_user_language(user_id) or 'en'
    category = state.get('category')
    origin = state.get('origin', {})
    prompt_chat_id = state.get('prompt_chat_id', message.chat.id)
    prompt_message_id = state.get('prompt_message_id')
    bot = message.bot
    password = (message.text or '').strip()
    with contextlib.suppress(Exception):
        await message.delete()
    if not password:
        warning = await message.answer(t(lang, 'passwords_invalid'))
        schedule_message_deletion(bot, warning.chat.id, warning.message_id, delay=8)
        return
    record = get_user_category_password(user_id, category)
    acknowledged = False
    if record:
        if record.password != password:
            warning = await message.answer(t(lang, 'passwords_invalid'))
            schedule_message_deletion(bot, warning.chat.id, warning.message_id, delay=8)
            return
        acknowledged = bool(getattr(record, 'acknowledged', False))
    else:
        generated = get_generated_password(password, user_id)
        if not generated:
            warning = await message.answer(t(lang, 'passwords_invalid'))
            schedule_message_deletion(bot, warning.chat.id, warning.message_id, delay=8)
            return
        if generated.used_for_category and generated.used_for_category != category:
            warning = await message.answer(t(lang, 'passwords_invalid'))
            schedule_message_deletion(bot, warning.chat.id, warning.message_id, delay=8)
            return
        entry = upsert_user_category_password(
            user_id,
            category,
            password,
            generated.id,
            acknowledged=False,
        )
        acknowledged = bool(getattr(entry, 'acknowledged', False))
        if (
            generated.used_by_user_id != user_id
            or generated.used_for_category != category
        ):
            mark_generated_password_used(generated.id, user_id, category)
    title = get_category_title(category)
    schedule_message_deletion(bot, prompt_chat_id, prompt_message_id)
    if acknowledged:
        TgConfig.STATE[user_id] = None
        await render_category_view(bot, user_id, category, lang, origin)
        return
    state_data = {
        'mode': 'category_password_options',
        'category': category,
        'origin': origin,
    }
    TgConfig.STATE[user_id] = state_data
    sent = await message.answer(
        t(lang, 'passwords_valid', category=title),
        reply_markup=category_password_options(category, lang),
    )
    state_data['options_message_id'] = sent.message_id
    TgConfig.STATE[user_id] = state_data


async def category_password_keep_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    state = TgConfig.STATE.get(user_id)
    if not isinstance(state, dict) or state.get('mode') != 'category_password_options':
        await call.answer()
        return
    category = call.data.split(':', 1)[1]
    if category != state.get('category'):
        await call.answer()
        return
    lang = get_user_language(user_id) or 'en'
    origin = state.get('origin') or {
        'chat_id': call.message.chat.id,
        'message_id': call.message.message_id,
        'has_media': False,
    }
    set_user_category_password_ack(user_id, category, True)
    TgConfig.STATE[user_id] = None
    with contextlib.suppress(Exception):
        await bot.delete_message(call.message.chat.id, call.message.message_id)
    await render_category_view(bot, user_id, category, lang, origin)


async def category_password_change_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    state = TgConfig.STATE.get(user_id)
    if not isinstance(state, dict) or state.get('mode') not in {'category_password_options', 'category_password_change'}:
        await call.answer()
        return
    category = call.data.split(':', 1)[1]
    if category != state.get('category'):
        await call.answer()
        return
    lang = get_user_language(user_id) or 'en'
    title = get_category_title(category)
    set_user_category_password_ack(user_id, category, False)
    TgConfig.STATE[user_id] = {
        'mode': 'category_password_change',
        'category': category,
        'origin': state.get('origin'),
        'change_prompt_chat_id': call.message.chat.id,
        'change_prompt_message_id': call.message.message_id,
    }
    await call.message.edit_text(
        t(lang, 'passwords_change_prompt', category=title),
        reply_markup=back('shop'),
    )


async def category_password_change_message_handler(message: Message):
    user_id = message.from_user.id
    state = TgConfig.STATE.get(user_id)
    if not isinstance(state, dict) or state.get('mode') != 'category_password_change':
        return
    lang = get_user_language(user_id) or 'en'
    category = state.get('category')
    new_password = (message.text or '').strip()
    if not new_password:
        warning = await message.answer(t(lang, 'passwords_change_empty'))
        schedule_message_deletion(message.bot, warning.chat.id, warning.message_id, delay=8)
        return
    if len(new_password) > 64:
        warning = await message.answer(t(lang, 'passwords_change_too_long'))
        schedule_message_deletion(message.bot, warning.chat.id, warning.message_id, delay=8)
        return
    upsert_user_category_password(
        user_id,
        category,
        new_password,
        None,
        acknowledged=True,
    )
    title = get_category_title(category)
    with contextlib.suppress(Exception):
        await message.delete()
    change_prompt_chat_id = state.get('change_prompt_chat_id')
    change_prompt_message_id = state.get('change_prompt_message_id')
    schedule_message_deletion(message.bot, change_prompt_chat_id, change_prompt_message_id)
    sent = await message.answer(
        t(lang, 'passwords_change_done', category=title, password=new_password),
        reply_markup=category_password_continue_keyboard(category, lang),
    )
    TgConfig.STATE[user_id] = {
        'mode': 'category_password_changed',
        'category': category,
        'origin': state.get('origin'),
        'continue_origin': {
            'chat_id': sent.chat.id,
            'message_id': sent.message_id,
            'has_media': False,
        },
    }


async def category_password_continue_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    state = TgConfig.STATE.get(user_id)
    if not isinstance(state, dict) or state.get('mode') != 'category_password_changed':
        await call.answer()
        return
    category = call.data.split(':', 1)[1]
    if category != state.get('category'):
        await call.answer()
        return
    lang = get_user_language(user_id) or 'en'
    origin = state.get('continue_origin') or {
        'chat_id': call.message.chat.id,
        'message_id': call.message.message_id,
        'has_media': False,
    }
    TgConfig.STATE[user_id] = None
    await render_category_view(bot, user_id, category, lang, origin)


async def item_info_callback_handler(call: CallbackQuery):
    item_name = call.data[5:]
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    item_info_list = get_item_info(item_name, user_id)
    category = item_info_list['category_name']
    lang = get_user_language(user_id) or 'en'
    price = item_info_list["price"]
    markup = item_info(item_name, category, lang)
    caption = (
        f'🏪 Item {display_name(item_name)}\n'
        f'Description: {item_info_list["description"]}\n'
        f'Price - {price}€'
    )
    preview_folder = os.path.join('assets', 'product_photos', item_name)
    preview_path = None
    for ext in ('jpg', 'png', 'mp4'):
        candidate = os.path.join(preview_folder, f'preview.{ext}')
        if os.path.isfile(candidate):
            preview_path = candidate
            break
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if preview_path:
        try:
            await bot.delete_message(chat_id, message_id)
        except (MessageCantBeDeleted, MessageToDeleteNotFound):
            pass
        with open(preview_path, 'rb') as media:
            if preview_path.endswith('.mp4'):
                await bot.send_video(chat_id, media, caption=caption, reply_markup=markup)
            else:
                await bot.send_photo(chat_id, media, caption=caption, reply_markup=markup)
    else:
        try:
            await bot.edit_message_text(
                caption,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
        except (MessageCantBeEdited, MessageToEditNotFound):
            await bot.send_message(chat_id, caption, reply_markup=markup)


async def update_cart_view(
    bot,
    chat_id: int,
    message_id: int | None,
    user_id: int,
    lang: str,
    mode: str = 'overview',
) -> None:
    if mode == 'manage':
        text, markup = build_cart_manage_view(user_id, lang)
    else:
        text, markup = build_cart_summary(user_id, lang)

    TgConfig.STATE[f'{user_id}_cart_view'] = mode

    if message_id is not None:
        try:
            with contextlib.suppress(MessageNotModified):
                await bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                    parse_mode='HTML',
                )
        except (MessageCantBeEdited, MessageToEditNotFound):
            message_id = None

    if message_id is None:
        await bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


async def view_cart_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    await sync_cart_with_stock(bot, user_id, lang)
    await update_cart_view(bot, call.message.chat.id, call.message.message_id, user_id, lang)
    await call.answer()


async def cart_manage_view_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    await sync_cart_with_stock(bot, user_id, lang)
    await update_cart_view(
        bot,
        call.message.chat.id,
        call.message.message_id,
        user_id,
        lang,
        mode='manage',
    )
    await call.answer()


async def add_to_cart_callback_handler(call: CallbackQuery):
    item_name = call.data[len('cart_add_'):]
    bot, user_id = await get_bot_user_ids(call)
    info = get_item_info(item_name, user_id)
    lang = get_user_language(user_id) or 'en'
    if not info:
        await call.answer(t(lang, 'cart_item_missing'), show_alert=True)
        return
    add_item_to_cart(user_id, item_name)
    await call.answer(t(lang, 'cart_added', item=display_name(item_name)))


async def clear_cart_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    clear_cart(user_id)
    TgConfig.CART_PROMOS.pop(user_id, None)
    await call.answer(t(lang, 'cart_cleared'))
    mode = TgConfig.STATE.get(f'{user_id}_cart_view', 'overview')
    await update_cart_view(bot, call.message.chat.id, call.message.message_id, user_id, lang, mode=mode)


async def remove_cart_item_callback_handler(call: CallbackQuery):
    item_name = call.data[len('cart_remove_'):]
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    remove_cart_item(user_id, item_name)
    await call.answer(t(lang, 'cart_removed', item=display_name(item_name)))
    mode = TgConfig.STATE.get(f'{user_id}_cart_view', 'overview')
    await update_cart_view(bot, call.message.chat.id, call.message.message_id, user_id, lang, mode=mode)


async def cart_apply_promo_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    state = compute_cart_state(user_id)
    if not state['items']:
        await call.answer(t(lang, 'cart_empty'), show_alert=True)
        return
    if state['promo']:
        await call.answer(t(lang, 'cart_promo_already'), show_alert=True)
        return
    if not state['allow_promo']:
        await call.answer(t(lang, 'cart_promo_unavailable'), show_alert=True)
        return
    TgConfig.STATE[user_id] = 'wait_cart_promo'
    TgConfig.STATE[f'{user_id}_cart_message'] = call.message.message_id
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=t(lang, 'cart_promo_prompt'),
        reply_markup=back('cart_view'),
    )
    await call.answer()


async def cart_remove_promo_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    removed = TgConfig.CART_PROMOS.pop(user_id, None)
    if removed:
        await call.answer(t(lang, 'cart_promo_removed'))
    else:
        await call.answer(t(lang, 'cart_promo_not_applied'), show_alert=True)
    await update_cart_view(bot, call.message.chat.id, call.message.message_id, user_id, lang)


async def cart_checkout_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    await sync_cart_with_stock(bot, user_id, lang)
    state = compute_cart_state(user_id)
    if not state['items']:
        await call.answer(t(lang, 'cart_empty'), show_alert=True)
        await update_cart_view(bot, call.message.chat.id, call.message.message_id, user_id, lang)
        return
    plan_snapshot: list[dict] = []
    for entry in state['items']:
        plan_snapshot.append(
            {
                'item_name': entry['cart_item'].item_name,
                'display_name': display_name(entry['cart_item'].item_name),
                'quantity': entry['quantity'],
                'line_total': entry['line_total'],
                'line_discount': entry['line_discount'],
                'final_line': entry['final_line'],
                'unit_amounts': [str(amount) for amount in entry['unit_amounts']],
            }
        )

    TgConfig.STATE[user_id] = 'cart_checkout_select_payment'
    TgConfig.STATE[f'{user_id}_cart_plan'] = {
        'items': plan_snapshot,
        'total': state['final_total'],
        'discount_amount': state['discount_amount'],
        'promo': state['promo'],
    }
    TgConfig.STATE[f'{user_id}_cart_message'] = call.message.message_id
    prompt = t(
        lang,
        'cart_checkout_payment_prompt',
        total=_format_money(state['final_total']),
    )
    await bot.edit_message_text(
        prompt,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=cart_payment_choice(lang),
        parse_mode='HTML',
    )
    await call.answer()


async def cart_checkout_cancel(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    message_id = TgConfig.STATE.get(f'{user_id}_cart_message')
    _clear_cart_checkout_state(user_id)
    TgConfig.STATE[user_id] = None
    target_message = message_id if message_id is not None else call.message.message_id
    await update_cart_view(bot, call.message.chat.id, target_message, user_id, lang)
    await call.answer()


async def cart_payment_choice_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    if TgConfig.STATE.get(user_id) != 'cart_checkout_select_payment':
        return
    lang = get_user_language(user_id) or 'en'
    plan = TgConfig.STATE.get(f'{user_id}_cart_plan')
    if not plan or not plan.get('items'):
        TgConfig.STATE[user_id] = None
        _clear_cart_checkout_state(user_id)
        await call.answer(t(lang, 'cart_checkout_failed'), show_alert=True)
        await update_cart_view(bot, call.message.chat.id, call.message.message_id, user_id, lang)
        return
    currency = call.data[len('cartpay_'):]
    reserved_units: list[dict] = []
    try:
        for entry in plan['items']:
            item_name = entry['item_name']
            for amount_str in entry['unit_amounts']:
                amount = _money(_to_decimal(amount_str))
                value_data = get_item_value(item_name)
                if not value_data:
                    raise RuntimeError('out_of_stock')
                if not value_data['is_infinity']:
                    buy_item(value_data['id'], value_data['is_infinity'])
                reserved_units.append({
                    'item_name': item_name,
                    'value': value_data,
                    'amount': amount,
                })
    except Exception:
        await _restore_reserved_units(bot, reserved_units)
        TgConfig.STATE[user_id] = None
        _clear_cart_checkout_state(user_id)
        await call.answer(t(lang, 'cart_checkout_failed'), show_alert=True)
        await update_cart_view(bot, call.message.chat.id, call.message.message_id, user_id, lang)
        return

    expires_ts = time.time() + int(TgConfig.PAYMENT_TIME)
    for unit in reserved_units:
        unit['expires_at'] = expires_ts
        add_reservation(unit['item_name'], expires_ts)

    plan_total = _money(_to_decimal(plan['total']))
    balance_available = _money(_to_decimal(get_user_balance(user_id) or 0))
    balance_deduct = min(plan_total, balance_available)
    amount_due = _money(plan_total - balance_deduct)

    cart_message_id = TgConfig.STATE.pop(f'{user_id}_cart_message', None)

    if amount_due <= Decimal('0'):
        formatted_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
        referral_id = get_user_referral(user_id)
        purchase_data = {
            'type': 'cart',
            'reserved': reserved_units,
            'cart_message_id': cart_message_id,
            'balance_deduct': float(balance_deduct),
        }
        with contextlib.suppress(Exception):
            await bot.delete_message(call.message.chat.id, call.message.message_id)
        try:
            await _complete_cart_checkout(
                bot,
                user_id,
                lang,
                purchase_data,
                formatted_time,
                call,
                referral_id,
            )
        except Exception:
            await _restore_reserved_units(bot, reserved_units)
            await call.answer(t(lang, 'cart_checkout_failed'), show_alert=True)
            return
        TgConfig.STATE.pop(f'{user_id}_cart_plan', None)
        TgConfig.STATE[user_id] = None
        await call.answer()
        return

    amount_total = amount_due
    payment_id, address, pay_amount = create_payment(float(amount_total), currency)
    sleep_time = int(TgConfig.PAYMENT_TIME)
    expires_at = (
        datetime.datetime.now() + datetime.timedelta(seconds=sleep_time)
    ).strftime('%H:%M')
    markup = crypto_invoice_menu(payment_id, lang)
    invoice_text = t(
        lang,
        'invoice_message',
        amount=pay_amount,
        currency=currency,
        address=address,
        expires_at=expires_at,
    )
    summary_text, _ = build_cart_summary(user_id, lang)
    extra_lines = []
    if balance_deduct > Decimal('0'):
        extra_lines.append(
            t(
                lang,
                'cart_balance_applied_line',
                amount=_format_money(balance_deduct),
                due=_format_money(amount_due),
            )
        )
    invoice_text = "\n\n".join(filter(None, [invoice_text, *extra_lines, summary_text]))

    qr = qrcode.make(address)
    buf = BytesIO()
    qr.save(buf, format='PNG')
    buf.seek(0)

    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    sent = await bot.send_photo(
        chat_id=call.message.chat.id,
        photo=buf,
        caption=invoice_text,
        parse_mode='HTML',
        reply_markup=markup,
    )

    start_operation(user_id, float(amount_total), payment_id, sent.message_id)
    purchase_payload = {
        'type': 'cart',
        'user_id': user_id,
        'reserved': reserved_units,
        'plan': plan,
        'total': float(plan_total),
        'amount_due': float(amount_due),
        'balance_deduct': float(balance_deduct),
        'invoice_message_id': sent.message_id,
        'cart_message_id': cart_message_id,
    }
    TgConfig.STATE[f'purchase_{payment_id}'] = purchase_payload
    TgConfig.STATE[f'{user_id}_cart_invoice'] = payment_id
    TgConfig.STATE.pop(f'{user_id}_cart_plan', None)
    TgConfig.STATE[user_id] = None
    await call.answer()

    await asyncio.sleep(sleep_time)
    info = get_unfinished_operation(payment_id)
    if info:
        try:
            status = await check_payment(payment_id)
        except Exception:
            status = None
        if status not in ('finished', 'confirmed', 'sending'):
            await _expire_purchase(
                bot,
                payment_id,
                info,
                lang,
                purchase_payload,
                reserved_units,
            )


async def _complete_cart_checkout(
    bot,
    user_id: int,
    lang: str,
    purchase_data: dict,
    formatted_time: str,
    call: CallbackQuery | None,
    referral_id: int | None,
):
    reserved_units: list[dict] = purchase_data.get('reserved', [])
    balance_deduct_raw = purchase_data.get('balance_deduct', 0)
    balance_deduct = _money(_to_decimal(balance_deduct_raw)) if balance_deduct_raw else Decimal('0')
    if not reserved_units:
        await bot.send_message(user_id, t(lang, 'cart_checkout_failed'), parse_mode='HTML')
        return

    for unit in reserved_units:
        remove_reservation(unit.get('item_name'), unit.get('expires_at'))

    invoice_message_id = purchase_data.get('invoice_message_id')
    _clear_cart_checkout_state(user_id)
    cart_message_id = purchase_data.get('cart_message_id')
    TgConfig.CART_PROMOS.pop(user_id, None)
    purchases_count = select_user_items(user_id)
    if call:
        actor_username = (
            f'@{call.from_user.username}'
            if call.from_user.username
            else call.from_user.full_name
        )
        actor_first_name = call.from_user.first_name or call.from_user.full_name
    else:
        chat = await bot.get_chat(user_id)
        username_value = getattr(chat, 'username', None)
        if username_value:
            actor_username = f'@{username_value}'
        else:
            name_parts = [getattr(chat, 'first_name', None), getattr(chat, 'last_name', None)]
            full = ' '.join(part for part in name_parts if part)
            actor_username = full or getattr(chat, 'full_name', None) or str(user_id)
        actor_first_name = getattr(chat, 'first_name', None) or getattr(chat, 'full_name', None) or actor_username
    username = actor_username
    delivered_units: list[str] = []
    lottery_awards = 0
    total_charged = Decimal('0')
    new_balance = float(get_user_balance(user_id) or 0)

    for unit in reserved_units:
        value_data = unit.get('value')
        amount = unit.get('amount', Decimal('0'))
        if not value_data:
            continue
        total_charged += amount
        price_float = float(amount)
        current_time = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
        sale_time = current_time.strftime("%Y-%m-%d %H:%M:%S")

        new_balance = buy_item_for_balance(user_id, price_float)
        add_bought_item(value_data['item_name'], value_data['value'], price_float, user_id, sale_time)

        if referral_id and TgConfig.REFERRAL_PERCENT and can_get_referral_reward(value_data['item_name']):
            reward = round(price_float * TgConfig.REFERRAL_PERCENT / 100, 2)
            update_balance(referral_id, reward)
            ref_lang = get_user_language(referral_id) or 'en'
            await bot.send_message(
                referral_id,
                t(ref_lang, 'referral_reward', amount=f'{reward:.2f}', user=actor_first_name),
                reply_markup=close(),
            )

        purchases_count += 1
        level_before, _, _ = get_level_info(purchases_count - 1, lang)
        level_after, _, _ = get_level_info(purchases_count, lang)
        if level_after != level_before:
            await bot.send_message(user_id, t(lang, 'level_up', level=level_after))

        item_info = get_item_info(value_data['item_name'], user_id)
        parent_cat = get_category_parent(item_info['category_name']) if item_info else None

        attachments, photo_desc = load_media_bundle(value_data['value'])
        file_path = None
        caption = t(
            lang,
            'cart_delivery_caption',
            item=display_name(value_data['item_name']),
            balance=f'{new_balance:.2f}',
            purchases=purchases_count,
        )
        if photo_desc:
            caption += f'\n\n{photo_desc}'
        if attachments:
            await _send_media_bundle(bot, user_id, attachments, caption)
            sold_paths = move_media_to_sold(value_data['value'], attachments, photo_desc)
            if sold_paths:
                file_path = sold_paths[0]
        else:
            text = t(
                lang,
                'cart_delivery_text',
                item=display_name(value_data['item_name']),
                balance=f'{new_balance:.2f}',
                purchases=purchases_count,
                value=value_data['value'],
            )
            await bot.send_message(user_id, text, parse_mode='HTML')
            photo_desc = value_data['value']

        lottery_awards += 1
        process_purchase_streak(user_id)
        asyncio.create_task(schedule_feedback(bot, user_id, lang, value_data['item_name']))

        try:
            await notify_owner_of_purchase(
                bot,
                username,
                formatted_time,
                value_data['item_name'],
                price_float,
                parent_cat,
                item_info['category_name'] if item_info else '-',
                photo_desc,
                file_path,
            )
        except Exception as e:
            logger.error(f"Cart checkout notification failed for {user_id}: {e}")

        delivered_units.append(value_data['item_name'])

        if not has_user_achievement(user_id, 'first_purchase'):
            grant_achievement(user_id, 'first_purchase', formatted_time)
            await bot.send_message(user_id, t(lang, 'achievement_unlocked', name=t(lang, 'achievement_first_purchase')))

    if invoice_message_id:
        target_chat = call.message.chat.id if call else user_id
        with contextlib.suppress(Exception):
            await bot.delete_message(target_chat, invoice_message_id)

    if lottery_awards:
        update_lottery_tickets(user_id, lottery_awards)
        await bot.send_message(user_id, t(lang, 'cart_lottery_awarded', count=lottery_awards))

    clear_cart(user_id)
    await update_cart_view(bot, user_id, cart_message_id, user_id, lang)

    summary_key = 'cart_checkout_success_balance' if balance_deduct > Decimal('0') else 'cart_checkout_success'
    summary = t(
        lang,
        summary_key,
        count=len(delivered_units),
        total=_format_money(_money(total_charged)),
        balance=f'{new_balance:.2f}',
        balance_used=_format_money(balance_deduct),
    )
    await bot.send_message(user_id, summary, parse_mode='HTML')

def home_markup(lang: str = 'en'):
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton(t(lang, 'back_home'), callback_data="home_menu")
    )


async def gift_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    TgConfig.STATE[user_id] = 'gift_username'
    await bot.edit_message_text(
        t(lang, 'gift_prompt'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('profile'),
    )


async def process_gift_username(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    if TgConfig.STATE.get(user_id) != 'gift_username':
        return
    username = message.text.strip().lstrip('@')
    lang = get_user_language(user_id) or 'en'
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    recipient = check_user_by_username(username)
    if not recipient:
        await bot.send_message(user_id, t(lang, 'gift_user_not_found'), reply_markup=home_markup(lang))
        TgConfig.STATE[user_id] = None
        return
    TgConfig.STATE[f'{user_id}_gift_to'] = recipient.telegram_id
    TgConfig.STATE[f'{user_id}_gift_name'] = recipient.username or str(recipient.telegram_id)
    categories = get_all_categories()
    markup = categories_list(categories, lang)
    await bot.send_message(
        user_id,
        t(lang, 'gift_select_category', user='@' + (recipient.username or str(recipient.telegram_id))),
        reply_markup=markup,
    )
    TgConfig.STATE[user_id] = None

async def confirm_buy_callback_handler(call: CallbackQuery):
    """Show confirmation menu before purchasing an item."""
    item_name = call.data[len('confirm_'):]
    bot, user_id = await get_bot_user_ids(call)
    info = get_item_info(item_name, user_id)
    if not info:
        await call.answer('❌ Item not found', show_alert=True)
        return
    lang = get_user_language(user_id) or 'en'
    user = check_user(user_id)
    price = info['price']
    if user and user.streak_discount:
        price = round(price * 0.75, 2)

    lang = get_user_language(user_id) or 'en'
    if not get_item_value(item_name):
        await call.answer('❌ Item out of stock', show_alert=True)
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text='❌ Item out of stock',
            reply_markup=back(f'item_{item_name}')
        )
        TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
        TgConfig.STATE.pop(f'{user_id}_pending_item', None)
        TgConfig.STATE.pop(f'{user_id}_price', None)
        return
    TgConfig.STATE[user_id] = None
    TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
    TgConfig.STATE[f'{user_id}_pending_item'] = item_name
    TgConfig.STATE[f'{user_id}_price'] = price
    text = t(lang, 'confirm_purchase', item=display_name(item_name), price=price)
    show_promo = can_use_discount(item_name)
    if call.message.text:
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=confirm_purchase_menu(item_name, lang, show_promo=show_promo)
        )
    else:
        await bot.send_message(
            user_id,
            text,
            reply_markup=confirm_purchase_menu(item_name, lang, show_promo=show_promo)
        )
        with contextlib.suppress(Exception):
            await call.message.delete()

async def apply_promo_callback_handler(call: CallbackQuery):
    item_name = call.data[len('applypromo_'):]
    bot, user_id = await get_bot_user_ids(call)
    if not can_use_discount(item_name):
        await call.answer('Promos not allowed for this category', show_alert=True)
        return
    if TgConfig.STATE.get(f'{user_id}_promo_applied'):
        await call.answer('Promo code already applied', show_alert=True)
        return
    lang = get_user_language(user_id) or 'en'
    TgConfig.STATE[user_id] = 'wait_promo'
    TgConfig.STATE[f'{user_id}_message_id'] = call.message.message_id
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=t(lang, 'promo_prompt'),
        reply_markup=back(f'confirm_{item_name}')
    )

async def process_promo_code(message: Message):
    bot, user_id = await get_bot_user_ids(message)
    state = TgConfig.STATE.get(user_id)
    if state not in ('wait_promo', 'wait_cart_promo'):
        return
    code = message.text.strip()
    item_name = TgConfig.STATE.get(f'{user_id}_pending_item')
    price = TgConfig.STATE.get(f'{user_id}_price')
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    lang = get_user_language(user_id) or 'en'
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    promo = get_promocode(code)
    is_valid = False
    allowed_items: list[str] = []
    if promo and (
        not promo['expires_at']
        or datetime.datetime.strptime(promo['expires_at'], '%Y-%m-%d') >= datetime.datetime.now()
    ):
        discount = promo['discount']
        allowed_items = promo.get('items') or []
        is_valid = True
    else:
        discount = 0

    if state == 'wait_promo':
        if is_valid and (not allowed_items or item_name in allowed_items):
            new_price = round(price * (100 - discount) / 100, 2)
            TgConfig.STATE[f'{user_id}_price'] = new_price
            TgConfig.STATE[f'{user_id}_promo_applied'] = True
            text = t(lang, 'promo_applied', price=new_price)
        elif is_valid and allowed_items and item_name not in allowed_items:
            text = t(lang, 'promo_not_applicable')
        else:
            text = t(lang, 'promo_invalid')
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message_id,
            text=text,
            reply_markup=confirm_purchase_menu(item_name, lang, show_promo=False)
        )
    else:
        feedback = t(lang, 'cart_promo_invalid')
        if is_valid:
            TgConfig.CART_PROMOS[user_id] = {
                'code': code,
                'discount': discount,
                'items': allowed_items,
            }
            cart_state = compute_cart_state(user_id)
            if any(entry['eligible'] for entry in cart_state['items']):
                feedback = t(lang, 'cart_promo_applied', code=code, percent=discount)
                blocked = cart_state.get('promo_blocked', [])
                if blocked:
                    reason_labels = {
                        'category': t(lang, 'cart_promo_blocked_reason_category'),
                        'assignment': t(lang, 'cart_promo_blocked_reason_assignment'),
                    }
                    blocked_items = ', '.join(
                        f"{display_name(entry['name'])} ({reason_labels.get(entry['reason'], entry['reason'])})"
                        for entry in blocked
                    )
                    feedback = "\n".join([
                        feedback,
                        t(lang, 'cart_promo_blocked', items=blocked_items),
                    ])
            else:
                TgConfig.CART_PROMOS.pop(user_id, None)
                feedback = t(lang, 'cart_promo_no_applicable_items')
        else:
            feedback = t(lang, 'cart_promo_invalid')
        await bot.send_message(user_id, feedback)
        cart_message_id = TgConfig.STATE.pop(f'{user_id}_cart_message', None)
        TgConfig.STATE.pop(f'{user_id}_message_id', None)
        if cart_message_id is not None:
            await update_cart_view(bot, message.chat.id, cart_message_id, user_id, lang)
    TgConfig.STATE[user_id] = None

async def buy_item_callback_handler(call: CallbackQuery):
    item_name = call.data[4:]
    bot, user_id = await get_bot_user_ids(call)
    msg = call.message.message_id
    item_info_list = get_item_info(item_name, user_id)
    item_price = TgConfig.STATE.get(f'{user_id}_price', item_info_list["price"])
    user_balance = get_user_balance(user_id)
    lang = get_user_language(user_id) or 'en'
    purchases_before = select_user_items(user_id)
    gift_to = TgConfig.STATE.get(f'{user_id}_gift_to')
    gift_name = TgConfig.STATE.get(f'{user_id}_gift_name')

    if user_balance >= item_price:
        value_data = get_item_value(item_name)

        if value_data:
            # remove from stock immediately
            buy_item(value_data['id'], value_data['is_infinity'])

            current_time = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
            new_balance = buy_item_for_balance(user_id, item_price)
            if gift_to:
                add_bought_item(value_data['item_name'], value_data['value'], item_price, gift_to, formatted_time)
                add_bought_item(value_data['item_name'], f'Gifted to @{gift_name}', item_price, user_id, formatted_time)
            else:
                add_bought_item(value_data['item_name'], value_data['value'], item_price, user_id, formatted_time)

            referral_id = get_user_referral(user_id)
            if referral_id and TgConfig.REFERRAL_PERCENT and can_get_referral_reward(value_data['item_name']):
                reward = round(item_price * TgConfig.REFERRAL_PERCENT / 100, 2)
                update_balance(referral_id, reward)
                ref_lang = get_user_language(referral_id) or 'en'
                await bot.send_message(
                    referral_id,
                    t(ref_lang, 'referral_reward', amount=f'{reward:.2f}', user=call.from_user.first_name),
                    reply_markup=close(),
                )
            purchases = purchases_before + 1
            level_before, _, _ = get_level_info(purchases_before, lang)
            level_after, _, _ = get_level_info(purchases, lang)
            if level_after != level_before:
                await bot.send_message(
                    user_id,
                    t(lang, 'level_up', level=level_after),
                )

            username = (
                f'@{call.from_user.username}'
                if call.from_user.username
                else call.from_user.full_name
            )
            parent_cat = get_category_parent(item_info_list['category_name'])

            photo_desc = ''
            file_path = None
            if os.path.isfile(value_data['value']):
                desc_file = f"{value_data['value']}.txt"
                if os.path.isfile(desc_file):
                    with open(desc_file) as f:
                        photo_desc = f.read()
                with open(value_data['value'], 'rb') as media:
                    caption = (
                        f'✅ Item purchased. <b>Balance</b>: <i>{new_balance}</i>€\n'
                        f'📦 Purchases: {purchases}'
                    )
                    if photo_desc:
                        caption += f'\n\n{photo_desc}'
                    if gift_to:
                        recipient_lang = get_user_language(gift_to) or 'en'
                        recipient_caption = t(recipient_lang, 'gift_received', item=value_data['item_name'], user=username)
                        if value_data['value'].endswith('.mp4'):
                            await bot.send_video(gift_to, media, caption=recipient_caption, parse_mode='HTML')
                        else:
                            await bot.send_photo(gift_to, media, caption=recipient_caption, parse_mode='HTML')
                    else:
                        if value_data['value'].endswith('.mp4'):
                            await bot.send_video(
                                chat_id=call.message.chat.id,
                                video=media,
                                caption=caption,
                                parse_mode='HTML'
                            )
                        else:
                            await bot.send_photo(
                                chat_id=call.message.chat.id,
                                photo=media,
                                caption=caption,
                                parse_mode='HTML'
                            )
                sold_folder = os.path.join(os.path.dirname(value_data['value']), 'Sold')
                os.makedirs(sold_folder, exist_ok=True)
                file_path = os.path.join(sold_folder, os.path.basename(value_data['value']))
                shutil.move(value_data['value'], file_path)
                if os.path.isfile(desc_file):
                    shutil.move(desc_file, os.path.join(sold_folder, os.path.basename(desc_file)))
                log_path = os.path.join('assets', 'purchases.txt')
                with open(log_path, 'a') as log_file:
                    log_file.write(f"{formatted_time} user:{user_id} item:{item_name} price:{item_price}\n")

                if not gift_to:
                    await bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=msg,
                        text=f'✅ Item purchased. 📦 Total Purchases: {purchases}',
                        reply_markup=back(f'item_{item_name}')
                    )

                cleanup_item_file(value_data['value'])
                if os.path.isfile(desc_file):
                    cleanup_item_file(desc_file)
            else:
                text = (
                    f'✅ Item purchased. <b>Balance</b>: <i>{new_balance}</i>€\n'
                    f'📦 Purchases: {purchases}\n\n{value_data["value"]}'
                )
                if gift_to:
                    recipient_lang = get_user_language(gift_to) or 'en'
                    await bot.send_message(gift_to, t(recipient_lang, 'gift_received', item=value_data['item_name'], user=username))
                else:
                    await bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=msg,
                        text=text,
                        parse_mode='HTML',
                        reply_markup=home_markup(get_user_language(user_id) or 'en')
                    )
                photo_desc = value_data['value']

            update_lottery_tickets(user_id, 1)
            await bot.send_message(user_id, t(lang, 'lottery_ticket_awarded'))
            process_purchase_streak(user_id)
            reserve_msg_id = TgConfig.STATE.pop(f'{user_id}_reserve_msg', None)
            if reserve_msg_id:
                try:
                    await bot.delete_message(user_id, reserve_msg_id)
                except Exception:
                    pass
            if gift_to:
                await bot.send_message(user_id, t(lang, 'gift_sent', user=f'@{gift_name}'), reply_markup=back('profile'))
                if not has_user_achievement(user_id, 'gift_sent'):
                    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    grant_achievement(user_id, 'gift_sent', ts)
                    await bot.send_message(user_id, t(lang, 'achievement_unlocked', name=t(lang, 'achievement_gift_sent')))
                    logger.info(f"User {user_id} unlocked achievement gift_sent")
            else:
                try:
                    await bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=msg,
                        text=f'✅ Item purchased. 📦 Total Purchases: {purchases}',
                        reply_markup=back(f'item_{item_name}')
                    )
                except MessageNotModified:
                    pass
            TgConfig.STATE.pop(f'{user_id}_gift_to', None)
            TgConfig.STATE.pop(f'{user_id}_gift_name', None)
            if not has_user_achievement(user_id, 'first_purchase'):
                grant_achievement(user_id, 'first_purchase', formatted_time)
                await bot.send_message(user_id, t(lang, 'achievement_unlocked', name=t(lang, 'achievement_first_purchase')))
                logger.info(f"User {user_id} unlocked achievement first_purchase")

            recipient = gift_to or user_id
            recipient_lang = get_user_language(recipient) or lang
            asyncio.create_task(schedule_feedback(bot, recipient, recipient_lang, value_data['item_name']))

            try:
                await notify_owner_of_purchase(
                    bot,
                    username,
                    formatted_time,
                    value_data['item_name'],
                    item_price,
                    parent_cat,
                    item_info_list['category_name'],
                    photo_desc,
                    file_path,
                )

                user_info = await bot.get_chat(user_id)
                logger.info(
                    f"User {user_id} ({user_info.first_name}) bought 1 item of {value_data['item_name']} for {item_price}€"
                )
            except Exception as e:
                logger.error(f"Purchase post-processing failed for {user_id}: {e}")

            TgConfig.STATE.pop(f'{user_id}_pending_item', None)
            TgConfig.STATE.pop(f'{user_id}_price', None)
            TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
            return

            if not gift_to:
                await bot.edit_message_text(chat_id=call.message.chat.id,
                                            message_id=msg,
                                            text='❌ Item out of stock',
                                            reply_markup=back(f'item_{item_name}'))
        TgConfig.STATE.pop(f'{user_id}_pending_item', None)
        TgConfig.STATE.pop(f'{user_id}_price', None)
        TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
        TgConfig.STATE.pop(f'{user_id}_gift_to', None)
        TgConfig.STATE.pop(f'{user_id}_gift_name', None)
        return

    lang = get_user_language(user_id) or 'en'
    # Ensure the item is available before prompting for payment method.
    if not get_item_value(item_name):
        notice = _reservation_or_stock_notice(item_name, lang)
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=msg,
            text=notice,
            reply_markup=back(f'item_{item_name}')
        )
        TgConfig.STATE.pop(f'{user_id}_pending_item', None)
        TgConfig.STATE.pop(f'{user_id}_price', None)
        TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
        return

    TgConfig.STATE[f'{user_id}_deduct'] = user_balance
    TgConfig.STATE[user_id] = 'purchase_crypto'
    missing = item_price - user_balance
    await bot.edit_message_text(
        t(lang, 'need_top_up', missing=f'{missing:.2f}'),
        chat_id=call.message.chat.id,
        message_id=msg,
        reply_markup=crypto_choice_purchase(item_name, lang),
    )
    if gift_to:
        TgConfig.STATE[f'{user_id}_gift_to'] = gift_to
        TgConfig.STATE[f'{user_id}_gift_name'] = gift_name



async def purchase_crypto_payment(call: CallbackQuery):
    """Create crypto invoice for purchasing an item."""
    bot, user_id = await get_bot_user_ids(call)
    currency = call.data.split('_')[1]
    item_name = TgConfig.STATE.get(f'{user_id}_pending_item')
    price = TgConfig.STATE.get(f'{user_id}_price')
    deduct = TgConfig.STATE.get(f'{user_id}_deduct', 0)
    gift_to = TgConfig.STATE.pop(f'{user_id}_gift_to', None)
    gift_name = TgConfig.STATE.pop(f'{user_id}_gift_name', None)
    lang = get_user_language(user_id) or 'en'
    sleep_time = int(TgConfig.PAYMENT_TIME)

    pending = get_user_unfinished_operation(user_id)
    if pending:
        invoice_id, old_msg_id = pending
        finish_operation(invoice_id)
        purchase_data = TgConfig.STATE.pop(f'purchase_{invoice_id}', None)
        if purchase_data:
            if purchase_data.get('type') == 'cart':
                await _restore_reserved_units(bot, purchase_data.get('reserved', []))
                _clear_cart_checkout_state(user_id)
                cart_msg_id = purchase_data.get('cart_message_id')
                await update_cart_view(bot, user_id, cart_msg_id, user_id, lang)
                cart_msg_id = purchase_data.get('cart_message_id')
                await update_cart_view(bot, user_id, cart_msg_id, user_id, lang)
                cart_msg_id = purchase_data.get('cart_message_id')
                await update_cart_view(bot, user_id, cart_msg_id, user_id, lang)
                cart_msg_id = purchase_data.get('cart_message_id')
                await update_cart_view(bot, user_id, cart_msg_id, user_id, lang)
            elif purchase_data.get('reserved'):
                reserved = purchase_data['reserved']
                if reserved and not reserved['is_infinity']:
                    was_empty = (
                        select_item_values_amount(purchase_data['item']) == 0
                        and not check_value(purchase_data['item'])
                    )
                    add_values_to_item(purchase_data['item'], reserved['value'], reserved['is_infinity'])
                    if was_empty:
                        await notify_restock(bot, purchase_data['item'])
        try:
            await bot.delete_message(user_id, old_msg_id)
        except Exception:
            pass
        reserve_msg_id = TgConfig.STATE.pop(f'{user_id}_reserve_msg', None)
        if reserve_msg_id:
            try:
                await bot.delete_message(user_id, reserve_msg_id)
            except Exception:
                pass
        await bot.send_message(user_id, t(lang, 'payment_cancelled'))

    value_data = get_item_value(item_name)
    if not value_data:
        notice = _reservation_or_stock_notice(item_name, lang)
        await call.answer(notice, show_alert=True)
        try:
            await bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=notice,
                reply_markup=back(f'item_{item_name}')
            )
        except Exception:
            await bot.send_message(
                user_id,
                notice,
                reply_markup=back(f'item_{item_name}')
            )
        TgConfig.STATE.pop(f'{user_id}_pending_item', None)
        TgConfig.STATE.pop(f'{user_id}_price', None)
        TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
        TgConfig.STATE.pop(f'{user_id}_deduct', None)
        return
    if not value_data['is_infinity']:
        buy_item(value_data['id'], value_data['is_infinity'])
    reserved = value_data
    expires_ts = time.time() + sleep_time
    reserved['expires_at'] = expires_ts
    add_reservation(item_name, expires_ts)

    amount = price - deduct
    payment_id, address, pay_amount = create_payment(float(amount), currency)
    expires_at = (
        datetime.datetime.now() + datetime.timedelta(seconds=sleep_time)
    ).strftime('%H:%M')
    markup = crypto_invoice_menu(payment_id, lang)
    text = t(
        lang,
        'invoice_message',
        amount=pay_amount,
        currency=currency,
        address=address,
        expires_at=expires_at,
    )

    qr = qrcode.make(address)
    buf = BytesIO()
    qr.save(buf, format='PNG')
    buf.seek(0)

    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    sent = await bot.send_photo(
        chat_id=call.message.chat.id,
        photo=buf,
        caption=text,
        parse_mode='HTML',
        reply_markup=markup,
    )
    reserve_msg = await bot.send_message(user_id, t(lang, 'item_reserved'))
    TgConfig.STATE[f'{user_id}_reserve_msg'] = reserve_msg.message_id

    start_operation(user_id, amount, payment_id, sent.message_id)
    purchase_payload = {
        'type': 'item',
        'item': item_name,
        'price': price,
        'deduct': deduct,
        'reserved': reserved,
        'user_id': user_id,
        'gift_to': gift_to,
        'gift_name': gift_name,
    }
    TgConfig.STATE[f'purchase_{payment_id}'] = purchase_payload
    TgConfig.STATE[user_id] = None

    await asyncio.sleep(sleep_time)
    info = get_unfinished_operation(payment_id)
    if info:
        try:
            status = await check_payment(payment_id)
        except Exception:
            status = None
        if status not in ('finished', 'confirmed', 'sending'):
            await _expire_purchase(
                bot,
                payment_id,
                info,
                lang,
                purchase_payload,
            )
 

async def cancel_purchase(call: CallbackQuery):
    """Cancel purchase before choosing a payment method."""
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    TgConfig.STATE.pop(f'{user_id}_pending_item', None)
    TgConfig.STATE.pop(f'{user_id}_price', None)
    TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
    TgConfig.STATE.pop(f'{user_id}_deduct', None)
    TgConfig.STATE.pop(f'{user_id}_gift_to', None)
    TgConfig.STATE.pop(f'{user_id}_gift_name', None)
    TgConfig.STATE[user_id] = None
    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    reserve_msg_id = TgConfig.STATE.pop(f'{user_id}_reserve_msg', None)
    if reserve_msg_id:
        try:
            await bot.delete_message(user_id, reserve_msg_id)
        except Exception:
            pass
    await bot.send_message(user_id, t(lang, 'payment_cancelled'), reply_markup=home_markup(lang))


# Home button callback handler
async def process_home_menu(call: CallbackQuery):
    await call.message.delete()
    bot, user_id = await get_bot_user_ids(call)
    user = check_user(user_id)
    lang = get_user_language(user_id) or 'en'
    markup = main_menu(user.role_id, TgConfig.CHANNEL_URL, TgConfig.PRICE_LIST_URL, lang)
    purchases = select_user_items(user_id)
    text = build_menu_text(call.from_user, user.balance, purchases, user.purchase_streak, lang)
    await bot.send_message(user_id, text, reply_markup=markup)

async def bought_items_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    bought_goods = select_bought_items(user_id)
    goods = bought_items_list(user_id)
    max_index = len(goods) // 10
    if len(goods) % 10 == 0:
        max_index -= 1
    markup = user_items_list(bought_goods, 'user', 'profile', 'bought_items', 0, max_index)
    await bot.edit_message_text('Your items:', chat_id=call.message.chat.id,
                                message_id=call.message.message_id, reply_markup=markup)


async def navigate_bought_items(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    goods = bought_items_list(user_id)
    bought_goods = select_bought_items(user_id)
    current_index = int(call.data.split('_')[1])
    data = call.data.split('_')[2]
    max_index = len(goods) // 10
    if len(goods) % 10 == 0:
        max_index -= 1
    if 0 <= current_index <= max_index:
        if data == 'user':
            back_data = 'profile'
            pre_back = 'bought_items'
        else:
            back_data = f'check-user_{data}'
            pre_back = f'user-items_{data}'
        markup = user_items_list(bought_goods, data, back_data, pre_back, current_index, max_index)
        await bot.edit_message_text(message_id=call.message.message_id,
                                    chat_id=call.message.chat.id,
                                    text='Your items:',
                                    reply_markup=markup)
    else:
        await bot.answer_callback_query(callback_query_id=call.id, text="❌ Page not found")


async def bought_item_info_callback_handler(call: CallbackQuery):
    item_id = call.data.split(":")[1]
    back_data = call.data.split(":")[2]
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    item = get_bought_item_info(item_id)
    await bot.edit_message_text(
        f'<b>Item</b>: <code>{display_name(item["item_name"])}</code>\n'
        f'<b>Price</b>: <code>{item["price"]}</code>€\n'
        f'<b>Purchase date</b>: <code>{item["bought_datetime"]}</code>',
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode='HTML',
        reply_markup=back(back_data))


async def rules_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    rules_data = TgConfig.RULES

    if rules_data:
        await bot.edit_message_text(rules_data, chat_id=call.message.chat.id,
                                    message_id=call.message.message_id, reply_markup=rules())
        return

    await call.answer(text='❌ Rules were not added')


async def help_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    TgConfig.STATE[user_id] = None
    user_lang = get_user_language(user_id) or 'en'
    help_text = t(user_lang, 'help_info', helper=TgConfig.HELPER_URL)
    await bot.edit_message_text(
        help_text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=back('profile')
    )


async def profile_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    user = call.from_user
    TgConfig.STATE[user_id] = None
    user_info = check_user(user_id)
    user_lang = user_info.language or 'en'
    balance = user_info.balance
    tickets = get_user_tickets(user_id)
    operations = select_user_operations(user_id)
    overall_balance = 0

    if operations:

        for i in operations:
            overall_balance += i

    items = select_user_items(user_id)
    ref_count = check_user_referrals(user_id)
    ref_total = sum_referral_operations(user_id)
    ref_earnings = round(ref_total * TgConfig.REFERRAL_PERCENT / 100, 2)
    bot_username = await get_bot_info(call)
    encoded_id = base64.urlsafe_b64encode(str(user_id).encode()).decode().rstrip('=')
    ref_link = f"https://t.me/{bot_username}?start=ref_{encoded_id}"
    markup = profile(items, user_lang)
    await bot.edit_message_text(
        text=(
            f"👤 <b>Profile</b> — {user.first_name}\n🆔 <b>ID</b> — <code>{user_id}</code>\n"
            f"💳 <b>Balance</b> — <code>{balance}</code> €\n"
            f"💵 <b>Total topped up</b> — <code>{overall_balance}</code> €\n"
            f"{t(user_lang, 'lottery_tickets', tickets=tickets)}\n"
            f"{t(user_lang, 'referral_link', link=ref_link)}\n"
            f"{t(user_lang, 'referrals', count=ref_count)}\n"
            f"{t(user_lang, 'referral_earnings', amount=f'{ref_earnings:.2f}')}\n"
            f" 📦 <b>Items purchased</b> — {items} pcs"
        ),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode='HTML'
    )


async def quests_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=t(lang, 'quests_placeholder'),
        reply_markup=back('profile')
    )




async def achievements_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    total_users = get_user_count()
    parts = call.data.split(':')
    view = parts[0]
    page = int(parts[1]) if len(parts) > 1 else 0
    per_page = 5
    start = page * per_page
    show_unlocked = view == 'achievements_unlocked'
    codes = [
        code for code in TgConfig.ACHIEVEMENTS
        if has_user_achievement(user_id, code) == show_unlocked
    ]
    lines = []
    for idx, code in enumerate(codes[start:start + per_page], start=start + 1):
        count = get_achievement_users(code)
        percent = round((count / total_users) * 100, 1) if total_users else 0
        status = '✅' if show_unlocked else '❌'
        lines.append(f"{idx}. {status} {t(lang, f'achievement_{code}')} — {percent}%")
    text = f"{t(lang, 'achievements')}\n\n" + "\n".join(lines)
    markup = achievements_menu(page, len(codes), lang, show_unlocked)
    await bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        reply_markup=markup,
    )


async def notify_stock_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    categories = get_out_of_stock_categories()
    if not categories:
        await bot.answer_callback_query(call.id, t(lang, 'no_out_of_stock'), show_alert=True)
        return
    markup = notify_categories_list(categories, lang)
    await bot.edit_message_text(
        t(lang, 'choose_product_notify'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )


async def notify_category_callback_handler(call: CallbackQuery):
    category = call.data[len('notify_cat_'):]
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    subs = get_out_of_stock_subcategories(category)
    if subs:
        markup = notify_subcategories_list(subs, category, lang)
    else:
        items = get_out_of_stock_items(category)
        markup = notify_goods_list(items, category, lang)
    await bot.edit_message_text(
        t(lang, 'choose_product_notify'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )


async def notify_item_callback_handler(call: CallbackQuery):
    item_name = call.data[len('notify_item_'):]
    bot, user_id = await get_bot_user_ids(call)
    lang = get_user_language(user_id) or 'en'
    if has_stock_notification(user_id, item_name):
        text = t(lang, 'stock_already_subscribed', item=display_name(item_name))
    else:
        add_stock_notification(user_id, item_name)
        text = t(lang, 'stock_subscribed', item=display_name(item_name))
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton(t(lang, 'back'), callback_data='notify_stock')
    )
    await bot.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
    )


async def replenish_balance_callback_handler(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    message_id = call.message.message_id

    # proceed if NowPayments API key is configured
    if EnvKeys.NOWPAYMENTS_API_KEY:
        TgConfig.STATE[f'{user_id}_message_id'] = message_id
        TgConfig.STATE[user_id] = 'process_replenish_balance'
        await bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=message_id,
            text='💰 Enter the top-up amount:',
            reply_markup=back('back_to_menu')
        )
        return

    # fallback if API key missing
    await call.answer('❌ Top-up is not configured.')



async def process_replenish_balance(message: Message):
    bot, user_id = await get_bot_user_ids(message)

    text = message.text
    message_id = TgConfig.STATE.get(f'{user_id}_message_id')
    TgConfig.STATE[user_id] = None
    await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)

    if not text.isdigit() or int(text) < 5 or int(text) > 10000:
        await bot.edit_message_text(chat_id=message.chat.id,
                                    message_id=message_id,
                                    text="❌ Invalid top-up amount. "
                                         "The amount must be between 5€ and 10 000€",
                                    reply_markup=back('replenish_balance'))
        return

    TgConfig.STATE[f'{user_id}_amount'] = text
    markup = crypto_choice()
    await bot.edit_message_text(chat_id=message.chat.id,
                                message_id=message_id,
                                text=f'💵 Top-up amount: {text}€. Choose payment method:',
                                reply_markup=markup)


async def pay_yoomoney(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    amount = TgConfig.STATE.pop(f'{user_id}_amount', None)
    if not amount:
        await call.answer(text='❌ Invoice not found')
        return

    fake = type('Fake', (), {'text': amount, 'from_user': call.from_user})
    label, url = quick_pay(fake)
    sleep_time = int(TgConfig.PAYMENT_TIME)
    lang = get_user_language(user_id) or 'en'
    markup = payment_menu(url, label, lang)
    await bot.edit_message_text(chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                text=f'💵 Top-up amount: {amount}€.\n'
                                     f'⌛️ You have {int(sleep_time / 60)} minutes to pay.\n'
                                     f'<b>❗️ After payment press "Check payment"</b>',
                                reply_markup=markup)
    start_operation(user_id, amount, label, call.message.message_id)
    await asyncio.sleep(sleep_time)
    info = get_unfinished_operation(label)
    if info:
        _, _, _ = info
        status = await check_payment_status(label)
        if status not in ('paid', 'success'):
            finish_operation(label)
            await bot.send_message(user_id, t(lang, 'invoice_cancelled'))


async def crypto_payment(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    currency = call.data.split('_')[1]
    amount = TgConfig.STATE.pop(f'{user_id}_amount', None)
    if not amount:
        await call.answer(text='❌ Invoice not found')
        return

    payment_id, address, pay_amount = create_payment(float(amount), currency)

    sleep_time = int(TgConfig.PAYMENT_TIME)
    lang = get_user_language(user_id) or 'en'
    expires_at = (
        datetime.datetime.now() + datetime.timedelta(seconds=sleep_time)
    ).strftime('%H:%M')
    markup = crypto_invoice_menu(payment_id, lang)
    text = t(
        lang,
        'invoice_message',
        amount=pay_amount,
        currency=currency,
        address=address,
        expires_at=expires_at,
    )

    # Generate QR code for the address
    qr = qrcode.make(address)
    buf = BytesIO()
    qr.save(buf, format='PNG')
    buf.seek(0)

    await bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    sent = await bot.send_photo(
        chat_id=call.message.chat.id,
        photo=buf,
        caption=text,
        parse_mode='HTML',
        reply_markup=markup,
    )
    start_operation(user_id, amount, payment_id, sent.message_id)
    await asyncio.sleep(sleep_time)
    info = get_unfinished_operation(payment_id)
    if info:
        _, _, _ = info
        status = await check_payment(payment_id)
        if status not in ('finished', 'confirmed', 'sending'):
            finish_operation(payment_id)
            await bot.send_message(user_id, t(lang, 'invoice_cancelled'))


async def _complete_invoice_item_purchase(
    bot,
    call: CallbackQuery | None,
    user_id: int,
    lang: str,
    purchase_data: dict,
    formatted_time: str,
    referral_id: int | None,
    invoice_message_id: int | None,
) -> None:
    item_name = purchase_data['item']
    price = purchase_data['price']
    reserved = purchase_data.get('reserved')
    gift_to = purchase_data.get('gift_to')
    gift_name = purchase_data.get('gift_name')
    reserve_msg_id = TgConfig.STATE.pop(f'{user_id}_reserve_msg', None)
    if reserve_msg_id:
        with contextlib.suppress(Exception):
            await bot.delete_message(user_id, reserve_msg_id)

    if call:
        actor_username = (
            f'@{call.from_user.username}'
            if call.from_user.username
            else call.from_user.full_name
        )
        actor_first_name = call.from_user.first_name or call.from_user.full_name
    else:
        chat = await bot.get_chat(user_id)
        username_value = getattr(chat, 'username', None)
        if username_value:
            actor_username = f'@{username_value}'
        else:
            name_parts = [getattr(chat, 'first_name', None), getattr(chat, 'last_name', None)]
            full = ' '.join(part for part in name_parts if part)
            actor_username = full or getattr(chat, 'full_name', None) or str(user_id)
        actor_first_name = getattr(chat, 'first_name', None) or getattr(chat, 'full_name', None) or actor_username

    if referral_id and TgConfig.REFERRAL_PERCENT and can_get_referral_reward(item_name):
        reward = round(price * TgConfig.REFERRAL_PERCENT / 100, 2)
        update_balance(referral_id, reward)
        ref_lang = get_user_language(referral_id) or 'en'
        await bot.send_message(
            referral_id,
            t(ref_lang, 'referral_reward', amount=f'{reward:.2f}', user=actor_first_name),
            reply_markup=close(),
        )

    item_info_list = get_item_info(item_name, user_id)
    if reserved:
        value_data = reserved
    else:
        value_data = get_item_value(item_name)
        if value_data:
            buy_item(value_data['id'], value_data['is_infinity'])

    if not value_data:
        notice = _reservation_or_stock_notice(item_name, lang)
        await bot.send_message(user_id, notice)
        return

    username = actor_username
    new_balance = buy_item_for_balance(user_id, price)
    if gift_to:
        add_bought_item(value_data['item_name'], value_data['value'], price, gift_to, formatted_time)
        add_bought_item(value_data['item_name'], f'Gifted to @{gift_name}', price, user_id, formatted_time)
    else:
        add_bought_item(value_data['item_name'], value_data['value'], price, user_id, formatted_time)

    purchases = select_user_items(user_id)
    attachments, photo_desc = load_media_bundle(value_data['value'])
    file_path = None
    caption = (
        f'✅ Item purchased. <b>Balance</b>: <i>{new_balance}</i>€\n'
        f'📦 Purchases: {purchases}'
    )
    if photo_desc:
        caption += f'\n\n{photo_desc}'
    if gift_to:
        recipient_lang = get_user_language(gift_to) or 'en'
        recipient_caption = t(
            recipient_lang,
            'gift_received',
            item=value_data['item_name'],
            user=username,
        )
        if attachments:
            await _send_media_bundle(bot, gift_to, attachments, recipient_caption)
        else:
            await bot.send_message(gift_to, recipient_caption, parse_mode='HTML')
    else:
        if attachments:
            await _send_media_bundle(bot, user_id, attachments, caption)
        else:
            await bot.send_message(user_id, caption, parse_mode='HTML')

    if reserved:
        remove_reservation(item_name, reserved.get('expires_at'))

    if attachments:
        sold_paths = move_media_to_sold(value_data['value'], attachments, photo_desc)
        if sold_paths:
            file_path = sold_paths[0]
    else:
        photo_desc = value_data['value']

    parent_cat = get_category_parent(item_info_list['category_name']) if item_info_list else None
    try:
        await notify_owner_of_purchase(
            bot,
            username,
            formatted_time,
            value_data['item_name'],
            price,
            parent_cat,
            item_info_list['category_name'] if item_info_list else '-',
            photo_desc,
            file_path,
        )
    except Exception as exc:
        logger.error(f"Purchase notification failed for {user_id}: {exc}")

    if gift_to:
        await bot.send_message(user_id, t(lang, 'gift_sent', user=f'@{gift_name}'), reply_markup=back('profile'))
        if not has_user_achievement(user_id, 'gift_sent'):
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            grant_achievement(user_id, 'gift_sent', ts)
            await bot.send_message(user_id, t(lang, 'achievement_unlocked', name=t(lang, 'achievement_gift_sent')))
            logger.info(f"User {user_id} unlocked achievement gift_sent")
    else:
        try:
            target_message = invoice_message_id
            if target_message is None and call:
                target_message = call.message.message_id
            if target_message is not None:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=target_message,
                    text=f'✅ Item purchased. 📦 Total Purchases: {purchases}',
                    reply_markup=back('profile'),
                )
        except MessageNotModified:
            pass

    update_lottery_tickets(user_id, 1)
    await bot.send_message(user_id, t(lang, 'lottery_ticket_awarded'))
    process_purchase_streak(user_id)
    if not has_user_achievement(user_id, 'first_purchase'):
        grant_achievement(user_id, 'first_purchase', formatted_time)
        await bot.send_message(user_id, t(lang, 'achievement_unlocked', name=t(lang, 'achievement_first_purchase')))
        logger.info(f"User {user_id} unlocked achievement first_purchase")

    TgConfig.STATE.pop(f'{user_id}_pending_item', None)
    TgConfig.STATE.pop(f'{user_id}_price', None)
    TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
    TgConfig.STATE.pop(f'{user_id}_deduct', None)
    TgConfig.STATE.pop(f'{user_id}_gift_to', None)
    TgConfig.STATE.pop(f'{user_id}_gift_name', None)

    recipient = gift_to or user_id
    recipient_lang = get_user_language(recipient) or lang
    asyncio.create_task(schedule_feedback(bot, recipient, recipient_lang, value_data['item_name']))


async def checking_payment(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    label = call.data[6:]
    info = get_unfinished_operation(label)

    if not info:
        await call.answer(text='❌ Invoice not found')
        return

    user_id_db, operation_value, invoice_message_id = info
    lang = get_user_language(user_id_db) or 'en'
    payment_status = await check_payment_status(label)
    if payment_status is None:
        payment_status = await check_payment(label)
    if payment_status not in ("success", "paid", "finished", "confirmed", "sending"):
        await call.answer(text='❌ Payment was not successful')
        return

    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
    referral_id = get_user_referral(user_id_db)
    finish_operation(label)

    purchase_data = TgConfig.STATE.pop(f'purchase_{label}', None)
    purchase_type = purchase_data.get('type', 'item') if purchase_data else 'topup'

    if purchase_type == 'cart':
        create_operation(user_id_db, operation_value, formatted_time)
        update_balance(user_id_db, operation_value)
        await _complete_cart_checkout(bot, user_id_db, lang, purchase_data, formatted_time, call, referral_id)
        with contextlib.suppress(Exception):
            await bot.delete_message(user_id_db, invoice_message_id or call.message.message_id)
        await call.answer()
        return

    create_operation(user_id_db, operation_value, formatted_time)
    update_balance(user_id_db, operation_value)

    if purchase_type == 'item' and purchase_data:
        await _complete_invoice_item_purchase(
            bot,
            call,
            user_id_db,
            lang,
            purchase_data,
            formatted_time,
            referral_id,
            invoice_message_id,
        )
        await call.answer()
        return

    message_id = invoice_message_id or call.message.message_id
    try:
        await bot.edit_message_text(
            chat_id=user_id_db,
            message_id=message_id,
            text=f'✅ Balance topped up by {operation_value}€',
            reply_markup=back('profile'),
        )
    except MessageNotModified:
        pass
    await bot.send_message(user_id_db, t(lang, 'top_up_completed'))
    if not has_user_achievement(user_id_db, 'first_topup'):
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        grant_achievement(user_id_db, 'first_topup', ts)
        await bot.send_message(user_id_db, t(lang, 'achievement_unlocked', name=t(lang, 'achievement_first_topup')))
        logger.info(f"User {user_id_db} unlocked achievement first_topup")

    username = f'@{call.from_user.username}' if call.from_user.username else call.from_user.full_name
    await bot.send_message(
        EnvKeys.OWNER_ID,
        f'User {username} topped up {operation_value}€'
    )
    await call.answer()


async def cancel_payment(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    invoice_id = call.data.split('_', 1)[1]
    info = get_unfinished_operation(invoice_id)
    lang = get_user_language(user_id) or 'en'
    if info:
        user_id_db, _, message_id = info
        finish_operation(invoice_id)
        purchase_data = TgConfig.STATE.pop(f'purchase_{invoice_id}', None)
        if purchase_data:
            if purchase_data.get('type') == 'cart':
                await _restore_reserved_units(bot, purchase_data.get('reserved', []))
                _clear_cart_checkout_state(user_id_db)
                cart_msg_id = purchase_data.get('cart_message_id')
                await update_cart_view(bot, user_id_db, cart_msg_id, user_id_db, lang)
            elif purchase_data.get('reserved'):
                reserved = purchase_data['reserved']
                remove_reservation(purchase_data['item'], reserved.get('expires_at'))
                if reserved and not reserved['is_infinity']:
                    was_empty = (
                        select_item_values_amount(purchase_data['item']) == 0
                        and not check_value(purchase_data['item'])
                    )
                    add_values_to_item(purchase_data['item'], reserved['value'], reserved['is_infinity'])
                    if was_empty:
                        await notify_restock(bot, purchase_data['item'])
        TgConfig.STATE.pop(f'{user_id_db}_pending_item', None)
        TgConfig.STATE.pop(f'{user_id_db}_price', None)
        TgConfig.STATE.pop(f'{user_id_db}_promo_applied', None)
        TgConfig.STATE.pop(f'{user_id_db}_deduct', None)
        try:
            await bot.delete_message(user_id_db, message_id)
        except Exception:
            pass
        reserve_msg_id = TgConfig.STATE.pop(f'{user_id_db}_reserve_msg', None)
        if reserve_msg_id:
            try:
                await bot.delete_message(user_id_db, reserve_msg_id)
            except Exception:
                pass
        await bot.send_message(user_id_db, t(lang, 'payment_cancelled'), reply_markup=home_markup(lang))
    else:
        await call.answer(text='❌ Invoice not found')


async def check_sub_to_channel(call: CallbackQuery):

    bot, user_id = await get_bot_user_ids(call)
    invoice_id = call.data.split('_', 1)[1]
    lang = get_user_language(user_id) or 'en'
    if get_unfinished_operation(invoice_id):
        finish_operation(invoice_id)
        purchase_data = TgConfig.STATE.pop(f'purchase_{invoice_id}', None)
        if purchase_data:
            if purchase_data.get('type') == 'cart':
                await _restore_reserved_units(bot, purchase_data.get('reserved', []))
                _clear_cart_checkout_state(user_id)
                cart_msg_id = purchase_data.get('cart_message_id')
                await update_cart_view(bot, user_id, cart_msg_id, user_id, lang)
            elif purchase_data.get('reserved'):
                reserved = purchase_data['reserved']
                remove_reservation(purchase_data['item'], reserved.get('expires_at'))
                if reserved and not reserved['is_infinity']:
                    was_empty = (
                        select_item_values_amount(purchase_data['item']) == 0
                        and not check_value(purchase_data['item'])
                    )
                    add_values_to_item(purchase_data['item'], reserved['value'], reserved['is_infinity'])
                    if was_empty:
                        await notify_restock(bot, purchase_data['item'])
        TgConfig.STATE.pop(f'{user_id}_pending_item', None)
        TgConfig.STATE.pop(f'{user_id}_price', None)
        TgConfig.STATE.pop(f'{user_id}_promo_applied', None)
        TgConfig.STATE.pop(f'{user_id}_deduct', None)
        reserve_msg_id = TgConfig.STATE.pop(f'{user_id}_reserve_msg', None)
        if reserve_msg_id:
            try:
                await bot.delete_message(user_id, reserve_msg_id)
            except Exception:
                pass
        await bot.edit_message_text(
            t(lang, 'invoice_cancelled'),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=back('replenish_balance'),
        )
    else:
        await call.answer(text='❌ Invoice not found')




async def change_language(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    current_lang = get_user_language(user_id) or 'en'
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton('English \U0001F1EC\U0001F1E7', callback_data='set_lang_en'),
        InlineKeyboardButton('Русский \U0001F1F7\U0001F1FA', callback_data='set_lang_ru'),
        InlineKeyboardButton('Lietuvi\u0173 \U0001F1F1\U0001F1F9', callback_data='set_lang_lt')
    )
    await bot.edit_message_text(
        t(current_lang, 'choose_language'),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup
    )


async def set_language(call: CallbackQuery):
    bot, user_id = await get_bot_user_ids(call)
    lang_code = call.data.split('_')[-1]
    update_user_language(user_id, lang_code)
    await call.message.delete()
    role = check_role(user_id)
    user = check_user(user_id)
    balance = user.balance if user else 0
    markup = main_menu(role, TgConfig.CHANNEL_URL, TgConfig.PRICE_LIST_URL, lang_code)
    purchases = select_user_items(user_id)
    text = build_menu_text(call.from_user, balance, purchases, user.purchase_streak, lang_code)

    try:
        with open(TgConfig.START_PHOTO_PATH, 'rb') as photo:
            await bot.send_photo(user_id, photo)
    except Exception:
        pass

    await bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=markup
    )






def register_user_handlers(dp: Dispatcher):
    dp.register_message_handler(start,
                                commands=['start'])
    dp.register_message_handler(
        process_captcha_answer,
        lambda m: TgConfig.STATE.get(m.from_user.id) == 'await_captcha',
        content_types=['text'],
        state='*'
    )

    dp.register_callback_query_handler(shop_callback_handler,
                                       lambda c: c.data == 'shop')
    dp.register_callback_query_handler(view_cart_callback_handler,
                                       lambda c: c.data == 'cart_view')
    dp.register_callback_query_handler(cart_manage_view_handler,
                                       lambda c: c.data == 'cart_manage')
    dp.register_callback_query_handler(cart_apply_promo_handler,
                                       lambda c: c.data == 'cart_apply_promo')
    dp.register_callback_query_handler(cart_remove_promo_handler,
                                       lambda c: c.data == 'cart_remove_promo')
    dp.register_callback_query_handler(cart_payment_choice_handler,
                                       lambda c: c.data.startswith('cartpay_'))
    dp.register_callback_query_handler(cart_checkout_handler,
                                       lambda c: c.data == 'cart_checkout')
    dp.register_callback_query_handler(cart_checkout_cancel,
                                       lambda c: c.data == 'cart_checkout_cancel')
    dp.register_callback_query_handler(add_to_cart_callback_handler,
                                       lambda c: c.data.startswith('cart_add_'))
    dp.register_callback_query_handler(remove_cart_item_callback_handler,
                                       lambda c: c.data.startswith('cart_remove_'))
    dp.register_callback_query_handler(clear_cart_callback_handler,
                                       lambda c: c.data == 'cart_clear')
    dp.register_callback_query_handler(dummy_button,
                                       lambda c: c.data == 'dummy_button')
    dp.register_callback_query_handler(profile_callback_handler,
                                       lambda c: c.data == 'profile')
    dp.register_callback_query_handler(gift_callback_handler,
                                       lambda c: c.data == 'gift')
    dp.register_callback_query_handler(quests_callback_handler,
                                       lambda c: c.data == 'quests')
    dp.register_callback_query_handler(achievements_callback_handler,
                                       lambda c: c.data.startswith('achievements'))
    dp.register_callback_query_handler(notify_stock_callback_handler,
                                       lambda c: c.data == 'notify_stock')
    dp.register_callback_query_handler(notify_category_callback_handler,
                                       lambda c: c.data.startswith('notify_cat_'))
    dp.register_callback_query_handler(notify_item_callback_handler,
                                       lambda c: c.data.startswith('notify_item_'))
    dp.register_callback_query_handler(rules_callback_handler,
                                       lambda c: c.data == 'rules')
    dp.register_callback_query_handler(help_callback_handler,
                                       lambda c: c.data == 'help')
    dp.register_callback_query_handler(replenish_balance_callback_handler,
                                       lambda c: c.data == 'replenish_balance')
    dp.register_callback_query_handler(price_list_callback_handler,
                                       lambda c: c.data == 'price_list')
    dp.register_callback_query_handler(blackjack_callback_handler,
                                       lambda c: c.data == 'blackjack')
    dp.register_callback_query_handler(blackjack_set_bet_handler,
                                       lambda c: c.data == 'blackjack_set_bet')
    dp.register_callback_query_handler(blackjack_place_bet_handler,
                                       lambda c: c.data == 'blackjack_place_bet')
    dp.register_callback_query_handler(blackjack_play_again_handler,
                                       lambda c: c.data.startswith('blackjack_play_'))
    dp.register_callback_query_handler(blackjack_move_handler,
                                       lambda c: c.data in ('blackjack_hit', 'blackjack_stand'))
    dp.register_callback_query_handler(blackjack_history_handler,
                                       lambda c: c.data.startswith('blackjack_history_'))
    dp.register_callback_query_handler(games_callback_handler,
                                       lambda c: c.data == 'games')
    dp.register_callback_query_handler(coinflip_callback_handler,
                                       lambda c: c.data == 'coinflip')
    dp.register_callback_query_handler(coinflip_play_bot_handler,
                                       lambda c: c.data == 'coinflip_bot')
    dp.register_callback_query_handler(coinflip_find_handler,
                                       lambda c: c.data == 'coinflip_find')
    dp.register_callback_query_handler(coinflip_create_handler,
                                       lambda c: c.data == 'coinflip_create')
    dp.register_callback_query_handler(coinflip_side_handler,
                                       lambda c: c.data.startswith('coinflip_side_'))
    dp.register_callback_query_handler(coinflip_create_confirm_handler,
                                       lambda c: c.data.startswith('coinflip_create_room_'))
    dp.register_callback_query_handler(coinflip_cancel_handler,
                                       lambda c: c.data.startswith('coinflip_cancel_'))
    dp.register_callback_query_handler(coinflip_room_handler,
                                       lambda c: c.data.startswith('coinflip_room_'))
    dp.register_callback_query_handler(coinflip_join_handler,
                                       lambda c: c.data.startswith('coinflip_join_'))
    dp.register_callback_query_handler(service_feedback_handler,
                                       lambda c: c.data.startswith('service_feedback_'), state='*')
    dp.register_callback_query_handler(product_feedback_handler,
                                       lambda c: c.data.startswith('product_feedback_'), state='*')
    dp.register_callback_query_handler(bought_items_callback_handler,
                                       lambda c: c.data == 'bought_items', state='*')
    dp.register_callback_query_handler(back_to_menu_callback_handler,
                                       lambda c: c.data == 'back_to_menu',
                                       state='*')
    dp.register_callback_query_handler(close_callback_handler,
                                       lambda c: c.data == 'close', state='*')
    dp.register_callback_query_handler(change_language,
                                       lambda c: c.data == 'change_language', state='*')
    dp.register_callback_query_handler(set_language,
                                       lambda c: c.data.startswith('set_lang_'), state='*')

    dp.register_callback_query_handler(navigate_bought_items,
                                       lambda c: c.data.startswith('bought-goods-page_'), state='*')
    dp.register_callback_query_handler(bought_item_info_callback_handler,
                                       lambda c: c.data.startswith('bought-item:'), state='*')
    dp.register_callback_query_handler(items_list_callback_handler,
                                       lambda c: c.data.startswith('category_'), state='*')
    dp.register_callback_query_handler(item_info_callback_handler,
                                       lambda c: c.data.startswith('item_'), state='*')
    dp.register_callback_query_handler(category_password_keep_handler,
                                       lambda c: c.data.startswith('pwdCkeep:'), state='*')
    dp.register_callback_query_handler(category_password_change_handler,
                                       lambda c: c.data.startswith('pwdCchg:'), state='*')
    dp.register_callback_query_handler(category_password_continue_handler,
                                       lambda c: c.data.startswith('pwdCgo:'), state='*')
    dp.register_callback_query_handler(confirm_buy_callback_handler,
                                       lambda c: c.data.startswith('confirm_'), state='*')
    dp.register_callback_query_handler(apply_promo_callback_handler,
                                       lambda c: c.data.startswith('applypromo_'), state='*')
    dp.register_callback_query_handler(buy_item_callback_handler,
                                       lambda c: c.data.startswith('buy_'), state='*')
    dp.register_callback_query_handler(pay_yoomoney,
                                       lambda c: c.data == 'pay_yoomoney', state='*')
    dp.register_callback_query_handler(crypto_payment,
                                       lambda c: c.data.startswith('crypto_'), state='*')
    dp.register_callback_query_handler(cancel_purchase,
                                       lambda c: c.data == 'cancel_purchase', state='*')
    dp.register_callback_query_handler(purchase_crypto_payment,
                                       lambda c: c.data.startswith('buycrypto_'), state='*')
    dp.register_callback_query_handler(cancel_payment,
                                       lambda c: c.data.startswith('cancel_'), state='*')
    dp.register_callback_query_handler(checking_payment,
                                       lambda c: c.data.startswith('check_'), state='*')
    dp.register_callback_query_handler(process_home_menu,
                                       lambda c: c.data == 'home_menu', state='*')

    dp.register_message_handler(process_replenish_balance,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'process_replenish_balance')
    dp.register_message_handler(process_promo_code,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'wait_promo')
    dp.register_message_handler(process_gift_username,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'gift_username')
    dp.register_message_handler(blackjack_receive_bet,
                                lambda c: TgConfig.STATE.get(c.from_user.id) == 'blackjack_enter_bet')
    dp.register_message_handler(coinflip_receive_bet,
                                lambda c: TgConfig.STATE.get(c.from_user.id) in ('coinflip_bot_enter_bet', 'coinflip_create_enter_bet'))
    dp.register_message_handler(
        category_password_input_handler,
        lambda m: isinstance(TgConfig.STATE.get(m.from_user.id), dict)
        and TgConfig.STATE[m.from_user.id].get('mode') == 'category_password_prompt',
        content_types=['text'],
        state='*'
    )
    dp.register_message_handler(
        category_password_change_message_handler,
        lambda m: isinstance(TgConfig.STATE.get(m.from_user.id), dict)
        and TgConfig.STATE[m.from_user.id].get('mode') == 'category_password_change',
        content_types=['text'],
        state='*'
    )
    dp.register_message_handler(pavogti,
                                commands=['pavogti'])
    dp.register_callback_query_handler(pavogti_item_callback,
                                       lambda c: c.data.startswith('pavogti_item_'))
