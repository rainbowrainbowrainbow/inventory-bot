"""
🎭 Telegram бот для інвентаризації костюмів та реквізиту аніматорів
v2.1 - Покращена версія:
- Автоматичне розпізнавання фото/голосу
- Фото коробки → список всіх предметів
- Запис хто додав (Telegram user)
- Автоматичні теги через AI
- Посилання на таблицю
"""

import logging
import requests
import json
import re
import os
import base64
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ==================== КОНФІГУРАЦІЯ ====================

BOT_TOKEN = os.getenv("BOT_TOKEN", "7817058984:AAE6jqS5Vop3hNIejPm6XaTeDNI6snTHVAE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL", "https://script.google.com/macros/s/AKfycbxq-6XJsTkYpDY8XzWelxIt87MAz0cgReVS948mPNAzIzdSqoCCe-oPBlOggVTASt-Z/exec")

# Посилання на таблицю
SPREADSHEET_ID = "11Oi2WR1-BGC1ws-SKdIexBQyQHnA2BgFQcOXm70PGYg"
SPREADSHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"

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

# Теги для AI (фіксований список)
AVAILABLE_TAGS = [
    "#деньнародження", "#хелловін", "#новийрік", "#випускний", "#корпоратив",
    "#дитячесвято", "#фотозона", "#квест", "#аніматор", "#ведучий",
    "#принцеси", "#супергерої", "#казка", "#піратська", "#диско",
    "#спорт", "#наука", "#мультики", "#ретро", "#гламур"
]

# База даних
items_db = []
user_states = {}

# ==================== КЛАВІАТУРА ====================

def get_main_keyboard():
    """Головна клавіатура"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Додати"), KeyboardButton("🔍 Пошук")],
        [KeyboardButton("📦 Де що лежить"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("📋 Таблиця")]
    ], resize_keyboard=True)

# ==================== ДОПОМІЖНІ ФУНКЦІЇ ====================

def get_user_info(user):
    """Отримати інформацію про користувача"""
    parts = []
    if user.first_name:
        parts.append(user.first_name)
    if user.last_name:
        parts.append(user.last_name)
    name = " ".join(parts) if parts else "Unknown"
    username = f"@{user.username}" if user.username else ""
    if username:
        return f"{name} ({username})"
    return f"{name} [ID:{user.id}]"

def generate_tags_with_ai(item_name, category):
    """Генерувати теги через AI"""
    if not OPENAI_API_KEY:
        return ""
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
                        "content": f"""Ти помічник для інвентаризації аніматорів.
Підбери 2-4 релевантних теги для предмету.

ДОСТУПНІ ТЕГИ (ТІЛЬКИ з цього списку):
{', '.join(AVAILABLE_TAGS)}

Правила:
- Вибери 2-4 підходящих теги
- ТІЛЬКИ теги зі списку
- Відповідь - тільки теги через пробіл
- Якщо нічого не підходить - #дитячесвято"""
                    },
                    {
                        "role": "user",
                        "content": f"Предмет: {item_name}\nКатегорія: {category}"
                    }
                ],
                "max_tokens": 50,
                "temperature": 0.3
            },
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            tags = data['choices'][0]['message']['content'].strip()
            valid_tags = [tag for tag in tags.split() if tag.startswith('#')]
            return " ".join(valid_tags[:4])
    except Exception as e:
        logger.error(f"AI tags error: {e}")
    return "#дитячесвято"

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
        logger.info(f"📝 Sheets: {response.status_code} - {item['name']}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"❌ Sheets помилка: {e}")
        return False

def load_from_sheets():
    """Завантажити з Google Sheets"""
    global items_db
    try:
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:json&sheet=Інвентар"
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
                                'added_by': cells[6]['v'] if len(cells) > 6 and cells[6] else '',
                            }
                            if item['name']:
                                items_db.append(item)
                    logger.info(f"✅ Завантажено {len(items_db)} речей")
                    return True
    except Exception as e:
        logger.error(f"❌ Помилка завантаження: {e}")
    return False

# ==================== РОЗУМНИЙ ПОШУК ====================

