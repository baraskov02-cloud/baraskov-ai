import asyncio, os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from aiogram.filters import Command
from aiogram import F

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")

client = AsyncOpenAI(
    api_key=GROQ_KEY,
    base_url="https://api.groq.com/openai/v1"
)

MODEL = "llama-3.1-8b-instant"

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
    await m.answer("Привет! Я AI-помощник от ОАО. Теперь на Groq 🤖")

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