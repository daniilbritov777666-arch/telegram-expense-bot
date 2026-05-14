import logging
import json
import os
from pathlib import Path
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

BASE_DIR = Path(__file__).resolve().parent

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", str(BASE_DIR / "expenses.json"))
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
CREDENTIALS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", str(BASE_DIR / "credentials.json"))
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATE, NAME, AMOUNT, COMMISSION, DIRECTION, PAYMENT, COMMENT, CONFIRM = range(8)


def require_env():
    missing = []
    if not TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not SPREADSHEET_ID:
        missing.append("GOOGLE_SPREADSHEET_ID")
    if not GOOGLE_CREDENTIALS_JSON and not os.path.exists(CREDENTIALS_FILE):
        missing.append("GOOGLE_CREDENTIALS_JSON")

    if missing:
        raise RuntimeError(
            "Не заданы переменные окружения для запуска: " + ", ".join(missing)
            + ". Добавь их в Railway Variables."
        )


def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_google_credentials(scopes):
    if GOOGLE_CREDENTIALS_JSON:
        try:
            service_account_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GOOGLE_CREDENTIALS_JSON содержит некорректный JSON") from exc
        return Credentials.from_service_account_info(service_account_info, scopes=scopes)

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            "Не найден файл Google credentials: " + CREDENTIALS_FILE
            + ". Положи credentials.json рядом с bot.py или задай GOOGLE_APPLICATION_CREDENTIALS."
        )

    return Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)


def google_error_text(error):
    message = str(error)
    lower_message = message.lower()

    if isinstance(error, FileNotFoundError):
        return str(error)
    if "invalid_grant" in lower_message or "invalid jwt signature" in lower_message:
        return (
            "Google не принимает ключ из credentials.json (invalid JWT signature). "
            "Создай новый JSON-ключ для сервисного аккаунта в Google Cloud, замени credentials.json "
            "и проверь, что дата/время на сервере выставлены правильно."
        )
    if "permission" in lower_message or "forbidden" in lower_message or "403" in lower_message:
        return (
            "нет доступа к Google Таблице. Открой таблицу и дай доступ на редактирование "
            "сервисному аккаунту из credentials.json: "
            + get_service_account_email()
        )
    if "not found" in lower_message or "404" in lower_message:
        return "таблица не найдена. Проверь GOOGLE_SPREADSHEET_ID/SPREADSHEET_ID."
    if "api has not been used" in lower_message or "disabled" in lower_message:
        return "в Google Cloud не включен Google Sheets API для проекта сервисного аккаунта."
    return message


def get_service_account_email():
    try:
        if GOOGLE_CREDENTIALS_JSON:
            return json.loads(GOOGLE_CREDENTIALS_JSON).get("client_email", "не указан")
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("client_email", "не указан")
    except Exception:
        return "не удалось прочитать client_email"


def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    creds = get_google_credentials(scopes)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    try:
        sheet = spreadsheet.worksheet("Расходы")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Расходы", rows=1000, cols=10)
        sheet.append_row(["Дата", "Наименование", "Сумма", "Комиссия", "Итого", "Направление", "Форма оплаты", "Комментарий", "Кто добавил", "Время записи"])
    return sheet


def write_to_sheet(record):
    try:
        sheet = get_sheet()
        total = record["amount"] + record["commission"]
        row = [
            record["date"],
            record["name"],
            record["amount"],
            record["commission"],
            round(total, 2),
            record["direction"],
            record["payment"],
            record["comment"],
            record["added_by"],
            record["timestamp"]
        ]
        sheet.append_row(row)
        return True, ""
    except Exception as e:
        error_text = google_error_text(e)
        logger.exception("Ошибка записи в Google Sheets: %s", error_text)
        return False, error_text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("+ Добавить расход", callback_data="add")],
        [InlineKeyboardButton("Итог за месяц", callback_data="finish")],
        [InlineKeyboardButton("Удалить все данные", callback_data="confirm_clear")],
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
        # Сохраняем локально
        db = load_db()
        db.append(record)
        save_db(db)
        # Пишем в Google Sheets
        sheets_ok, sheets_error = write_to_sheet(record)
        sheets_status = " и в Google Таблицу" if sheets_ok else "\n\nОшибка записи в таблицу: " + sheets_error

        keyboard = [
            [InlineKeyboardButton("+ Добавить ещё", callback_data="add")],
            [InlineKeyboardButton("Итог за месяц", callback_data="finish")],
        ]
        await query.message.reply_text(
            "Запись сохранена локально" + sheets_status,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
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

    detail_lines = []
    for i, r in enumerate(month_records, 1):
        total_r = r["amount"] + r["commission"]
        line = (
            str(i) + ". " + r["date"] + " | " + r["name"] + "\n"
            "   Сумма: " + str(r["amount"]) + " руб"
            + (" | Комиссия: " + str(r["commission"]) + " руб" if r["commission"] > 0 else "")
            + " | Итого: " + str(round(total_r, 2)) + " руб\n"
            "   " + r["direction"] + " | " + r["payment"]
            + (" | " + r["comment"] if r["comment"] != "-" else "")
        )
        detail_lines.append(line)

    header = (
        "Итог за " + now.strftime("%m.%Y") + "\n"
        "Всего записей: " + str(len(month_records)) + "\n\n"
        "Сумма расходов: " + str(round(total_amount, 2)) + " руб\n"
        "Сумма комиссий: " + str(round(total_commission, 2)) + " руб\n"
        "ИТОГО (с комиссией): " + str(round(total_all, 2)) + " руб\n\n"
        "По направлениям:\n" + dir_text + "\n\n"
        "По форме оплаты:\n" + pay_text
    )
    await send(header)

    chunk = "--- Все платежи ---\n"
    for line in detail_lines:
        if len(chunk) + len(line) + 1 > 4000:
            await send(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await send(chunk)


async def confirm_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("ДА, удалить все данные", callback_data="do_clear")],
        [InlineKeyboardButton("Нет, отмена", callback_data="cancel_clear")],
    ]
    await query.message.reply_text(
        "Ты уверен? Все локальные данные бота будут удалены безвозвратно!\n(Данные в Google Таблице останутся)",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def do_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    save_db([])
    await query.message.reply_text("Все локальные данные удалены.\nДанные в Google Таблице сохранены.\nНапиши /start чтобы начать заново.")


async def cancel_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Отмена. Данные не тронуты. Напиши /start.")


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
    elif query.data == "confirm_clear":
        await confirm_clear(update, context)
    elif query.data == "do_clear":
        await do_clear(update, context)
    elif query.data == "cancel_clear":
        await cancel_clear(update, context)


def main():
    require_env()
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
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
