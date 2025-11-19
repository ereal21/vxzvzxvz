import datetime

import json

from typing import Sequence

import sqlalchemy
from sqlalchemy import exc, func

from bot.database.models import (
    Database,
    User,
    ItemValues,
    Goods,
    Categories,
    Role,
    BoughtGoods,
    Operations,
    UnfinishedOperations,
    PromoCode,
    Achievement,
    UserAchievement,
    StockNotification,
    Reseller,
    ResellerPrice,
    CartItem,
    CategoryPassword,
    UserCategoryPassword,
)
from bot.utils.reservations import has_active_reservation


def check_user(telegram_id: int) -> User | None:
    try:
        return Database().session.query(User).filter(User.telegram_id == telegram_id).one()
    except exc.NoResultFound:
        return None


def check_user_by_username(username: str) -> User | None:
    try:
        return Database().session.query(User).filter(User.username == username).one()
    except exc.NoResultFound:
        return None


def check_role(telegram_id: int) -> User | None:
    role_id = Database().session.query(User.role_id).filter(User.telegram_id == telegram_id).one()[0]
    return Database().session.query(Role.permissions).filter(Role.id == role_id).one()[0]


def check_role_name_by_id(role_id: int):
    return Database().session.query(Role.name).filter(Role.id == role_id).one()[0]


def get_role_id_by_name(role_name: str) -> int | None:
    """Return role id for the given name or None if not found."""
    try:
        return Database().session.query(Role.id).filter(Role.name == role_name).one()[0]
    except exc.NoResultFound:
        return None


def select_today_users(date: str) -> int | None:
    try:
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        start_of_day = datetime.datetime.combine(date_obj, datetime.time.min)
        end_of_day = datetime.datetime.combine(date_obj, datetime.time.max)

        return Database().session.query(User).filter(
            User.registration_date >= str(start_of_day),
            User.registration_date <= str(end_of_day)
        ).count()
    except exc.NoResultFound:
        return None


def get_user_count() -> int:
    return Database().session.query(User).count()


def select_admins() -> int | None:
    try:
        return Database().session.query(func.count()).filter(User.role_id > 1).scalar()
    except exc.NoResultFound:
        return None


def get_all_users() -> list[tuple[int]]:
    return Database().session.query(User.telegram_id).all()


def get_resellers() -> list[tuple[int, str | None]]:
    session = Database().session
    return session.query(User.telegram_id, User.username).join(
        Reseller, Reseller.user_id == User.telegram_id
    ).all()


def is_reseller(user_id: int) -> bool:
    return Database().session.query(Reseller).filter(Reseller.user_id == user_id).first() is not None


def item_in_stock(item_name: str) -> bool:
    """Return True if item has unlimited quantity or remaining stock."""
    if check_value(item_name):
        return True
    if select_item_values_amount(item_name) > 0:
        return True
    return has_active_reservation(item_name)


def get_all_categories() -> list[str]:
    """Return categories that contain at least one item in stock."""
    session = Database().session
    categories = [
        c[0]
        for c in session.query(Categories.name)
        .filter(Categories.parent_name.is_(None))
        .order_by(Categories.title)
        .all()
    ]
    result = []
    for name in categories:
        if get_all_items(name) or get_subcategories(name):
            result.append(name)
    return result


def get_all_category_names() -> list[str]:
    """Return all top-level categories regardless of contents."""
    session = Database().session
    return [
        c[0]
        for c in session.query(Categories.name)
        .filter(Categories.parent_name.is_(None))
        .order_by(Categories.title)
        .all()
    ]


def get_categories_with_lock_status() -> list[tuple[str, str, bool]]:
    """Return main categories with their lock status."""
    session = Database().session
    rows = (
        session.query(
            Categories.name,
            Categories.title,
            Categories.requires_password,
        )
        .filter(Categories.parent_name.is_(None))
        .order_by(Categories.title)
        .all()
    )
    return [
        (name, title or name, bool(locked)) for name, title, locked in rows
    ]


