import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiocryptopay import AioCryptoPay, Networks

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "8575793456:AAHsBAadhTUtqpKJ8y1nUh581KsD2-F-1vM"
CRYPTO_TOKEN = "582564:AAoc74UICvR25vnbobMEFVGg1n8xz8TJhhY"

CHANNEL_ID = -1003982895940
BASE_PRICE = 5  # ~115 Kč, чтобы чистыми выходило 100 крон

# ================= СОСТОЯНИЯ ДЛЯ СВОЕЙ СУММЫ =================


class TipState(StatesGroup):
    waiting_for_amount = State()

# ================= БАЗА ДАННЫХ =================


def init_db():
    conn = sqlite3.connect('sales.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            username TEXT,
            user_id TEXT,
            total_sum REAL,
            tip REAL,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()


def log_sale(username, user_id, total_sum, tip):
    conn = sqlite3.connect('sales.db')
    cursor = conn.cursor()
    date_now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    cursor.execute(
        'INSERT INTO sales (date, username, user_id, total_sum, tip, status) VALUES (?, ?, ?, ?, ?, ?)',
        (date_now, f"@{username}" if username else "NoUsername",
         str(user_id), total_sum, tip, "Success")
    )
    conn.commit()
    conn.close()


# ================= ИНИЦИАЛИЗАЦИЯ =================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

crypto = None

# ================= КЛАВИАТУРЫ =================


def get_start_kb():
    buttons = [
        [InlineKeyboardButton(text="🆓 Наш бесплатный канал",
                              url="https://t.me/CatLite")],
        [InlineKeyboardButton(
            text="💳 Перейти к оплате курса", callback_data="go_to_pay")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_pay_options():
    buttons = [
        [InlineKeyboardButton(
            text=f"Курс ({BASE_PRICE} USDT)", callback_data=f"pay_{BASE_PRICE}")],
        [InlineKeyboardButton(
            text="Курс + Чай ☕ (7.0 USDT)", callback_data="pay_7.0")],
        [InlineKeyboardButton(
            text="✍️ Другая сумма (Курс + твой Чай)", callback_data="pay_custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_check_kb(url, invoice_id):
    buttons = [
        [InlineKeyboardButton(text="💳 Оплатить", url=url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату",
                              callback_data=f"check_{invoice_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= ОБРАБОТЧИКИ =================


@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 **Привет! Рад видеть тебя в CatPay!**\n\n"
        "Прежде чем приобрести курс, я настоятельно рекомендую заглянуть в наш "
        "бесплатный канал. Там я подробно рассказываю про ИИ, делюсь секретами автоматизации "
        "и показываю, как именно нейросети помогают зарабатывать реальные деньги! 💰🚀\n\n"
        "Переходи по кнопке ниже 👇, изучай информацию, а когда будешь готов присоединиться "
        "к приватному обучению — просто напиши мне команду /pay или нажми вторую кнопку прямо здесь."
    )
    await message.answer(text, reply_markup=get_start_kb(), parse_mode="Markdown")

# Обработчик для кнопки "Перейти к оплате" из стартового меню


@dp.callback_query(F.data == "go_to_pay")
async def go_to_pay_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        f"Выбери вариант оплаты. Курс с учетом комиссии сервиса стоит **{BASE_PRICE} USDT**.\n"
        "Ты можешь выбрать готовый вариант или указать свою сумму (поддержать автора)! 👇",
        reply_markup=get_pay_options(),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(Command("pay"))
async def pay_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Выбери вариант оплаты. Курс с учетом комиссии сервиса стоит **{BASE_PRICE} USDT**.\n"
        "Ты можешь выбрать готовый вариант или указать свою сумму (поддержать автора)! 👇",
        reply_markup=get_pay_options(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "pay_custom")
async def pay_custom_cmd(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"Введите сумму в USDT, которую вы хотите отправить (минимум **{BASE_PRICE}**):\n\n"
        "Пример: `5.5` или `15`",
        parse_mode="Markdown"
    )
    await state.set_state(TipState.waiting_for_amount)
    await callback.answer()


@dp.message(TipState.waiting_for_amount)
async def process_custom_amount(message: Message, state: FSMContext):
    text = message.text.replace(",", ".")

    try:
        amount = float(text)
        if amount < BASE_PRICE:
            await message.answer(f"❌ Сумма не может быть меньше стоимости курса ({BASE_PRICE} USDT). Попробуй еще раз:")
            return

        amount = round(amount, 2)
        invoice = await crypto.create_invoice(asset="USDT", amount=amount)

        await message.answer(
            f"Сумма к оплате: **{amount} USDT**\n\n"
            "После оплаты нажми кнопку проверки ниже. Доступ придет мгновенно!",
            reply_markup=get_check_kb(
                invoice.bot_invoice_url, invoice.invoice_id),
            parse_mode="Markdown"
        )
        await state.clear()

    except ValueError:
        await message.answer("❌ Пожалуйста, введи корректное число. Например: `6.5`", parse_mode="Markdown")


@dp.callback_query(F.data.startswith("pay_"))
async def create_invoice(callback: CallbackQuery):
    amount = float(callback.data.split("_")[1])
    invoice = await crypto.create_invoice(asset="USDT", amount=amount)

    await callback.message.edit_text(
        f"Сумма к оплате: **{amount} USDT**\n\n"
        "После оплаты нажми кнопку проверки ниже. Доступ придет мгновенно!",
        reply_markup=get_check_kb(invoice.bot_invoice_url, invoice.invoice_id),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("check_"))
async def check_invoice(callback: CallbackQuery):
    invoice_id = int(callback.data.split("_")[1])

    # В этой версии библиотеки нам возвращается сразу объект счета
    invoice = await crypto.get_invoices(invoice_ids=invoice_id)

    # Проверяем статус напрямую у invoice
    if invoice and invoice.status == "paid":
        total = float(invoice.amount)
        tip = round(total - BASE_PRICE, 2)
        user = callback.from_user

        await callback.message.edit_text("✅ Оплата получена! Генерирую твой пропуск...")

        log_sale(user.username, user.id, total, tip)

        try:
            # Создаем ссылку, которая сгорит после 1 входа
            link = await bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                name=f"User_{user.id}"
            )

            # Исправленный текст без ошибок разметки
            await bot.send_message(
                user.id,
                f"🎉 Добро пожаловать!\n\nТвоя уникальная ссылка на вход:\n{link.invite_link}\n\n"
                f"Внимание: ссылка сработает только для ОДНОГО входа.",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Link Error: {e}")
            await bot.send_message(user.id, f"Ошибка при отправке ссылки: {e}")
    else:
        await callback.answer("❌ Оплата еще не прошла или счет не найден.", show_alert=True)

# ================= ЗАПУСК =================


async def main():
    global crypto
    crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)

    init_db()
    print("Бот запущен и готов принимать платежи с чаевыми! 🚀")

    try:
        await dp.start_polling(bot)
    finally:
        await crypto.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
