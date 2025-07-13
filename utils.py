import asyncio
import re
from typing import Optional
import aiohttp
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}

def normalize_text(text: str) -> str:
    """Нормализация текста для поиска"""
    return re.sub(r'[^\w\s]', '', text).lower().strip()

async def fetch(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Асинхронное получение HTML-контента страницы"""
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as response:
            if response.status == 200:
                return await response.text()
            logger.warning(f"Status {response.status} for {url}")
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Error fetching {url}: {e}")
    return None

def remove_miele(text: str) -> str:
    """Удаляет все упоминания Miele из текста с корректной обработкой пробелов"""
    # Удаляем "Miele" в различных формах написания
    cleaned_text = re.sub(r'\bmiele\b', '', text, flags=re.IGNORECASE)
    
    # Удаляем лишние пробелы и двойные пробелы
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    
    return cleaned_text
