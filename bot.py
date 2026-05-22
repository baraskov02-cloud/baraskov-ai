import asyncio, os, time, uuid, re
from datetime import datetime, timedelta
from collections import defaultdict
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
user_chats = defaultdict(list)
active_chat = {}

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
    return [{"role": msg["role"], "content": msg["content"]} for msg in chat["messages"]]

def add_message_to_chat(chat, role, content):
    chat["messages"].append({"role": role, "content": content})

# ========== ХРАНИЛИЩЕ НАПОМИНАНИЙ ==========
# reminders[user_id] = список словарей: {'id': int, 'time': datetime, 'text': str}
reminders = defaultdict(list)
reminder_counter = 1  # для нумерации напоминаний

# ========== КНОПКИ ==========
def main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💬 Новый чат", callback_data="new_chat"),
        InlineKeyboardButton(text="📁 Мои чаты", callback_data="my_chats")
    )
    builder.row(
        InlineKeyboardButton(text="⏰ Напоминания", callback_data="reminders")
    )
    return builder.as_markup()

def active_chat_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏹ Завершить чат", callback_data="end_chat"),
        InlineKeyboardButton(text="📁 Мои чаты", callback_data="my_chats")
    )
    return builder.as_markup()

def after_answer_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏹ Завершить чат", callback_data="end_chat"),
        InlineKeyboardButton(text="📁 Мои чаты", callback_data="my_chats")
    )
    return builder.as_markup()

# ========== AI (только текст) ==========
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

# ========== ПРОВЕРКА НАПОМИНАНИЙ (фоновый таск) ==========
async def reminder_checker():
    while True:
        now = datetime.now()
        for user_id, user_reminders in list(reminders.items()):
            for rem in user_reminders[:]:
                if rem['time'] <= now:
                    try:
                        await bot.send_message(
                            user_id,
                            f"🔔 Напоминание:\n{rem['text']}"
                        )
                    except:
                        pass  # если пользователь заблокировал бота
                    user_reminders.remove(rem)
        await asyncio.sleep(30)  # проверять каждые 30 секунд

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def start_cmd(m: types.Message):
    await m.answer(
        "👋 Привет! Я AI-помощник с историей чатов и напоминаниями.\n"
        "Используй кнопки ниже для управления.",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("menu"))
async def menu_cmd(m: types.Message):
    await start_cmd(m)

@dp.message(Command("remind"))
async def remind_cmd(m: types.Message):
    global reminder_counter
    user_id = m.from_user.id
    # Формат: /remind 17:00 текст
    args = m.text.strip().split(maxsplit=2)
    if len(args) < 3:
        await m.answer(
            "❌ Неверный формат.\n"
            "Пример: `/remind 17:00 Купить хлеб`\n"
            "Время в формате ЧЧ:ММ, текст — обязательно.",
            parse_mode="Markdown"
        )
        return
    time_str = args[1]
    text = args[2]
    # Парсим время
    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except:
        await m.answer("❌ Неверный формат времени. Используй ЧЧ:ММ, например 17:00.")
        return

    now = datetime.now()
    reminder_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reminder_time <= now:
        reminder_time += timedelta(days=1)  # если время уже прошло, ставим на завтра

    rem_id = reminder_counter
    reminder_counter += 1
    reminders[user_id].append({
        'id': rem_id,
        'time': reminder_time,
        'text': text
    })
    await m.answer(
        f"✅ Напоминание №{rem_id} установлено на {reminder_time.strftime('%H:%M')}:\n"
        f"«{text}»"
    )

@dp.message(Command("myreminds"))
async def myreminds_cmd(m: types.Message):
    user_id = m.from_user.id
    if not reminders[user_id]:
        await m.answer("У вас нет активных напоминаний.")
        return
    msg_lines = ["📋 **Ваши напоминания:**"]
    for rem in reminders[user_id]:
        msg_lines.append(f"№{rem['id']} — {rem['time'].strftime('%H:%M')} — {rem['text']}")
    msg_lines.append("\nУдалить: `/delremind НОМЕР`")
    await m.answer("\n".join(msg_lines), parse_mode="Markdown")