def smart_search(query):
    """Розумний пошук по назві, опису і тегам"""
    if not query:
        return []
    query_lower = query.lower().strip()

    # Пошук по тегу
    if query_lower.startswith('#'):
        tag_search = query_lower.replace(' ', '')
        results = []
        for item in items_db:
            item_tags = item.get('description', '').lower()
            if tag_search in item_tags:
                results.append({'item': item, 'score': 1.0})
        return [r['item'] for r in results]

    words = query_lower.split()
    results = []
    for item in items_db:
        item_text = f"{item.get('name', '')} {item.get('category', '')} {item.get('location_name', '')} {item.get('description', '')}".lower()
        match_count = sum(1 for word in words if word in item_text)
        if match_count > 0:
            results.append({'item': item, 'score': match_count / len(words)})
    results.sort(key=lambda x: x['score'], reverse=True)
    return [r['item'] for r in results]

# ==================== AI ФУНКЦІЇ ====================

def analyze_photo_for_items(image_base64):
    """Розпізнати предмети на фото"""
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
                        "content": """Ти помічник для інвентаризації костюмів та реквізиту аніматорів.
Перелічи ВСІ предмети на фото.

Формат:
- Кожен предмет на ОКРЕМОМУ рядку
- Назва (колір/особливості)
- Без номерів і тире

Приклад:
Костюм Спайдермена червоний
Маска Бетмена чорна
Плащ синій"""
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Перелічи всі предмети:"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                        ]
                    }
                ],
                "max_tokens": 500
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            logger.error(f"OpenAI error: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Vision помилка: {e}")
    return None

def transcribe_voice(audio_data):
    """Розпізнати голос"""
    if not OPENAI_API_KEY:
        return None
    try:
        response = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": ("voice.ogg", audio_data, "audio/ogg")},
            data={"model": "whisper-1", "language": "uk"},
            timeout=30
        )
        if response.status_code == 200:
            return response.json().get('text')
        else:
            logger.error(f"Whisper error: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Whisper помилка: {e}")
    return None

