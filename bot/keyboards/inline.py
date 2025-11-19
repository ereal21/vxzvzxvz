from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.database.models import Permission

from bot.localization import t
from bot.database.methods import get_category_parent, get_category_titles, select_item_values_amount
from bot.utils import display_name





def main_menu(role: int, channel: str = None, price: str = None, lang: str = 'en') -> InlineKeyboardMarkup:
    """Return main menu with layout:
       1) Shop
       2) Profile | Top Up
       3) Channel | Price List (only those that exist)
       4) Language
       (+ Admin panel if role > 1)
    """
    inline_keyboard = []

    # Row 1: Shop (single wide)
    inline_keyboard.append(
        [InlineKeyboardButton(t(lang, 'shop'), callback_data='shop')]
    )

    # Row 2: Profile | Top Up
    inline_keyboard.append([
        InlineKeyboardButton(t(lang, 'profile'), callback_data='profile'),
        InlineKeyboardButton(t(lang, 'view_cart'), callback_data='cart_view'),
    ])

    # Row 3: Channel | Price List (conditionally add one or both)
    row3 = []
    if channel:
        row3.append(InlineKeyboardButton(t(lang, 'channel'), url=channel))
    if price:
        row3.append(InlineKeyboardButton(t(lang, 'price_list'), callback_data='price_list'))
    if row3:
        inline_keyboard.append(row3)

    # Row 4: Language (single wide)
    inline_keyboard.append(
        [InlineKeyboardButton(t(lang, 'language'), callback_data='change_language')]
    )

    # Optional: Admin panel
    if role > 1:
        inline_keyboard.append(
            [InlineKeyboardButton(t(lang, 'admin_panel'), callback_data='console')]
        )

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def categories_list(list_items: list[str], lang: str | None = None, show_cart: bool = False) -> InlineKeyboardMarkup:
    """Show all categories without pagination."""
    markup = InlineKeyboardMarkup()
    titles = get_category_titles(list_items)
    for name in list_items:
        label = titles.get(name, name)
        markup.add(InlineKeyboardButton(text=label, callback_data=f'category_{name}'))
    if show_cart and lang:
        markup.add(InlineKeyboardButton(t(lang, 'view_cart'), callback_data='cart_view'))
    back_label = t(lang, 'back_to_menu') if lang else '🔙 Back to menu'
    markup.add(InlineKeyboardButton(back_label, callback_data='back_to_menu'))
    return markup


def goods_list(list_items: list[str], category_name: str, lang: str | None = None,
               parent: str | None = None) -> InlineKeyboardMarkup:
    """Show all goods for a category without pagination."""
    markup = InlineKeyboardMarkup()
    for name in list_items:
        markup.add(InlineKeyboardButton(text=display_name(name), callback_data=f'item_{name}'))
    if lang:
        markup.add(InlineKeyboardButton(t(lang, 'view_cart'), callback_data='cart_view'))
    back_parent = parent or get_category_parent(category_name)
    back_data = 'shop' if back_parent is None else f'category_{back_parent}'
    back_label = t(lang, 'back') if lang else '🔙 Go back'
    markup.add(InlineKeyboardButton(back_label, callback_data=back_data))
    return markup


