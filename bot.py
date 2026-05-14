    import logging
import json
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

# ——— Настройки ———
TOKEN = "8808558522:AAFxRBXWUBmjLN2ZK3khHdt_hMXXP_eXxFw"
DB_FILE = "expenses.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——— Шаги диалога ———
DATE, NAME, AMOUNT, COMMISSION, DIRECTION, PAYMENT, COMMENT, CONFIRM = range(8)

# ——— База данных (простой JSON файл) ———
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ——— /start ———
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить расход", callback_data="add")],
        [InlineKeyboardButton("📊 Итог за месяц (/finish)", callback_data="finish")],
    ]
    await update.message.reply_text(
        "👋 Привет! Я бот учёта расходов.\n\n"
        "Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ——— Старт добавления записи ———
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.reply_text(
            "📅 *Шаг 1/7 — Дата оплаты*\n\nВведи дату в формате ДД.ММ.ГГГГ\n_(например: 14.05.2025)_",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "📅 *Шаг 1/7 — Дата оплаты*\n\nВведи дату в формате ДД.ММ.ГГГГ\n_(например: 14.05.2025)_",
            parse_mode="Markdown"
        )
    context.user_data.clear()
    return DATE

# ——— Шаг 1: Дата ———
async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.strptime(text, "%d.%m.%Y")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введи дату как ДД.ММ.ГГГГ\n_(например: 14.05.2025)_", parse_mode="Markdown")
        return DATE
    context.user_data["date"] = text
    await update.message.reply_text("🏷 *Шаг 2/7 — Наименование оплаты*\n\nНапиши за что платёж:", parse_mode="Markdown")
    return NAME

# ——— Шаг 2: Наименование ———
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("💰 *Шаг 3/7 — Сумма оплаты*\n\nВведи сумму (только цифры, например: 1500.50):", parse_mode="Markdown")
    return AMOUNT

# ——— Шаг 3: Сумма ———
async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ Введи только число, например: 1500.50")
        return AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text("📋 *Шаг 4/7 — Сумма комиссии*\n\nВведи сумму комиссии (или 0 если нет):", parse_mode="Markdown")
    return COMMISSION

# ——— Шаг 4: Комиссия ———
async def get_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    try:
        commission = float(text)
    except ValueError:
        await update.message.reply_text("❌ Введи только число, например: 50 или 0")
        return COMMISSION
    context.user_data["commission"] = commission

    keyboard = [
        [InlineKeyboardButton("📉 Расход", callback_data="dir_расход")],
        [InlineKeyboardButton("📈 Развитие", callback_data="dir_развитие")],
    ]
    await update.message.reply_text(
        "🎯 *Шаг 5/7 — Направление*\n\nВыбери категорию:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DIRECTION

# ——— Шаг 5: Направление ———
async def get_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    direction = query.data.replace("dir_", "")
    context.user_data["direction"] = direction

    keyboard = [
        [InlineKeyboardButton("🏢 ИП", callback_data="pay_ИП")],
        [InlineKeyboardButton("💵 Наличные", callback_data="pay_Наличные")],
        [InlineKeyboardButton("💳 Карта Соня", callback_data="pay_Карта Соня")],
    ]
    await query.message.reply_text(
        "💳 *Шаг 6/7 — Форма оплаты*\n\nВыбери способ оплаты:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PAYMENT

# ——— Шаг 6: Форма оплаты ———
async def get_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    payment = query.data.replace("pay_", "")
    context.user_data["payment"] = payment

    await query.message.reply_text(
        "💬 *Шаг 7/7 — Комментарий*\n\nДобавь комментарий или напиши *нет* если не нужен:",
        parse_mode="Markdown"
    )
    return COMMENT

# ——— Шаг 7: Комментарий + Подтверждение ———
async def get_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()
    if comment.lower() == "нет":
        comment = "—"
    context.user_data["comment"] = comment

    d = context.user_data
    summary = (
        f"✅ *Проверь данные перед сохранением:*\n\n"
        f"📅 Дата: {d['date']}\n"
        f"🏷 Наименование: {d['name']}\n"
        f"💰 Сумма: {d['amount']:,.2f} ₽\n"
        f"📋 Комиссия: {d['commission']:,.2f} ₽\n"
        f"🎯 Направление: {d['direction']}\n"
        f"💳 Форма оплаты: {d['payment']}\n"
        f"💬 Комментарий: {d['comment']}\n"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Сохранить", callback_data="save")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel")],
    ]
    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM

# ——— Сохранение или отмена ———
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
            [InlineKeyboardButton("➕ Добавить ещё", callback_data="add")],
            [InlineKeyboardButton("📊 Итог за месяц", callback_data="finish")],
        ]
        await query.message.reply_text(
            "✅ *Запись сохранена!*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.message.reply_text("❌ Запись отменена. Напиши /start чтобы начать заново.")

    context.user_data.clear()
    return ConversationHandler.END

# ——— /finish — итог за текущий месяц ———
async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Поддержка вызова через inline кнопку или команду
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        send = query.message.reply_text
    else:
        send = update.message.reply_text

    now = datetime.now()
    current_month = now.month
    current_year = now.year

    db = load_db()

    # Фильтруем за текущий месяц
    month_records = []
    for r in db:
        try:
            d = datetime.strptime(r["date"], "%d.%m.%Y")
            if d.month == current_month and d.year == current_year:
                month_records.append(r)
        except:
            continue

    if not month_records:
        await send(f"📊 За {now.strftime('%B %Y')} расходов не найдено.")
        return

    # Считаем итоги
    total_amount = sum(r["amount"] for r in month_records)
    total_commission = sum(r["commission"] for r in month_records)
    total_all = total_amount + total_commission

    # По направлениям
    by_direction = {}
    for r in month_records:
        d = r["direction"]
        by_direction[d] = by_direction.get(d, 0) + r["amount"] + r["commission"]

    # По форме оплаты
    by_payment = {}
    for r in month_records:
        p = r["payment"]
        by_payment[p] = by_payment.get(p, 0) + r["amount"] + r["commission"]

    dir_text = "\n".join([f"  • {k}: {v:,.2f} ₽" for k, v in by_direction.items()])
    pay_text = "\n".join([f"  • {k}: {v:,.2f} ₽" for k, v in by_payment.items()])

    month_name = now.strftime("%B %Y")
    text = (
        f"📊 *Итог за {month_name}*\n"
        f"Записей: {len(month_records)}\n\n"
        f"💰 Сумма расходов: {total_amount:,.2f} ₽\n"
        f"📋 Сумма комиссий: {total_commission:,.2f} ₽\n"
        f"📦 *Итого (с комиссией): {total_all:,.2f} ₽*\n\n"
        f"🎯 *По направлениям:*\n{dir_text}\n\n"
        f"💳 *По форме оплаты:*\n{pay_text}"
    )
    await send(text, parse_mode="Markdown")

# ——— Отмена диалога ———
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено. Напиши /start чтобы начать заново.")
    return ConversationHandler.END

# ——— Обработка inline кнопок вне диалога ———
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "finish":
        await finish(update, context)
    elif query.data == "add":
        await add_start(update, context)

# ——— Запуск ———
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
            CONFIRM: [CallbackQueryHandler(confirm, pattern="^(save|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("finish", finish))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(finish|add)$"))

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
