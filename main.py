import asyncio
from typing import Dict, List, Optional
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

# Импортируем конфигурацию
from config import BOT_TOKEN, REQUIRED_CHANNEL_ID, logger

# Импорт утилит
from utils import normalize_text

from parsers.hausdorf import parse_hausdorf
from parsers.mieles import parse_mieles
from parsers.miele_unique import parse_miele_unique
from parsers.tehnikapremium import parse_tehnikapremium

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Кэширование результатов
cache: Dict[str, List[Dict]] = {} 
last_cache_clear_date: Optional[datetime] = None

# --- Вспомогательная функция для проверки подписки на канал ---
async def is_user_subscribed_to_required_channel(user_id: int) -> bool:
    """
    Проверяет, является ли пользователь подписчиком обязательного приватного канала.
    Использует строковые значения статусов членства для совместимости со старыми версиями aiogram.
    """
    if not REQUIRED_CHANNEL_ID: # Если REQUIRED_CHANNEL_ID не установлен, считаем, что проверка не нужна
        logger.warning("REQUIRED_CHANNEL_ID не установлен в config.py. Проверка подписки на канал отключена.")
        return True # Разрешаем доступ, если канал не указан
        
    try:
        # Получаем информацию о членстве пользователя в канале
        chat_member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL_ID, user_id=user_id)
        
        # Проверяем статус пользователя, используя строковые значения
        # 'member', 'administrator', 'creator', 'restricted' - это активные подписчики/участники
        is_subscribed = chat_member.status in ['member', 'administrator', 'creator', 'restricted']
            
        if not is_subscribed:
            logger.info(f"Пользователь {user_id} (статус: {chat_member.status}) не является подписчиком канала {REQUIRED_CHANNEL_ID}.")
        return is_subscribed
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки пользователя {user_id} на канал {REQUIRED_CHANNEL_ID}: {e}", exc_info=True)
        # Если произошла ошибка (например, бот не админ в канале, или канал не найден),
        # лучше отказать в доступе, чтобы не давать доступ всем подряд.
        return False


# --- Telegram Bot Handlers ---

@dp.message(Command("start"), F.chat.type == 'private') # <-- Используем строковое значение 'private'
async def start_command(message: Message):
    # Проверяем подписку на канал
    if not await is_user_subscribed_to_required_channel(message.from_user.id):
        await message.answer("🚫 Для использования бота вы должны быть подписчиком нашего приватного канала. Пожалуйста, подпишитесь на него, чтобы получить доступ.")
        return
    
    await message.answer(
        "🔍 Привет! Я бот для сравнения цен на Miele.\n\n"
        "Просто отправь мне название или артикул товара, например:\n"
        "<code>WWR880WPS</code> или <code>Стиральная машина</code>\n\n"
        "Я проверю цены на:\n"
        "• TehnikaPremium.ru\n"
        "• Mieles.ru\n"
        "• Hausdorf.ru\n"
        "• Miele-Unique.ru",
        parse_mode="HTML"
    )

