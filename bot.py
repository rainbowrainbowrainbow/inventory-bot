"""
🎭 Telegram бот для інвентаризації костюмів та реквізиту аніматорів
- Розумний пошук
- Розпізнавання фото через AI
- Голосові повідомлення
- Збереження в Google Sheets
"""

import logging
import requests
import json
import base64
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ==================== КОНФІГУРАЦІЯ ====================

BOT_TOKEN = os.getenv("BOT_TOKEN", "7817058984:AAE6jqS5Vop3hNIejPm6XaTeDNI6snTHVAE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "https://script.google.com/macros/s/AKfycbzdA27mdyyEQIDawEq5sEMeq2w3Me4qJJFraSAAlnWLagt6L4MzBNUCBkj5H7xBDBnG/exec")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== КАТЕГОРІЇ ДЛЯ АНІМАТОРІВ ====================

CATEGORIES = [
    "🎭 Костюми",
    "🦸 Супергерої",
    "👸 Принцеси/Казкові",
    "🎪 Реквізит",
    "🎈 Декорації",
    "🎵 Музика/Колонки",
    "🎤 Мікрофони",
    "📸 Фото/Відео",
    "🎁 Призи/Подарунки",
    "🧹 Господарче",
    "📦 Інше"
]

LOCATIONS = [
    "📦 Коробка",
    "🗄️ Шафа",
    "👗 Вішалка",
    "🏪 Склад",
    "🚗 Машина",
    "🏠 Офіс",
    "📍 Інше"
]

# База даних (в пам'яті + Google Sheets)
items_db = []
user_states = {}

# ==================== КЛАВІАТУРА ====================

def get_main_keyboard():
    """Головна клавіатура внизу екрану"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Додати"), KeyboardButton("🔍 Знайти")],
        [KeyboardButton("📦 Коробки"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("📸 Фото"), KeyboardButton("🎤 Голос")]
    ], resize_keyboard=True)

# ==================== GOOGLE SHEETS ====================

def save_to_sheets(item):
    """Зберегти в Google Sheets"""
    if not APPS_SCRIPT_URL:
        return False
    try:
        response = requests.post(
            APPS_SCRIPT_URL,
            json=item,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        logger.info(f"📝 Google Sheets: {response.status_code} - {item['name']}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"❌ Google Sheets помилка: {e}")
        return False

def load_from_sheets():
    """Завантажити дані з Google Sheets"""
    global items_db
    try:
        # Використовуємо публічний JSON endpoint
        spreadsheet_id = "11Oi2WR1-BGC1ws-SKdIexBQyQHnA2BgFQcOXm70PGYg"
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:json&sheet=Інвентар"

        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            text = response.text
            start = text.find('(') + 1
            end = text.rfind(')')
            if start > 0 and end > start:
                data = json.loads(text[start:end])
                if 'table' in data and 'rows' in data['table']:
                    items_db = []
                    for i, row in enumerate(data['table']['rows']):
                        if row.get('c') and len(row['c']) >= 4:
                            cells = row['c']
                            item = {
                                'id': i + 1,
                                'name': cells[0]['v'] if cells[0] else '',
                                'category': cells[1]['v'] if len(cells) > 1 and cells[1] else '',
                                'location_type': cells[2]['v'] if len(cells) > 2 and cells[2] else '',
                                'location_name': cells[3]['v'] if len(cells) > 3 and cells[3] else '',
                                'description': cells[4]['v'] if len(cells) > 4 and cells[4] else '',
                            }
                            if item['name']:
                                items_db.append(item)
                    logger.info(f"✅ Завантажено {len(items_db)} речей з Google Sheets")
                    return True
    except Exception as e:
        logger.error(f"❌ Помилка завантаження: {e}")
    return False

# ==================== РОЗУМНИЙ ПОШУК ====================

def smart_search(query):
    """Розумний пошук - шукає по всіх словах окремо"""
    if not query:
        return []

    query_lower = query.lower().strip()
    words = query_lower.split()
    results = []

    for item in items_db:
        item_text = f"{item.get('name', '')} {item.get('category', '')} {item.get('location_name', '')} {item.get('description', '')}".lower()

        # Перевіряємо чи всі слова є в тексті
        match_count = sum(1 for word in words if word in item_text)

        if match_count > 0:
            results.append({
                'item': item,
                'score': match_count / len(words)  # Відсоток співпадінь
            })

    # Сортуємо по релевантності
    results.sort(key=lambda x: x['score'], reverse=True)
    return [r['item'] for r in results]

# ==================== AI ФУНКЦІЇ ====================

def analyze_photo(image_base64):
    """Розпізнати що на фото через OpenAI Vision"""
    if not OPENAI_API_KEY:
        return None

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": "Ти помічник для інвентаризації костюмів та реквізиту аніматорів. Опиши що на фото коротко українською: назва предмету, колір, особливості. Формат: одне речення."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Що це за предмет? Опиши коротко для інвентаризації."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                        ]
                    }
                ],
                "max_tokens": 150
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            return data['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"❌ OpenAI Vision помилка: {e}")
    return None

def transcribe_voice(audio_file_path):
    """Розпізнати голосове повідомлення через OpenAI Whisper"""
    if not OPENAI_API_KEY:
        return None

    try:
        with open(audio_file_path, 'rb') as audio_file:
            response = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": audio_file},
                data={"model": "whisper-1", "language": "uk"},
                timeout=30
            )

        if response.status_code == 200:
            return response.json().get('text')
    except Exception as e:
        logger.error(f"❌ Whisper помилка: {e}")
    return None

# ==================== КОМАНДИ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Головне меню"""
    # Завантажуємо дані з таблиці
    load_from_sheets()

    await update.message.reply_text(
        "🎭 *Склад аніматорів*\n\n"
        f"📦 В базі: *{len(items_db)}* речей\n\n"
        "🔹 *➕ Додати* — нова річ\n"
        "🔹 *🔍 Знайти* — пошук\n"
        "🔹 *📸 Фото* — сфоткай і додам\n"
        "🔹 *🎤 Голос* — скажи що шукаєш\n\n"
        "_Просто напиши назву — пошукаю!_",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Допомога"""
    await update.message.reply_text(
        "📖 *Як користуватися:*\n\n"
        "🔹 Напиши назву — пошукаю\n"
        "🔹 Надішли фото — розпізнаю і запитаю куди покласти\n"
        "🔹 Надішли голосове — розпізнаю і пошукаю\n\n"
        "*Кнопки:*\n"
        "➕ Додати — крок за кроком\n"
        "🔍 Знайти — режим пошуку\n"
        "📦 Коробки — що де лежить\n"
        "📊 Статистика — скільки чого\n"
        "📸 Фото — додати через фото\n"
        "🎤 Голос — пошук голосом",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

# ==================== ДОДАВАННЯ ====================

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок додавання"""
    user_id = update.effective_user.id
    user_states[user_id] = {'step': 'name', 'mode': 'add'}

    await update.message.reply_text(
        "➕ *Нова річ*\n\n"
        "Напиши назву:\n"
        "_Наприклад: Костюм Спайдермена червоний_\n\n"
        "Або надішли 📸 фото!",
        parse_mode='Markdown'
    )

async def process_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    """Обробка назви"""
    user_id = update.effective_user.id
    user_states[user_id] = {'step': 'category', 'mode': 'add', 'name': name}

    keyboard = []
    row = []
    for cat in CATEGORIES:
        row.append(InlineKeyboardButton(cat, callback_data=f"cat|{cat}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        f"📝 *{name}*\n\nОбери категорію:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вибрано категорію"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    category = query.data.split('|')[1]

    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку: натисни ➕ Додати")
        return

    user_states[user_id]['category'] = category
    user_states[user_id]['step'] = 'location_type'

    keyboard = []
    row = []
    for loc in LOCATIONS:
        row.append(InlineKeyboardButton(loc, callback_data=f"loc|{loc}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        f"📝 *{user_states[user_id]['name']}*\n"
        f"📁 {category}\n\n"
        f"Де зберігається?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def location_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вибрано тип місця"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    location_type = query.data.split('|')[1]

    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку")
        return

    user_states[user_id]['location_type'] = location_type
    user_states[user_id]['step'] = 'location_name'

    # Показуємо існуючі місця
    existing = list(set(item.get('location_name', '') for item in items_db if item.get('location_name')))

    keyboard = []
    if existing:
        row = []
        for place in existing[:6]:
            row.append(InlineKeyboardButton(place, callback_data=f"place|{place}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✏️ Ввести нове", callback_data="place|NEW")])

    await query.edit_message_text(
        f"📝 *{user_states[user_id]['name']}*\n"
        f"📁 {user_states[user_id]['category']}\n"
        f"📍 {location_type}\n\n"
        f"Обери місце або введи нове:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def place_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вибрано конкретне місце"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    place = query.data.split('|')[1]

    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку")
        return

    if place == "NEW":
        await query.edit_message_text(
            "✏️ Напиши назву місця:\n"
            "_Коробка 1, Шафа червона, Вішалка костюми_",
            parse_mode='Markdown'
        )
        return

    # Зберігаємо
    await save_item(query, context, place)

async def save_item(update_or_query, context: ContextTypes.DEFAULT_TYPE, location_name: str):
    """Зберегти річ"""
    user_id = update_or_query.effective_user.id if hasattr(update_or_query, 'effective_user') else update_or_query.from_user.id

    if user_id not in user_states:
        return

    state = user_states[user_id]

    item = {
        'name': state.get('name', ''),
        'category': state.get('category', '📦 Інше'),
        'location_type': state.get('location_type', '📍 Інше'),
        'location_name': location_name,
        'description': state.get('description', ''),
        'date': datetime.now().strftime('%Y-%m-%d %H:%M')
    }

    items_db.append(item)
    saved = save_to_sheets(item)

    status = "✅ Збережено в таблицю!" if saved else "💾 Збережено локально"

    text = (
        f"🎉 *Готово!*\n\n"
        f"📝 {item['name']}\n"
        f"📁 {item['category']}\n"
        f"📍 {item['location_name']}\n\n"
        f"{status}"
    )

    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(text, parse_mode='Markdown')
    else:
        await update_or_query.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_keyboard())

    del user_states[user_id]

# ==================== ПОШУК ====================

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим пошуку"""
    user_id = update.effective_user.id
    user_states[user_id] = {'step': 'search', 'mode': 'search'}

    await update.message.reply_text(
        "🔍 *Пошук*\n\n"
        "Напиши що шукаєш:\n"
        "_Можна частину назви: 'куртка', 'спайдер', 'червон'_",
        parse_mode='Markdown'
    )

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    """Виконати пошук"""
    results = smart_search(query)

    if not results:
        await update.message.reply_text(
            f"😕 Не знайшов *{query}*\n\n"
            f"Спробуй інші слова або натисни ➕ Додати",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard()
        )
        return

    text = f"🔍 *Знайдено {len(results)}:*\n\n"
    for item in results[:15]:
        text += f"🎭 *{item['name']}*\n"
        text += f"   📍 {item.get('location_name', '?')} | {item.get('category', '')}\n\n"

    if len(results) > 15:
        text += f"_...та ще {len(results) - 15}_"

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==================== КОРОБКИ ====================

async def boxes_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перегляд коробок"""
    locations = list(set(item.get('location_name', '') for item in items_db if item.get('location_name')))

    if not locations:
        await update.message.reply_text(
            "📦 Ще немає місць.\n\nДодай першу річ: ➕ Додати",
            reply_markup=get_main_keyboard()
        )
        return

    keyboard = []
    row = []
    for loc in sorted(locations):
        count = len([i for i in items_db if i.get('location_name') == loc])
        row.append(InlineKeyboardButton(f"{loc} ({count})", callback_data=f"box|{loc}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "📦 *Обери місце:*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_box(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показати вміст"""
    query = update.callback_query
    await query.answer()

    location = query.data.split('|')[1]
    items = [item for item in items_db if item.get('location_name') == location]

    if not items:
        await query.edit_message_text(f"📦 *{location}* — порожньо", parse_mode='Markdown')
        return

    text = f"📦 *{location}* ({len(items)} шт):\n\n"

    # Групуємо по категоріях
    by_cat = {}
    for item in items:
        cat = item.get('category', 'Інше')
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(item['name'])

    for cat, names in by_cat.items():
        text += f"*{cat}:*\n"
        for name in names[:10]:
            text += f"  • {name}\n"
        if len(names) > 10:
            text += f"  _...ще {len(names) - 10}_\n"
        text += "\n"

    await query.edit_message_text(text, parse_mode='Markdown')

# ==================== СТАТИСТИКА ====================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика"""
    total = len(items_db)

    if total == 0:
        await update.message.reply_text(
            "📊 Ще пусто!\n\nДодай першу річ: ➕ Додати",
            reply_markup=get_main_keyboard()
        )
        return

    categories = {}
    locations = {}
    for item in items_db:
        cat = item.get('category', 'Інше')
        loc = item.get('location_name', 'Невідомо')
        categories[cat] = categories.get(cat, 0) + 1
        locations[loc] = locations.get(loc, 0) + 1

    text = f"📊 *Статистика складу*\n\n"
    text += f"📦 Всього речей: *{total}*\n"
    text += f"📍 Місць: *{len(locations)}*\n\n"

    text += "*По категоріях:*\n"
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        text += f"  {cat}: {count}\n"

    text += "\n*Топ місць:*\n"
    for loc, count in sorted(locations.items(), key=lambda x: x[1], reverse=True)[:7]:
        text += f"  📍 {loc}: {count}\n"

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==================== ФОТО ====================

async def photo_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим фото"""
    user_id = update.effective_user.id
    user_states[user_id] = {'step': 'photo', 'mode': 'photo'}

    await update.message.reply_text(
        "📸 *Фото режим*\n\n"
        "Надішли фото речі — я розпізнаю і запитаю куди покласти!",
        parse_mode='Markdown'
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка фото"""
    user_id = update.effective_user.id

    await update.message.reply_text("🔄 Аналізую фото...")

    try:
        # Отримуємо фото
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        # Завантажуємо
        photo_bytes = await file.download_as_bytearray()
        image_base64 = base64.b64encode(photo_bytes).decode('utf-8')

        # Аналізуємо через AI
        description = analyze_photo(image_base64)

        if description:
            user_states[user_id] = {
                'step': 'category',
                'mode': 'add',
                'name': description,
                'photo_id': photo.file_id
            }

            keyboard = []
            row = []
            for cat in CATEGORIES:
                row.append(InlineKeyboardButton(cat, callback_data=f"cat|{cat}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            await update.message.reply_text(
                f"📸 Розпізнано:\n*{description}*\n\n"
                f"Обери категорію або напиши свою назву:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "😕 Не вдалося розпізнати.\n\nНапиши назву вручну:",
                reply_markup=get_main_keyboard()
            )
            user_states[user_id] = {'step': 'name', 'mode': 'add'}

    except Exception as e:
        logger.error(f"Помилка фото: {e}")
        await update.message.reply_text(
            "❌ Помилка обробки фото.\n\nСпробуй ще раз або напиши назву:",
            reply_markup=get_main_keyboard()
        )

# ==================== ГОЛОС ====================

async def voice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим голосу"""
    user_id = update.effective_user.id
    user_states[user_id] = {'step': 'voice', 'mode': 'voice'}

    await update.message.reply_text(
        "🎤 *Голосовий режим*\n\n"
        "Надішли голосове повідомлення:\n"
        "• Скажи що шукаєш — пошукаю\n"
        "• Скажи 'додати [назва]' — додам",
        parse_mode='Markdown'
    )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка голосу"""
    user_id = update.effective_user.id

    await update.message.reply_text("🔄 Розпізнаю...")

    try:
        # Отримуємо аудіо
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        # Зберігаємо тимчасово
        file_path = f"/tmp/voice_{user_id}.ogg"
        await file.download_to_drive(file_path)

        # Розпізнаємо
        text = transcribe_voice(file_path)

        # Видаляємо тимчасовий файл
        try:
            os.remove(file_path)
        except:
            pass

        if text:
            text_lower = text.lower()

            # Якщо "додати" — режим додавання
            if 'додати' in text_lower or 'додай' in text_lower:
                # Видаляємо слово "додати"
                name = text.replace('додати', '').replace('Додати', '').replace('додай', '').replace('Додай', '').strip()
                if name:
                    await process_add_name(update, context, name)
                else:
                    user_states[user_id] = {'step': 'name', 'mode': 'add'}
                    await update.message.reply_text(
                        f"🎤 Почув: *{text}*\n\n"
                        f"Напиши або скажи назву речі:",
                        parse_mode='Markdown'
                    )
            else:
                # Пошук
                await update.message.reply_text(
                    f"🎤 Почув: *{text}*\n\n"
                    f"Шукаю...",
                    parse_mode='Markdown'
                )
                await do_search(update, context, text)
        else:
            await update.message.reply_text(
                "😕 Не вдалося розпізнати.\n\nСпробуй ще раз або напиши текстом.",
                reply_markup=get_main_keyboard()
            )

    except Exception as e:
        logger.error(f"Помилка голосу: {e}")
        await update.message.reply_text(
            "❌ Помилка розпізнавання.\n\nСпробуй ще раз.",
            reply_markup=get_main_keyboard()
        )

# ==================== ОБРОБКА ТЕКСТУ ====================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка текстових повідомлень"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Кнопки меню
    if text == "➕ Додати":
        await add_start(update, context)
        return
    elif text == "🔍 Знайти":
        await search_start(update, context)
        return
    elif text == "📦 Коробки":
        await boxes_start(update, context)
        return
    elif text == "📊 Статистика":
        await stats(update, context)
        return
    elif text == "📸 Фото":
        await photo_mode(update, context)
        return
    elif text == "🎤 Голос":
        await voice_mode(update, context)
        return

    # Якщо є стан користувача
    if user_id in user_states:
        state = user_states[user_id]

        if state['step'] == 'name':
            await process_add_name(update, context, text)
            return

        elif state['step'] == 'location_name':
            await save_item(update, context, text)
            return

        elif state['step'] == 'search':
            del user_states[user_id]
            await do_search(update, context, text)
            return

    # За замовчуванням — пошук
    await do_search(update, context, text)

# ==================== MAIN ====================

def main():
    """Запуск бота"""
    # Завантажуємо дані при старті
    load_from_sheets()

    app = Application.builder().token(BOT_TOKEN).build()

    # Команди
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))
    app.add_handler(CommandHandler('add', add_start))
    app.add_handler(CommandHandler('find', search_start))
    app.add_handler(CommandHandler('box', boxes_start))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('refresh', lambda u, c: load_from_sheets() or u.message.reply_text("✅ Оновлено!")))

    # Callbacks
    app.add_handler(CallbackQueryHandler(category_selected, pattern='^cat\\|'))
    app.add_handler(CallbackQueryHandler(location_selected, pattern='^loc\\|'))
    app.add_handler(CallbackQueryHandler(place_selected, pattern='^place\\|'))
    app.add_handler(CallbackQueryHandler(show_box, pattern='^box\\|'))

    # Медіа
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🎭 Бот запущено!")
    print(f"📦 В базі: {len(items_db)} речей")
    app.run_polling()

if __name__ == '__main__':
    main()
