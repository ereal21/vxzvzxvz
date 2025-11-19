import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    BigInteger,
    ForeignKey,
    Text,
    Boolean,
    VARCHAR,
    UniqueConstraint,
    inspect,
    text,
)
from bot.database.main import Database
from sqlalchemy.orm import relationship


class Permission:
    USE = 1
    BROADCAST = 2
    SETTINGS_MANAGE = 4
    USERS_MANAGE = 8
    SHOP_MANAGE = 16
    ADMINS_MANAGE = 32
    OWN = 64
    ASSIGN_PHOTOS = 128


class Role(Database.BASE):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True)
    default = Column(Boolean, default=False, index=True)
    permissions = Column(Integer)
    users = relationship('User', backref='role', lazy='dynamic')

    def __init__(self, name: str, permissions=None, **kwargs):
        super(Role, self).__init__(**kwargs)
        if self.permissions is None:
            self.permissions = 0
        self.name = name
        self.permissions = permissions

    @staticmethod
    def insert_roles():
        roles = {
            'USER': [Permission.USE],
            'ADMIN': [Permission.USE, Permission.BROADCAST,
                      Permission.SETTINGS_MANAGE, Permission.USERS_MANAGE,
                      Permission.SHOP_MANAGE, Permission.ASSIGN_PHOTOS],
            'OWNER': [Permission.USE, Permission.BROADCAST,
                      Permission.SETTINGS_MANAGE, Permission.USERS_MANAGE,
                      Permission.SHOP_MANAGE, Permission.ADMINS_MANAGE,
                      Permission.OWN, Permission.ASSIGN_PHOTOS],
            'ASSISTANT': [Permission.USE, Permission.ASSIGN_PHOTOS],
        }
        default_role = 'USER'
        for r in roles:
            role = Database().session.query(Role).filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
            role.reset_permissions()
            for perm in roles[r]:
                role.add_permission(perm)
            role.default = (role.name == default_role)
            Database().session.add(role)
        Database().session.commit()

    def add_permission(self, perm):
        if not self.has_permission(perm):
            self.permissions += perm

    def remove_permission(self, perm):
        if self.has_permission(perm):
            self.permissions -= perm

    def reset_permissions(self):
        self.permissions = 0

    def has_permission(self, perm):
        return self.permissions & perm == perm

    def __repr__(self):
        return '<Role %r>' % self.name


class User(Database.BASE):
    __tablename__ = 'users'
    telegram_id = Column(BigInteger, nullable=False, unique=True, primary_key=True)
    username = Column(String(64), nullable=True)
    role_id = Column(Integer, ForeignKey('roles.id'), default=1)
    balance = Column(BigInteger, nullable=False, default=0)
    lottery_tickets = Column(Integer, nullable=False, default=0)
    purchase_streak = Column(Integer, nullable=False, default=0)
    last_purchase_date = Column(VARCHAR, nullable=True)
    streak_discount = Column(Boolean, nullable=False, default=False)
    language = Column(String(5), nullable=True)
    referral_id = Column(BigInteger, nullable=True)
    registration_date = Column(VARCHAR, nullable=False)
    user_operations = relationship("Operations", back_populates="user_telegram_id")
    user_unfinished_operations = relationship("UnfinishedOperations", back_populates="user_telegram_id")
    user_goods = relationship("BoughtGoods", back_populates="user_telegram_id")

    def __init__(self, telegram_id: int, registration_date: datetime.datetime, balance: int = 0,
                 referral_id=None, role_id: int = 1, language: str | None = None,
                 username: str | None = None, purchase_streak: int = 0,
                 last_purchase_date: str | None = None, streak_discount: bool = False):
        self.telegram_id = telegram_id
        self.username = username
        self.role_id = role_id
        self.balance = balance
        self.referral_id = referral_id
        self.registration_date = registration_date
        self.language = language
        self.purchase_streak = purchase_streak
        self.last_purchase_date = last_purchase_date
        self.streak_discount = streak_discount


class Categories(Database.BASE):
    __tablename__ = 'categories'
    name = Column(String(100), primary_key=True, unique=True, nullable=False)
    title = Column(String(100), nullable=False, default='')
    parent_name = Column(String(100), nullable=True)
    allow_discounts = Column(Boolean, nullable=False, default=True)
    allow_referral_rewards = Column(Boolean, nullable=False, default=True)
    requires_password = Column(Boolean, nullable=False, default=False)
    item = relationship("Goods", back_populates="category")

    def __init__(
        self,
        name: str,
        parent_name: str | None = None,
        allow_discounts: bool = True,
        allow_referral_rewards: bool = True,
        requires_password: bool = False,
        title: str | None = None,
    ):
        self.name = name
        self.title = title or name
        self.parent_name = parent_name
        self.allow_discounts = allow_discounts
        self.allow_referral_rewards = allow_referral_rewards
        self.requires_password = requires_password


