"""
Telegram-бот расписания занятий
1 курс, 1 поток, Юридический факультет КФУ
"""

import os
import logging
from datetime import date, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from data import SCHEDULE, GROUPS, DAY_ORDER, DAY_FULL, SEMESTER_START, ELECTIVES, LANGUAGES

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["TOKEN"]


# ---------- Утилиты ----------

def get_week(target: date | None = None) -> int | None:
    if target is None:
        target = date.today()
    delta = (target - SEMESTER_START).days
    week = delta // 7 + 1
    if 1 <= week <= 17:
        return week
    return None


def week_info_str(week: int | None) -> str:
    if week is None:
        return ""
    parity = "нечётная" if week % 2 == 1 else "чётная"
    return f"{week}-я неделя ({parity})"


def day_abbr(d: date) -> str:
    return ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]


def build_day_text(group: str, day: str, week: int | None = None,
                   elective: str | None = None, lang: str | None = None) -> str:
    """Формирует текст расписания на день с учётом настроек пользователя."""
    entries = list(SCHEDULE.get(group, {}).get(day, []))
    if week is not None:
        entries = [e for e in entries if week in e["weeks"]]

    # Подставляем дисциплину по выбору и иностранный язык
    result: list[dict] = []
    for e in entries:
        if "Дисциплина по выбору" in e.get("subject", "") and elective:
            el = ELECTIVES.get(elective)
            if el:
                for el_e in el["entries"]:
                    if week is None or week in el_e["weeks"]:
                        result.append(el_e)
                continue
        if ("Иностранный язык" in e.get("subject", "")
                and "ЦОР" not in e.get("subject", "") and lang):
            lg = LANGUAGES.get(lang)
            if lg:
                result.append({**e, "subject": "Иностранный язык в сфере юриспруденции",
                               "teacher": lg["teacher"], "room": lg["room"]})
                continue
        result.append(e)

    if not result:
        return "Нет занятий"

    lines: list[str] = []
    for e in result:
        line = f"  {e['time']}  |  {e['subject']}"
        parts: list[str] = []
        if e.get("teacher"):
            parts.append(e["teacher"])
        if e.get("room"):
            parts.append(f"ауд. {e['room']}")
        if parts:
            line += f"\n    {', '.join(parts)}"
        lines.append(line)
    return "\n\n".join(lines)


# ---------- Клавиатуры ----------

def group_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(g, callback_data=f"grp:{g}")] for g in GROUPS]
    return InlineKeyboardMarkup(rows)


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("На сегодня", callback_data="today")],
        [InlineKeyboardButton("На завтра", callback_data="tomorrow")],
        [InlineKeyboardButton("Выбрать день", callback_data="pickday")],
        [InlineKeyboardButton("Полное расписание", callback_data="full")],
        [InlineKeyboardButton("Настройки", callback_data="settings"),
         InlineKeyboardButton("Сменить группу", callback_data="chgrp")],
    ])


def days_keyboard() -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for d in DAY_ORDER:
        row.append(InlineKeyboardButton(DAY_FULL[d], callback_data=f"day:{d}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("<< Назад", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("<< Меню", callback_data="menu")],
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Дисциплина по выбору", callback_data="set_el")],
        [InlineKeyboardButton("Иностранный язык", callback_data="set_lg")],
        [InlineKeyboardButton("<< Меню", callback_data="menu")],
    ])


# ---------- Хэндлеры ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот расписания ЮФ КФУ.\nВыбери свою группу:",
        reply_markup=group_keyboard(),
    )


def _get_prefs(context):
    return context.user_data.get("elective"), context.user_data.get("lang")


