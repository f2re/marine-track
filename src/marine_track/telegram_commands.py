from __future__ import annotations

from telegram import BotCommand

BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("start", "Главное меню"),
    BotCommand("menu", "Открыть меню"),
    BotCommand("help", "Помощь и примеры"),
    BotCommand("status", "Статус конфигурации"),
    BotCommand("whoami", "Показать Telegram user id"),
    BotCommand("dates", "Сроки снимков по AOI"),
    BotCommand("bboxdates", "Сроки снимков по bbox"),
    BotCommand("image", "Preview снимка по token"),
    BotCommand("detect", "Детекция по scene token"),
    BotCommand("detectbbox", "Детекция по bbox"),
)

BOT_COMMAND_LINES: tuple[str, ...] = tuple(
    f"/{command.command} — {command.description}" for command in BOT_COMMANDS
)


async def register_bot_commands(application) -> None:
    await application.bot.set_my_commands(list(BOT_COMMANDS))