class Goods(Database.BASE):
    __tablename__ = 'goods'
    name = Column(String(100), nullable=False, unique=True, primary_key=True)
    price = Column(BigInteger, nullable=False)
    description = Column(Text, nullable=False)
    delivery_description = Column(Text, nullable=True)
    category_name = Column(String(100), ForeignKey('categories.name'), nullable=False)
    category = relationship("Categories", back_populates="item")
    values = relationship("ItemValues", back_populates="item")

    def __init__(self, name: str, price: int, description: str, category_name: str,
                 delivery_description: str | None = None):
        self.name = name
        self.price = price
        self.description = description
        self.delivery_description = delivery_description
        self.category_name = category_name


class ItemValues(Database.BASE):
    __tablename__ = 'item_values'
    id = Column(Integer, nullable=False, primary_key=True)
    item_name = Column(String(100), ForeignKey('goods.name'), nullable=False)
    value = Column(Text, nullable=True)
    is_infinity = Column(Boolean, nullable=False)
    item = relationship("Goods", back_populates="values")

    def __init__(self, name: str, value: str, is_infinity: bool):
        self.item_name = name
        self.value = value
        self.is_infinity = is_infinity


class BoughtGoods(Database.BASE):
    __tablename__ = 'bought_goods'
    id = Column(Integer, nullable=False, primary_key=True)
    item_name = Column(String(100), nullable=False)
    value = Column(Text, nullable=False)
    price = Column(BigInteger, nullable=False)
    buyer_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    bought_datetime = Column(VARCHAR, nullable=False)
    unique_id = Column(BigInteger, nullable=False, unique=True)
    user_telegram_id = relationship("User", back_populates="user_goods")

    def __init__(self, name: str, value: str, price: int, bought_datetime: str, unique_id,
                 buyer_id: int = 0):
        self.item_name = name
        self.value = value
        self.price = price
        self.buyer_id = buyer_id
        self.bought_datetime = bought_datetime
        self.unique_id = unique_id


class Operations(Database.BASE):
    __tablename__ = 'operations'
    id = Column(Integer, nullable=False, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    operation_value = Column(BigInteger, nullable=False)
    operation_time = Column(VARCHAR, nullable=False)
    user_telegram_id = relationship("User", back_populates="user_operations")

    def __init__(self, user_id: int, operation_value: int, operation_time: str):
        self.user_id = user_id
        self.operation_value = operation_value
        self.operation_time = operation_time


class UnfinishedOperations(Database.BASE):
    __tablename__ = 'unfinished_operations'
    id = Column(Integer, nullable=False, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    operation_value = Column(BigInteger, nullable=False)
    operation_id = Column(String(500), nullable=False)
    message_id = Column(BigInteger, nullable=True)
    user_telegram_id = relationship("User", back_populates="user_unfinished_operations")

    def __init__(self, user_id: int, operation_value: int, operation_id: str, message_id: int | None = None):
        self.user_id = user_id
        self.operation_value = operation_value
        self.operation_id = operation_id
        self.message_id = message_id


class Achievement(Database.BASE):
    __tablename__ = 'achievements'
    code = Column(String(50), primary_key=True, unique=True)

    def __init__(self, code: str):
        self.code = code


class UserAchievement(Database.BASE):
    __tablename__ = 'user_achievements'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    achievement_code = Column(String(50), ForeignKey('achievements.code'), nullable=False)
    achieved_at = Column(VARCHAR, nullable=False)

    def __init__(self, user_id: int, achievement_code: str, achieved_at: str):
        self.user_id = user_id
        self.achievement_code = achievement_code
        self.achieved_at = achieved_at


class PromoCode(Database.BASE):
    __tablename__ = 'promo_codes'
    code = Column(String(50), primary_key=True, unique=True)
    discount = Column(Integer, nullable=False)
    expires_at = Column(VARCHAR, nullable=True)
    active = Column(Boolean, default=True)
    applicable_items = Column(Text, nullable=True)

    def __init__(self, code: str, discount: int, expires_at: str | None = None,
                 active: bool = True, applicable_items: str | None = None):
        self.code = code
        self.discount = discount
        self.expires_at = expires_at
        self.active = active
        self.applicable_items = applicable_items


class Reseller(Database.BASE):
    __tablename__ = 'resellers'
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), primary_key=True, unique=True)

    def __init__(self, user_id: int):
        self.user_id = user_id