def _menu_header(group, wi):
    header = f"Группа: {group}"
    if wi:
        header += f"\nСейчас: {wi}"
    return header


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data
    elective, lang = _get_prefs(context)

    # --- Выбор группы ---
    if data.startswith("grp:"):
        group = data.split(":", 1)[1]
        context.user_data["group"] = group
        await q.edit_message_text(
            f"{_menu_header(group, week_info_str(get_week()))}\n\nВыбери действие:",
            reply_markup=menu_keyboard(),
        )
        return

    # --- Меню ---
    if data == "menu":
        group = context.user_data.get("group")
        if not group:
            await q.edit_message_text("Выбери группу:", reply_markup=group_keyboard())
            return
        await q.edit_message_text(
            f"{_menu_header(group, week_info_str(get_week()))}\n\nВыбери действие:",
            reply_markup=menu_keyboard(),
        )
        return

    # --- Сменить группу ---
    if data == "chgrp":
        await q.edit_message_text("Выбери группу:", reply_markup=group_keyboard())
        return

    # --- Настройки ---
    if data == "settings":
        el_name = ELECTIVES[elective]["name"] if elective and elective in ELECTIVES else "не выбрана"
        lg_name = LANGUAGES[lang]["name"] if lang and lang in LANGUAGES else "не выбран"
        text = (f"Настройки:\n\n"
                f"Дисциплина по выбору: {el_name}\n"
                f"Иностранный язык: {lg_name}")
        await q.edit_message_text(text, reply_markup=settings_keyboard())
        return

    if data == "set_el":
        rows = []
        for key, val in ELECTIVES.items():
            check = " [v]" if elective == key else ""
            rows.append([InlineKeyboardButton(val["name"] + check, callback_data=f"sel:{key}")])
        rows.append([InlineKeyboardButton("<< Назад", callback_data="settings")])
        await q.edit_message_text("Выбери дисциплину по выбору:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("sel:"):
        context.user_data["elective"] = data.split(":", 1)[1]
        el_name = ELECTIVES[context.user_data["elective"]]["name"]
        await q.edit_message_text(f"Выбрано: {el_name}", reply_markup=settings_keyboard())
        return

    if data == "set_lg":
        rows = []
        for key, val in LANGUAGES.items():
            check = " [v]" if lang == key else ""
            rows.append([InlineKeyboardButton(val["name"] + check, callback_data=f"slg:{key}")])
        rows.append([InlineKeyboardButton("<< Назад", callback_data="settings")])
        await q.edit_message_text("Выбери преподавателя ин. языка:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("slg:"):
        context.user_data["lang"] = data.split(":", 1)[1]
        lg_name = LANGUAGES[context.user_data["lang"]]["name"]
        await q.edit_message_text(f"Выбрано: {lg_name}", reply_markup=settings_keyboard())
        return

    group = context.user_data.get("group")
    if not group:
        await q.edit_message_text("Сначала выбери группу:", reply_markup=group_keyboard())
        return

    # Обновляем после возможных изменений в настройках
    elective, lang = _get_prefs(context)

    # --- На сегодня ---
    if data == "today":
        today = date.today()
        d = day_abbr(today)
        week = get_week(today)
        wi = week_info_str(week)
        if d == "Вс":
            text = f"Группа {group} | {DAY_FULL['Вс']}"
            if wi:
                text += f"\n{wi}"
            text += "\n\nСегодня воскресенье — занятий нет."
        else:
            header = f"Группа {group} | {DAY_FULL[d]}"
            if wi:
                header += f"\n{wi}"
            body = build_day_text(group, d, week, elective, lang)
            text = f"{header}\n\n{body}"
        await safe_edit(q, text, back_keyboard())
        return

    # --- На завтра ---
    if data == "tomorrow":
        tmr = date.today() + timedelta(days=1)
        d = day_abbr(tmr)
        week = get_week(tmr)
        wi = week_info_str(week)
        if d == "Вс":
            text = f"Группа {group} | {DAY_FULL['Вс']}"
            if wi:
                text += f"\n{wi}"
            text += "\n\nВоскресенье — занятий нет."
        else:
            header = f"Группа {group} | {DAY_FULL[d]}"
            if wi:
                header += f"\n{wi}"
            body = build_day_text(group, d, week, elective, lang)
            text = f"{header}\n\n{body}"
        await safe_edit(q, text, back_keyboard())
        return

    # --- Выбрать день ---
    if data == "pickday":
        await q.edit_message_text("Выбери день:", reply_markup=days_keyboard())
        return

    if data.startswith("day:"):
        d = data.split(":", 1)[1]
        week = get_week()
        wi = week_info_str(week)
        header = f"Группа {group} | {DAY_FULL.get(d, d)}"
        if wi:
            header += f"\n{wi}"
        body = build_day_text(group, d, week, elective, lang)
        text = f"{header}\n\n{body}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("<< Дни", callback_data="pickday"),
             InlineKeyboardButton("<< Меню", callback_data="menu")],
        ])
        await safe_edit(q, text, kb)
        return

    # --- Полное расписание ---
    if data == "full":
        await q.edit_message_text(f"Полное расписание — {group}:", reply_markup=back_keyboard())
        for d in DAY_ORDER:
            entries = SCHEDULE.get(group, {}).get(d, [])
            if not entries:
                continue
            header = f"--- {DAY_FULL[d]} ---"
            body = build_day_text(group, d, week=None, elective=elective, lang=lang)
            msg = f"{header}\n\n{body}"
            await q.message.reply_text(msg)
        await q.message.reply_text("Вот и всё расписание!", reply_markup=back_keyboard())
        return


async def safe_edit(query, text: str, reply_markup=None):
    if len(text) <= 4096:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text[:4090] + "...", reply_markup=reply_markup)


# ---------- Запуск ----------

def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
