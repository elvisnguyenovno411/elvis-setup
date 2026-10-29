from __future__ import annotations

import asyncio
import logging
import shutil
import time
from contextlib import suppress
from dataclasses import dataclass, field
from urllib.parse import urlparse
from uuid import uuid4

import discord
import imageio_ffmpeg
import yt_dlp
from discord import app_commands
from discord.ext import commands

LOGGER = logging.getLogger(__name__)
COLOR = discord.Colour.from_rgb(180, 122, 255)
PAGE_SIZE = 10


def short(value: str, limit: int = 100) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "LIVE"
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


@dataclass
class Track:
    key: str
    title: str
    url: str
    length: float | None
    thumbnail: str | None = None
    artist: str = "YouTube"
    uid: str = field(default_factory=lambda: uuid4().hex)


def extract(query: str) -> dict:
    """Chỉ nhận tìm kiếm hoặc URL YouTube; không đọc file/URL nội bộ."""
    query = query.strip()
    if not query or len(query) > 500:
        raise ValueError("Nhập tên bài hoặc link YouTube, tối đa 500 ký tự.")
    if "://" in query:
        parsed = urlparse(query)
        if parsed.scheme != "https" or parsed.hostname not in {
            "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"
        }:
            raise ValueError("Hiện bot hỗ trợ tên bài hoặc link HTTPS của YouTube.")
        target = query
    else:
        target = f"ytsearch1:{query}"
    with yt_dlp.YoutubeDL({
        "format": "bestaudio/best", "noplaylist": True, "quiet": True,
        "no_warnings": True, "socket_timeout": 20, "retries": 2,
        "extractor_retries": 2, "cachedir": False,
        "js_runtimes": {"node": {"path": shutil.which("node")}} if shutil.which("node") else {},
    }) as loader:
        info = loader.extract_info(target, download=False)
    if info and "entries" in info:
        info = next((entry for entry in info["entries"] if entry), None)
    if not info or not info.get("url") or not info.get("id"):
        raise ValueError("Không tìm thấy bài có thể phát. Thử link YouTube của từng bài.")
    return info


def track_from_info(info: dict) -> Track:
    return Track(
        key=str(info["id"]), title=info.get("title") or "Không rõ tên",
        url=f"https://www.youtube.com/watch?v={info['id']}",
        length=info.get("duration"), thumbnail=info.get("thumbnail"),
        artist=info.get("uploader") or "YouTube",
    )


class Session:
    def __init__(self, manager: MusicManager, guild: discord.Guild) -> None:
        self.manager = manager
        self.guild = guild
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self.lock = asyncio.Lock()
        self.started = 0.0
        self.paused_at: float | None = None
        self.paused_total = 0.0
        self.generation = 0
        self.player_message: discord.Message | None = None
        self.panel_queue = False
        self.queue_page = 0
        self.views: dict[str, MusicView] = {}
        self.render_lock = asyncio.Lock()
        self.last_error: str | None = None
        self.idle_since = time.monotonic()

    @property
    def elapsed(self) -> float:
        if self.current is None:
            return 0
        value = (self.paused_at or time.monotonic()) - self.started - self.paused_total
        return min(max(0, value), self.current.length or float("inf"))

    def enqueue(self, track: Track) -> bool:
        if (self.current and self.current.key == track.key) or any(
            item.key == track.key for item in self.queue
        ):
            return False
        if len(self.queue) >= 100:
            raise ValueError("Hàng chờ đã đủ 100 bài. Hãy bỏ bớt bài trước khi thêm.")
        self.queue.append(track)
        return True

    def remove(self, uid: str) -> Track | None:
        for index, track in enumerate(self.queue):
            if track.uid == uid:
                return self.queue.pop(index)
        return None

    async def advance(self) -> None:
        """Caller giữ lock; token bảo vệ callback cũ khi skip/disconnect."""
        self.current = None
        self.paused_at = None
        self.idle_since = time.monotonic()
        while self.queue and self.voice and self.voice.is_connected():
            track = self.queue.pop(0)
            self.current = track
            source = None
            try:
                info = await asyncio.to_thread(extract, track.url)
                source = discord.FFmpegOpusAudio(
                    info["url"], executable=imageio_ffmpeg.get_ffmpeg_exe(),
                    before_options="-nostdin -reconnect 1 -reconnect_streamed 1 "
                    "-reconnect_delay_max 5",
                    options="-vn -loglevel warning", bitrate=128,
                )
                self.generation += 1
                token = self.generation
                loop = asyncio.get_running_loop()

                def after(
                    error: Exception | None, token: int = token,
                    loop: asyncio.AbstractEventLoop = loop,
                ) -> None:
                    asyncio.run_coroutine_threadsafe(self.finished(token, error), loop)

                self.voice.play(source, after=after)
                self.started = time.monotonic()
                self.paused_total = 0
                self.last_error = None
                return
            except Exception:
                if source:
                    source.cleanup()
                LOGGER.exception("Không thể phát bài %s", track.key)
                self.last_error = f"Không phát được: {short(track.title, 120)}. Đã bỏ qua bài này."
                self.current = None
        self.idle_since = time.monotonic()

    async def finished(self, token: int, error: Exception | None) -> None:
        async with self.lock:
            if token != self.generation:
                return
            if error:
                LOGGER.error("Lỗi audio: %s", error)
            await self.advance()
            if error:
                self.last_error = "Luồng âm thanh gặp lỗi; bot đã chuyển sang bài tiếp theo nếu có."
        await self.update()

    def toggle_pause(self) -> None:
        if not self.voice or not self.current:
            raise ValueError("Chưa có bài đang phát.")
        if self.voice.is_paused():
            self.voice.resume()
            self.paused_total += time.monotonic() - (self.paused_at or time.monotonic())
            self.paused_at = None
        elif self.voice.is_playing():
            self.voice.pause()
            self.paused_at = time.monotonic()
        else:
            raise ValueError("Bài đang được nạp. Hãy chờ một chút.")

    async def skip(self) -> None:
        if not self.current or not self.queue:
            raise ValueError("Chỉ chuyển bài khi có bài tiếp theo trong hàng chờ.")
        self.generation += 1
        if self.voice:
            self.voice.stop()
        await self.advance()

    async def stop(self) -> None:
        self.generation += 1
        self.queue.clear()
        self.current = None
        self.paused_at = None
        if self.voice:
            await self.voice.disconnect(force=True)
        self.voice = None
        if self.player_message:
            with suppress(discord.HTTPException):
                await self.player_message.delete()
        self.player_message = None
        for view in self.views.values():
            view.stop()
        self.views.clear()

    def embed(self, *, queue: bool = False) -> discord.Embed:
        track = self.current
        embed = discord.Embed(
            title="🎶 HÀNG CHỜ" if queue else "🎧 ELVIS MUSIC",
            colour=COLOR, timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name="CON VỢ BOT CỦA VỸ • MUSIC LOUNGE")
        if track:
            title = discord.utils.escape_markdown(short(track.title, 180))
            embed.description = f"**[{title}]({track.url})**\n{short(track.artist, 100)}"
            if track.thumbnail:
                if queue:
                    embed.set_thumbnail(url=track.thumbnail)
                else:
                    embed.set_image(url=track.thumbnail)
            ratio = min(1, self.elapsed / track.length) if track.length else 0
            marker = min(14, int(ratio * 15))
            bar = "━" * marker + "●" + "─" * (14 - marker)
            state = "⏸ Tạm dừng" if self.paused_at is not None else "▶ Đang phát"
            embed.add_field(
                name=state,
                value=f"`{bar}`\n`{duration(self.elapsed)} / {duration(track.length)}`",
                inline=False,
            )
        else:
            embed.description = "🌙 Chưa có bài đang phát. Dùng `/phat-nhac` để thêm bài."
        if queue:
            pages = max(1, (len(self.queue) + PAGE_SIZE - 1) // PAGE_SIZE)
            self.queue_page = min(self.queue_page, pages - 1)
            start = self.queue_page * PAGE_SIZE
            lines = [
                f"`{index + 1:02}` {discord.utils.escape_markdown(short(item.title, 100))} "
                f"· `{duration(item.length)}`"
                for index, item in enumerate(self.queue[start:start + PAGE_SIZE], start)
            ]
            embed.add_field(
                name=f"Tiếp theo · {len(self.queue)} bài · Trang {self.queue_page + 1}/{pages}",
                value="\n".join(lines) or "✨ Hàng chờ trống.", inline=False,
            )
        elif self.queue:
            embed.add_field(name="⏭ Tiếp theo", value=short(self.queue[0].title, 200))
        if self.last_error:
            embed.add_field(name="Thông báo", value=self.last_error, inline=False)
        embed.set_footer(text="Con Vợ Bot Của Vỹ • Tự cập nhật mỗi 15 giây")
        return embed

    async def publish(self, interaction: discord.Interaction, *, queue: bool = False) -> None:
        self.panel_queue = queue
        await interaction.followup.send(
            "Đã mở bảng hàng chờ." if queue else "Đã cập nhật trình phát nhạc.", ephemeral=True
        )
        async with self.render_lock:
            await self._update()
            if self.player_message is None:
                embed = self.embed(queue=queue)
                view = MusicView(self, queue=queue)
                self.player_message = await interaction.channel.send(
                    embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none(),
                )
                self.views["player_message"] = view

    async def update(self) -> None:
        async with self.render_lock:
            await self._update()

    async def _update(self) -> None:
        for attribute, queue in (("player_message", self.panel_queue),):
            message = getattr(self, attribute)
            if message:
                if attribute in self.views:
                    self.views[attribute].stop()
                try:
                    embed = self.embed(queue=queue)
                    view = MusicView(self, queue=queue)
                    await message.edit(
                        embed=embed, view=view,
                    )
                    self.views[attribute] = view
                except discord.HTTPException:
                    setattr(self, attribute, None)


class RemoveSelect(discord.ui.Select):
    def __init__(self, session: Session) -> None:
        start = session.queue_page * PAGE_SIZE
        super().__init__(
            placeholder="🗑 Chọn bài muốn bỏ khỏi hàng chờ…", row=1,
            options=[discord.SelectOption(
                label=short(f"{index + 1}. {item.title}"), value=item.uid,
                description=f"Thời lượng: {duration(item.length)}",
            ) for index, item in enumerate(session.queue[start:start + PAGE_SIZE], start)],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, MusicView)
        await interaction.response.defer()
        async with view.session.lock:
            removed = view.session.remove(self.values[0])
        await view.session.update()
        await interaction.followup.send(
            f"Đã bỏ **{short(removed.title, 150)}**." if removed else "Bài này đã rời hàng chờ.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )


class MusicView(discord.ui.View):
    def __init__(self, session: Session, *, queue: bool = False) -> None:
        super().__init__(timeout=None)
        self.session = session
        self.pause.label = "Tiếp tục" if session.paused_at is not None else "Tạm dừng"
        self.pause.emoji = "▶️" if session.paused_at is not None else "⏸️"
        self.pause.disabled = session.current is None
        self.next_track.disabled = not session.queue or session.current is None
        self.leave.disabled = session.voice is None
        if queue and session.queue:
            self.add_item(RemoveSelect(session))
        if not queue:
            self.remove_item(self.previous_page)
            self.remove_item(self.next_page)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Ai cũng được kết thúc phiên; pause/skip yêu cầu cùng kênh để tránh nhầm phiên.
        if interaction.data and interaction.data.get("custom_id") == self.leave.custom_id:
            return True
        voice = getattr(interaction.user, "voice", None)
        if self.session.voice and (
            not voice or voice.channel != self.session.voice.channel
        ):
            await interaction.response.send_message(
                "Hãy vào cùng kênh thoại với bot để điều khiển.", ephemeral=True
            )
            return False
        return True

    async def act(self, interaction: discord.Interaction, action: str) -> None:
        await interaction.response.defer()
        try:
            async with self.session.lock:
                if action == "pause":
                    self.session.toggle_pause()
                elif action == "skip":
                    await self.session.skip()
                else:
                    await self.session.stop()
            await self.session.update()
        except (ValueError, discord.DiscordException) as exc:
            await interaction.followup.send(short(str(exc), 500), ephemeral=True)

    @discord.ui.button(label="Tạm dừng", emoji="⏸️", style=discord.ButtonStyle.primary)
    async def pause(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.act(interaction, "pause")

    @discord.ui.button(label="Chuyển bài", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def next_track(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.act(interaction, "skip")

    @discord.ui.button(label="Kết thúc", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.act(interaction, "stop")

    @discord.ui.button(label="Nhạc / Hàng chờ", emoji="📋")
    async def switch_panel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        self.session.panel_queue = not self.session.panel_queue
        await self.session.update()

    @discord.ui.button(label="Trang trước", emoji="◀️", row=2)
    async def previous_page(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        self.session.queue_page = max(0, self.session.queue_page - 1)
        await self.session.update()

    @discord.ui.button(label="Trang sau", emoji="▶️", row=2)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        pages = max(1, (len(self.session.queue) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.session.queue_page = min(pages - 1, self.session.queue_page + 1)
        await self.session.update()


class MusicManager:
    def __init__(self, bot: commands.Bot, owner_id: int) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self.sessions: dict[int, Session] = {}
        self.refresh_task: asyncio.Task | None = None

    def start(self) -> None:
        self.refresh_task = asyncio.create_task(self.run_refresh())

    async def run_refresh(self) -> None:
        while True:
            await asyncio.sleep(15)
            await self.refresh()

    def get(self, guild: discord.Guild) -> Session:
        if guild.id not in self.sessions:
            self.sessions[guild.id] = Session(self, guild)
        return self.sessions[guild.id]

    async def refresh(self) -> None:
        for session in list(self.sessions.values()):
            try:
                async with session.lock:
                    if session.voice and (
                        not session.voice.is_connected()
                        or (not session.current and time.monotonic() - session.idle_since > 180)
                    ):
                        await session.stop()
                await session.update()
            except Exception:
                LOGGER.exception("Lỗi cập nhật bảng nhạc cho server %s", session.guild.id)

    async def close(self) -> None:
        if self.refresh_task:
            self.refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.refresh_task
        for session in list(self.sessions.values()):
            async with session.lock:
                await session.stop()
            await session.update()


def register_music_commands(bot: commands.Bot, manager: MusicManager) -> None:
    async def check(interaction: discord.Interaction) -> bool:
        return interaction.guild is not None

    @bot.tree.command(name="phat-nhac", description="Phát nhạc từ tên bài hoặc link YouTube")
    @app_commands.guild_only()
    @app_commands.describe(bai_hat="Tên bài hoặc link YouTube của một bài")
    async def play(interaction: discord.Interaction, bai_hat: str) -> None:
        if not await check(interaction):
            return
        voice_state = getattr(interaction.user, "voice", None)
        if not voice_state or not isinstance(voice_state.channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "Hãy vào một kênh thoại thường trước khi phát nhạc.", ephemeral=True
            )
            return
        channel = voice_state.channel
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.connect or not permissions.speak:
            await interaction.response.send_message(
                "Bot cần quyền Kết nối và Nói trong kênh thoại này.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        session = manager.get(interaction.guild)
        try:
            info = await asyncio.to_thread(extract, bai_hat)
            track = track_from_info(info)
            async with session.lock:
                if session.voice and session.voice.channel != channel:
                    raise ValueError("Bot đang ở kênh thoại khác. Hãy vào cùng kênh với bot.")
                if not session.voice:
                    session.voice = await channel.connect(self_deaf=True, timeout=30)
                added = session.enqueue(track)
                if added and session.current is None:
                    await session.advance()
                await session.update()
                if not added:
                    await interaction.followup.send(
                        "♻️ Bài này đang phát hoặc đã có trong hàng chờ.", ephemeral=True
                    )
                else:
                    await session.publish(interaction)
        except ValueError as exc:
            await interaction.followup.send(short(str(exc), 500), ephemeral=True)
        except Exception:
            LOGGER.exception("Không thể thêm bài hát")
            await interaction.followup.send(
                "Không thể thêm bài. Kiểm tra link, quyền voice và kết nối mạng. "
                "Bài giới hạn đăng nhập/vùng hoặc bị YouTube chặn có thể không phát được. "
                "Chi tiết nằm trong log trên máy.",
                ephemeral=True,
            )

    @bot.tree.command(name="queue", description="Xem hàng chờ tự cập nhật và chọn bài để bỏ")
    @app_commands.guild_only()
    async def queue(interaction: discord.Interaction) -> None:
        if not await check(interaction):
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        session = manager.get(interaction.guild)
        async with session.lock:
            await session.publish(interaction, queue=True)

    @bot.tree.command(name="play", description="Phát nhạc hoặc thêm bài vào hàng chờ")
    @app_commands.guild_only()
    @app_commands.describe(bai_hat="Tên bài hoặc link YouTube của một bài")
    async def play_alias(interaction: discord.Interaction, bai_hat: str) -> None:
        await play.callback(interaction, bai_hat)

    @bot.tree.command(name="stop", description="Dừng nhạc, xóa queue và bảng điều khiển")
    @app_commands.guild_only()
    async def stop(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        session = manager.get(interaction.guild)
        async with session.lock:
            await session.stop()
        await interaction.followup.send(
            "⏹ Đã dừng nhạc, xóa hàng chờ và bảng điều khiển.", ephemeral=True
        )