# ==================== КОМАНДИ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Головне меню"""
    load_from_sheets()
    await update.message.reply_text(
        f"🎭 *Склад аніматорів*\n\n"
        f"👤 Привіт, {update.effective_user.first_name}!\n"
        f"📦 В базі: *{len(items_db)}* речей\n\n"
        f"Що можу:\n"
        f"• Напиши назву → пошукаю\n"
        f"• Напиши #тег → знайду по тегу\n"
        f"• Надішли 📸 фото → розпізнаю\n"
        f"• Надішли 🎤 голосове → зрозумію\n\n"
        f"_Теги:_ {' '.join(AVAILABLE_TAGS[:5])}...",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

async def show_spreadsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Посилання на таблицю"""
    await update.message.reply_text(
        f"📋 *Google Таблиця:*\n\n[Відкрити таблицю]({SPREADSHEET_URL})",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard(),
        disable_web_page_preview=True
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Допомога"""
    await update.message.reply_text(
        "📖 *Як користуватися:*\n\n"
        "1️⃣ *Пошук* — напиши назву\n"
        "2️⃣ *Пошук по тегах* — #хелловін\n"
        "3️⃣ *Фото* — сфоткай, розпізнаю все\n"
        "4️⃣ *Голос* — скажи що шукаєш\n\n"
        f"🏷 *Теги:*\n{' '.join(AVAILABLE_TAGS)}",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

# ==================== ПОШУК ====================

async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {'step': 'search', 'mode': 'search'}
    await update.message.reply_text("🔍 Напиши що шукаєш або #тег:", parse_mode='Markdown')

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    load_from_sheets()
    results = smart_search(query)
    if results:
        text = f"🔍 *Знайдено {len(results)}:*\n\n"
        for item in results[:10]:
            text += f"• *{item['name']}*\n"
            text += f"  📍 {item.get('location_type', '')} → {item.get('location_name', '')}\n"
            if item.get('category'):
                text += f"  🏷 {item['category']}\n"
            if item.get('description'):
                text += f"  🔖 {item['description']}\n"
            text += "\n"
    else:
        text = f"😕 Нічого не знайшов: _{query}_"
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==================== ПЕРЕГЛЯД ПО МІСЦЯХ ====================

async def boxes_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_from_sheets()
    locations = {}
    for item in items_db:
        loc = f"{item.get('location_type', '')} → {item.get('location_name', '')}"
        if loc not in locations:
            locations[loc] = []
        locations[loc].append(item['name'])

    if not locations:
        await update.message.reply_text("📦 Поки немає записів.", reply_markup=get_main_keyboard())
        return

    keyboard = []
    for loc, items in sorted(locations.items()):
        keyboard.append([InlineKeyboardButton(f"📍 {loc} ({len(items)})", callback_data=f"box|{loc[:40]}")])
    await update.message.reply_text("📦 *Де що лежить:*", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_box(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    location = query.data.split('|')[1]
    items = [item for item in items_db if f"{item.get('location_type', '')} → {item.get('location_name', '')}".startswith(location)]
    if items:
        text = f"📍 *{location}:*\n\n"
        for item in items[:20]:
            text += f"• {item['name']}"
            if item.get('description'):
                text += f" {item['description']}"
            text += "\n"
    else:
        text = f"📍 *{location}* — порожньо"
    await query.edit_message_text(text, parse_mode='Markdown')

# ==================== СТАТИСТИКА ====================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    load_from_sheets()
    categories = {}
    for item in items_db:
        cat = item.get('category', 'Без категорії')
        categories[cat] = categories.get(cat, 0) + 1

    tags_count = {}
    for item in items_db:
        for tag in item.get('description', '').split():
            if tag.startswith('#'):
                tags_count[tag] = tags_count.get(tag, 0) + 1

    text = f"📊 *Статистика*\n\n📦 Всього: *{len(items_db)}*\n\n"
    if categories:
        text += "*Категорії:*\n"
        for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:8]:
            text += f"  {cat}: {count}\n"
    if tags_count:
        text += "\n*Теги:*\n"
        for tag, count in sorted(tags_count.items(), key=lambda x: -x[1])[:8]:
            text += f"  {tag}: {count}\n"
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==================== ДОДАВАННЯ ====================

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {'step': 'name', 'mode': 'add', 'added_by': get_user_info(update.effective_user)}
    await update.message.reply_text("➕ *Нова річ*\n\nНапиши назву або надішли фото!", parse_mode='Markdown')

async def process_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    user_id = update.effective_user.id
    user_states[user_id] = {
        'step': 'category', 'mode': 'add', 'name': name,
        'added_by': get_user_info(update.effective_user)
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
    await update.message.reply_text(f"📝 *{name}*\n\nКатегорія:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    category = query.data.split('|')[1]
    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку: ➕ Додати")
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
    await query.edit_message_text(f"📝 *{user_states[user_id]['name']}*\n🏷 {category}\n\nДе зберігається?", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def location_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    location_type = query.data.split('|')[1]
    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку")
        return
    user_states[user_id]['location_type'] = location_type
    user_states[user_id]['step'] = 'location_name'

    existing = set()
    for item in items_db:
        if item.get('location_type') == location_type and item.get('location_name'):
            existing.add(item['location_name'])

    keyboard = []
    for place in sorted(existing)[:6]:
        keyboard.append([InlineKeyboardButton(f"📍 {place}", callback_data=f"place|{place}")])
    keyboard.append([InlineKeyboardButton("➕ Нове місце", callback_data="place|_new_")])
    await query.edit_message_text(f"📝 *{user_states[user_id]['name']}*\n📦 {location_type}\n\nОбери місце:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def place_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    place = query.data.split('|')[1]
    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку")
        return
    if place == "_new_":
        await query.edit_message_text(f"📝 *{user_states[user_id]['name']}*\n\nНапиши назву місця:", parse_mode='Markdown')
        return
    await save_item_direct(query, context, place)

async def save_item(update: Update, context: ContextTypes.DEFAULT_TYPE, location_name: str):
    user_id = update.effective_user.id
    if user_id not in user_states:
        await update.message.reply_text("⚠️ Почни спочатку", reply_markup=get_main_keyboard())
        return
    state = user_states[user_id]

    await update.message.reply_text("🏷 Генерую теги...")
    tags = generate_tags_with_ai(state.get('name', ''), state.get('category', ''))

    item = {
        'name': state.get('name', ''),
        'category': state.get('category', ''),
        'location_type': state.get('location_type', ''),
        'location_name': location_name,
        'description': tags,
        'added_by': state.get('added_by', ''),
        'date': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    saved = save_to_sheets(item)
    items_db.append(item)
    del user_states[user_id]

    await update.message.reply_text(
        f"{'✅' if saved else '⚠️'} *Додано:*\n\n"
        f"📝 {item['name']}\n🏷 {item['category']}\n"
        f"📍 {item['location_type']} → {location_name}\n"
        f"🔖 {tags}\n👤 {item['added_by']}",
        parse_mode='Markdown', reply_markup=get_main_keyboard()
    )

async def save_item_direct(query, context: ContextTypes.DEFAULT_TYPE, location_name: str):
    user_id = query.from_user.id
    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку")
        return
    state = user_states[user_id]
    tags = generate_tags_with_ai(state.get('name', ''), state.get('category', ''))

    item = {
        'name': state.get('name', ''),
        'category': state.get('category', ''),
        'location_type': state.get('location_type', ''),
        'location_name': location_name,
        'description': tags,
        'added_by': state.get('added_by', ''),
        'date': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    saved = save_to_sheets(item)
    items_db.append(item)
    del user_states[user_id]

    await query.edit_message_text(
        f"{'✅' if saved else '⚠️'} *Додано:*\n\n"
        f"📝 {item['name']}\n🏷 {item['category']}\n"
        f"📍 {item['location_type']} → {location_name}\n"
        f"🔖 {tags}\n👤 {item['added_by']}",
        parse_mode='Markdown'
    )

# ==================== ФОТО ====================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user_info(update.effective_user)
    await update.message.reply_text("🔄 Аналізую фото...")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_data = await file.download_as_bytearray()
        image_base64 = base64.b64encode(photo_data).decode('utf-8')

        result = analyze_photo_for_items(image_base64)
        if result:
            items = [line.strip() for line in result.split('\n') if line.strip()]
            cleaned = []
            for item in items:
                c = re.sub(r'^[\d]+[.\)]\s*', '', item)
                c = re.sub(r'^[-•]\s*', '', c)
                if c:
                    cleaned.append(c)

            if len(cleaned) > 1:
                user_states[user_id] = {'step': 'photo_items', 'mode': 'add_multi', 'items': cleaned, 'added_by': user_info}
                text = f"📸 *Розпізнано {len(cleaned)}:*\n\n"
                for i, item in enumerate(cleaned, 1):
                    text += f"{i}. {item}\n"
                keyboard = []
                for i, item in enumerate(cleaned[:8]):
                    keyboard.append([InlineKeyboardButton(f"➕ {item[:30]}", callback_data=f"additem|{i}")])
                keyboard.append([InlineKeyboardButton("➕ Додати ВСЕ", callback_data="additem|all")])
                keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="additem|cancel")])
                await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
            elif len(cleaned) == 1:
                user_states[user_id] = {'added_by': user_info}
                await process_add_name(update, context, cleaned[0])
            else:
                await update.message.reply_text("😕 Не розпізнав.", reply_markup=get_main_keyboard())
        else:
            await update.message.reply_text("😕 Не розпізнав.", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await update.message.reply_text(f"❌ Помилка", reply_markup=get_main_keyboard())

async def add_item_from_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action = query.data.split('|')[1]

    if user_id not in user_states:
        await query.edit_message_text("⚠️ Надішли фото знову")
        return

    state = user_states[user_id]
    items = state.get('items', [])
    added_by = state.get('added_by', get_user_info(query.from_user))

    if action == 'cancel':
        del user_states[user_id]
        await query.edit_message_text("❌ Скасовано")
        return

    if action == 'all':
        user_states[user_id] = {'step': 'category', 'mode': 'add_batch', 'items': items, 'added_by': added_by}
        keyboard = []
        row = []
        for cat in CATEGORIES:
            row.append(InlineKeyboardButton(cat, callback_data=f"catbatch|{cat}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text(f"📦 *{len(items)} предметів*\n\nКатегорія:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    index = int(action)
    if index < len(items):
        item_name = items[index]
        user_states[user_id] = {'step': 'category', 'mode': 'add', 'name': item_name, 'added_by': added_by}
        keyboard = []
        row = []
        for cat in CATEGORIES:
            row.append(InlineKeyboardButton(cat, callback_data=f"cat|{cat}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text(f"📝 *{item_name}*\n\nКатегорія:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def category_batch_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    category = query.data.split('|')[1]
    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку")
        return
    user_states[user_id]['category'] = category
    user_states[user_id]['step'] = 'location_type_batch'
    keyboard = []
    row = []
    for loc in LOCATIONS:
        row.append(InlineKeyboardButton(loc, callback_data=f"locbatch|{loc}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    await query.edit_message_text(f"📦 *{len(user_states[user_id]['items'])}*\n🏷 {category}\n\nДе?", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def location_batch_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    location_type = query.data.split('|')[1]
    if user_id not in user_states:
        await query.edit_message_text("⚠️ Почни спочатку")
        return
    user_states[user_id]['location_type'] = location_type
    user_states[user_id]['step'] = 'location_name_batch'
    await query.edit_message_text(f"📦 *{len(user_states[user_id]['items'])}*\n📍 {location_type}\n\nНапиши назву місця:", parse_mode='Markdown')

async def save_batch_items(update: Update, context: ContextTypes.DEFAULT_TYPE, location_name: str):
    user_id = update.effective_user.id
    state = user_states.get(user_id, {})
    items = state.get('items', [])
    category = state.get('category', '')
    location_type = state.get('location_type', '')
    added_by = state.get('added_by', get_user_info(update.effective_user))

    await update.message.reply_text(f"🏷 Генерую теги для {len(items)} предметів...")
    saved_count = 0
    for item_name in items:
        tags = generate_tags_with_ai(item_name, category)
        item = {
            'name': item_name, 'category': category, 'location_type': location_type,
            'location_name': location_name, 'description': tags, 'added_by': added_by,
            'date': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        if save_to_sheets(item):
            saved_count += 1
        items_db.append(item)

    del user_states[user_id]
    await update.message.reply_text(f"✅ *Додано {saved_count}/{len(items)}!*\n\n📍 {location_type} → {location_name}\n👤 {added_by}", parse_mode='Markdown', reply_markup=get_main_keyboard())

# ==================== ГОЛОС ====================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = get_user_info(update.effective_user)
    await update.message.reply_text("🎤 Слухаю...")

    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        audio_data = await file.download_as_bytearray()
        text = transcribe_voice(bytes(audio_data))

        if text:
            text_lower = text.lower()
            if any(w in text_lower for w in ['додай', 'додати', 'запиши']):
                name = text
                for w in ['додай', 'додати', 'запиши', 'будь ласка']:
                    name = name.lower().replace(w, '').strip()
                name = name.strip().capitalize()
                if name and len(name) > 2:
                    user_states[user_id] = {'added_by': user_info}
                    await update.message.reply_text(f"🎤 *{text}*", parse_mode='Markdown')
                    await process_add_name(update, context, name)
                else:
                    user_states[user_id] = {'step': 'name', 'mode': 'add', 'added_by': user_info}
                    await update.message.reply_text(f"🎤 *{text}*\n\nЩо додати?", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"🎤 *{text}*\n\n🔍 Шукаю...", parse_mode='Markdown')
                await do_search(update, context, text)
        else:
            await update.message.reply_text("😕 Не розпізнав. Спробуй ще.", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("❌ Помилка", reply_markup=get_main_keyboard())

# ==================== ТЕКСТ ====================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "➕ Додати":
        await add_start(update, context)
    elif text == "🔍 Пошук":
        await search_start(update, context)
    elif text == "📦 Де що лежить":
        await boxes_start(update, context)
    elif text == "📊 Статистика":
        await stats(update, context)
    elif text == "📋 Таблиця":
        await show_spreadsheet(update, context)
    elif user_id in user_states:
        state = user_states[user_id]
        if state['step'] == 'name':
            await process_add_name(update, context, text)
        elif state['step'] == 'location_name':
            await save_item(update, context, text)
        elif state['step'] == 'location_name_batch':
            await save_batch_items(update, context, text)
        elif state['step'] == 'search':
            del user_states[user_id]
            await do_search(update, context, text)
    else:
        await do_search(update, context, text)

# ==================== MAIN ====================

def main():
    load_from_sheets()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_cmd))

    app.add_handler(CallbackQueryHandler(category_selected, pattern='^cat\\|'))
    app.add_handler(CallbackQueryHandler(location_selected, pattern='^loc\\|'))
    app.add_handler(CallbackQueryHandler(place_selected, pattern='^place\\|'))
    app.add_handler(CallbackQueryHandler(show_box, pattern='^box\\|'))
    app.add_handler(CallbackQueryHandler(add_item_from_photo, pattern='^additem\\|'))
    app.add_handler(CallbackQueryHandler(category_batch_selected, pattern='^catbatch\\|'))
    app.add_handler(CallbackQueryHandler(location_batch_selected, pattern='^locbatch\\|'))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🎭 Бот v2.1 запущено!")
    print(f"📦 В базі: {len(items_db)} речей")
    app.run_polling()

if __name__ == '__main__':
    main()
