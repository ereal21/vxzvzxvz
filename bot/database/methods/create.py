import datetime
import json
import random
from typing import Sequence

import sqlalchemy.exc

from bot.database.models import (
    User,
    ItemValues,
    Goods,
    Categories,
    BoughtGoods,
    Operations,
    UnfinishedOperations,
    PromoCode,
    UserAchievement,
    StockNotification,
    Reseller,
    ResellerPrice,
    CartItem,
    CategoryPassword,
)
from bot.database import Database


def create_user(telegram_id: int, registration_date, referral_id, role: int = 1,
                language: str | None = None, username: str | None = None) -> None:
    session = Database().session
    try:
        user = session.query(User).filter(User.telegram_id == telegram_id).one()
        if user.username != username:
            user.username = username
            session.commit()
    except sqlalchemy.exc.NoResultFound:
        if referral_id != '':
            session.add(
                User(telegram_id=telegram_id, role_id=role, registration_date=registration_date,
                     referral_id=referral_id, language=language, username=username))
            session.commit()
        else:
            session.add(
                User(telegram_id=telegram_id, role_id=role, registration_date=registration_date,
                     referral_id=None, language=language, username=username))
            session.commit()


def create_item(item_name: str, item_description: str, item_price: int, category_name: str,
                delivery_description: str | None = None) -> None:
    session = Database().session
    session.add(
        Goods(name=item_name, description=item_description, price=item_price,
              category_name=category_name, delivery_description=delivery_description))
    session.commit()


def add_values_to_item(item_name: str, value: str, is_infinity: bool) -> None:
    session = Database().session
    if is_infinity is False:
        session.add(
            ItemValues(name=item_name, value=value, is_infinity=False))
    else:
        session.add(
            ItemValues(name=item_name, value=value, is_infinity=True))
    session.commit()


def create_category(
    category_name: str,
    parent: str | None = None,
    allow_discounts: bool = True,
    allow_referral_rewards: bool = True,
    title: str | None = None,
) -> None:
    session = Database().session
    session.add(
        Categories(
            name=category_name,
            title=title or category_name,
            parent_name=parent,
            allow_discounts=allow_discounts,
            allow_referral_rewards=allow_referral_rewards,
        )
    )
    session.commit()


def create_operation(user_id: int, value: int, operation_time: str) -> None:
    session = Database().session
    session.add(
        Operations(user_id=user_id, operation_value=value, operation_time=operation_time))
    session.commit()


def start_operation(user_id: int, value: int, operation_id: str, message_id: int | None = None) -> None:
    session = Database().session
    session.add(
        UnfinishedOperations(user_id=user_id, operation_value=value, operation_id=operation_id, message_id=message_id))
    session.commit()


def add_bought_item(item_name: str, value: str, price: int, buyer_id: int,
                    bought_time: str) -> int:
    session = Database().session
    unique_id = random.randint(1000000000, 9999999999)
    session.add(
        BoughtGoods(name=item_name, value=value, price=price, buyer_id=buyer_id, bought_datetime=bought_time,
                    unique_id=str(unique_id)))
    session.commit()
    return unique_id


def create_promocode(code: str, discount: int, expires_at: str | None,
                     items: list[str] | None = None) -> None:
    session = Database().session
    stored_items = json.dumps(sorted(set(items))) if items else None
    session.add(
        PromoCode(
            code=code,
            discount=discount,
            expires_at=expires_at,
            active=True,
            applicable_items=stored_items,
        )
    )
    session.commit()


def grant_achievement(user_id: int, code: str, achieved_at: str) -> None:
    session = Database().session
    session.add(UserAchievement(user_id=user_id, achievement_code=code, achieved_at=achieved_at))
    session.commit()


def add_stock_notification(user_id: int, item_name: str) -> None:
    session = Database().session
    session.add(StockNotification(user_id=user_id, item_name=item_name))
    session.commit()


def create_reseller(user_id: int) -> None:
    session = Database().session
    session.add(Reseller(user_id=user_id))
    session.commit()


def add_item_to_cart(user_id: int, item_name: str, quantity: int = 1) -> None:
    """Add an item to the user's cart or increase its quantity."""
    if quantity <= 0:
        return
    session = Database().session
    cart_item = session.query(CartItem).filter_by(user_id=user_id, item_name=item_name).first()
    if cart_item:
        cart_item.quantity += quantity
    else:
        session.add(CartItem(user_id=user_id, item_name=item_name, quantity=quantity))
    session.commit()


def create_category_passwords(passwords: Sequence[str]) -> list[CategoryPassword]:
    """Create generated passwords for locked categories."""
    if not passwords:
        return []
    session = Database().session
    now = datetime.datetime.utcnow().isoformat()
    entries: list[CategoryPassword] = []
    for password in passwords:
        entry = CategoryPassword(password=password, created_at=now)
        session.add(entry)
        entries.append(entry)
    session.commit()
    return entries
