import aiohttp
import json
import time
import re
from typing import Optional, List, Dict
import logging

# Предполагаем, что utils.py с normalize_text, remove_miele существует
# (fetch не нужен, так как здесь прямой API вызов через aiohttp.ClientSession)
from utils import normalize_text, remove_miele 

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def parse_mieles(original_title: str, search_query: str) -> List[Dict]:
    """
    Парсинг mieles.ru через API с поиском по обоим запросам (original_title и search_query)
    и возвратом наиболее релевантных уникальных позиций.

    Args:
        original_title (str): Исходное, более полное название товара.
        search_query (str): Сокращенный или основной поисковый запрос.

    Returns:
        List[Dict]: Список из 3 наиболее релевантных уникальных объектов, каждый со словарями:
                    {'title': str, 'link': str, 'price': float}.
    """
    c = int(time.time() * 1000) # Текущее время в миллисекундах для параметра c
    url = (
        f"https://store.tildaapi.com/api/getproductslist/"
        f"?storepartuid=118745354213"
        f"&recid=501398769"
        f"&c={c}"
        f"&getparts=true"
        f"&getoptions=true"
        f"&slice=1"
        f"&filters%5Bstorepartuid%5D%5B0%5D=%D0%A5%D0%B8%D0%BC%D0%B8%D1%8F"
        f"&size=100"
    )
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://mieles.ru/",
        "Origin": "https://mieles.ru",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=10) as response:
                response.raise_for_status() # Вызовет исключение для статусов 4xx/5xx
                response_text = await response.text()
                
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError:
                    json_match = re.search(r'({.*})', response_text, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                        except json.JSONDecodeError:
                            logger.error("Не удалось извлечь JSON из ответа mieles.ru")
                            return []
                    else:
                        logger.error("Ответ mieles.ru не содержит валидный JSON")
                        return []
                
                # Нормализуем оба поисковых запроса
                clean_original_title = remove_miele(normalize_text(original_title))
                clean_search_query = remove_miele(normalize_text(search_query))

                # Если оба запроса пустые, нет смысла продолжать
                if not clean_original_title and not clean_search_query:
                    logger.warning("Оба поисковых запроса пусты после нормализации.")
                    return []

                found_products = [] 
                seen_links = set() # Множество для отслеживания уникальных ссылок
                
                for item in data.get("products", []):
                    item_title = item.get("title", "")
                    item_link = item.get("url", "")
                    item_price = item.get("price")

                    if not item_title or not item_link or item_price is None:
                        continue # Пропускаем неполные данные

                    # Нормализуем название товара из API
                    clean_item_title = remove_miele(normalize_text(item_title))

                    # Проверяем уникальность ссылки
                    if item_link in seen_links:
                        logger.debug(f"Пропускаем дубликат ссылки: {item_link}")
                        continue
                    
                    relevance_score = float('inf') # Начинаем с очень большого значения, чем меньше, тем лучше
                    
                    # Оценка релевантности
                    # 1. Точное совпадение с original_title
                    if clean_original_title and clean_original_title == clean_item_title:
                        relevance_score = min(relevance_score, 0)
                    # 2. Точное совпадение с search_query
                    elif clean_search_query and clean_search_query == clean_item_title:
                        relevance_score = min(relevance_score, 1)

                    # 3. Совпадение как подстроки (original_title имеет больший приоритет)
                    if clean_original_title and clean_original_title in clean_item_title:
                        relevance_score = min(relevance_score, 2)
                    elif clean_search_query and clean_search_query in clean_item_title:
                        relevance_score = min(relevance_score, 3)

                    # 4. Все слова из original_title присутствуют
                    if clean_original_title:
                        original_title_words = clean_original_title.split()
                        if all(word in clean_item_title for word in original_title_words):
                            relevance_score = min(relevance_score, 4)
                    
                    # 5. Все слова из search_query присутствуют
                    if clean_search_query:
                        search_query_words = clean_search_query.split()
                        if all(word in clean_item_title for word in search_query_words):
                            relevance_score = min(relevance_score, 5)

                    # Если хоть какое-то совпадение (relevance_score не inf)
                    if relevance_score != float('inf'):
                        # Добавляем длину названия как множитель для дополнительной сортировки
                        relevance_score += len(clean_item_title) * 0.01 
                        
                        try:
                            price = float(item_price)
                            found_products.append((relevance_score, item_title, item_link, price))
                            seen_links.add(item_link) # Добавляем ссылку в множество
                        except ValueError:
                            logger.error(f"Ошибка преобразования цены '{item_price}' для товара '{item_title}'")
                
                # Сортируем найденные товары по оценке релевантности (чем меньше, тем лучше)
                found_products.sort(key=lambda x: x[0])
                
                results = []
                for _, title, link, price in found_products[:3]: # Берем до 3х самых релевантных
                    results.append({
                        'title': title,
                        'link': link,
                        'price': price
                    })
                    logger.info(f"Найден релевантный товар: '{title}' (Ссылка: {link}, Цена: {price})")
                
                if not results:
                    logger.warning(f"Товары по запросам '{original_title}' и '{search_query}' не найдены на mieles.ru.")
                
                return results
                
        except aiohttp.ClientResponseError as e:
            logger.error(f"Ошибка HTTP-ответа от mieles.ru: {e.status} - {e.message}")
            return []
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка сети при запросе к mieles.ru: {e}")
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при парсинге mieles.ru: {e}", exc_info=True)
            return []

# Пример использования
async def main():
    results = await parse_mieles(
        original_title="Картридж для очистки от накипи CM7", 
        search_query="Картридж TwinDos" # Изменил search_query для примера, так как в mieles.ru есть TwinDos
    )
    
    if results:
        print("\nНайденные товары на Mieles:")
        for item in results:
            print(f"  Название: {item['title']}")
            print(f"  Ссылка: {item['link']}")
            print(f"  Цена: {item['price']}")
            print("-" * 20)
    else:
        print("Товары не найдены или произошла ошибка.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())