def get_all_subcategories(parent_name: str) -> list[str]:
    """Return all subcategories of a given category."""
    session = Database().session
    return [
        c[0]
        for c in session.query(Categories.name)
        .filter(Categories.parent_name == parent_name)
        .order_by(Categories.title)
        .all()
    ]


def get_subcategories(parent_name: str) -> list[str]:
    subs = [c[0] for c in Database().session.query(Categories.name)
            .filter(Categories.parent_name == parent_name).all()]
    result = []
    for sub in subs:
        if get_all_items(sub) or get_subcategories(sub):
            result.append(sub)
    return result


def get_category_parent(category_name: str) -> str | None:
    result = (Database().session.query(Categories.parent_name)
              .filter(Categories.name == category_name).first())
    return result[0] if result else None


def is_category_locked(category_name: str) -> bool:
    result = (
        Database()
        .session.query(Categories.requires_password)
        .filter(Categories.name == category_name)
        .first()
    )
    return bool(result[0]) if result else False


def get_category_title(name: str) -> str:
    result = (
        Database()
        .session.query(Categories.title)
        .filter(Categories.name == name)
        .first()
    )
    if not result:
        return name
    return result[0] or name


def get_category_titles(names: Sequence[str]) -> dict[str, str]:
    if not names:
        return {}
    session = Database().session
    rows = (
        session.query(Categories.name, Categories.title)
        .filter(Categories.name.in_(list(names)))
        .all()
    )
    return {name: title or name for name, title in rows}


def get_user_category_password(user_id: int, category_name: str) -> UserCategoryPassword | None:
    session = Database().session
    return (
        session.query(UserCategoryPassword)
        .filter(
            UserCategoryPassword.user_id == user_id,
            UserCategoryPassword.category_name == category_name,
        )
        .first()
    )


def get_generated_password(password: str, user_id: int | None = None) -> CategoryPassword | None:
    session = Database().session
    try:
        entry = (
            session.query(CategoryPassword)
            .filter(CategoryPassword.password == password)
            .one()
        )
    except exc.NoResultFound:
        return None
    if entry.used_by_user_id and user_id and entry.used_by_user_id != user_id:
        return None
    return entry


def get_category_password_by_id(entry_id: int) -> CategoryPassword | None:
    session = Database().session
    return (
        session.query(CategoryPassword)
        .filter(CategoryPassword.id == entry_id)
        .first()
    )


def list_users_with_category_passwords() -> list[tuple[int, str | None, int]]:
    session = Database().session
    rows = (
        session.query(
            UserCategoryPassword.user_id,
            User.username,
            func.count(UserCategoryPassword.id),
            func.max(UserCategoryPassword.updated_at),
        )
        .join(User, User.telegram_id == UserCategoryPassword.user_id)
        .group_by(UserCategoryPassword.user_id, User.username)
        .order_by(func.max(UserCategoryPassword.updated_at).desc())
        .all()
    )
    return [(user_id, username, count) for user_id, username, count, _ in rows]


def get_user_category_passwords(user_id: int) -> list[UserCategoryPassword]:
    session = Database().session
    return (
        session.query(UserCategoryPassword)
        .filter(UserCategoryPassword.user_id == user_id)
        .order_by(UserCategoryPassword.updated_at.desc())
        .all()
    )


def get_all_items(category_name: str) -> list[str]:
    items = [item[0] for item in
             Database().session.query(Goods.name)
             .filter(Goods.category_name == category_name).all()]
    return [name for name in items if item_in_stock(name)]


def get_all_item_names(category_name: str) -> list[str]:
    """Return all items for a category regardless of stock."""
    return [item[0] for item in
            Database().session.query(Goods.name)
            .filter(Goods.category_name == category_name).all()]


def get_out_of_stock_items(category_name: str) -> list[str]:
    """Return items in a category that currently have no stock."""
    items = get_all_item_names(category_name)
    result = []
    for name in items:
        if not item_in_stock(name):
            result.append(name)
    return result