class ResellerPrice(Database.BASE):
    __tablename__ = 'reseller_prices'
    id = Column(Integer, primary_key=True)
    reseller_id = Column(BigInteger, ForeignKey('resellers.user_id'), nullable=True)
    item_name = Column(String(100), ForeignKey('goods.name'), nullable=False)
    price = Column(BigInteger, nullable=False)

    def __init__(self, reseller_id: int | None, item_name: str, price: int):
        self.reseller_id = reseller_id
        self.item_name = item_name
        self.price = price


class StockNotification(Database.BASE):
    __tablename__ = 'stock_notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    item_name = Column(String(100), ForeignKey('goods.name'), nullable=False)

    def __init__(self, user_id: int, item_name: str):
        self.user_id = user_id
        self.item_name = item_name


class CartItem(Database.BASE):
    __tablename__ = 'cart_items'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    item_name = Column(String(100), ForeignKey('goods.name'), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)

    def __init__(self, user_id: int, item_name: str, quantity: int = 1):
        self.user_id = user_id
        self.item_name = item_name
        self.quantity = quantity


class CategoryPassword(Database.BASE):
    __tablename__ = 'category_passwords'
    id = Column(Integer, primary_key=True)
    password = Column(String(64), nullable=False, unique=True)
    created_at = Column(VARCHAR, nullable=False)
    used_by_user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=True)
    used_for_category = Column(String(100), ForeignKey('categories.name'), nullable=True)

    user = relationship('User', backref='category_passwords', lazy='joined')
    category = relationship('Categories', lazy='joined')

    def __init__(self, password: str, created_at: str):
        self.password = password
        self.created_at = created_at


class UserCategoryPassword(Database.BASE):
    __tablename__ = 'user_category_passwords'
    __table_args__ = (
        UniqueConstraint('user_id', 'category_name', name='uq_user_category_password'),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    category_name = Column(String(100), ForeignKey('categories.name'), nullable=False)
    password = Column(String(64), nullable=False)
    generated_password_id = Column(Integer, ForeignKey('category_passwords.id'), nullable=True)
    updated_at = Column(VARCHAR, nullable=False)
    acknowledged = Column(Boolean, nullable=False, server_default=text('0'))

    user = relationship('User', backref='category_password_entries', lazy='joined')
    category = relationship('Categories', lazy='joined')
    generated_password = relationship('CategoryPassword', lazy='joined')

    def __init__(self, user_id: int, category_name: str, password: str,
                 updated_at: str, generated_password_id: int | None = None,
                 acknowledged: bool = False):
        self.user_id = user_id
        self.category_name = category_name
        self.password = password
        self.updated_at = updated_at
        self.generated_password_id = generated_password_id
        self.acknowledged = acknowledged


def register_models():
    engine = Database().engine
    inspector = inspect(engine)
    if 'categories' in inspector.get_table_names():
        columns = {column['name'] for column in inspector.get_columns('categories')}
        if 'title' not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE categories ADD COLUMN title VARCHAR(100)")
                )
                connection.execute(
                    text("UPDATE categories SET title = name WHERE title IS NULL OR title = ''")
                )
        if 'requires_password' not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE categories ADD COLUMN requires_password BOOLEAN DEFAULT 0"
                    )
                )
                connection.execute(
                    text("UPDATE categories SET requires_password = 0 WHERE requires_password IS NULL")
                )
    if 'user_category_passwords' in inspector.get_table_names():
        columns = {column['name'] for column in inspector.get_columns('user_category_passwords')}
        if 'acknowledged' not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE user_category_passwords ADD COLUMN acknowledged BOOLEAN DEFAULT 0"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE user_category_passwords SET acknowledged = 0 WHERE acknowledged IS NULL"
                    )
                )
    if 'promo_codes' in inspector.get_table_names():
        promo_columns = {column['name'] for column in inspector.get_columns('promo_codes')}
        if 'applicable_items' not in promo_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE promo_codes ADD COLUMN applicable_items TEXT")
                )
    if 'reseller_prices' in inspector.get_table_names():
        for column in inspector.get_columns('reseller_prices'):
            if column['name'] == 'reseller_id' and not column['nullable']:
                ResellerPrice.__table__.drop(engine)
                break
    Database.BASE.metadata.create_all(engine)
    Role.insert_roles()
