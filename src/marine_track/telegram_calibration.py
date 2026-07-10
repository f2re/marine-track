from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from marine_track.calibration import (
    ANSWER_NONE,
    ANSWER_SKIP,
    ANSWER_UNCERTAIN,
    CalibrationTargets,
    calibration_needed,
    create_next_calibration_task,
    load_calibration_profile,
    rebuild_calibration_profile,
    submit_calibration_answer,
)
from marine_track.telegram_calibration_areas import (
    ACTION_AREA_HOME,
    CALIBRATION_AREA_ACTIONS,
    calibration_area_callback,
)
from marine_track.telegram_calibration_phase2 import (
    ACTION_OPEN as PHASE2_ACTION_OPEN,
)
from marine_track.telegram_calibration_phase2 import (
    phase2_callback,
)
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_ui import ACTION_MENU, MENU_CALLBACK_PREFIX

LOGGER = logging.getLogger(__name__)
CALIBRATION_CALLBACK_PREFIX = "mtcal"
ACTION_OPEN = "open"
ACTION_NEXT = "next"
ACTION_STATUS = "status"
ACTION_REBUILD = "rebuild"
ACTION_ANSWER = "answer"


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def is_calibration_admin(update: Update, config: TelegramBotConfig) -> bool:
    user_id = effective_user_id(update)
    return bool(config.admin_ids) and user_id in config.admin_ids


def calibration_targets(config: TelegramBotConfig) -> CalibrationTargets:
    return CalibrationTargets(
        min_labels=config.calibration_min_labels,
        min_positive=config.calibration_min_positive,
        min_negative=config.calibration_min_negative,
    )


def calibration_warning_text(profile: dict[str, Any]) -> str:
    labels = profile.get("labels") or {}
    targets = profile.get("targets") or {}
    return (
        "⚠️ <b>Требуется калибровка детектора</b>\n"
        "Сейчас кандидаты ранжируются исходной эвристикой. До накопления разметки "
        "score не является вероятностью обнаружения судна.\n\n"
        f"Размечено: <code>{int(labels.get('usable', 0))}/{int(targets.get('min_labels', 0))}</code>\n"
        f"Судно: <code>{int(labels.get('positive', 0))}/{int(targets.get('min_positive', 0))}</code> · "
        f"ложный кандидат: <code>{int(labels.get('negative', 0))}/{int(targets.get('min_negative', 0))}</code>\n\n"
        "Выберите акваторию: бот найдёт сцену, выполнит детекцию и подготовит candidate-задачи "
        "и независимые tiles."
    )


def calibration_menu_text(profile: dict[str, Any]) -> str:
    labels = profile.get("labels") or {}
    targets = profile.get("targets") or {}
    model = profile.get("ranking_model") or {}
    metrics = profile.get("metrics") or {}
    state_labels = {
        "not_started": "не начата",
        "collecting": "сбор разметки",
        "ready": "профиль активен",
    }
    status = state_labels.get(str(profile.get("status")), str(profile.get("status")))
    coefficient_lines = ""
    coefficients = model.get("coefficients")
    if isinstance(coefficients, dict):
        coefficient_lines = (
            "\n<b>Эмпирическая формула</b>\n"
            f"peak: <code>{float(coefficients.get('peak_score', 0.0)):.3f}</code> · "
            f"contrast: <code>{float(coefficients.get('contrast_term', 0.0)):.3f}</code> · "
            f"shape: <code>{float(coefficients.get('shape_term', 0.0)):.3f}</code>\n"
            f"intercept: <code>{float(model.get('intercept', 0.0)):.3f}</code> · "
            f"порог: <code>{float(model.get('decision_threshold', 0.5)):.3f}</code>"
        )
    metric_line = ""
    if metrics.get("scope") == "in_sample_training_only":
        metric_line = (
            "\n<b>Только обучающая выборка</b>\n"
            f"F1: <code>{float(metrics.get('f1', 0.0)):.3f}</code> · "
            f"balanced accuracy: <code>{float(metrics.get('balanced_accuracy', 0.0)):.3f}</code>"
        )
    return (
        "🧪 <b>Калибровка Marine Track</b>\n"
        f"Состояние: <code>{html.escape(status)}</code>\n"
        f"Размечено: <code>{int(labels.get('usable', 0))}/{int(targets.get('min_labels', 0))}</code>\n"
        f"Положительные: <code>{int(labels.get('positive', 0))}/{int(targets.get('min_positive', 0))}</code>\n"
        f"Отрицательные: <code>{int(labels.get('negative', 0))}/{int(targets.get('min_negative', 0))}</code>\n"
        f"Коррекции локализации: <code>{int(labels.get('localization_corrections', 0))}</code>\n"
        f"Неуверенные: <code>{int(labels.get('uncertain', 0))}</code> · "
        f"пропущенные: <code>{int(labels.get('skipped', 0))}</code>"
        f"{coefficient_lines}{metric_line}\n\n"
        "Сначала подготовьте сцены из выбранной акватории. Candidate-разметка калибрует ranking score. "
        "Phase 2 независимо оценивает false alarms и пропущенные цели; CFAR и формула скорости "
        "автоматически не меняются."
    )