def get_out_of_stock_categories() -> list[str]:
    """Return root categories containing any out-of-stock items."""
    categories = [c[0] for c in Database().session.query(Categories.name)
                  .filter(Categories.parent_name.is_(None)).all()]
    result = []
    for name in categories:
        if get_out_of_stock_items(name) or get_out_of_stock_subcategories(name):
            result.append(name)
    return result


def get_out_of_stock_subcategories(parent_name: str) -> list[str]:
    subs = [c[0] for c in Database().session.query(Categories.name)
            .filter(Categories.parent_name == parent_name).all()]
    result = []
    for sub in subs:
        if get_out_of_stock_items(sub) or get_out_of_stock_subcategories(sub):
            result.append(sub)
    return result


def get_bought_item_info(item_id: str) -> dict | None:
    result = Database().session.query(BoughtGoods).filter(BoughtGoods.id == item_id).first()
    return result.__dict__ if result else None


def get_item_info(item_name: str, user_id: int | None = None) -> dict | None:
    session = Database().session
    result = session.query(Goods).filter(Goods.name == item_name).first()
    if not result:
        return None
    data = result.__dict__.copy()
    if user_id is not None and is_reseller(user_id):
        price = session.query(ResellerPrice.price).filter_by(
            reseller_id=None, item_name=item_name
        ).first()
        if price:
            data['price'] = price[0]
    return data


def get_user_balance(telegram_id: int) -> float | None:
    result = Database().session.query(User.balance).filter(User.telegram_id == telegram_id).first()
    return result[0] if result else None


def get_user_language(telegram_id: int) -> str | None:
    result = Database().session.query(User.language).filter(User.telegram_id == telegram_id).first()
    return result[0] if result else None


def get_cart_items(user_id: int) -> list[CartItem]:
    session = Database().session
    return session.query(CartItem).filter(CartItem.user_id == user_id).all()


def get_cart_items_with_prices(user_id: int) -> list[tuple[CartItem, Goods]]:
    session = Database().session
    return (
        session.query(CartItem, Goods)
        .join(Goods, Goods.name == CartItem.item_name)
        .filter(CartItem.user_id == user_id)
        .all()
    )


def get_cart_total(user_id: int) -> float:
    session = Database().session
    rows = (
        session.query(CartItem.quantity, Goods.price)
        .join(Goods, Goods.name == CartItem.item_name)
        .filter(CartItem.user_id == user_id)
        .all()
    )
    return float(sum(quantity * price for quantity, price in rows))


def get_user_tickets(telegram_id: int) -> int:
    result = (Database().session.query(User.lottery_tickets)
              .filter(User.telegram_id == telegram_id).first())
    return result[0] if result else 0


def get_users_with_tickets() -> list[tuple[int, str | None, int]]:
    return Database().session.query(
        User.telegram_id, User.username, User.lottery_tickets
    ).filter(User.lottery_tickets > 0).all()


def has_user_achievement(user_id: int, code: str) -> bool:
    return Database().session.query(UserAchievement).filter_by(
        user_id=user_id, achievement_code=code
    ).first() is not None


def get_achievement_users(code: str) -> int:
    session = Database().session
    return session.query(func.count(UserAchievement.user_id)).filter(
        UserAchievement.achievement_code == code
    ).scalar()


def get_all_admins() -> list[int]:
    return [admin[0] for admin in Database().session.query(User.telegram_id).filter(User.role_id == 'ADMIN').all()]


def check_item(item_name: str) -> dict | None:
    result = Database().session.query(Goods).filter(Goods.name == item_name).first()
    return result.__dict__ if result else None


def check_category(category_name: str) -> dict | None:
    result = Database().session.query(Categories).filter(Categories.name == category_name).first()
    return result.__dict__ if result else None


def can_use_discount(item_name: str) -> bool:
    """Return True if item's main category allows discounts."""
    session = Database().session
    category_name = session.query(Goods.category_name).filter(Goods.name == item_name).scalar()
    if not category_name:
        return True
    while True:
        category = session.query(Categories.parent_name, Categories.allow_discounts) \
            .filter(Categories.name == category_name).first()
        if not category:
            return True
        parent, allow = category
        if parent is None:
            return bool(allow)
        category_name = parent


