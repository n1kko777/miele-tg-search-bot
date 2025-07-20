from dotenv import load_dotenv
load_dotenv()

import logging
import os

# Telegram Bot Token
# Токен бота берется из переменной окружения BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- Настройки доступа ---
# ID ОБЯЗАТЕЛЬНОГО ПРИВАТНОГО КАНАЛА для доступа к боту.
# Берется из переменной окружения REQUIRED_CHANNEL_ID.
# Ожидается отрицательное число (например, -1001234567890).
required_channel_id_str = os.getenv("REQUIRED_CHANNEL_ID")
REQUIRED_CHANNEL_ID = None
if required_channel_id_str:
    try:
        REQUIRED_CHANNEL_ID = int(required_channel_id_str)
    except ValueError:
        logging.getLogger(__name__).error(f"Не удалось распарсить REQUIRED_CHANNEL_ID из переменной окружения: {required_channel_id_str}. Убедитесь, что это число.")


# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO, # Уровень логирования: INFO, DEBUG, WARNING, ERROR, CRITICAL
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Проверка наличия обязательных переменных окружения
if not BOT_TOKEN:
    logger.critical("Переменная окружения BOT_TOKEN не установлена. Бот не сможет запуститься.")
if REQUIRED_CHANNEL_ID is None:
    logger.warning("Переменная окружения REQUIRED_CHANNEL_ID не установлена. Проверка подписки на канал будет отключена.")