import asyncio
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from elvis_setup.music import (
    MusicManager,
    MusicRecoveryView,
    MusicView,
    Session,
    Track,
    duration,
    extract,
)


def session() -> Session:
    return Session(SimpleNamespace(owner_id=123), SimpleNamespace(id=1))


def track(key: str) -> Track:
    return Track(key, key, f"https://www.youtube.com/watch?v={key}", 200)


def test_queue_deduplicates_current_and_waiting_tracks() -> None:
    state = session()
    state.current = track("playing")
    assert not state.enqueue(track("playing"))
    assert state.enqueue(track("next"))
    assert not state.enqueue(track("next"))
    assert len(state.queue) == 1


def test_remove_uses_stable_id_when_positions_change() -> None:
    state = session()
    first, second = track("a"), track("b")
    state.queue = [first, second]
    state.queue.pop(0)
    assert state.remove(first.uid) is None
    assert state.remove(second.uid) is second
    assert not state.queue


def test_pause_resume_freezes_time_and_resumes_same_source(monkeypatch) -> None:
    state = session()
    state.current = track("a")
    state.started = 100
    state.voice = Mock()
    state.voice.is_paused.return_value = False
    state.voice.is_playing.return_value = True
    monkeypatch.setattr("elvis_setup.music.time.monotonic", lambda: 130)
    state.toggle_pause()
    state.voice.pause.assert_called_once()
    monkeypatch.setattr("elvis_setup.music.time.monotonic", lambda: 190)
    assert state.elapsed == 30
    state.voice.is_paused.return_value = True
    state.toggle_pause()
    state.voice.resume.assert_called_once()
    state.voice.play.assert_not_called()
    monkeypatch.setattr("elvis_setup.music.time.monotonic", lambda: 200)
    assert state.elapsed == 40


@pytest.mark.parametrize("query", ["https://localhost/x", "file:///a", "http://youtube.com/a"])
def test_rejects_unsupported_urls_before_network_access(query) -> None:
    with pytest.raises(ValueError):
        extract(query)


def test_queue_page_clamps_after_deleting_last_page() -> None:
    state = session()
    state.queue = [track("a")]
    state.queue_page = 3
    embed = state.embed(queue=True)
    assert state.queue_page == 0
    assert "Trang 1/1" in embed.fields[-1].name


def test_duration_handles_live_and_long_tracks() -> None:
    assert duration(None) == "LIVE"
    assert duration(3661) == "1:01:01"
    assert duration(65) == "1:05"


def test_skip_ignores_old_completion_callback_and_stop_clears_state() -> None:
    async def scenario() -> None:
        state = session()
        state.current = track("a")
        state.queue = [track("b")]
        state.voice = Mock()
        state.voice.disconnect = AsyncMock()
        state.advance = AsyncMock()
        old_token = state.generation
        await state.skip()
        await state.finished(old_token, None)
        state.advance.assert_awaited_once()
        await state.stop()
        assert not state.queue and state.current is None and state.voice is None

    asyncio.run(scenario())


def test_buttons_and_selector_follow_current_state() -> None:
    async def scenario() -> None:
        state = session()
        empty = MusicView(state)
        assert empty.pause.disabled and empty.next_track.disabled
        state.current = track("a")
        state.queue = [track(str(index)) for index in range(30)]
        state.paused_at = 10
        view = MusicView(state, queue=True)
        assert view.pause.label == "Tiếp tục"
        assert not view.next_track.disabled
        selector = next(child for child in view.children if hasattr(child, "options"))
        assert len(selector.options) == 10
        assert selector.options[0].value == state.queue[0].uid

    asyncio.run(scenario())


def test_publish_reuses_one_message_and_stop_deletes_it() -> None:
    async def scenario() -> None:
        state = session()
        message = SimpleNamespace(edit=AsyncMock(), delete=AsyncMock())
        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=AsyncMock()),
            channel=SimpleNamespace(send=AsyncMock(return_value=message)),
        )
        await state.publish(interaction)
        await state.publish(interaction, queue=True)
        interaction.channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        assert state.panel_queue
        await state.stop()
        message.delete.assert_awaited_once()
        assert state.player_message is None

    asyncio.run(scenario())


