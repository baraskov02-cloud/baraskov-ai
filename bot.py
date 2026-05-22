import asyncio, os, time, base64, uuid
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, types, BaseMiddleware
from aiogram.types import (
    InlineQueryResultArticle, InputTextMessageContent,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram import F
from aiogram.utils.keyboard import InlineKeyboardBuilder

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")

client = AsyncOpenAI(
    api_key=GROQ_KEY,
    base_url="https://api.groq.com/openai/v1"
)

TEXT_MODEL = "llama-3.1-8b-instant"
VISION_MODEL = "llama-3.2-11b-vision-preview"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ========== АНТИ-СПАМ ==========
user_messages_timestamps = defaultdict(list)
MAX_MESSAGES = 3
TIME_WINDOW = 5

class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not hasattr(event, 'text') and not hasattr(event, 'photo'):
            return await handler(event, data)
        user_id = event.from_user.id
        now = time.time()
        timestamps = user_messages_timestamps[user_id]
        timestamps = [t for t in timestamps if now - t < TIME_WINDOW]
        user_messages_timestamps[user_id] = timestamps
        if len(timestamps) >= MAX_MESSAGES:
            return None
        timestamps.append(now)
        return await handler(event, data)

dp.message.middleware(RateLimitMiddleware())

# ========== ХРАНИЛИЩЕ ЧАТОВ ==========
# Структура: user_chats[user_id] = список чатов
# Каждый чат: {
#   "id": str uuid,
#   "created_at": datetime,
#   "messages": [{"role": "user"/"assistant", "content": str}],
#   "active": bool
# }
user_chats = defaultdict(list)
active_chat = {}  # user_id -> chat_id (строка) активного чата

def get_chat_by_id(user_id, chat_id):
    for c in user_chats[user_id]:
        if c["id"] == chat_id:
            return c
    return None

def get_active_chat(user_id):
    chat_id = active_chat.get(user_id)
    if not chat_id:
        return None
    return get_chat_by_id(user_id, chat_id)

def get_chat_history(chat):
    """Возвращает список сообщений в формате OpenAI"""
    return [{"role": msg["role"], "content": msg["content"]} for msg in chat["messages"]]

def add_message_to_chat(chat, role, content):
    chat["messages"].append({"role": role, "content": content})

# ========== КНОПКИ ==========
def main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💬 Новый чат", callback_data="new_chat"),
        InlineKeyboardButton(text="📁 Мои чаты", callback_data="my_chats")
    )
    return builder.as_markup()

def active_chat_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏹ Завершить чат", callback_data="end_chat"),
        InlineKeyboardButton(text="📁 Мои чаты", callback_data="my_chats")
    )
    return builder.as_markup()

# ========== ЗАПРОСЫ К AI ==========
async def ask_ai_text(chat, question):
    try:
        history = get_chat_history(chat)
        messages = [
            {"role": "system", "content": "Ты — AI-ассистент, отвечай развёрнуто и дружелюбно."}
        ] + history + [{"role": "user", "content": question}]

        r = await client.chat.completions.create(
            model=TEXT_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=2000
        )
        answer = r.choices[0].message.content.strip()
        add_message_to_chat(chat, "user", question)
        add_message_to_chat(chat, "assistant", answer)
        return answer
    except Exception as e:
        return f"Ошибка: {e}"

async def ask_ai_vision(chat, caption, photo_base64):
    try:
        history = get_chat_history(chat)
        messages = [
            {"role": "system", "content": "Ты — AI-ассистент, анализируй изображения и отвечай на русском."}
        ] + history

        user_message = []
        if caption:
            user_message.append({"type": "text", "text": caption})
        user_message.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{photo_base64}"}
        })
        messages.append({"role": "user", "content": user_message})

        r = await client.chat.completions.create(
            model=VISION_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=2000
        )
        answer = r.choices[0].message.content.strip()

        history_text = f"[Фото]{': ' + caption if caption else ''}"
        add_message_to_chat(chat, "user", history_text)
        add_message_to_chat(chat, "assistant", answer)
        return answer
    except Exception as e:
        return f"Ошибка анализа фото: {e}"

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def start_cmd(m: types.Message):
    await m.answer(
        "👋 Привет! Я AI-помощник с историей чатов.\n"
        "Используй кнопки ниже для управления.",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("menu"))
async def menu_cmd(m: types.Message):
    await start_cmd(m)

