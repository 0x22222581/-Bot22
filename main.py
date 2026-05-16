import asyncio
import logging
import sqlite3
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiocryptopay import AioCryptoPay, Networks

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
CHANNEL_ID = -1003982895940
BASE_PRICE = 0.1  # ~115 Kč, чтобы чистыми выходило 100 крон

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
        [InlineKeyboardButton(text="🆓 Náš bezplatný kanál",
                              url="https://t.me/CatLite")],
        [InlineKeyboardButton(text="💳 Přejít k platbě kurzu",
                              callback_data="go_to_pay")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_pay_options():
    buttons = [
        [InlineKeyboardButton(
            text=f"Kurz ({BASE_PRICE} USDT)", callback_data=f"pay_{BASE_PRICE}")],
        [InlineKeyboardButton(
            text="Kurz + Dýško ☕ (7.0 USDT)", callback_data="pay_7.0")],
        [InlineKeyboardButton(
            text="✍️ Jiná částka (Kurz + tvé dýško)", callback_data="pay_custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_check_kb(url, invoice_id):
    buttons = [
        [InlineKeyboardButton(text="💳 Zaplatit", url=url)],
        [InlineKeyboardButton(text="🔄 Zkontrolovat platbu",
                              callback_data=f"check_{invoice_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= ОБРАБОТЧИКИ =================


@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 **Ahoj! Rád tě vidím v CatPay!**\n\n"
        "Než si pořídíš kurz, vřele doporučuji nahlédnout do našeho "
        "bezplatného kanálu. Tam podrobně mluvím o umělé inteligenci, sdílím tajemství automatizace "
        "a ukazuji, jak přesně neuronové sítě pomáhají vydělávat reálné peníze! 💰🚀\n\n"
        "Klikni na tlačítko níže 👇, prostuduj si informace, a až budeš připraven připojit se "
        "k privátnímu kurzu — jednoduše mi napiš příkaz /pay nebo klikni na druhé tlačítko přímo zde."
    )
    await message.answer(text, reply_markup=get_start_kb(), parse_mode="Markdown")


@dp.callback_query(F.data == "go_to_pay")
async def go_to_pay_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        f"Vyber si variantu platby. Kurz včetně poplatků služby stojí **{BASE_PRICE} USDT**.\n"
        "Můžeš si vybrat hotovou variantu nebo zadat vlastní částku (a podpořit autora)! 👇",
        reply_markup=get_pay_options(),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.message(Command("pay"))
async def pay_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Vyber si variantu platby. Kurz včetně poplatků služby stojí **{BASE_PRICE} USDT**.\n"
        "Můžeš si vybrat hotovou variantu nebo zadat vlastní částku (a podpořit autora)! 👇",
        reply_markup=get_pay_options(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "pay_custom")
async def pay_custom_cmd(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"Zadej částku v USDT, kterou chceš poslat (minimum **{BASE_PRICE}**):\n\n"
        "Příklad: `5.5` nebo `15`",
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
            await message.answer(f"❌ Částka nesmí být menší než cena kurzu ({BASE_PRICE} USDT). Zkus to znovu:")
            return

        amount = round(amount, 2)
        invoice = await crypto.create_invoice(asset="USDT", amount=amount)

        await message.answer(
            f"Částka k platbě: **{amount} USDT**\n\n"
            "Po zaplacení klikni na tlačítko kontroly níže. Přístup obdržíš okamžitě!",
            reply_markup=get_check_kb(
                invoice.bot_invoice_url, invoice.invoice_id),
            parse_mode="Markdown"
        )
        await state.clear()

    except ValueError:
        await message.answer("❌ Zadej prosím platné číslo. Například: `6.5`", parse_mode="Markdown")


@dp.callback_query(F.data.startswith("pay_"))
async def create_invoice(callback: CallbackQuery):
    amount = float(callback.data.split("_")[1])
    invoice = await crypto.create_invoice(asset="USDT", amount=amount)

    await callback.message.edit_text(
        f"Částka k platbě: **{amount} USDT**\n\n"
        "Po zaplacení klikni na tlačítko kontroly níže. Přístup obdržíš okamžitě!",
        reply_markup=get_check_kb(invoice.bot_invoice_url, invoice.invoice_id),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("check_"))
async def check_invoice(callback: CallbackQuery):
    invoice_id = int(callback.data.split("_")[1])

    invoice = await crypto.get_invoices(invoice_ids=invoice_id)

    if invoice and invoice.status == "paid":
        total = float(invoice.amount)
        tip = round(total - BASE_PRICE, 2)
        user = callback.from_user

        await callback.message.edit_text("✅ Platba byla přijata! Generuji tvoji propustku...")

        log_sale(user.username, user.id, total, tip)

        try:
            link = await bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                name=f"User_{user.id}"
            )

            await bot.send_message(
                user.id,
                f"🎉 Vítej!\n\nTady je tvůj unikátní odkaz pro vstup:\n{link.invite_link}\n\n"
                f"Pozor: Odkaz bude fungovat pouze pro JEDEN vstup.",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Link Error: {e}")
            await bot.send_message(user.id, f"Chyba při odesílání odkazu: {e}")
    else:
        await callback.answer("❌ Platba zatím neprošla nebo účet nebyl nalezen.", show_alert=True)

# ================= ЗАПУСК =================


async def main():
    global crypto
    crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)

    init_db()
    print("Bot je spuštěn a připraven přijímat platby s dýšky! 🚀")

    try:
        await dp.start_polling(bot)
    finally:
        await crypto.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