def can_get_referral_reward(item_name: str) -> bool:
    """Return True if item's main category allows referral rewards."""
    session = Database().session
    category_name = session.query(Goods.category_name).filter(Goods.name == item_name).scalar()
    if not category_name:
        return True
    while True:
        category = session.query(Categories.parent_name, Categories.allow_referral_rewards) \
            .filter(Categories.name == category_name).first()
        if not category:
            return True
        parent, allow = category
        if parent is None:
            return bool(allow)
        category_name = parent



def get_item_value(item_name: str) -> dict | None:
    result = Database().session.query(ItemValues).filter(ItemValues.item_name == item_name).first()
    return result.__dict__ if result else None


def get_item_values(item_name: str):
    return Database().session.query(ItemValues).filter(ItemValues.item_name == item_name).all()


def get_item_value_by_id(value_id: int) -> dict | None:
    result = Database().session.query(ItemValues).filter(ItemValues.id == value_id).first()
    return result.__dict__ if result else None


def select_item_values_amount(item_name: str) -> int:
    return Database().session.query(func.count()).filter(ItemValues.item_name == item_name).scalar()


def check_value(item_name: str) -> bool | None:
    try:
        result = False
        values = select_item_values_amount(item_name)
        for i in range(values):
            is_inf = Database().session.query(ItemValues).filter(ItemValues.item_name == item_name).first()
            if is_inf and is_inf.is_infinity:
                result = True
    except exc.NoResultFound:
        return False
    return result


def has_stock_notification(user_id: int, item_name: str) -> bool:
    return Database().session.query(StockNotification).filter_by(
        user_id=user_id, item_name=item_name
    ).first() is not None


def get_item_subscribers(item_name: str) -> list[int]:
    return [row[0] for row in Database().session.query(StockNotification.user_id)
            .filter(StockNotification.item_name == item_name).all()]


def select_user_items(buyer_id: int) -> int:
    return Database().session.query(func.count()).filter(BoughtGoods.buyer_id == buyer_id).scalar()


def select_bought_items(buyer_id: int) -> list[str]:
    return Database().session.query(BoughtGoods).filter(BoughtGoods.buyer_id == buyer_id).all()


def select_bought_item(unique_id: int) -> dict | None:
    result = Database().session.query(BoughtGoods).filter(BoughtGoods.unique_id == unique_id).first()
    return result.__dict__ if result else None


def bought_items_list(buyer_id: int) -> list[str]:
    return [
        item[0] for item in
        Database().session.query(BoughtGoods.item_name).filter(BoughtGoods.buyer_id == buyer_id).all()]


def get_purchase_dates() -> list[str]:
    return [d[0] for d in Database().session.query(func.date(BoughtGoods.bought_datetime)).distinct().all()]


def get_purchases_by_date(date: str) -> list[dict]:
    rows = (
        Database().session.query(BoughtGoods)
        .filter(func.date(BoughtGoods.bought_datetime) == date)
        .all()
    )
    return [r.__dict__ for r in rows]


def select_all_users() -> int:
    return Database().session.query(func.count()).filter(User).scalar()


def select_count_items() -> int:
    return Database().session.query(ItemValues).count()


def select_count_goods() -> int:
    return Database().session.query(Goods).count()


def select_count_categories() -> int:
    return Database().session.query(Categories).count()


def select_count_bought_items() -> int:
    return Database().session.query(BoughtGoods).count()


def select_today_orders(date: str) -> int | None:
    try:
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        start_of_day = datetime.datetime.combine(date_obj, datetime.time.min)
        end_of_day = datetime.datetime.combine(date_obj, datetime.time.max)

        return (
                Database().session.query(func.sum(BoughtGoods.price))
                .filter(
                    func.date(BoughtGoods.bought_datetime) >= start_of_day.date(),
                    func.date(BoughtGoods.bought_datetime) <= end_of_day.date()
                )
                .scalar() or 0
        )
    except exc.NoResultFound:
        return None


