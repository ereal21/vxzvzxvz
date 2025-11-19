import datetime
import json
import datetime

from bot.database.models import (
    User,
    ItemValues,
    Goods,
    Categories,
    PromoCode,
    StockNotification,
    ResellerPrice,
    CartItem,
    CategoryPassword,
    UserCategoryPassword,
)
from bot.database import Database


_MISSING = object()


def set_role(telegram_id: str, role: int) -> None:
    Database().session.query(User).filter(User.telegram_id == telegram_id).update(
        values={User.role_id: role})
    Database().session.commit()


def update_balance(telegram_id: int | str, summ: int) -> None:
    old_balance = User.balance
    new_balance = old_balance + summ
    Database().session.query(User).filter(User.telegram_id == telegram_id).update(
        values={User.balance: new_balance})
    Database().session.commit()


def update_user_language(telegram_id: int, language: str) -> None:
    Database().session.query(User).filter(User.telegram_id == telegram_id).update(
        values={User.language: language})
    Database().session.commit()


def update_lottery_tickets(telegram_id: int, delta: int) -> None:
    Database().session.query(User).filter(User.telegram_id == telegram_id).update(
        values={User.lottery_tickets: User.lottery_tickets + delta}, synchronize_session=False)
    Database().session.commit()


def reset_lottery_tickets() -> None:
    Database().session.query(User).update({User.lottery_tickets: 0})
    Database().session.commit()


def buy_item_for_balance(telegram_id: str, summ: int) -> int:
    old_balance = User.balance
    new_balance = old_balance - summ
    Database().session.query(User).filter(User.telegram_id == telegram_id).update(
        values={User.balance: new_balance})
    Database().session.commit()
    return Database().session.query(User.balance).filter(User.telegram_id == telegram_id).one()[0]


def update_item(item_name: str, new_name: str, new_description: str, new_price: int,
                new_category_name: str, new_delivery_description: str | None) -> None:
    Database().session.query(ItemValues).filter(ItemValues.item_name == item_name).update(
        values={ItemValues.item_name: new_name}
    )
    Database().session.query(Goods).filter(Goods.name == item_name).update(
        values={Goods.name: new_name,
                Goods.description: new_description,
                Goods.price: new_price,
                Goods.category_name: new_category_name,
                Goods.delivery_description: new_delivery_description}
    )
    Database().session.commit()


def update_category(category_name: str, new_name: str) -> None:
    Database().session.query(Categories).filter(Categories.name == category_name).update(
        values={Categories.title: new_name}
    )
    Database().session.commit()


def set_category_options(category_name: str,
                         allow_discounts: bool | None = None,
                         allow_referral_rewards: bool | None = None) -> None:
    values = {}
    if allow_discounts is not None:
        values[Categories.allow_discounts] = allow_discounts
    if allow_referral_rewards is not None:
        values[Categories.allow_referral_rewards] = allow_referral_rewards
    if not values:
        return
    Database().session.query(Categories).filter(Categories.name == category_name).update(values=values)
    Database().session.commit()


def update_promocode(
    code: str,
    discount: int | None = _MISSING,
    expires_at: str | None = _MISSING,
    items: list[str] | None = _MISSING,
) -> None:
    """Update promo code discount, expiry date or applicable items."""
    values = {}
    if discount is not _MISSING:
        values[PromoCode.discount] = discount
    if expires_at is not _MISSING:
        values[PromoCode.expires_at] = expires_at
    if items is not _MISSING:
        stored = json.dumps(sorted(set(items))) if items else None
        values[PromoCode.applicable_items] = stored
    if not values:
        return
    Database().session.query(PromoCode).filter(PromoCode.code == code).update(values=values)
    Database().session.commit()


def set_promocode_items(code: str, items: list[str]) -> None:
    """Update which items a promo code applies to."""
    update_promocode(code, items=items)


