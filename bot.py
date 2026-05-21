import asyncio, os
from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from aiogram.filters import Command
from aiogram import F

# ---------- Токены вшиты напрямую ----------
TOKEN = "8788937942:AAG8dVIgBWt9h0zr_uXWyWKkEik0uiDPrwA"
API_KEY = "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"
# -------------------------------------------

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://openrouter.ai/api/v1"
)

MODEL = "meta-llama/llama-3.2-3b-instruct:free"  # бесплатная модель

bot = Bot(token=TOKEN)
dp = Dispatcher()

async def ask_ai(q):
    try:
        r = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Ты — AI-ассистент, отвечай развёрнуто и дружелюбно."},
                {"role": "user", "content": q}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка: {e}"

@dp.message(Command("start"))
async def start_cmd(m: types.Message):
    await m.answer("Привет! Я AI-помощник от ОАО. Сейчас на бесплатной модели Llama 🤖")

@dp.message(F.text)
async def handle(m: types.Message):
    wait = await m.answer("ЩА ДРУГ ПОГОДИ СЕКУНДУ...")
    ans = await ask_ai(m.text)
    await wait.edit_text(ans)

@dp.inline_query()
async def inline(q: types.InlineQuery):
    txt = q.query.strip()
    if not txt:
        r = [InlineQueryResultArticle(id="1", title="Введи запрос",
              input_message_content=InputTextMessageContent(message_text="Напишите вопрос после @aiOAO_bot"))]
        await q.answer(r, cache_time=1)
        return
    ans = await ask_ai(txt)
    r = [InlineQueryResultArticle(id="1", title=txt[:50], description=ans[:100],
          input_message_content=InputTextMessageContent(message_text=ans))]
    await q.answer(r, cache_time=10)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())