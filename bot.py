import os
import json
import logging
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === НАСТРОЙКИ ===
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
MY_CHAT_ID = int(os.environ.get("MY_CHAT_ID", "0"))
DATA_FILE  = "subscriptions.json"

# Дни, в которые отправляем напоминание
REMINDER_DAYS = {7, 3, 1}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# === РАБОТА С ДАННЫМИ ===

def load_subs() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_subs(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def next_payment_date(day: int) -> date:
    """
    Возвращает ближайшую будущую дату оплаты по дню месяца.
    Например, day=15 → следующее 15-е число (этого или следующего месяца).
    Если сегодня уже 15-е или позже — берём следующий месяц.
    """
    today = date.today()
    # Пробуем этот месяц
    try:
        candidate = today.replace(day=day)
    except ValueError:
        # Такого дня нет в этом месяце (напр. 31 февраля) — берём следующий
        candidate = (today.replace(day=1) + relativedelta(months=1)).replace(day=day)

    if candidate <= today:
        # Дата уже прошла или сегодня — следующий месяц
        candidate = candidate + relativedelta(months=1)
        # На случай коротких месяцев
        try:
            candidate = candidate.replace(day=day)
        except ValueError:
            import calendar
            last_day = calendar.monthrange(candidate.year, candidate.month)[1]
            candidate = candidate.replace(day=last_day)

    return candidate

def days_until_next(day: int) -> int:
    return (next_payment_date(day) - date.today()).days

# === КОМАНДЫ БОТА ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Привет! Я слежу за вашими подписками и напоминаю об оплате.\n\n"
        "📋 *Команды:*\n"
        "/add Название ЧислоМесяца Цена — добавить подписку\n"
        "/list — список всех подписок\n"
        "/delete Название — удалить подписку\n"
        "/check — проверить прямо сейчас\n\n"
        "📌 *Примеры:*\n"
        "`/add Netflix 15 799` — списание каждое 15-е\n"
        "`/add Spotify 1 299` — списание каждое 1-е\n\n"
        "🔔 Напоминания приходят за *7, 3 и 1 день* до оплаты."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /add Netflix 15 799
    Число месяца — от 1 до 28 (28 чтобы работало в феврале).
    """
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Укажите: /add Название ЧислоМесяца Цена\n"
            "Пример: `/add Netflix 15 799`",
            parse_mode="Markdown"
        )
        return

    name     = context.args[0]
    day_str  = context.args[1]
    price    = context.args[2] if len(context.args) >= 3 else ""

    try:
        day = int(day_str)
        if not (1 <= day <= 31):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Число месяца должно быть от 1 до 31.\n"
            "Пример: `/add Netflix 15 799`",
            parse_mode="Markdown"
        )
        return

    if day > 28:
        warning = (
            f"\n⚠️ День {day} есть не во всех месяцах. "
            "В коротких месяцах буду брать последний день."
        )
    else:
        warning = ""

    subs = load_subs()
    subs[name] = {"day": day, "price": price}
    save_subs(subs)

    next_date = next_payment_date(day)
    d = days_until_next(day)
    price_text = f", {price} ₸/₽" if price else ""

    await update.message.reply_text(
        f"✅ Добавлено: *{name}*\n"
        f"📅 Списание: каждое *{day}-е* число{price_text}\n"
        f"⏳ Следующий платёж: {next_date.strftime('%d.%m.%Y')} (через {d} дн.)"
        f"{warning}",
        parse_mode="Markdown"
    )

async def list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = load_subs()

    if not subs:
        await update.message.reply_text("📭 Подписок пока нет. Добавьте через /add")
        return

    # Сортируем по количеству дней до следующего платежа
    sorted_subs = sorted(subs.items(), key=lambda x: days_until_next(x[1]["day"]))

    lines = ["📋 *Ваши подписки:*\n"]
    for name, info in sorted_subs:
        d          = days_until_next(info["day"])
        next_date  = next_payment_date(info["day"])
        price_text = f" — {info['price']} ₸/₽" if info.get("price") else ""

        if d == 0:
            status = "🔴 сегодня!"
        elif d == 1:
            status = "🟠 завтра!"
        elif d <= 3:
            status = f"🟠 через {d} дн."
        elif d <= 7:
            status = f"🟡 через {d} дн."
        else:
            status = f"🟢 через {d} дн."

        lines.append(
            f"• *{name}*{price_text}\n"
            f"  каждое {info['day']}-е | след. {next_date.strftime('%d.%m.%Y')} — {status}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def delete_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите название: `/delete Netflix`", parse_mode="Markdown")
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
    """/check — показывает подписки, по которым сегодня нужно напомнить."""
    found = await send_reminders(context, chat_id=update.message.chat_id, force=True)
    if not found:
        await update.message.reply_text(
            "✅ Сегодня напоминаний нет.\n"
            "Напоминания приходят за 7, 3 и 1 день до оплаты."
        )

# === АВТОМАТИЧЕСКИЕ НАПОМИНАНИЯ ===

async def send_reminders(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int = None,
    force: bool = False
) -> bool:
    """
    Проверяет подписки и отправляет напоминание, если до оплаты
    осталось ровно 7, 3 или 1 день.

    force=True — показать все совпадения (для /check).
    Возвращает True если что-то отправлено.
    """
    target = chat_id or MY_CHAT_ID
    if not target:
        return False

    subs = load_subs()
    if not subs:
        return False

    hits = []
    for name, info in subs.items():
        d = days_until_next(info["day"])
        # Отправляем только в нужные дни (или всё при force)
        if d in REMINDER_DAYS or force:
            hits.append((name, info, d))

    if not hits:
        return False

    # Сортируем: ближайшие первыми
    hits.sort(key=lambda x: x[2])

    lines = ["💳 *Напоминание об оплате:*\n"]
    for name, info, d in hits:
        next_date  = next_payment_date(info["day"])
        price_text = f" — {info['price']} ₸/₽" if info.get("price") else ""

        if d == 0:
            urgency = "🔴 *сегодня!*"
        elif d == 1:
            urgency = "🟠 *завтра!*"
        elif d <= 3:
            urgency = f"🟠 через *{d} дня*"
        else:
            urgency = f"🟡 через *{d} дней*"

        lines.append(
            f"• *{name}*{price_text}\n"
            f"  {next_date.strftime('%d.%m.%Y')} — {urgency}"
        )

    await context.bot.send_message(target, "\n".join(lines), parse_mode="Markdown")
    return True

# === ЗАПУСК ===

def main():
    if not BOT_TOKEN:
        raise ValueError("Не задан BOT_TOKEN!")
    if not MY_CHAT_ID:
        raise ValueError("Не задан MY_CHAT_ID!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("add",    add_subscription))
    app.add_handler(CommandHandler("list",   list_subscriptions))
    app.add_handler(CommandHandler("delete", delete_subscription))
    app.add_handler(CommandHandler("check",  check_now))

    # Запускаем проверку каждый день в 09:00 по Алматы (UTC+5 = 04:00 UTC)
    from datetime import time as dtime
    app.job_queue.run_daily(
        send_reminders,
        time=dtime(hour=4, minute=0)  # 04:00 UTC = 09:00 Алматы
    )

    print("✅ Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