def set_reseller_price(reseller_id: int | None, item_name: str, price: int) -> None:
    session = Database().session
    entry = session.query(ResellerPrice).filter_by(
        reseller_id=reseller_id, item_name=item_name
    ).first()
    if entry:
        entry.price = price
    else:
        session.add(ResellerPrice(reseller_id=reseller_id, item_name=item_name, price=price))
    session.commit()


def clear_stock_notifications(item_name: str) -> None:
    Database().session.query(StockNotification).filter(
        StockNotification.item_name == item_name
    ).delete(synchronize_session=False)
    Database().session.commit()


def set_cart_quantity(user_id: int, item_name: str, quantity: int) -> None:
    """Update stored quantity for a cart item, removing it when quantity <= 0."""
    session = Database().session
    entry = session.query(CartItem).filter_by(user_id=user_id, item_name=item_name).first()
    if not entry:
        return
    if quantity <= 0:
        session.delete(entry)
    else:
        entry.quantity = quantity
    session.commit()


def set_category_requires_password(category_name: str, requires_password: bool) -> None:
    session = Database().session
    session.query(Categories).filter(Categories.name == category_name).update(
        {Categories.requires_password: requires_password}
    )
    session.commit()


def upsert_user_category_password(
    user_id: int,
    category_name: str,
    password: str,
    generated_password_id: int | None = None,
    *,
    acknowledged: bool | None = None,
) -> UserCategoryPassword:
    session = Database().session
    entry = (
        session.query(UserCategoryPassword)
        .filter(
            UserCategoryPassword.user_id == user_id,
            UserCategoryPassword.category_name == category_name,
        )
        .first()
    )
    now = datetime.datetime.utcnow().isoformat()
    if entry:
        entry.password = password
        entry.generated_password_id = generated_password_id
        entry.updated_at = now
        if acknowledged is not None:
            entry.acknowledged = acknowledged
    else:
        ack_value = acknowledged if acknowledged is not None else False
        entry = UserCategoryPassword(
            user_id=user_id,
            category_name=category_name,
            password=password,
            updated_at=now,
            generated_password_id=generated_password_id,
            acknowledged=ack_value,
        )
        session.add(entry)
    session.commit()
    return entry


def set_user_category_password_ack(
    user_id: int,
    category_name: str,
    acknowledged: bool,
) -> None:
    session = Database().session
    entry = (
        session.query(UserCategoryPassword)
        .filter(
            UserCategoryPassword.user_id == user_id,
            UserCategoryPassword.category_name == category_name,
        )
        .first()
    )
    if not entry:
        return
    entry.acknowledged = acknowledged
    session.commit()


def mark_generated_password_used(password_id: int, user_id: int, category_name: str) -> None:
    session = Database().session
    entry = session.query(CategoryPassword).filter(CategoryPassword.id == password_id).first()
    if not entry:
        return
    entry.used_by_user_id = user_id
    entry.used_for_category = category_name
    session.commit()


def clear_generated_password_usage(password_id: int) -> None:
    session = Database().session
    entry = session.query(CategoryPassword).filter(CategoryPassword.id == password_id).first()
    if not entry:
        return
    entry.used_by_user_id = None
    entry.used_for_category = None
    session.commit()


def process_purchase_streak(telegram_id: int) -> None:
    """Update streak data after a successful purchase."""
    session = Database().session
    user = session.query(User).filter(User.telegram_id == telegram_id).one()
    today = datetime.date.today()

    if user.streak_discount:
        user.streak_discount = False
        user.purchase_streak = 0

    if user.last_purchase_date:
        last_date = datetime.date.fromisoformat(user.last_purchase_date)
        diff = (today - last_date).days
        if diff == 1:
            user.purchase_streak += 1
        elif diff > 1:
            user.purchase_streak = 1
    else:
        user.purchase_streak = 1

    user.last_purchase_date = today.isoformat()

    if user.purchase_streak >= 3:
        user.purchase_streak = 0
        user.streak_discount = True

    session.commit()