def calibration_menu_markup(profile: dict[str, Any]) -> InlineKeyboardMarkup:
    action_label = (
        "▶️ Начать candidate-разметку"
        if profile.get("status") == "not_started"
        else "▶️ Продолжить candidate"
    )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗺 Выбрать акваторию и найти сцены",
                    callback_data=f"{CALIBRATION_CALLBACK_PREFIX}:{ACTION_AREA_HOME}",
                )
            ],
            [
                InlineKeyboardButton(
                    action_label,
                    callback_data=f"{CALIBRATION_CALLBACK_PREFIX}:{ACTION_NEXT}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🌊 Независимые tiles · phase 2",
                    callback_data=f"{CALIBRATION_CALLBACK_PREFIX}:{PHASE2_ACTION_OPEN}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Статус",
                    callback_data=f"{CALIBRATION_CALLBACK_PREFIX}:{ACTION_STATUS}",
                ),
                InlineKeyboardButton(
                    "♻️ Пересчитать",
                    callback_data=f"{CALIBRATION_CALLBACK_PREFIX}:{ACTION_REBUILD}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏠 Меню", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}"
                )
            ],
        ]
    )


def calibration_task_markup(task_id: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(str(cell), callback_data=_answer_callback(task_id, str(cell)))
            for cell in range(start, start + 3)
        ]
        for start in (1, 4, 7)
    ]
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "🚫 Судна нет", callback_data=_answer_callback(task_id, ANSWER_NONE)
                ),
                InlineKeyboardButton(
                    "❔ Не уверен", callback_data=_answer_callback(task_id, ANSWER_UNCERTAIN)
                ),
            ],
            [
                InlineKeyboardButton(
                    "⏭ Пропустить", callback_data=_answer_callback(task_id, ANSWER_SKIP)
                ),
                InlineKeyboardButton(
                    "📊 Статус",
                    callback_data=f"{CALIBRATION_CALLBACK_PREFIX}:{ACTION_STATUS}",
                ),
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


def _answer_callback(task_id: str, answer: str) -> str:
    return f"{CALIBRATION_CALLBACK_PREFIX}:{ACTION_ANSWER}:{task_id}:{answer}"


async def calibration_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    del context
    if not await require_calibration_admin(update, config):
        return
    await show_calibration_menu(update, config)


async def show_calibration_menu(update: Update, config: TelegramBotConfig) -> None:
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not target:
        return
    profile = load_calibration_profile(config.output_dir, calibration_targets(config))
    await target.reply_text(
        calibration_menu_text(profile),
        parse_mode=ParseMode.HTML,
        reply_markup=calibration_menu_markup(profile),
    )


async def require_calibration_admin(update: Update, config: TelegramBotConfig) -> bool:
    if is_calibration_admin(update, config):
        return True
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(
            "Доступ к калибровке разрешён только Telegram-администраторам. "
            f"Ваш user id: {effective_user_id(update)}."
        )
    return False


async def calibration_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split(":")
    if len(parts) < 2 or parts[0] != CALIBRATION_CALLBACK_PREFIX:
        return
    action = parts[1]
    if action.startswith("p2"):
        await phase2_callback(update, context, config)
        return
    if action in CALIBRATION_AREA_ACTIONS:
        await calibration_area_callback(update, context, config)
        return

    del context
    await query.answer()
    if not await require_calibration_admin(update, config):
        return
    if action in {ACTION_OPEN, ACTION_STATUS}:
        await show_calibration_menu(update, config)
        return
    if action == ACTION_NEXT:
        await send_next_calibration_task(update, config)
        return
    if action == ACTION_REBUILD:
        profile = await asyncio.to_thread(
            rebuild_calibration_profile,
            config.output_dir,
            calibration_targets(config),
        )
        await query.message.reply_text(
            "♻️ Профиль пересчитан.\n\n" + calibration_menu_text(profile),
            parse_mode=ParseMode.HTML,
            reply_markup=calibration_menu_markup(profile),
        )
        return
    if action == ACTION_ANSWER and len(parts) == 4:
        task_id, answer = parts[2], parts[3]
        try:
            result = await asyncio.to_thread(
                submit_calibration_answer,
                config.output_dir,
                task_id,
                effective_user_id(update),
                answer,
                calibration_targets(config),
            )
        except (FileNotFoundError, ValueError) as exc:
            await query.message.reply_text(f"Не удалось сохранить ответ: {exc}")
            return
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as exc:  # pragma: no cover
            LOGGER.debug("Unable to clear calibration keyboard for task %s: %s", task_id, exc)
        await query.message.reply_text(answer_feedback(result), parse_mode=ParseMode.HTML)
        await send_next_calibration_task(update, config)


async def send_next_calibration_task(update: Update, config: TelegramBotConfig) -> None:
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not target:
        return
    task = await asyncio.to_thread(
        create_next_calibration_task,
        config.output_dir,
        effective_user_id(update),
        config.calibration_crop_size_px,
    )
    if task is None:
        profile = load_calibration_profile(config.output_dir, calibration_targets(config))
        await target.reply_text(
            "Нет новых candidates: в output_dir ещё нет необработанных candidate-заданий. "
            "Нажмите <b>Выбрать акваторию и найти сцены</b>; даже при нуле candidates бот создаст "
            "независимые phase 2 tiles.\n\n"
            + calibration_menu_text(profile),
            parse_mode=ParseMode.HTML,
            reply_markup=calibration_menu_markup(profile),
        )
        return

    source = task.get("source") or {}
    image_path = Path(str(task["image_path"]))
    caption = (
        "🧪 <b>Калибровка кандидата</b>\n"
        "Выберите клетку, в которой находится <b>центр корпуса судна</b>. "
        "Не ориентируйтесь только на длинный след.\n\n"
        f"sensor: <code>{html.escape(str(source.get('sensor') or 'unknown'))}</code> · "
        f"provider: <code>{html.escape(str(source.get('provider') or 'unknown'))}</code>\n"
        f"time: <code>{html.escape(str(source.get('acquisition_time') or 'unknown'))}</code>\n\n"
        "Если виден только шум, берег, платформа или волновой фронт — нажмите <b>Судна нет</b>."
    )
    with image_path.open("rb") as file_obj:
        await target.reply_photo(
            photo=file_obj,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=calibration_task_markup(str(task["task_id"])),
        )


def answer_feedback(result: dict[str, Any]) -> str:
    record = result.get("record") or {}
    profile = result.get("profile") or {}
    labels = profile.get("labels") or {}
    targets = profile.get("targets") or {}
    label = record.get("label")
    messages = {
        "positive": "✅ Подтверждено: судно находится в ожидаемой клетке.",
        "negative": "🚫 Сохранено как ложный кандидат.",
        "negative_localization": "↔️ Сохранена ошибка локализации: судно найдено в другой клетке.",
        "uncertain": "❔ Ответ сохранён без включения в обучение.",
        "skipped": "⏭ Кандидат пропущен.",
    }
    active_note = (
        "Профиль активирован и будет применяться к новым ranking score."
        if profile.get("active")
        else "Пока используется исходная эвристика."
    )
    return (
        f"{messages.get(label, 'Ответ сохранён.')}\n"
        f"Размечено: <code>{int(labels.get('usable', 0))}/{int(targets.get('min_labels', 0))}</code> · "
        f"+ <code>{int(labels.get('positive', 0))}</code> · − <code>{int(labels.get('negative', 0))}</code>\n"
        f"{active_note}"
    )


def startup_calibration_required(config: TelegramBotConfig) -> bool:
    return calibration_needed(config.output_dir, calibration_targets(config))
