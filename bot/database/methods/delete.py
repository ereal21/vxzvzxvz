import os

from bot.utils.files import sanitize_name
from bot.database.models import (
    Database,
    Goods,
    ItemValues,
    Categories,
    UnfinishedOperations,
    PromoCode,
    Reseller,
    ResellerPrice,
    CartItem,
    UserCategoryPassword,
    CategoryPassword,
)


def delete_item(item_name: str) -> None:
    values = Database().session.query(ItemValues.value).filter(ItemValues.item_name == item_name).all()
    for val in values:
        if os.path.isfile(val[0]):
            os.remove(val[0])
    Database().session.query(Goods).filter(Goods.name == item_name).delete()
    Database().session.query(ItemValues).filter(ItemValues.item_name == item_name).delete()
    Database().session.commit()
    folder = os.path.join('assets', 'uploads', sanitize_name(item_name))
    if os.path.isdir(folder) and not os.listdir(folder):
        os.rmdir(folder)


def delete_only_items(item_name: str) -> None:
    values = Database().session.query(ItemValues.value).filter(ItemValues.item_name == item_name).all()
    for val in values:
        if os.path.isfile(val[0]):
            os.remove(val[0])
    Database().session.query(ItemValues).filter(ItemValues.item_name == item_name).delete()
    folder = os.path.join('assets', 'uploads', sanitize_name(item_name))
    if os.path.isdir(folder) and not os.listdir(folder):
        os.rmdir(folder)


def delete_category(category_name: str) -> None:
    # delete subcategories recursively
    subs = Database().session.query(Categories.name).filter(Categories.parent_name == category_name).all()
    for sub in subs:
        delete_category(sub.name)
    goods = Database().session.query(Goods.name).filter(Goods.category_name == category_name).all()
    for item in goods:
        values = Database().session.query(ItemValues.value).filter(ItemValues.item_name == item.name).all()
        for val in values:
            if os.path.isfile(val[0]):
                os.remove(val[0])
        Database().session.query(ItemValues).filter(ItemValues.item_name == item.name).delete()
        folder = os.path.join('assets', 'uploads', sanitize_name(item.name))
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
    Database().session.query(Goods).filter(Goods.category_name == category_name).delete()
    Database().session.query(Categories).filter(Categories.name == category_name).delete()
    Database().session.commit()


def delete_user_category_password(user_id: int, category_name: str) -> None:
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
    generated_id = entry.generated_password_id
    session.delete(entry)
    if generated_id:
        generated = (
            session.query(CategoryPassword)
            .filter(CategoryPassword.id == generated_id)
            .first()
        )
        if generated:
            generated.used_by_user_id = None
            generated.used_for_category = None
    session.commit()


def finish_operation(operation_id: str) -> None:
    Database().session.query(UnfinishedOperations).filter(UnfinishedOperations.operation_id == operation_id).delete()
    Database().session.commit()


def buy_item(item_id: str, infinity: bool = False) -> None:
    """Remove an item's value record after purchase.

    File cleanup is handled separately by the caller."""
    if not infinity:
        session = Database().session
        session.query(ItemValues).filter(ItemValues.id == item_id).delete()
        session.commit()
    # Nothing to do for infinite items


def delete_promocode(code: str) -> None:
    session = Database().session
    session.query(PromoCode).filter(PromoCode.code == code).delete()
    session.commit()


def delete_reseller(user_id: int) -> None:
    session = Database().session
    session.query(ResellerPrice).filter(ResellerPrice.reseller_id == user_id).delete()
    session.query(Reseller).filter(Reseller.user_id == user_id).delete()
    session.commit()


def remove_cart_item(user_id: int, item_name: str) -> None:
    session = Database().session
    session.query(CartItem).filter_by(user_id=user_id, item_name=item_name).delete()
    session.commit()


def clear_cart(user_id: int) -> None:
    session = Database().session
    session.query(CartItem).filter(CartItem.user_id == user_id).delete()
    session.commit()
