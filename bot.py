import os
import json
import logging
from datetime import datetime, date
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === НАСТРОЙКИ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MY_CHAT_ID = int(os.environ.get("MY_CHAT_ID", "0"))
REMINDER_DAYS = int(os.environ.get("REMINDER_DAYS", "7"))
DATA_FILE = "subscriptions.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# === РАБОТА С ДАННЫМИ ===

def load_subs() -> dict:
    """Загружает подписки из файла."""
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_subs(data: dict):
    """Сохраняет подписки в файл."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def days_until(date_str: str) -> int:
    """Сколько дней до даты оплаты."""
    pay_date = datetime.strptime(date_str, "%d.%m.%Y").date()
    return (pay_date - date.today()).days

# === КОМАНДЫ БОТА ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие и список команд."""
    text = (
        "👋 Привет! Я бот для напоминаний об оплате подписок.\n\n"
        "📋 *Команды:*\n"
        "/add Название ДД.ММ.ГГГГ Цена — добавить подписку\n"
        "/list — показать все подписки\n"
        "/delete Название — удалить подписку\n"
        "/check — проверить ближайшие платежи прямо сейчас\n\n"
        "📌 *Пример:*\n"
        "`/add Netflix 15.02.2026 799`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /add Netflix 15.02.2026 799
    Добавляет или обновляет подписку.
    """
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Укажите: /add Название ДД.ММ.ГГГГ Цена\n"
            "Пример: `/add Netflix 15.02.2026 799`",
            parse_mode="Markdown"
        )
        return

    name = context.args[0]
    date_str = context.args[1]
    price = context.args[2] if len(context.args) >= 3 else ""

    # Проверяем формат даты
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ\n"
            "Пример: `15.02.2026`",
            parse_mode="Markdown"
        )
        return

    subs = load_subs()
    subs[name] = {"date": date_str, "price": price}
    save_subs(subs)

    price_text = f", {price} ₸/₽" if price else ""
    await update.message.reply_text(
        f"✅ Добавлено: *{name}*\n"
        f"📅 Дата оплаты: {date_str}{price_text}",
        parse_mode="Markdown"
    )

async def list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /list — показывает все подписки, отсортированные по дате.
    """
    subs = load_subs()

    if not subs:
        await update.message.reply_text("📭 Подписок пока нет. Добавьте через /add")
        return

    # Сортируем по дате
    sorted_subs = sorted(subs.items(), key=lambda x: datetime.strptime(x[1]["date"], "%d.%m.%Y"))

    lines = ["📋 *Ваши подписки:*\n"]
    for name, info in sorted_subs:
        d = days_until(info["date"])
        price_text = f" — {info['price']} ₸/₽" if info.get("price") else ""

        if d < 0:
            status = f"⛔ просрочено ({abs(d)} дн. назад)"
        elif d == 0:
            status = "🔴 сегодня!"
        elif d <= 3:
            status = f"🟠 через {d} дн."
        elif d <= 7:
            status = f"🟡 через {d} дн."
        else:
            status = f"🟢 через {d} дн."

        lines.append(f"• *{name}*{price_text}\n  {info['date']} — {status}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def delete_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /delete Netflix — удаляет подписку.
    """
    if not context.args:
        await update.message.reply_text("❌ Укажите название: /delete Netflix")
        return

    name = context.args[0]
    subs = load_subs()

    if name not in subs:
        await update.message.reply_text(f"❌ Подписка *{name}* не найдена.", parse_mode="Markdown")
        return

    del subs[name]
    save_subs(subs)
    await update.message.reply_text(f"🗑 Подписка *{name}* удалена.", parse_mode="Markdown")

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /check — немедленная проверка ближайших платежей.
    """
    await send_reminders(context, chat_id=update.message.chat_id)

# === АВТОМАТИЧЕСКОЕ НАПОМИНАНИЕ ===

async def send_reminders(context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
    """Отправляет напоминания о ближайших платежах."""
    target = chat_id or MY_CHAT_ID
    if not target:
        return

    subs = load_subs()
    if not subs:
        if chat_id:  # только если вызвано вручную
            await context.bot.send_message(target, "📭 Подписок нет.")
        return

    urgent = []
    for name, info in subs.items():
        d = days_until(info["date"])
        if d < 0:
            urgent.append((name, info, d, "⛔"))
        elif d == 0:
            urgent.append((name, info, d, "🔴"))
        elif d <= REMINDER_DAYS:
            urgent.append((name, info, d, "🟡" if d > 3 else "🟠"))

    if not urgent:
        if chat_id:  # только если вызвано вручную
            await context.bot.send_message(
                target,
                f"✅ Ближайших платежей (в течение {REMINDER_DAYS} дней) нет."
            )
        return

    lines = ["💳 *Ближайшие платежи:*\n"]
    for name, info, d, icon in sorted(urgent, key=lambda x: x[2]):
        price_text = f" — {info['price']} ₸/₽" if info.get("price") else ""
        if d < 0:
            timing = f"просрочено {abs(d)} дн. назад"
        elif d == 0:
            timing = "сегодня!"
        else:
            timing = f"через {d} дн."
        lines.append(f"{icon} *{name}*{price_text}\n  {info['date']} ({timing})")

    await context.bot.send_message(target, "\n".join(lines), parse_mode="Markdown")

# === ЗАПУСК ===

def main():
    if not BOT_TOKEN:
        raise ValueError("Не задан BOT_TOKEN в переменных окружения!")
    if not MY_CHAT_ID:
        raise ValueError("Не задан MY_CHAT_ID в переменных окружения!")

    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_subscription))
    app.add_handler(CommandHandler("list", list_subscriptions))
    app.add_handler(CommandHandler("delete", delete_subscription))
    app.add_handler(CommandHandler("check", check_now))

    # Ежедневное напоминание в 9:00 (UTC+5 для Алматы = 4:00 UTC)
    app.job_queue.run_daily(
        send_reminders,
        time=datetime.strptime("04:00", "%H:%M").time()  # 09:00 Алматы
    )

    print("✅ Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
