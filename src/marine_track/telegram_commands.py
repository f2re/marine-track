from __future__ import annotations

from telegram import BotCommand

BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("start", "🚢 Старт и режим работы"),
    BotCommand("help", "❓ Команды и примеры"),
    BotCommand("status", "⚙️ Статус конфигурации"),
    BotCommand("whoami", "🆔 Показать Telegram user id"),
    BotCommand("search", "🛰️ Поиск Sentinel-сцен по AOI"),
    BotCommand("bbox", "🗺️ Поиск Sentinel-сцен по bbox"),
)

BOT_COMMAND_LINES: tuple[str, ...] = tuple(
    f"/{command.command} — {command.description}" for command in BOT_COMMANDS
)


async def register_bot_commands(application) -> None:
    await application.bot.set_my_commands(list(BOT_COMMANDS))
