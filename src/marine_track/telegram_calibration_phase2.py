from __future__ import annotations

import asyncio
import html
import os
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from marine_track.calibration_phase2 import (
    HEADING_SECTORS,
    OBJECT_MULTIPLE,
    OBJECT_NONE,
    OBJECT_SKIP,
    OBJECT_UNCERTAIN,
    WAKE_BOTH,
    WAKE_KELVIN,
    WAKE_NONE,
    WAKE_TURBULENT,
    WAKE_UNCERTAIN,
    Phase2Targets,
    read_phase2_labels,
    submit_object_answer,
    submit_wake_answer,
)
from marine_track.calibration_phase2_evaluation import (
    build_proposed_profile,
    evaluate_phase2,
    load_active_phase2_profile,
    promote_proposed_profile,
    rollback_profile,
)
from marine_track.calibration_phase2_tiles import (
    create_next_independent_task,
    generate_independent_tasks,
)
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_ui import ACTION_MENU, MENU_CALLBACK_PREFIX

PHASE2_CALLBACK_PREFIX = "mtcal"
ACTION_OPEN = "p2open"
ACTION_NEXT = "p2next"
ACTION_GENERATE = "p2generate"
ACTION_STATUS = "p2status"
ACTION_EVALUATE = "p2evaluate"
ACTION_PROPOSE = "p2propose"
ACTION_PROMOTE = "p2promote"
ACTION_ROLLBACK = "p2rollback"
ACTION_OBJECT = "p2object"
ACTION_WAKE = "p2wake"
ACTION_HEADING = "p2heading"


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


async def require_calibration_admin(update: Update, config: TelegramBotConfig) -> bool:
    user_id = effective_user_id(update)
    if config.admin_ids and user_id in config.admin_ids:
        return True
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(
            "Доступ к калибровке разрешён только Telegram-администраторам. "
            f"Ваш user id: {user_id}."
        )
    return False


def phase2_targets(config: TelegramBotConfig) -> Phase2Targets:
    return Phase2Targets(
        tile_size_px=config.calibration_crop_size_px,
        max_tiles_per_scene=_env_int(
            "MARINE_TRACK_CALIBRATION_PHASE2_MAX_TILES_PER_SCENE", 24, 1, 500
        ),
        min_valid_fraction=_env_float(
            "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALID_FRACTION", 0.85, 0.1, 1.0
        ),
        min_test_groups=_env_int(
            "MARINE_TRACK_CALIBRATION_PHASE2_MIN_TEST_GROUPS", 3, 1, 1000
        ),
        min_validation_groups=_env_int(
            "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALIDATION_GROUPS", 3, 1, 1000
        ),
        min_improvement=_env_float(
            "MARINE_TRACK_CALIBRATION_PHASE2_MIN_IMPROVEMENT", 0.01, 0.0, 1.0
        ),
        bootstrap_samples=_env_int(
            "MARINE_TRACK_CALIBRATION_PHASE2_BOOTSTRAP_SAMPLES", 300, 10, 5000
        ),
    )


def context_geojson() -> Path | None:
    raw = os.getenv("MARINE_TRACK_CALIBRATION_CONTEXT_GEOJSON", "").strip()
    return Path(raw) if raw else None


def phase2_menu_text(config: TelegramBotConfig) -> str:
    labels = read_phase2_labels(config.output_dir)
    active = load_active_phase2_profile(config.output_dir)
    split_counts: dict[str, int] = {}
    stratum_counts: dict[str, int] = {}
    missed = 0
    wake = 0
    for record in labels:
        split = str(record.get("split") or "unknown")
        stratum = str(record.get("stratum") or "unknown")
        split_counts[split] = split_counts.get(split, 0) + 1
        stratum_counts[stratum] = stratum_counts.get(stratum, 0) + 1
        missed += int(bool(record.get("missed_target")))
        wake += int(isinstance(record.get("wake"), dict))
    active_line = (
        f"<code>{html.escape(str(active.get('profile_id')))}</code>"
        if active
        else "<code>нет</code>"
    )
    return (
        "🌊 <b>Калибровка phase 2</b>\n"
        "Независимые от detector tiles позволяют учитывать пропущенные цели и false alarms.\n\n"
        f"Разметок: <code>{len(labels)}</code> · missed targets: <code>{missed}</code>\n"
        f"Wake-разметок: <code>{wake}</code>\n"
        f"Split: <code>{html.escape(_compact_counts(split_counts))}</code>\n"
        f"Страты: <code>{html.escape(_compact_counts(stratum_counts))}</code>\n"
        f"Активный профиль: {active_line}\n\n"
        "AIS показывается только как reference. Post-filter применяется лишь после held-out gate; "
        "CFAR и Kelvin speed автоматически не изменяются."
    )


