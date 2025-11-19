LEVEL_THRESHOLDS = [0, 1, 5, 15, 30, 50]

LEVEL_NAMES = {
    'lt': [
        '😶‍🌫️ Niekšas',
        '👏 Fanas',
        '🎛️ Prodiuseris',
        '🛹 Mobo narys',
        '🧠 Mobo lyderis',
        '🎤 Reperis',
    ],
    'en': [
        '😶‍🌫️ Scoundrel',
        '👏 Fan',
        '🎛️ Producer',
        '🛹 Crew member',
        '🧠 Crew leader',
        '🎤 Rapper',
    ],
    'ru': [
        '😶‍🌫️ Негодяй',
        '👏 Фанат',
        '🎛️ Продюсер',
        '🛹 Участник банды',
        '🧠 Лидер банды',
        '🎤 Рэпер',
    ],
}


def get_level_info(purchases: int, lang: str = 'lt'):
    """Return level name and progress battery for purchase count.

    Discount levels have been disabled, so this function always returns 0 as the
    discount value to maintain compatibility with callers expecting three
    return values.
    """
    if purchases < 0:
        purchases = 0
    level_index = 0
    for idx, threshold in enumerate(LEVEL_THRESHOLDS):
        if purchases >= threshold:
            level_index = idx
        else:
            break
    names = LEVEL_NAMES.get(lang, LEVEL_NAMES['lt'])
    level_name = names[level_index]
    discount = 0

    if level_index < len(LEVEL_THRESHOLDS) - 1:
        next_threshold = LEVEL_THRESHOLDS[level_index + 1]
        progress = purchases - LEVEL_THRESHOLDS[level_index]
        needed = next_threshold - LEVEL_THRESHOLDS[level_index]
        battery = '🪫' if progress * 2 < needed else '🔋'
    else:
        battery = '🔋'
    return level_name, discount, battery
