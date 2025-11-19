import contextlib
import datetime

from aiogram.utils import executor
from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from bot.filters import register_all_filters
from bot.misc import EnvKeys
from bot.handlers import register_all_handlers
from bot.database.models import register_models
from bot.database.methods import create_user, get_role_id_by_name
from bot.database.methods.update import set_role
from bot.logger_mesh import logger, file_handler

logger.addHandler(file_handler)


async def _ensure_owner_account(bot: Bot, owner_id: int) -> None:
    """Ensure the OWNER_ID user exists and has the owner role assigned."""
    owner_role_id = get_role_id_by_name('OWNER')
    if owner_role_id is None:
        logger.warning("Owner role is not present in the database; cannot assign OWNER_ID")
        return

    username = None
    with contextlib.suppress(Exception):
        chat = await bot.get_chat(owner_id)
        username = chat.username

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    create_user(
        telegram_id=owner_id,
        registration_date=timestamp,
        referral_id=None,
        role=owner_role_id,
        username=username,
    )
    set_role(owner_id, owner_role_id)


async def __on_start_up(dp: Dispatcher) -> None:
    register_all_filters(dp)
    register_all_handlers(dp)
    register_models()

    try:
        owner_id = int(EnvKeys.OWNER_ID) if EnvKeys.OWNER_ID else None
    except (TypeError, ValueError):
        owner_id = None

    if owner_id:
        await _ensure_owner_account(dp.bot, owner_id)
        try:
            await dp.bot.send_message(
                owner_id,
                "✅ Viskas turėtų veikti be problemų pagal viską, nes ši žinutė siunčiama po patikrų. Sėkmės ❤️",
            )
        except Exception as e:
            logger.error("Startup ping to OWNER_ID=%s failed: %s", owner_id, e)
    else:
        logger.warning("OWNER_ID is not set or invalid; cannot send startup ping.")


def start_bot():
    bot = Bot(token=EnvKeys.TOKEN, parse_mode='HTML')
    dp = Dispatcher(bot, storage=MemoryStorage())
    executor.start_polling(dp, skip_updates=True, on_startup=__on_start_up)