def phase2_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "▶️ Размечать независимые tiles",
                    callback_data=f"{PHASE2_CALLBACK_PREFIX}:{ACTION_NEXT}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🧱 Сформировать tiles",
                    callback_data=f"{PHASE2_CALLBACK_PREFIX}:{ACTION_GENERATE}",
                ),
                InlineKeyboardButton(
                    "📊 Оценить",
                    callback_data=f"{PHASE2_CALLBACK_PREFIX}:{ACTION_EVALUATE}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🧮 Предложить профиль",
                    callback_data=f"{PHASE2_CALLBACK_PREFIX}:{ACTION_PROPOSE}",
                ),
                InlineKeyboardButton(
                    "✅ Активировать",
                    callback_data=f"{PHASE2_CALLBACK_PREFIX}:{ACTION_PROMOTE}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "↩️ Rollback",
                    callback_data=f"{PHASE2_CALLBACK_PREFIX}:{ACTION_ROLLBACK}",
                ),
                InlineKeyboardButton(
                    "🏠 Меню",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}",
                ),
            ],
        ]
    )


def object_markup(task_id: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                str(cell), callback_data=_callback(ACTION_OBJECT, task_id, str(cell))
            )
            for cell in range(start, start + 3)
        ]
        for start in (1, 4, 7)
    ]
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "🚫 Судна нет",
                    callback_data=_callback(ACTION_OBJECT, task_id, OBJECT_NONE),
                ),
                InlineKeyboardButton(
                    "👥 Несколько",
                    callback_data=_callback(ACTION_OBJECT, task_id, OBJECT_MULTIPLE),
                ),
            ],
            [
                InlineKeyboardButton(
                    "❔ Не уверен",
                    callback_data=_callback(ACTION_OBJECT, task_id, OBJECT_UNCERTAIN),
                ),
                InlineKeyboardButton(
                    "⏭ Пропустить",
                    callback_data=_callback(ACTION_OBJECT, task_id, OBJECT_SKIP),
                ),
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


def wake_markup(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Нет следа", callback_data=_callback(ACTION_WAKE, task_id, WAKE_NONE)
                ),
                InlineKeyboardButton(
                    "Турбулентный",
                    callback_data=_callback(ACTION_WAKE, task_id, WAKE_TURBULENT),
                ),
            ],
            [
                InlineKeyboardButton(
                    "Kelvin arms",
                    callback_data=_callback(ACTION_WAKE, task_id, WAKE_KELVIN),
                ),
                InlineKeyboardButton(
                    "Оба", callback_data=_callback(ACTION_WAKE, task_id, WAKE_BOTH)
                ),
            ],
            [
                InlineKeyboardButton(
                    "Не уверен",
                    callback_data=_callback(ACTION_WAKE, task_id, WAKE_UNCERTAIN),
                )
            ],
        ]
    )