@dp.message(F.text, F.chat.type == 'private') # <-- Используем строковое значение 'private'
async def handle_product_request(message: Message):
    global last_cache_clear_date, cache

    # Проверка подписки на канал
    if not await is_user_subscribed_to_required_channel(message.from_user.id):
        await message.answer("🚫 Для использования бота вы должны быть подписчиком нашего приватного канала. Пожалуйста, подпишитесь на него, чтобы получить доступ.")
        return

    # Проверяем и очищаем кэш, если день изменился
    current_date = datetime.now().date()
    if last_cache_clear_date is None or current_date > last_cache_clear_date.date():
        logger.info(f"Очистка кэша: предыдущая дата {last_cache_clear_date.date() if last_cache_clear_date else 'N/A'}, текущая дата {current_date}")
        cache.clear()
        last_cache_clear_date = datetime.now() # Обновляем время последней очистки до текущего момента
        logger.info("Кэш успешно очищен.")

    # Если вы оставили ALLOWED_USER_IDS, можно добавить здесь дополнительную проверку
    pass

    user_query = message.text.strip()
    if len(user_query) < 3:
        await message.answer("❌ Слишком короткий запрос. Минимум 3 символа.")
        return

    cache_key = normalize_text(user_query)
    
    main_product_data = None
    if cache_key in cache and cache[cache_key]:
        main_product_data = cache[cache_key][0]
        logger.info(f"Использую кэшированные данные для TehnikaPremium.ru: {main_product_data['title']}")
    
    if not main_product_data:
        await bot.send_chat_action(message.chat.id, "typing")
        
        tehnikapremium_results = await parse_tehnikapremium(f'Miele {user_query}') 
        
        if not tehnikapremium_results:
            tehnikapremium_results = [{
                'title': cache_key,
                'link': '',
                'price': '',
                'article': ''
            }]
        
        main_product_data = tehnikapremium_results[0]
        cache[cache_key] = tehnikapremium_results
        
        logger.info(f"На TehnikaPremium.ru найден основной товар: {main_product_data['title']} ({main_product_data['article']}) - {main_product_data['price']} RUB")

    original_title_for_competitors = main_product_data['title']
    article_tehnikapremium = main_product_data['article'] 
    
    price_tehnikapremium = main_product_data['price']
    if isinstance(price_tehnikapremium, (int, float)):
        formatted_price_tehnikapremium = f"{price_tehnikapremium:,.0f}".replace(',', ' ')
    else:
        formatted_price_tehnikapremium = 'нет данных'

    link_tehnikapremium = main_product_data['link']

    await bot.send_chat_action(message.chat.id, "typing")
    competitor_tasks = []
    
    competitor_tasks.append(parse_mieles(original_title_for_competitors, user_query))
    competitor_tasks.append(parse_hausdorf(original_title_for_competitors, user_query))
    competitor_tasks.append(parse_miele_unique(original_title_for_competitors, user_query))

    try:
        competitor_results = await asyncio.gather(*competitor_tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"Error during competitor parsing: {e}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при получении данных конкурентов.")
        return

    response_parts = [
        f"<b>{original_title_for_competitors}</b> <a href='{link_tehnikapremium}'>({article_tehnikapremium})</a>\n",
        f"🏷️ <b>TehnikaPremium.ru</b>: {formatted_price_tehnikapremium} руб.\n"
    ]
    
    response_parts.append("\nЦены конкурентов:")

    site_names = ["Mieles.ru", "Hausdorf.ru", "Miele-Unique.ru"]
    
    for i, result_list_or_exception in enumerate(competitor_results):
        site_name = site_names[i]
        
        if isinstance(result_list_or_exception, Exception):
            logger.error(f"Ошибка парсинга {site_name}: {result_list_or_exception}")
            response_parts.append(f"• {site_name}: ❌ Ошибка ({result_list_or_exception.__class__.__name__})")
        elif result_list_or_exception:
            response_parts.append(f"• <b>{site_name}</b>:")
            for item in result_list_or_exception:
                title = item.get('title', 'Название неизвестно')
                link = item.get('link', '#')
                price = item.get('price', None) 
                
                formatted_price = 'нет данных'
                if isinstance(price, (int, float)):
                    formatted_price = f"{price:,.0f}".replace(',', ' ') + " руб." 
                else:
                    formatted_price = 'нет данных' 

                response_parts.append(f"  - <a href='{link}'>{title}</a>: {formatted_price}")
        else:
            response_parts.append(f"• {site_name}: ❌ не найдено")

    final_response = "\n".join(response_parts)
    
    await message.answer(final_response, parse_mode="HTML", disable_web_page_preview=True)

# --- Main entry point ---

async def main():
    # Инициализируем last_cache_clear_date при запуске бота
    global last_cache_clear_date
    last_cache_clear_date = datetime.now() 
    logger.info(f"Кэш инициализирован. Дата последней очистки: {last_cache_clear_date.date()}")

    try:
        logger.info("Удаляем предыдущие вебхуки...")
        await bot.delete_webhook(drop_pending_updates=True) 
        logger.info("Вебхуки удалены. Запускаем бота через long polling...")
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