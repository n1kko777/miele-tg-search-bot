import os
import asyncio
import logging
from typing import Dict, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

# Если у вас все еще один файл, убедитесь, что функции определены выше или импортированы корректно.
# Для целей этого примера, оставим импорты как есть, предполагая, что они доступны.
from parse_hausdorf import parse_hausdorf
from parse_miele_unique import parse_miele_unique
from parse_mieles import parse_mieles
from parse_tehnikapremium import parse_tehnikapremium
from utils import normalize_text # Убедитесь, что remove_miele есть в utils

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS = list(map(int, os.getenv("ALLOWED_USERS", "").split(','))) if os.getenv("ALLOWED_USERS") else []

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэширование результатов (теперь может хранить список)
cache: Dict[str, List[Dict]] = {} # Кэш будет хранить списки результатов

@dp.message(Command("start"))
async def start_command(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        await message.answer("🚫 Доступ запрещен")
        return
    
    await message.answer(
        "🔍 Привет! Я бот для сравнения цен на химию Miele.\n\n"
        "Просто отправь мне название или артикул товара, например:\n"
        "<code>twindos</code> или <code>11206880</code>\n\n"
        "Я проверю цены на:\n"
        "• TehnikaPremium.ru\n"
        "• Mieles.ru\n"
        "• Hausdorf.ru\n"
        "• Miele-Unique.ru",
        parse_mode="HTML"
    )

@dp.message(F.text)
async def handle_product_request(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        await message.answer("🚫 Доступ запрещен")
        return

    user_query = message.text.strip()
    if len(user_query) < 3:
        await message.answer("❌ Слишком короткий запрос. Минимум 3 символа.")
        return

    cache_key = normalize_text(user_query)
    
    main_product_data = None
    # Проверяем, есть ли результаты TehnikaPremium в кэше
    if cache_key in cache and cache[cache_key]:
        main_product_data = cache[cache_key][0] # Берем первый (лучший) из TehnikaPremium для основного отображения
        logger.info(f"Использую кэшированные данные для TehnikaPremium.ru: {main_product_data['title']}")
    
    if not main_product_data: # Если в кэше не найдено, или кэш был пуст
        await bot.send_chat_action(message.chat.id, "typing")
        
        # Поиск на основном сайте. user_query будет выступать как original_title и search_query
        tehnikapremium_results = await parse_tehnikapremium(user_query, user_query) 
        
        if not tehnikapremium_results:
            await message.answer("❌ Товар не найден на TehnikaPremium.ru")
            return
        
        main_product_data = tehnikapremium_results[0] # Берем лучшую найденную позицию
        cache[cache_key] = tehnikapremium_results # Кэшируем все найденные на tehnikapremium
        
        logger.info(f"На TehnikaPremium.ru найден основной товар: {main_product_data['title']} ({main_product_data['article']}) - {main_product_data['price']} RUB")

    # Получаем данные основного товара для передачи конкурентам
    original_title_for_competitors = main_product_data['title']
    article_tehnikapremium = main_product_data['article'] 
    price_tehnikapremium = main_product_data['price']
    link_tehnikapremium = main_product_data['link']

    # Парсинг конкурентов
    await bot.send_chat_action(message.chat.id, "typing")
    competitor_tasks = []
    
    # Передаем оригинальное название (найденное на tehnikapremium) и запрос пользователя
    competitor_tasks.append(parse_mieles(original_title_for_competitors, user_query))
    competitor_tasks.append(parse_hausdorf(original_title_for_competitors, user_query))
    competitor_tasks.append(parse_miele_unique(original_title_for_competitors, user_query))

    try:
        competitor_results = await asyncio.gather(*competitor_tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"Error during competitor parsing: {e}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при получении данных конкурентов.")
        return

    # Форматирование ответа
    response_parts = [
        f"<b>{original_title_for_competitors}</b> <a href='{link_tehnikapremium}'>({article_tehnikapremium})</a>\n",
        f"🏷️ <b>TehnikaPremium.ru</b>: {price_tehnikapremium} руб.\n" # Убедимся, что ссылка отображается здесь
    ]
    
    response_parts.append("\nЦены конкурентов:")

    # Обработка результатов от конкурентов (каждый result_list_or_exception - это List[Dict] или Exception)
    site_names = ["Mieles.ru", "Hausdorf.ru", "Miele-Unique.ru"]
    
    for i, result_list_or_exception in enumerate(competitor_results):
        site_name = site_names[i]
        
        if isinstance(result_list_or_exception, Exception):
            logger.error(f"Ошибка парсинга {site_name}: {result_list_or_exception}")
            response_parts.append(f"• {site_name}: ❌ Ошибка ({result_list_or_exception.__class__.__name__})")
        elif result_list_or_exception: # Если список не пуст
            response_parts.append(f"• <b>{site_name}</b>:")
            for item in result_list_or_exception:
                title = item.get('title', 'Название неизвестно')
                link = item.get('link', '#')
                price = item.get('price', 'нет данных')
                response_parts.append(f"  - <a href='{link}'>{title}</a>: {price} руб.")
        else:
            response_parts.append(f"• {site_name}: ❌ не найдено")

    final_response = "\n".join(response_parts)
    
    await message.answer(final_response, parse_mode="HTML", disable_web_page_preview=True)

async def main():
    try:
        logger.info("Starting bot...")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        if bot and bot.session:
            await bot.session.close()
            logger.info("Bot session closed")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass