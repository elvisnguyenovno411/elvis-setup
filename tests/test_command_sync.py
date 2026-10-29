import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from elvis_setup.bot import ElvisSetupBot, register_commands
from elvis_setup.config import Settings


@pytest.mark.parametrize("sync_fails", [False, True])
def test_remote_cleanup_keeps_definitions_for_new_server(sync_fails: bool) -> None:
    async def scenario() -> None:
        bot = ElvisSetupBot(Settings("test", 123))
        register_commands(bot)
        original = {command.name for command in bot.tree.get_commands()}
        bot.tree.sync = AsyncMock(side_effect=RuntimeError("network") if sync_fails else None)
        if sync_fails:
            with pytest.raises(RuntimeError):
                await bot._clear_remote_global_commands()
        else:
            await bot._clear_remote_global_commands()
        assert {command.name for command in bot.tree.get_commands()} == original
        guild = SimpleNamespace(id=456, name="New server")
        bot.tree.sync = AsyncMock(return_value=list(bot.tree.get_commands()))
        await bot.on_guild_join(guild)
        bot.tree.sync.assert_awaited_once_with(guild=guild)
        assert {command.name for command in bot.tree.get_commands(guild=guild)} == original

    asyncio.run(scenario())