@dp.message(Command("delremind"))
async def delremind_cmd(m: types.Message):
    user_id = m.from_user.id
    args = m.text.strip().split()
    if len(args) < 2:
        await m.answer("Укажите номер напоминания: `/delremind 1`", parse_mode="Markdown")
        return
    try:
        num = int(args[1])
    except:
        await m.answer("Номер должен быть числом.")
        return
    before = len(reminders[user_id])
    reminders[user_id] = [r for r in reminders[user_id] if r['id'] != num]
    after = len(reminders[user_id])
    if before == after:
        await m.answer(f"Напоминание №{num} не найдено.")
    else:
        await m.answer(f"🗑 Напоминание №{num} удалено.")

# ========== CALLBACK-ОБРАБОТЧИКИ ==========
@dp.callback_query(F.data == "new_chat")
async def cb_new_chat(call: types.CallbackQuery):
    user_id = call.from_user.id
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
        f"✅ Новый чат создан ({chat_id}).\nЗадайте ваш вопрос.",
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
            f"⏹ Чат {chat['id']} завершён и сохранён.",
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
    sorted_chats = sorted(chats, key=lambda x: x["created_at"], reverse=True)
    builder = InlineKeyboardBuilder()
    for c in sorted_chats:
        label = f"{'📌 ' if c['active'] else '📄 '}{c['id']} ({c['created_at']})"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"view_chat_{c['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    await call.message.edit_text("📁 Ваши чаты:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "reminders")
async def cb_reminders(call: types.CallbackQuery):
    await call.message.edit_text(
        "⏰ **Напоминания**\n\n"
        "• Создать: `/remind 17:00 Купить хлеб`\n"
        "• Посмотреть: `/myreminds`\n"
        "• Удалить: `/delremind НОМЕР`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardBuilder()
            .row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
            .as_markup()
    )

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
    await call.message.answer(f"📜 Чат {chat_id} от {chat['created_at']}:")
    for i in range(0, len(msgs), 3):
        chunk = msgs[i:i+3]
        text = "\n\n".join([f"{'👤' if m['role']=='user' else '🤖'}: {m['content'][:500]}" for m in chunk])
        await call.message.answer(text)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить чат", callback_data=f"delete_chat_{chat_id}"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="my_chats")
    )
    await call.message.answer("Действия:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("delete_chat_"))
async def cb_delete_chat(call: types.CallbackQuery):
    user_id = call.from_user.id
    chat_id = call.data.split("delete_chat_")[1]
    user_chats[user_id] = [c for c in user_chats[user_id] if c["id"] != chat_id]
    if active_chat.get(user_id) == chat_id:
        active_chat.pop(user_id, None)
    await call.message.edit_text(f"🗑 Чат {chat_id} удалён.", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(call: types.CallbackQuery):
    await start_cmd(call.message)

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========
@dp.message(F.photo)
async def handle_photo(m: types.Message):
    await m.answer("📷 Я работаю только с текстом. Отправьте вопрос словами.")

@dp.message(F.text)
async def handle_text(m: types.Message):
    user_id = m.from_user.id
    chat = get_active_chat(user_id)
    if not chat:
        if m.text.startswith('/'):
            return
        await m.answer("Сначала создайте чат через /menu", reply_markup=main_menu_keyboard())
        return
    wait = await m.answer("ЩА ДРУГ ПОГОДИ СЕКУНДУ...")
    ans = await ask_ai_text(chat, m.text)
    await wait.edit_text(ans, reply_markup=after_answer_keyboard())

# ========== INLINE ==========
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
    # Запускаем фоновую проверку напоминаний
    asyncio.create_task(reminder_checker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())