def select_all_orders() -> float:
    return Database().session.query(func.sum(BoughtGoods.price)).scalar() or 0


def select_today_operations(date: str) -> int | None:
    try:
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        start_of_day = datetime.datetime.combine(date_obj, datetime.time.min)
        end_of_day = datetime.datetime.combine(date_obj, datetime.time.max)

        return (
                Database().session.query(func.sum(Operations.operation_value))
                .filter(
                    func.date(Operations.operation_time) >= start_of_day.date(),
                    func.date(Operations.operation_time) <= end_of_day.date()
                )
                .scalar() or 0
        )
    except exc.NoResultFound:
        return None


def select_all_operations() -> float:
    return Database().session.query(func.sum(Operations.operation_value)).scalar() or 0


def select_users_balance() -> float:
    return Database().session.query(func.sum(User.balance)).scalar()


def select_user_operations(user_id: int) -> list[float]:
    return [operation[0] for operation in
            Database().session.query(Operations.operation_value).filter(Operations.user_id == user_id).all()]


def select_unfinished_operations(operation_id: str) -> list[int] | None:
    try:
        return Database().session.query(UnfinishedOperations.operation_value).filter(
            UnfinishedOperations.operation_id == operation_id).one()
    except sqlalchemy.exc.NoResultFound:
        return None


def get_unfinished_operation(operation_id: str) -> tuple[int, int, int | None] | None:
    """Return (user_id, operation_value, message_id) for unfinished operation."""
    result = (
        Database()
        .session.query(
            UnfinishedOperations.user_id,
            UnfinishedOperations.operation_value,
            UnfinishedOperations.message_id,
        )
        .filter(UnfinishedOperations.operation_id == operation_id)
        .first()
    )
    return (result.user_id, result.operation_value, result.message_id) if result else None


def get_user_unfinished_operation(user_id: int) -> tuple[str, int | None] | None:
    """Return (operation_id, message_id) for a user's unfinished operation."""
    result = (
        Database()
        .session.query(
            UnfinishedOperations.operation_id,
            UnfinishedOperations.message_id,
        )
        .filter(UnfinishedOperations.user_id == user_id)
        .first()
    )
    return (result.operation_id, result.message_id) if result else None


def check_user_referrals(user_id: int) -> list[int]:
    return Database().session.query(User).filter(User.referral_id == user_id).count()


def get_user_referral(user_id: int) -> int | None:
    result = Database().session.query(User.referral_id).filter(User.telegram_id == user_id).first()
    return result[0] if result else None


def sum_referral_operations(user_id: int) -> int:
    """Return total top-up amount from users referred by given user."""
    session = Database().session
    refs = session.query(User.telegram_id).filter(User.referral_id == user_id).all()
    total = 0
    for (ref_id,) in refs:
        ops_sum = (
            session.query(func.sum(Operations.operation_value))
            .filter(Operations.user_id == ref_id)
            .scalar()
        )
        total += ops_sum or 0
    return total


def get_promocode(code: str) -> dict | None:
    result = (
        Database()
        .session.query(PromoCode)
        .filter(PromoCode.code == code, PromoCode.active.is_(True))
        .first()
    )
    if not result:
        return None
    raw_items = result.applicable_items or ""
    try:
        items = json.loads(raw_items) if raw_items else []
    except json.JSONDecodeError:
        items = []
    return {
        'code': result.code,
        'discount': result.discount,
        'expires_at': result.expires_at,
        'active': result.active,
        'items': items,
    }


def get_promocode_items(code: str) -> list[str]:
    stored = (
        Database()
        .session.query(PromoCode.applicable_items)
        .filter(PromoCode.code == code)
        .scalar()
    )
    if not stored:
        return []
    try:
        return json.loads(stored)
    except json.JSONDecodeError:
        return []


def get_all_promocodes() -> list[PromoCode]:
    return Database().session.query(PromoCode).filter(PromoCode.active.is_(True)).all()
