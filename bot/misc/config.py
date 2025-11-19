from abc import ABC
from typing import Final


class TgConfig(ABC):
    STATE: Final = {}
    BASKETS: Final = {}
    BLACKJACK_STATS: Final = {}
    COINFLIP_STATS: Final = {}
    COINFLIP_ROOMS: Final = {}
    CART_PROMOS: Final = {}
    RATE_LIMIT: Final = {}
    RATE_LIMIT_WINDOW: Final = 3.0
    RATE_LIMIT_MAX_CALLS: Final = 12
    HEADS_GIF: Final = r'C:\Users\Administrator\Desktop\bot\bot\misc\1.gif'
    TAILS_GIF: Final = r'C:\Users\Administrator\Desktop\bot\bot\misc\2.gif'
    CHANNEL_URL: Final = 'https://t.me/+3oEKG8gEK1o1ZWYx'
    HELPER_URL: Final = '@Karunele'
    PRICE_LIST_URL: Final = 'https://t.me/+iXbi98gT0v5lOTNk'
    GROUP_ID: Final = -988765433
    REFERRAL_PERCENT = 10
    PAYMENT_TIME: Final = 900
    RULES: Final = 'insert your rules here'
    START_PHOTO_PATH: Final = r'C:\Users\Administrator\Desktop\bot\bot\misc\3.jpg'
    ACHIEVEMENTS: Final = [
        'start',
        'first_purchase',
        'first_topup',
        'first_blackjack',
        'first_coinflip',
        'gift_sent',
        'first_referral',
        'five_purchases',
        'streak_three',
        'ten_referrals',
    ]