def cart_overview_keyboard(lang: str, allow_promo: bool, promo_applied: bool) -> InlineKeyboardMarkup:
    """Main cart actions keyboard."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton(t(lang, 'cart_checkout'), callback_data='cart_checkout'))
    markup.row(
        InlineKeyboardButton(t(lang, 'cart_manage'), callback_data='cart_manage'),
        InlineKeyboardButton(t(lang, 'cart_clear'), callback_data='cart_clear'),
    )
    if allow_promo and not promo_applied:
        markup.add(InlineKeyboardButton(t(lang, 'cart_apply_promo'), callback_data='cart_apply_promo'))
    if promo_applied:
        markup.add(InlineKeyboardButton(t(lang, 'cart_remove_promo'), callback_data='cart_remove_promo'))
    markup.add(InlineKeyboardButton(t(lang, 'cart_back'), callback_data='shop'))
    return markup


def empty_cart_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup().add(
        InlineKeyboardButton(t(lang, 'cart_back'), callback_data='shop')
    )


def cart_manage_keyboard(items: list[tuple], lang: str) -> InlineKeyboardMarkup:
    """Cart management keyboard for removing items."""
    markup = InlineKeyboardMarkup(row_width=1)
    for cart_item, _ in items:
        name = display_name(cart_item.item_name)
        markup.add(
            InlineKeyboardButton(
                t(lang, 'cart_remove_line', name=name, quantity=cart_item.quantity),
                callback_data=f'cart_remove_{cart_item.item_name}'
            )
        )
    markup.add(InlineKeyboardButton(t(lang, 'cart_clear'), callback_data='cart_clear'))
    markup.add(InlineKeyboardButton(t(lang, 'cart_view_summary'), callback_data='cart_view'))
    markup.add(InlineKeyboardButton(t(lang, 'cart_back'), callback_data='shop'))
    return markup


def cart_payment_choice(lang: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(
        InlineKeyboardButton('SOL', callback_data='cartpay_SOL'),
        InlineKeyboardButton('BTC', callback_data='cartpay_BTC'),
    )
    markup.row(
        InlineKeyboardButton('TRX', callback_data='cartpay_TRX'),
        InlineKeyboardButton('TON', callback_data='cartpay_TON'),
    )
    markup.row(
        InlineKeyboardButton('USDT (TRC20)', callback_data='cartpay_USDTTRC20'),
        InlineKeyboardButton('ETH', callback_data='cartpay_ETH'),
    )
    markup.add(InlineKeyboardButton('LTC', callback_data='cartpay_LTC'))
    markup.add(InlineKeyboardButton(t(lang, 'cart_view_summary'), callback_data='cart_checkout_cancel'))
    return markup


def subcategories_list(list_items: list[str], parent: str, lang: str | None = None,
                       show_cart: bool = False) -> InlineKeyboardMarkup:
    """Show all subcategories without pagination."""
    markup = InlineKeyboardMarkup()
    titles = get_category_titles(list_items)
    for name in list_items:
        label = titles.get(name, name)
        markup.add(InlineKeyboardButton(text=label, callback_data=f'category_{name}'))
    if show_cart and lang:
        markup.add(InlineKeyboardButton(t(lang, 'view_cart'), callback_data='cart_view'))
    back_parent = get_category_parent(parent)
    back_data = 'shop' if back_parent is None else f'category_{back_parent}'
    back_label = t(lang, 'back') if lang else '🔙 Go back'
    markup.add(InlineKeyboardButton(back_label, callback_data=back_data))
    return markup


def notify_categories_list(list_items: list[str], lang: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    titles = get_category_titles(list_items)
    for name in list_items:
        label = titles.get(name, name)
        markup.add(InlineKeyboardButton(text=label, callback_data=f'notify_cat_{name}'))
    markup.add(InlineKeyboardButton(t(lang, 'back'), callback_data='profile'))
    return markup


def notify_subcategories_list(list_items: list[str], parent: str, lang: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    titles = get_category_titles(list_items)
    for name in list_items:
        label = titles.get(name, name)
        markup.add(InlineKeyboardButton(text=label, callback_data=f'notify_cat_{name}'))
    back_parent = get_category_parent(parent)
    back_data = 'notify_stock' if back_parent is None else f'notify_cat_{back_parent}'
    markup.add(InlineKeyboardButton(t(lang, 'back'), callback_data=back_data))
    return markup


def notify_goods_list(list_items: list[str], category_name: str, lang: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for name in list_items:
        markup.add(InlineKeyboardButton(text=display_name(name), callback_data=f'notify_item_{name}'))
    back_parent = get_category_parent(category_name)
    back_data = 'notify_stock' if back_parent is None else f'notify_cat_{back_parent}'
    markup.add(InlineKeyboardButton(t(lang, 'back'), callback_data=back_data))
    return markup


def user_items_list(list_items: list, data: str, back_data: str, pre_back: str, current_index: int, max_index: int)\
        -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    page_items = list_items[current_index * 10: (current_index + 1) * 10]
    for item in page_items:
        markup.add(InlineKeyboardButton(text=display_name(item.item_name), callback_data=f'bought-item:{item.id}:{pre_back}'))
    if max_index > 0:
        buttons = [
            InlineKeyboardButton(text='◀️', callback_data=f'bought-goods-page_{current_index - 1}_{data}'),
            InlineKeyboardButton(text=f'{current_index + 1}/{max_index + 1}', callback_data='dummy_button'),
            InlineKeyboardButton(text='▶️', callback_data=f'bought-goods-page_{current_index + 1}_{data}')
        ]
        markup.row(*buttons)
    markup.add(InlineKeyboardButton('🔙 Go back', callback_data=back_data))
    return markup


def item_info(item_name: str, category_name: str, lang: str) -> InlineKeyboardMarkup:
    """Return inline keyboard for a single item."""
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'buy_now'), callback_data=f'confirm_{item_name}')],
        [InlineKeyboardButton(t(lang, 'add_to_cart'), callback_data=f'cart_add_{item_name}')],
        [InlineKeyboardButton(t(lang, 'back'), callback_data=f'category_{category_name}')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def profile(user_items: int = 0, lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'games'), callback_data='games')],
        [InlineKeyboardButton(t(lang, 'achievements'), callback_data='achievements')],
        [InlineKeyboardButton(t(lang, 'quests'), callback_data='quests')],
        [InlineKeyboardButton(t(lang, 'top_up'), callback_data='replenish_balance')],
        [InlineKeyboardButton(t(lang, 'gift'), callback_data='gift')],
        [InlineKeyboardButton(t(lang, 'stock_notify'), callback_data='notify_stock')],
    ]
    if user_items != 0:
        inline_keyboard.append([
            InlineKeyboardButton(t(lang, 'purchased_items'), callback_data='bought_items')
        ])
    inline_keyboard.append([InlineKeyboardButton(t(lang, 'help'), callback_data='help')])
    inline_keyboard.append([InlineKeyboardButton(t(lang, 'back_to_menu'), callback_data='back_to_menu')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def games_menu(lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'blackjack'), callback_data='blackjack')],
        [InlineKeyboardButton(t(lang, 'back'), callback_data='profile')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def achievements_menu(page: int, total: int, lang: str = 'en', unlocked: bool = False) -> InlineKeyboardMarkup:
    prefix = 'achievements_unlocked' if unlocked else 'achievements'
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton('⬅️', callback_data=f'{prefix}:{page-1}'))
    if (page + 1) * 5 < total:
        nav.append(InlineKeyboardButton('➡️', callback_data=f'{prefix}:{page+1}'))
    rows = [nav] if nav else []
    toggle_label = t(lang, 'show_locked') if unlocked else t(lang, 'show_unlocked')
    toggle_cb = 'achievements:0' if unlocked else 'achievements_unlocked:0'
    rows.append([InlineKeyboardButton(toggle_label, callback_data=toggle_cb)])
    rows.append([InlineKeyboardButton(t(lang, 'back'), callback_data='profile')])
    return InlineKeyboardMarkup(inline_keyboard=rows)




def coinflip_menu(lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'find_game'), callback_data='coinflip_find')],
        [InlineKeyboardButton(t(lang, 'create_game'), callback_data='coinflip_create')],
        [InlineKeyboardButton(t(lang, 'play_bot'), callback_data='coinflip_bot')],
        [InlineKeyboardButton(t(lang, 'back'), callback_data='games')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def coinflip_side_menu(lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'heads'), callback_data='coinflip_side_heads')],
        [InlineKeyboardButton(t(lang, 'tails'), callback_data='coinflip_side_tails')],
        [InlineKeyboardButton(t(lang, 'back'), callback_data='coinflip')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def coinflip_create_confirm_menu(side: str, bet: int, lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'create'), callback_data=f'coinflip_create_room_{side}_{bet}')],
        [InlineKeyboardButton(t(lang, 'back'), callback_data='coinflip')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def coinflip_waiting_menu(room_id: int, lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'cancel'), callback_data=f'coinflip_cancel_{room_id}')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def coinflip_rooms_menu(rooms: dict[int, dict], lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = []
    for room_id, data in rooms.items():
        side = t(lang, data['side'])
        text = f"{data['creator_name']} – {data['bet']}€ ({side})"
        inline_keyboard.append([InlineKeyboardButton(text, callback_data=f'coinflip_room_{room_id}')])
    inline_keyboard.append([InlineKeyboardButton(t(lang, 'back'), callback_data='coinflip')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def coinflip_join_confirm_menu(room_id: int, lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'join'), callback_data=f'coinflip_join_{room_id}')],
        [InlineKeyboardButton(t(lang, 'back'), callback_data='coinflip_find')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def rules() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🔙 Back to menu', callback_data='back_to_menu')
         ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def console(role: int) -> InlineKeyboardMarkup:
    assistant_role = Permission.USE | Permission.ASSIGN_PHOTOS
    if role == assistant_role:
        inline_keyboard = [
            [InlineKeyboardButton('🖼 Priskirti nuotraukas', callback_data='assign_photos')],
            [InlineKeyboardButton('❓ Pagalba', callback_data='admin_help')],
            [InlineKeyboardButton('🔙 Grįžti į meniu', callback_data='back_to_menu')]
        ]
        return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

    inline_keyboard = [
        [InlineKeyboardButton('🏪 Parduotuvės valdymas', callback_data='shop_management')],
        [InlineKeyboardButton('ℹ️ Informacija', callback_data='information')],
        [InlineKeyboardButton('🧰 Įrankiai', callback_data='miscs')],
    ]
    if role & Permission.OWN:
        inline_keyboard.append([InlineKeyboardButton('🔐 Slaptažodžiai', callback_data='passwords_menu')])
    inline_keyboard.append([InlineKeyboardButton('❓ Pagalba', callback_data='admin_help')])
    inline_keyboard.append([InlineKeyboardButton('🔙 Grįžti į meniu', callback_data='back_to_menu')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def passwords_menu() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🧾 Generuoti slaptažodžius', callback_data='passwords_generate')],
        [InlineKeyboardButton('🔒 Užrakinti kategorijas', callback_data='passwords_lock')],
        [InlineKeyboardButton('👥 Vartotojų slaptažodžiai', callback_data='passwords_view_users')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def passwords_lock_keyboard(entries: list[tuple[str, str, bool]]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for name, title, locked in entries:
        icon = '🔒' if locked else '🔓'
        markup.add(InlineKeyboardButton(f'{icon} {title}', callback_data=f'pwd_lock:{name}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='passwords_menu'))
    return markup


def passwords_users_keyboard(users: list[tuple[int, str | None, int]]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for user_id, username, count in users:
        label = f'@{username}' if username else str(user_id)
        markup.add(InlineKeyboardButton(f'{label} ({count})', callback_data=f'pwd_user:{user_id}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='passwords_menu'))
    return markup


def passwords_user_detail_keyboard(user_id: int, entries: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for category_name, title in entries:
        markup.row(
            InlineKeyboardButton('✏️ ' + title, callback_data=f'pwdUchg:{user_id}:{category_name}'),
            InlineKeyboardButton('🗑️ ' + title, callback_data=f'pwdUdel:{user_id}:{category_name}'),
        )
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='passwords_view_users'))
    return markup


def category_password_options(category_name: str, lang: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(t(lang, 'passwords_change'), callback_data=f'pwdCchg:{category_name}'),
        InlineKeyboardButton(t(lang, 'passwords_keep'), callback_data=f'pwdCkeep:{category_name}'),
    )
    markup.add(InlineKeyboardButton(t(lang, 'back_to_menu'), callback_data='shop'))
    return markup


def category_password_continue_keyboard(category_name: str, lang: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(t(lang, 'passwords_continue'), callback_data=f'pwdCgo:{category_name}'))
    return markup


def confirm_purchase_menu(item_name: str, lang: str, show_promo: bool = True) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'purchase_button'), callback_data=f'buy_{item_name}')]
    ]
    if show_promo:
        inline_keyboard.append(
            [InlineKeyboardButton(t(lang, 'apply_promo'), callback_data=f'applypromo_{item_name}')]
        )
    inline_keyboard.append([InlineKeyboardButton(t(lang, 'back_to_menu'), callback_data=f'item_{item_name}')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def user_management(admin_role: int, user_role: int, admin_manage: int, items: int, user_id: int) \
        -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('💸 Papildyti balansą', callback_data=f'fill-user-balance_{user_id}')]
    ]
    if items > 0:
        inline_keyboard.append([InlineKeyboardButton('🎁 Įsigytos prekės', callback_data=f'user-items_{user_id}')])
    if admin_role >= admin_manage and admin_role > user_role:
        if user_role == 1:
            inline_keyboard.append(
                [InlineKeyboardButton('⬆️ Suteikti adminą', callback_data=f'set-admin_{user_id}')])
        else:
            inline_keyboard.append(
                [InlineKeyboardButton('⬇️ Pašalinti adminą', callback_data=f'remove-admin_{user_id}')])
    inline_keyboard.append([InlineKeyboardButton('🔙 Grįžti atgal', callback_data='user_management')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def purchases_dates_list(dates: list[str]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for d in dates:
        markup.add(InlineKeyboardButton(d, callback_data=f'purchases_date_{d}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console'))
    return markup


def purchases_list(purchases: list[dict], date: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for p in purchases:
        markup.add(
            InlineKeyboardButton(
                f"{p['unique_id']} - {display_name(p['item_name'])}",
                callback_data=f"purchase_{p['unique_id']}_{date}"
            )
        )
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data='pirkimai'))
    return markup


def purchase_info_menu(purchase_id: int, date: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('👁 Peržiūrėti failą', callback_data=f'view_purchase_{purchase_id}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=f'purchases_date_{date}'))
    return markup


def user_manage_check(user_id: int) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('✅ Taip', callback_data=f'check-user_{user_id}')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='user_management')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def shop_management(role: int) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('📦 Prekių įpakavimas', callback_data='goods_management')],
        [InlineKeyboardButton('🗂️ Kategorijų kūrimas', callback_data='categories_management')],
        [InlineKeyboardButton('🛠️ Katalogo redagavimas', callback_data='catalog_editor')],
        [InlineKeyboardButton('🏷️ Nuolaidų kodai', callback_data='promo_management')],
        [InlineKeyboardButton('🤝 Reselleriai', callback_data='resellers_management')],
        [InlineKeyboardButton('📢 Pranešimų siuntimas', callback_data='send_message')],
    ]
    if role & Permission.OWN:
        inline_keyboard.append([InlineKeyboardButton('🗄️ Tvarkyti atsargas', callback_data='manage_stock')])
        inline_keyboard.append([InlineKeyboardButton('🛠️ Asistentų priskyrimas', callback_data='assistant_management')])
        inline_keyboard.append([InlineKeyboardButton('👑 Savininkų priskyrimas', callback_data='owner_management')])
    inline_keyboard.append([InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def information_menu(role: int) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('👥 Vartotojų valdymas', callback_data='user_management')],
        [InlineKeyboardButton('📝 Logai', callback_data='show_logs')],
        [InlineKeyboardButton('📊 Statistikos', callback_data='statistics')],
        [InlineKeyboardButton('🛒 Pirkimai', callback_data='pirkimai')],

    ]
    if role & Permission.OWN:
        inline_keyboard.append([InlineKeyboardButton('📦 Peržiūrėti atsargas', callback_data='view_stock')])
    inline_keyboard.append([InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def miscs_menu() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🎟️ Loterija', callback_data='lottery')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def lottery_menu() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('📋 Peržiūrėti bilietus', callback_data='view_tickets')],
        [InlineKeyboardButton('🎰 Vykdyti loteriją', callback_data='run_lottery')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='miscs')],
    ]
    if role & Permission.OWN:
        inline_keyboard.append([InlineKeyboardButton('📦 Peržiūrėti atsargas', callback_data='view_stock')])
    inline_keyboard.append([InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def miscs_menu() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🎟️ Loterija', callback_data='lottery')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def lottery_menu() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('📋 Peržiūrėti bilietus', callback_data='view_tickets')],
        [InlineKeyboardButton('🎰 Vykdyti loteriją', callback_data='run_lottery')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='miscs')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def lottery_run_menu(lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'confirm'), callback_data='lottery_confirm')],
        [InlineKeyboardButton(t(lang, 'rerun'), callback_data='lottery_rerun')],
        [InlineKeyboardButton(t(lang, 'cancel'), callback_data='lottery_cancel')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def lottery_broadcast_menu(role: int, lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = []
    if role & Permission.OWN:
        inline_keyboard.append([InlineKeyboardButton(t(lang, 'yes'), callback_data='lottery_broadcast_yes')])
    inline_keyboard.append([InlineKeyboardButton(t(lang, 'no'), callback_data='lottery_broadcast_no')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def information_menu(role: int) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('👥 Vartotojų valdymas', callback_data='user_management')],
        [InlineKeyboardButton('📝 Logai', callback_data='show_logs')],
        [InlineKeyboardButton('📊 Statistikos', callback_data='statistics')],
        [InlineKeyboardButton('🛒 Pirkimai', callback_data='pirkimai')],
    ]
    if role & Permission.OWN:
        inline_keyboard.append([InlineKeyboardButton('📦 Peržiūrėti atsargas', callback_data='view_stock')])
    inline_keyboard.append([InlineKeyboardButton('🔙 Grįžti atgal', callback_data='console')])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def goods_management() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('➕ Pridėti prekę', callback_data='item-management')],
        [InlineKeyboardButton('🖼 Priskirti nuotraukas', callback_data='assign_photos')],
        [InlineKeyboardButton('🗑️ Pašalinti prekę', callback_data='delete_item')],
        [InlineKeyboardButton('🛒 Nupirktų prekių informacija', callback_data='show_bought_item')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='shop_management')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)



def item_management() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🆕 Sukurti prekę', callback_data='add_item')],
        [InlineKeyboardButton('➕ Pridėti prie esamos prekės', callback_data='update_item_amount')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='goods_management')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def categories_management() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🗃️ Sukurti pagrindinę kategoriją', callback_data='add_main_category')],
        [InlineKeyboardButton('📁 Pridėti kategoriją', callback_data='add_category')],
        [InlineKeyboardButton('📂 Pridėti subkategoriją', callback_data='add_subcategory')],
        [InlineKeyboardButton('🗑️ Pašalinti kategoriją', callback_data='delete_category')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='shop_management')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def catalog_editor_menu(lang: str = 'en') -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'catalog_editor_button_main'), callback_data='catalog_edit_main')],
        [InlineKeyboardButton(t(lang, 'catalog_editor_button_category'), callback_data='catalog_edit_category')],
        [InlineKeyboardButton(t(lang, 'catalog_editor_button_item'), callback_data='catalog_edit_item')],
        [InlineKeyboardButton(t(lang, 'back'), callback_data='shop_management')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def resellers_management() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('➕ Pridėti resellerį', callback_data='reseller_add')],
        [InlineKeyboardButton('➖ Išimti resellerį', callback_data='reseller_remove')],
        [InlineKeyboardButton('🏷️ Taikyti kainas', callback_data='reseller_prices')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='shop_management')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def resellers_list(resellers: list[tuple[int, str | None]], action: str, back_data: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for user_id, username in resellers:
        name = f'@{username}' if username else str(user_id)
        markup.add(InlineKeyboardButton(name, callback_data=f'{action}_{user_id}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=back_data))
    return markup


def promo_codes_management() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('➕ Sukurti nuolaidos kodą', callback_data='create_promo')],
        [InlineKeyboardButton('🗑️ Ištrinti nuolaidos kodą', callback_data='delete_promo')],
        [InlineKeyboardButton('🛠 Tvarkyti nuolaidos kodą', callback_data='manage_promo')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='shop_management')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def promo_expiry_keyboard(back_data: str) -> InlineKeyboardMarkup:
    """Keyboard to choose promo code expiry units."""
    inline_keyboard = [
        [InlineKeyboardButton('Dienos', callback_data='promo_expiry_days')],
        [InlineKeyboardButton('Savaitės', callback_data='promo_expiry_weeks')],
        [InlineKeyboardButton('Mėnesiai', callback_data='promo_expiry_months')],
        [InlineKeyboardButton('Be galiojimo', callback_data='promo_expiry_none')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data=back_data)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def promo_codes_list(codes: list[str], action: str, back_data: str) -> InlineKeyboardMarkup:
    """Create a list of promo codes with callback prefix."""
    markup = InlineKeyboardMarkup()
    for code in codes:
        markup.add(InlineKeyboardButton(code, callback_data=f'{action}_{code}'))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=back_data))
    return markup


def promo_manage_actions(code: str) -> InlineKeyboardMarkup:
    """Keyboard with actions for a single promo code."""
    inline_keyboard = [
        [InlineKeyboardButton('✏️ Pakeisti nuolaidą', callback_data=f'promo_manage_discount_{code}')],
        [InlineKeyboardButton('⏰ Pakeisti galiojimą', callback_data=f'promo_manage_expiry_{code}')],
        [InlineKeyboardButton('🎯 Valdyti prekes', callback_data=f'promo_manage_items_{code}')],
        [InlineKeyboardButton('🗑️ Ištrinti', callback_data=f'promo_manage_delete_{code}')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data='manage_promo')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def stock_categories_list(list_items: list[str], parent: str | None, root_cb: str = 'console') -> InlineKeyboardMarkup:
    """List categories or subcategories for stock view."""
    markup = InlineKeyboardMarkup()
    for name in list_items:
        markup.add(InlineKeyboardButton(text=name, callback_data=f'stock_cat:{name}'))
    back_data = root_cb if parent is None else f'stock_cat:{parent}'



    back_data = root_cb if parent is None else f'stock_cat:{parent}'

    back_data = 'console' if parent is None else f'stock_cat:{parent}'


    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=back_data))
    return markup


def stock_goods_list(list_items: list[str], category_name: str, root_cb: str = 'console') -> InlineKeyboardMarkup:
    """Show goods with stock counts for a category."""
    markup = InlineKeyboardMarkup()
    for name in list_items:
        amount = select_item_values_amount(name)
        markup.add(InlineKeyboardButton(
            text=f'{display_name(name)} ({amount})',
            callback_data=f'stock_item:{name}:{category_name}'
        ))
    parent = get_category_parent(category_name)
    back_data = root_cb if parent is None else f'stock_cat:{parent}'



    back_data = root_cb if parent is None else f'stock_cat:{parent}'

    back_data = 'console' if parent is None else f'stock_cat:{parent}'

    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=back_data))
    return markup


def stock_values_list(values, item_name: str, category_name: str) -> InlineKeyboardMarkup:
    """List individual stock entries for an item."""
    markup = InlineKeyboardMarkup()
    for val in values:
        markup.add(InlineKeyboardButton(
            text=f'ID {val.id}',
            callback_data=f'stock_val:{val.id}:{item_name}:{category_name}'
        ))
    markup.add(InlineKeyboardButton('🔙 Grįžti atgal', callback_data=f'stock_item:{item_name}:{category_name}'))
    return markup


def stock_value_actions(value_id: int, item_name: str, category_name: str) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🗑️ Ištrinti', callback_data=f'stock_del:{value_id}:{item_name}:{category_name}')],
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data=f'stock_item:{item_name}:{category_name}')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)



def close() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('Hide', callback_data='close')
         ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def check_sub(channel_username: str) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('Subscribe', url=f'https://t.me/{channel_username}')
         ],
        [InlineKeyboardButton('Check', callback_data='sub_channel_done')
         ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def back(callback: str) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🔙 Grįžti atgal', callback_data=callback)]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def payment_menu(url: str, label: str, lang: str) -> InlineKeyboardMarkup:
    """Return markup for fiat payment invoices."""
    inline_keyboard = [
        [InlineKeyboardButton('✅ Pay', url=url)],
        [InlineKeyboardButton('🔄 Check payment', callback_data=f'check_{label}')],
        [InlineKeyboardButton(t(lang, 'cancel_payment'), callback_data=f'cancel_{label}')],
        [InlineKeyboardButton('🔙 Go back', callback_data='back_to_menu')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def crypto_invoice_menu(invoice_id: str, lang: str) -> InlineKeyboardMarkup:
    """Return markup for crypto invoice."""
    inline_keyboard = [
        [InlineKeyboardButton(t(lang, 'cart_invoice_check'), callback_data=f'check_{invoice_id}')],
        [InlineKeyboardButton(t(lang, 'cancel_payment'), callback_data=f'cancel_{invoice_id}')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def confirm_cancel(invoice_id: str, lang: str) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('✅ Yes', callback_data=f'confirm_cancel_{invoice_id}')],
        [InlineKeyboardButton('🔙 Back', callback_data=f'check_{invoice_id}')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def crypto_choice() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('SOL', callback_data='crypto_SOL'),
         InlineKeyboardButton('BTC', callback_data='crypto_BTC')],
        [InlineKeyboardButton('TRX', callback_data='crypto_TRX'),
         InlineKeyboardButton('TON', callback_data='crypto_TON')],
        [InlineKeyboardButton('USDT (TRC20)', callback_data='crypto_USDTTRC20'),
         InlineKeyboardButton('ETH', callback_data='crypto_ETH')],
        [InlineKeyboardButton('LTC', callback_data='crypto_LTC')],
        [InlineKeyboardButton('🔙 Go back', callback_data='replenish_balance')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def crypto_choice_purchase(item_name: str, lang: str) -> InlineKeyboardMarkup:
    """Return crypto choice markup for product purchase."""
    inline_keyboard = [
        [InlineKeyboardButton('SOL', callback_data='buycrypto_SOL'),
         InlineKeyboardButton('BTC', callback_data='buycrypto_BTC')],
        [InlineKeyboardButton('TRX', callback_data='buycrypto_TRX'),
         InlineKeyboardButton('TON', callback_data='buycrypto_TON')],
        [InlineKeyboardButton('USDT (TRC20)', callback_data='buycrypto_USDTTRC20'),
         InlineKeyboardButton('ETH', callback_data='buycrypto_ETH')],
        [InlineKeyboardButton('LTC', callback_data='buycrypto_LTC')],
        [InlineKeyboardButton(t(lang, 'cancel'), callback_data='cancel_purchase')],
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def reset_config(key: str) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(f'Reset {key}', callback_data=f'reset_{key}')
         ],
        [InlineKeyboardButton('🔙 Go back', callback_data='settings')
         ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def question_buttons(question: str, back_data: str) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('✅ Yes', callback_data=f'{question}_yes'),
         InlineKeyboardButton('❌ No', callback_data=f'{question}_no')
         ],
        [InlineKeyboardButton('🔙 Go back', callback_data=back_data)
         ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def blackjack_controls() -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton('🃏 Hit', callback_data='blackjack_hit'),
         InlineKeyboardButton('🛑 Stand', callback_data='blackjack_stand')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def blackjack_bet_input_menu(bet: int | None = None) -> InlineKeyboardMarkup:
    bet_text = f'🎲 Bet! ({bet}€)' if bet else '🎲 Bet!'
    inline_keyboard = [
        [InlineKeyboardButton(bet_text, callback_data='blackjack_place_bet')],
        [InlineKeyboardButton('💵 Set Bet', callback_data='blackjack_set_bet')],
        [InlineKeyboardButton('📜 History', callback_data='blackjack_history_0')],
        [InlineKeyboardButton('🔙 Back to menu', callback_data='back_to_menu')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def blackjack_end_menu(bet: int) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(f'▶️ Play Again ({bet}€)', callback_data=f'blackjack_play_{bet}')],
        [InlineKeyboardButton('🔙 Back to menu', callback_data='blackjack')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def blackjack_history_menu(index: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    if index > 0:
        buttons.append(InlineKeyboardButton('◀️', callback_data=f'blackjack_history_{index-1}'))
    buttons.append(InlineKeyboardButton(f'{index+1}/{total}', callback_data='dummy_button'))
    if index < total - 1:
        buttons.append(InlineKeyboardButton('▶️', callback_data=f'blackjack_history_{index+1}'))
    inline_keyboard = [buttons, [InlineKeyboardButton('🔙 Back', callback_data='blackjack')]]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def feedback_menu(prefix: str) -> InlineKeyboardMarkup:
    """Return 1-5 star rating buttons arranged vertically."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton("⭐" * i, callback_data=f"{prefix}_{i}")]
            for i in range(1, 6)
        ]
    )


def feedback_reason_menu(prefix: str, lang: str) -> InlineKeyboardMarkup:
    """Return Yes/No menu asking whether to provide feedback text."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(t(lang, 'yes'), callback_data=f'{prefix}_yes'),
        InlineKeyboardButton(t(lang, 'no'), callback_data=f'{prefix}_no'),
    ]])
