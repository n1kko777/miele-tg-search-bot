import asyncio
import re
import aiohttp
import logging
from typing import Optional

# Получаем логгер из общей конфигурации (предполагается, что конфиг установлен в config.py)
# Если вы не используете config.py и настроили логирование напрямую в main.py,
# то этот логгер будет использовать те настройки, которые были сделаны первыми.
logger = logging.getLogger(__name__)

async def fetch(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """
    Асинхронно получает HTML-содержимое по заданному URL.
    Увеличивает таймаут и добавляет User-Agent для обхода возможных блокировок.
    """
    # Добавляем стандартный User-Agent, чтобы запрос выглядел как от браузера
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    }
    
    try:
        # Увеличиваем таймаут до 30 секунд (можно настроить, если необходимо)
        async with session.get(url, timeout=45, headers=headers) as response:
            response.raise_for_status() # Вызывает исключение для статусов HTTP 4xx/5xx
            return await response.text()
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка HTTP при запросе {url}: {e}")
        return None
    except asyncio.TimeoutError:
        logger.error(f"Таймаут (30с) при запросе {url}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении {url}: {e}")
        return None

def normalize_text(text: str) -> str:
    """
    Нормализует текстовую строку: приводит к нижнему регистру,
    удаляет лишние пробелы и знаки препинания, заменяет 'ё' на 'е'.
    """
    text = text.lower()
    text = text.replace('ё', 'е')
    # Удаляем все, кроме букв, цифр и пробелов
    text = re.sub(r'[^a-z0-9а-я\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_miele(text: str) -> str:
    """
    Удаляет слово 'Miele' (и его вариации) из строки, игнорируя регистр.
    """
    text = re.sub(r'\bmiele\b', '', text, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', text).strip()

def extract_price_from_text(price_text: str) -> Optional[int]:
    """
    Извлекает целое число цены из строки.
    Удаляет все нецифровые символы и пытается преобразовать оставшуюся строку в int.
    Пример: "12 345 руб." -> 12345
    """
    # Используем регулярное выражение для удаления всего, что не является цифрой
    cleaned_price_str = re.sub(r'[^\d]', '', price_text)
    try:
        price = int(cleaned_price_str)
        return price
    except ValueError:
        logger.warning(f"Не удалось извлечь цену из текста: '{price_text}'")
        return None