# ========== ОБРАБОТЧИКИ CALLBACK ==========
@dp.callback_query(F.data == "new_chat")
async def cb_new_chat(call: types.CallbackQuery):
    user_id = call.from_user.id
    # Создаём новый чат
    chat_id = uuid.uuid4().hex[:8]
    new_chat = {
        "id": chat_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "messages": [],
        "active": True
    }
    user_chats[user_id].append(new_chat)
    active_chat[user_id] = chat_id
    await call.message.edit_text(
        f"✅ Новый чат создан ({chat_id}).\nЗадайте вопрос или отправьте фото.",
        reply_markup=active_chat_keyboard()
    )

@dp.callback_query(F.data == "end_chat")
async def cb_end_chat(call: types.CallbackQuery):
    user_id = call.from_user.id
    chat = get_active_chat(user_id)
    if chat:
        chat["active"] = False
        active_chat.pop(user_id, None)
        await call.message.edit_text(
            f"⏹ Чат {chat['id']} завершён и сохранён.\nСоздайте новый или посмотрите историю.",
            reply_markup=main_menu_keyboard()
        )
    else:
        await call.answer("Нет активного чата")

@dp.callback_query(F.data == "my_chats")
async def cb_my_chats(call: types.CallbackQuery):
    user_id = call.from_user.id
    chats = user_chats[user_id]
    if not chats:
        await call.message.edit_text("У вас пока нет чатов.", reply_markup=main_menu_keyboard())
        return

    # Сортируем по дате создания (сверху новые)
    sorted_chats = sorted(chats, key=lambda x: x["created_at"], reverse=True)
    builder = InlineKeyboardBuilder()
    for c in sorted_chats:
        label = f"{'📌 ' if c['active'] else '📄 '}{c['id']} ({c['created_at']})"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"view_chat_{c['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    await call.message.edit_text("📁 Ваши чаты:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("view_chat_"))
async def cb_view_chat(call: types.CallbackQuery):
    user_id = call.from_user.id
    chat_id = call.data.split("view_chat_")[1]
    chat = get_chat_by_id(user_id, chat_id)
    if not chat:
        await call.answer("Чат не найден")
        return

    msgs = chat["messages"]
    if not msgs:
        await call.answer("Чат пуст")
        return

    # Отправляем историю чата в виде пересланных сообщений
    await call.message.answer(f"📜 Чат {chat_id} от {chat['created_at']}:")
    # Пересылаем по 3 сообщения, чтобы не упереться в лимиты
    for i in range(0, len(msgs), 3):
        chunk = msgs[i:i+3]
        text = "\n\n".join([f"{'👤' if m['role']=='user' else '🤖'}: {m['content'][:500]}" for m in chunk])
        await call.message.answer(text)
    
    await call.message.answer("Конец истории.", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(call: types.CallbackQuery):
    await start_cmd(call.message)

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========
@dp.message(F.photo)
async def handle_photo(m: types.Message):
    user_id = m.from_user.id
    chat = get_active_chat(user_id)
    if not chat:
        await m.answer("Сначала создайте или выберите активный чат через /menu", reply_markup=main_menu_keyboard())
        return

    wait = await m.answer("ЩА ДРУГ ПОГОДИ СЕКУНДУ...")
    photo = m.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_bytes = await bot.download_file(file.file_path)
    photo_base64 = base64.b64encode(file_bytes.read()).decode('utf-8')
    caption = m.caption if m.caption else ""
    ans = await ask_ai_vision(chat, caption, photo_base64)
    await wait.edit_text(ans)

@dp.message(F.text)
async def handle_text(m: types.Message):
    user_id = m.from_user.id
    chat = get_active_chat(user_id)
    if not chat:
        if m.text.startswith('/'):
            return  # команды обработаются другими хендлерами
        await m.answer("Сначала создайте или выберите активный чат через /menu", reply_markup=main_menu_keyboard())
        return

    wait = await m.answer("ЩА ДРУГ ПОГОДИ СЕКУНДУ...")
    ans = await ask_ai_text(chat, m.text)
    await wait.edit_text(ans)

# ========== INLINE (без активного чата) ==========
@dp.inline_query()
async def inline(q: types.InlineQuery):
    txt = q.query.strip()
    if not txt:
        r = [InlineQueryResultArticle(id="1", title="Введи запрос",
              input_message_content=InputTextMessageContent(message_text="Напишите вопрос после @aiOAO_bot"))]
        await q.answer(r, cache_time=1)
        return
    try:
        r = await client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": "Ты — AI-ассистент, отвечай развёрнуто и дружелюбно."},
                {"role": "user", "content": txt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        ans = r.choices[0].message.content.strip()
    except Exception as e:
        ans = f"Ошибка: {e}"
    result = InlineQueryResultArticle(id="1", title=txt[:50], description=ans[:100],
          input_message_content=InputTextMessageContent(message_text=ans))
    await q.answer([result], cache_time=10)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())