def heading_markup(task_id: str, wake_type: str) -> InlineKeyboardMarkup:
    labels = {
        "n": "N",
        "ne": "NE",
        "e": "E",
        "se": "SE",
        "s": "S",
        "sw": "SW",
        "w": "W",
        "nw": "NW",
        "unknown": "Неизвестно",
    }
    order = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
    rows = [
        [
            InlineKeyboardButton(
                labels[value],
                callback_data=_callback(ACTION_HEADING, task_id, wake_type, value),
            )
            for value in order[start : start + 4]
        ]
        for start in (0, 4)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                labels["unknown"],
                callback_data=_callback(ACTION_HEADING, task_id, wake_type, "unknown"),
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


async def show_phase2_menu(update: Update, config: TelegramBotConfig) -> None:
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(
            phase2_menu_text(config),
            parse_mode=ParseMode.HTML,
            reply_markup=phase2_menu_markup(),
        )


async def phase2_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    del context
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not await require_calibration_admin(update, config):
        return
    parts = query.data.split(":")
    if len(parts) < 2 or parts[0] != PHASE2_CALLBACK_PREFIX:
        return
    action = parts[1]
    if action in {ACTION_OPEN, ACTION_STATUS}:
        await show_phase2_menu(update, config)
        return
    if action == ACTION_GENERATE:
        status = await query.message.reply_text("⏳ Формирую независимые tiles…")
        manifest = await asyncio.to_thread(
            generate_independent_tasks,
            config.output_dir,
            phase2_targets(config),
            context_geojson(),
        )
        await status.edit_text(
            "✅ Tiles сформированы\n"
            f"Всего: {len(manifest.get('tasks', []))}\n"
            f"Страты: {_compact_counts(manifest.get('counts', {}))}\n"
            f"Split: {_compact_counts(manifest.get('splits', {}))}",
            reply_markup=phase2_menu_markup(),
        )
        return
    if action == ACTION_NEXT:
        await send_next_phase2_task(update, config)
        return
    if action == ACTION_EVALUATE:
        report = await asyncio.to_thread(
            evaluate_phase2,
            config.output_dir,
            phase2_targets(config).bootstrap_samples,
        )
        await query.message.reply_text(
            evaluation_text(report),
            parse_mode=ParseMode.HTML,
            reply_markup=phase2_menu_markup(),
        )
        return
    if action == ACTION_PROPOSE:
        profile = await asyncio.to_thread(
            build_proposed_profile, config.output_dir, phase2_targets(config)
        )
        await query.message.reply_text(
            profile_text(profile),
            parse_mode=ParseMode.HTML,
            reply_markup=phase2_menu_markup(),
        )
        return
    if action == ACTION_PROMOTE:
        try:
            profile = await asyncio.to_thread(
                promote_proposed_profile,
                config.output_dir,
                phase2_targets(config),
            )
        except ValueError as exc:
            await query.message.reply_text(
                f"⛔ Профиль не активирован\n<code>{html.escape(str(exc))}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=phase2_menu_markup(),
            )
            return
        await query.message.reply_text(
            "✅ Профиль активирован\n" + profile_text(profile),
            parse_mode=ParseMode.HTML,
            reply_markup=phase2_menu_markup(),
        )
        return
    if action == ACTION_ROLLBACK:
        try:
            profile = await asyncio.to_thread(rollback_profile, config.output_dir)
        except FileNotFoundError as exc:
            await query.message.reply_text(str(exc), reply_markup=phase2_menu_markup())
            return
        await query.message.reply_text(
            f"↩️ Восстановлен профиль <code>{html.escape(str(profile.get('profile_id')))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=phase2_menu_markup(),
        )
        return
    if action == ACTION_OBJECT and len(parts) == 4:
        task_id, answer = parts[2], parts[3]
        try:
            result = await asyncio.to_thread(
                submit_object_answer,
                config.output_dir,
                task_id,
                effective_user_id(update),
                answer,
            )
        except (FileNotFoundError, ValueError) as exc:
            await query.message.reply_text(f"Ответ не сохранён: {exc}")
            return
        await _clear_keyboard(query)
        record = result["record"]
        await query.message.reply_text(object_feedback(record), parse_mode=ParseMode.HTML)
        if record.get("object_label") in {"ship", "multiple_ships"}:
            await query.message.reply_text(
                "Какой след виден у подтверждённой цели?",
                reply_markup=wake_markup(task_id),
            )
        else:
            await send_next_phase2_task(update, config)
        return
    if action == ACTION_WAKE and len(parts) == 4:
        task_id, wake_type = parts[2], parts[3]
        await _clear_keyboard(query)
        if wake_type in {WAKE_NONE, WAKE_UNCERTAIN}:
            await asyncio.to_thread(
                submit_wake_answer,
                config.output_dir,
                task_id,
                effective_user_id(update),
                wake_type,
                "unknown",
                True,
            )
            await query.message.reply_text("Wake-разметка сохранена.")
            await send_next_phase2_task(update, config)
        else:
            await query.message.reply_text(
                "Укажите направление оси/следа. Неоднозначность 180° сохраняется явно.",
                reply_markup=heading_markup(task_id, wake_type),
            )
        return
    if action == ACTION_HEADING and len(parts) == 5:
        task_id, wake_type, heading = parts[2], parts[3], parts[4]
        if heading not in HEADING_SECTORS:
            await query.message.reply_text("Неизвестный сектор.")
            return
        await asyncio.to_thread(
            submit_wake_answer,
            config.output_dir,
            task_id,
            effective_user_id(update),
            wake_type,
            heading,
            True,
        )
        await _clear_keyboard(query)
        await query.message.reply_text("Wake и сектор сохранены с ambiguity=180°.")
        await send_next_phase2_task(update, config)


async def send_next_phase2_task(update: Update, config: TelegramBotConfig) -> None:
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not target:
        return
    task = await asyncio.to_thread(
        create_next_independent_task,
        config.output_dir,
        effective_user_id(update),
        phase2_targets(config),
        context_geojson(),
    )
    if task is None:
        await target.reply_text(
            "Новых независимых tiles нет. Выполните детекцию новых сцен или сформируйте tiles заново.",
            reply_markup=phase2_menu_markup(),
        )
        return
    reference = task.get("reference") or {}
    prediction = task.get("prediction") or {}
    caption = (
        "🌊 <b>Независимый tile</b>\n"
        "Выберите клетку с центром корпуса. Tile сформирован независимо от текущих срабатываний detector.\n\n"
        f"Страта: <code>{html.escape(str(task.get('stratum')))}</code> · "
        f"split: <code>{html.escape(str(task.get('split')))}</code>\n"
        f"sensor: <code>{html.escape(str(task.get('source', {}).get('sensor') or 'unknown'))}</code>\n"
        f"Detector candidates в tile: <code>{int(prediction.get('candidate_count', 0))}</code>\n"
        f"AIS reference: <code>{html.escape(str(reference.get('ais_status') or 'unavailable'))}</code>"
    )
    image_path = Path(str(task["image_path"]))
    with image_path.open("rb") as file_obj:
        await target.reply_photo(
            photo=file_obj,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=object_markup(str(task["task_id"])),
        )


def evaluation_text(report: dict[str, Any]) -> str:
    lines = ["📊 <b>Held-out evaluation</b>"]
    for split in ("train", "calibration", "test"):
        metrics = report.get("splits", {}).get(split, {})
        lines.append(
            f"{split}: n=<code>{int(metrics.get('count', 0))}</code>, "
            f"F1=<code>{float(metrics.get('f1', 0.0)):.3f}</code>, "
            f"POD=<code>{float(metrics.get('pod', 0.0)):.3f}</code>, "
            f"FAR=<code>{float(metrics.get('far', 0.0)):.3f}</code>, "
            f"CSI=<code>{float(metrics.get('csi', 0.0)):.3f}</code>"
        )
    lines.append("\nScore не является probability; split выполняется по scene/pass group.")
    return "\n".join(lines)


def profile_text(profile: dict[str, Any]) -> str:
    gate = profile.get("promotion_gate") or {}
    threshold = profile.get("post_filter", {}).get("ranking_score_threshold")
    threshold_text = "n/a" if threshold is None else f"{float(threshold):.3f}"
    reasons = "; ".join(str(item) for item in gate.get("reasons", [])) or "нет"
    return (
        f"Профиль: <code>{html.escape(str(profile.get('profile_id')))}</code>\n"
        f"Статус: <code>{html.escape(str(profile.get('status')))}</code>\n"
        f"Post-filter threshold: <code>{threshold_text}</code>\n"
        f"Gate: <code>{'passed' if gate.get('passed') else 'failed'}</code>\n"
        f"Причины: <code>{html.escape(reasons)}</code>"
    )


def object_feedback(record: dict[str, Any]) -> str:
    messages = {
        "ship": "✅ Судно размечено.",
        "multiple_ships": "👥 Сохранено: несколько судов.",
        "no_ship": "🚫 Сохранено: судна нет.",
        "uncertain": "❔ Сохранено без включения в метрики.",
        "skipped": "⏭ Tile пропущен.",
    }
    missed = "\n⚠️ Это missed target текущего detector." if record.get("missed_target") else ""
    return messages.get(str(record.get("object_label")), "Ответ сохранён.") + missed


async def _clear_keyboard(query: Any) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:  # pragma: no cover - Telegram message state dependent
        return


def _callback(action: str, *parts: str) -> str:
    return ":".join((PHASE2_CALLBACK_PREFIX, action, *parts))


def _compact_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "нет"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))