def test_music_commands_have_no_owner_restriction() -> None:
    from elvis_setup.bot import ElvisSetupBot, register_commands
    from elvis_setup.config import Settings

    bot = ElvisSetupBot(Settings("test", 123))
    register_commands(bot)
    for name in ("play", "phat-nhac", "queue", "stop"):
        command = bot.tree.get_command(name)
        assert command is not None
        assert not command.checks
        assert command.default_permissions is None


def test_playback_advances_fifo_and_skips_failed_sources(monkeypatch) -> None:
    async def scenario() -> None:
        state = session()
        state.voice = Mock()
        state.voice.is_connected.return_value = True
        state.queue = [track("broken"), track("good"), track("later")]
        monkeypatch.setattr(
            "elvis_setup.music.asyncio.to_thread",
            AsyncMock(side_effect=[ValueError("unavailable"), {"url": "https://example.org/audio"}]),
        )
        source = Mock(spec=discord.AudioSource)
        source.is_opus.return_value = False
        monkeypatch.setattr("elvis_setup.music.discord.FFmpegPCMAudio", Mock(return_value=source))
        monkeypatch.setattr("elvis_setup.music.imageio_ffmpeg.get_ffmpeg_exe", lambda: "ffmpeg")
        await state.advance()
        assert state.current.key == "good"
        assert [item.key for item in state.queue] == ["later"]
        state.voice.play.assert_called_once()
        assert state.voice.play.call_args.args[0].original is source

    asyncio.run(scenario())


def test_volume_reduces_real_pcm_samples_without_restarting_playback() -> None:
    state = session()
    state.current = track("a")
    state.voice = Mock()
    pcm = Mock(spec=discord.AudioSource)
    pcm.is_opus.return_value = False
    pcm.read.return_value = struct.pack("<hh", 10000, -10000)
    state.audio_source = discord.PCMVolumeTransformer(pcm)
    state.lower_volume()
    assert state.volume_percent == 90
    assert struct.unpack("<hh", state.audio_source.read()) == (9000, -9000)
    for _ in range(15):
        state.lower_volume()
    assert state.volume_percent == 0
    assert struct.unpack("<hh", state.audio_source.read()) == (0, 0)
    state.raise_volume()
    assert state.volume_percent == 10
    assert struct.unpack("<hh", state.audio_source.read()) == (1000, -1000)
    for _ in range(15):
        state.raise_volume()
    assert state.volume_percent == 100
    assert struct.unpack("<hh", state.audio_source.read()) == (10000, -10000)
    state.voice.play.assert_not_called()
    state.voice.stop.assert_not_called()
    state.audio_source.cleanup()


def test_control_ids_stay_stable_and_have_restart_fallback() -> None:
    async def scenario() -> None:
        state = session()
        first = MusicView(state, queue=True)
        second = MusicView(state, queue=True)
        recovery = MusicRecoveryView(SimpleNamespace())
        ids = {item.custom_id for item in first.children}
        assert ids == {item.custom_id for item in second.children}
        assert ids == {item.custom_id for item in recovery.children}
        assert recovery.is_persistent()

    asyncio.run(scenario())


def test_stop_button_acknowledges_before_disconnect_and_deletes_panel() -> None:
    async def scenario() -> None:
        state = session()
        events = []

        async def acknowledge(**kwargs) -> None:
            events.append("ack")

        async def delete() -> None:
            events.append("delete")

        async def disconnect(**kwargs) -> None:
            events.append("disconnect")

        state.player_message = SimpleNamespace(delete=delete)
        state.voice = Mock(disconnect=disconnect)
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=acknowledge),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        await MusicView(state).act(interaction, "stop")
        assert events == ["ack", "delete", "disconnect"]
        assert state.voice is None and state.player_message is None
        interaction.followup.send.assert_awaited_once()

    asyncio.run(scenario())


def test_restart_recovery_can_stop_old_panel_without_voice_membership() -> None:
    async def scenario() -> None:
        manager = MusicManager(Mock(), 123)
        guild = SimpleNamespace(id=1, voice_client=None)
        message = SimpleNamespace(id=99, delete=AsyncMock())
        interaction = SimpleNamespace(
            guild=guild, message=message,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        await manager.recover(interaction, "leave")
        message.delete.assert_awaited_once()
        assert manager.get(guild).player_message is None

    asyncio.run(scenario())
