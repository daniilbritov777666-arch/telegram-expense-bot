import logging
import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

TOKEN = "8808558522:AAFxRBXWUBmjLN2ZK3khHdt_hMXXP_eXxFw"
DB_FILE = "expenses.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATE, NAME, AMOUNT, COMMISSION, DIRECTION, PAYMENT, COMMENT, CONFIRM = range(8)


def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("+ Добавить расход", callback_data="add")],
        [InlineKeyboardButton("Итог за месяц", callback_data="finish")],
    ]
    await update.message.reply_text(
        "Привет! Я бот учёта расходов.\n\nВыбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        msg = query.message
    else:
        msg = update.message
    context.user_data.clear()
    await msg.reply_text("Шаг 1/7 - Дата оплаты\n\nВведи дату в формате ДД.ММ.ГГГГ\nНапример: 14.05.2026")
    return DATE


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%d.%m.%Y")
    except ValueError:
        await update.message.reply_text("Неверный формат. Введи дату как ДД.ММ.ГГГГ\nНапример: 14.05.2026")
        return DATE
    context.user_data["date"] = text
    await update.message.reply_text("Шаг 2/7 - Наименование оплаты\n\nНапиши за что платёж:")
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Шаг 3/7 - Сумма оплаты\n\nВведи сумму (например: 1500.50):")
    return AMOUNT


async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("Введи только число, например: 1500.50")
        return AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text("Шаг 4/7 - Сумма комиссии\n\nВведи сумму комиссии (или 0 если нет):")
    return COMMISSION


async def get_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        commission = float(text)
    except ValueError:
        await update.message.reply_text("Введи только число, например: 50 или 0")
        return COMMISSION
    context.user_data["commission"] = commission
    keyboard = [
        [InlineKeyboardButton("Расход", callback_data="dir_расход")],
        [InlineKeyboardButton("Развитие", callback_data="dir_развитие")],
    ]
    await update.message.reply_text(
        "Шаг 5/7 - Направление\n\nВыбери категорию:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DIRECTION


async def get_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["direction"] = query.data.replace("dir_", "")
    keyboard = [
        [InlineKeyboardButton("ИП", callback_data="pay_ИП")],
        [InlineKeyboardButton("Наличные", callback_data="pay_Наличные")],
        [InlineKeyboardButton("Карта Соня", callback_data="pay_Карта Соня")],
    ]
    await query.message.reply_text(
        "Шаг 6/7 - Форма оплаты\n\nВыбери способ оплаты:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PAYMENT


async def get_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["payment"] = query.data.replace("pay_", "")
    await query.message.reply_text("Шаг 7/7 - Комментарий\n\nДобавь комментарий или напиши: нет")
    return COMMENT


async def get_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()
    if comment.lower() == "нет":
        comment = "-"
    context.user_data["comment"] = comment
    d = context.user_data
    summary = (
        "Проверь данные перед сохранением:\n\n"
        "Дата: " + d["date"] + "\n"
        "Наименование: " + d["name"] + "\n"
        "Сумма: " + str(d["amount"]) + " руб\n"
        "Комиссия: " + str(d["commission"]) + " руб\n"
        "Направление: " + d["direction"] + "\n"
        "Форма оплаты: " + d["payment"] + "\n"
        "Комментарий: " + d["comment"] + "\n"
    )
    keyboard = [
        [InlineKeyboardButton("Сохранить", callback_data="save")],
        [InlineKeyboardButton("Отменить", callback_data="cancel_entry")],
    ]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "save":
        db = load_db()
        record = {
            "date": context.user_data["date"],
            "name": context.user_data["name"],
            "amount": context.user_data["amount"],
            "commission": context.user_data["commission"],
            "direction": context.user_data["direction"],
            "payment": context.user_data["payment"],
            "comment": context.user_data["comment"],
            "added_by": query.from_user.full_name,
            "timestamp": datetime.now().isoformat()
        }
        db.append(record)
        save_db(db)
        keyboard = [
            [InlineKeyboardButton("+ Добавить ещё", callback_data="add")],
            [InlineKeyboardButton("Итог за месяц", callback_data="finish")],
        ]
        await query.message.reply_text("Запись сохранена!", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text("Запись отменена. Напиши /start чтобы начать заново.")
    context.user_data.clear()
    return ConversationHandler.END


async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        send = query.message.reply_text
    else:
        send = update.message.reply_text

    now = datetime.now()
    db = load_db()
    month_records = []
    for r in db:
        try:
            d = datetime.strptime(r["date"], "%d.%m.%Y")
            if d.month == now.month and d.year == now.year:
                month_records.append(r)
        except Exception:
            continue

    if not month_records:
        await send("За " + now.strftime("%m.%Y") + " расходов не найдено.")
        return

    total_amount = sum(r["amount"] for r in month_records)
    total_commission = sum(r["commission"] for r in month_records)
    total_all = total_amount + total_commission

    by_direction = {}
    for r in month_records:
        k = r["direction"]
        by_direction[k] = by_direction.get(k, 0) + r["amount"] + r["commission"]

    by_payment = {}
    for r in month_records:
        k = r["payment"]
        by_payment[k] = by_payment.get(k, 0) + r["amount"] + r["commission"]

    dir_text = "\n".join(["  - " + k + ": " + str(round(v, 2)) + " руб" for k, v in by_direction.items()])
    pay_text = "\n".join(["  - " + k + ": " + str(round(v, 2)) + " руб" for k, v in by_payment.items()])

    text = (
        "Итог за " + now.strftime("%m.%Y") + "\n"
        "Записей: " + str(len(month_records)) + "\n\n"
        "Сумма расходов: " + str(round(total_amount, 2)) + " руб\n"
        "Сумма комиссий: " + str(round(total_commission, 2)) + " руб\n"
        "ИТОГО (с комиссией): " + str(round(total_all, 2)) + " руб\n\n"
        "По направлениям:\n" + dir_text + "\n\n"
        "По форме оплаты:\n" + pay_text
    )
    await send(text)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Отменено. Напиши /start чтобы начать заново.")
    return ConversationHandler.END


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "finish":
        await finish(update, context)
    elif query.data == "add":
        await add_start(update, context)


def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            CallbackQueryHandler(add_start, pattern="^add$"),
        ],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            COMMISSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_commission)],
            DIRECTION: [CallbackQueryHandler(get_direction, pattern="^dir_")],
            PAYMENT: [CallbackQueryHandler(get_payment, pattern="^pay_")],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_comment)],
            CONFIRM: [CallbackQueryHandler(confirm, pattern="^(save|cancel_entry)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("finish", finish))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(finish|add)$"))

    print("Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
