from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .config import ROOT_DIR, Settings
from .music import MusicManager, register_music_commands
from .reporting import ReportWriter
from .setup_engine import channel_permission_for
from .template_loader import TemplateLoader
from .views import (
    BRAND_COLOR,
    CreateGameChannelsModal,
    CreateRolesModal,
    DeleteChannelsModal,
    DeleteRolesModal,
    TopicPickerView,
    show_structure_confirmation,
)

LOGGER = logging.getLogger(__name__)
CARL_BOT_USER_ID = 235148962103951360
ROLE_PICKER_CHANNEL_NAME = "🎭┊『𝐂𝐇𝐎̣𝐍-𝐑𝐎𝐋𝐄』"


class ElvisSetupBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        loader = TemplateLoader(ROOT_DIR / "templates")
        self.base_template = loader.load_base()
        self.server_layout = loader.load_server_layout()
        self.templates = loader.load_all()
        self.report_writer = ReportWriter(ROOT_DIR)
        self._guild_commands_synced = False
        self._command_sync_lock = asyncio.Lock()
        self.music = MusicManager(self, settings.owner_user_id)

    async def setup_hook(self) -> None:
        self.music.start()
        LOGGER.info("Đã nạp %s slash command.", len(self.tree.get_commands()))

    async def close(self) -> None:
        await self.music.close()
        await super().close()

    async def on_ready(self) -> None:
        if self.user is not None:
            LOGGER.info("Đã đăng nhập: %s (%s)", self.user, self.user.id)
            await self.change_presence(activity=discord.Game(name="/setup • Elvis Setup"))
        if not self._guild_commands_synced:
            async with self._command_sync_lock:
                if self._guild_commands_synced:
                    return
                for guild in self.guilds:
                    await self._sync_guild_commands(guild)
                await self._clear_remote_global_commands()
                self._guild_commands_synced = True

    async def _sync_guild_commands(self, guild: discord.Guild) -> None:
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
        except discord.HTTPException:
            LOGGER.exception("Không thể đồng bộ command cho server %s.", guild.id)
            return
        LOGGER.info("Đã đồng bộ %s command tức thời cho %s.", len(synced), guild.name)

    async def _clear_remote_global_commands(self) -> None:
        # Giữ định nghĩa trong RAM để các server vừa mời bot vào vẫn có lệnh.
        definitions = self.tree.get_commands()
        self.tree.clear_commands(guild=None)
        try:
            await self.tree.sync()
        finally:
            for command in definitions:
                self.tree.add_command(command, override=True)
        LOGGER.info("Đã xóa command global trùng lặp; vẫn giữ định nghĩa để đồng bộ server mới.")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        async with self._command_sync_lock:
            await self._sync_guild_commands(guild)


def _is_owner(interaction: discord.Interaction, settings: Settings) -> bool:
    return interaction.user.id == settings.owner_user_id


def register_commands(bot: ElvisSetupBot) -> None:
    register_music_commands(bot, bot.music)
    @bot.tree.command(name="setup", description="Mở bảng chọn template và setup server")
    @app_commands.guild_only()
    async def setup(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="Elvis Setup — Chọn nhiều chủ đề",
            description=(
                "Chọn một hoặc nhiều chủ đề. Mỗi chủ đề sẽ trở thành một category "
                "và chủ đề không chọn sẽ không được tạo."
            ),
            colour=BRAND_COLOR,
        )
        embed.add_field(
            name="Lưu ý",
            value="Setup sẽ xóa cấu trúc cũ sau hai bước xác nhận.",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=TopicPickerView(
                bot.settings.owner_user_id,
                bot.base_template,
                bot.templates,
            ),
            ephemeral=True,
        )

    @bot.tree.command(
        name="lam-server",
        description="Thêm template lên đầu và giữ nguyên toàn bộ kênh, role cũ",
    )
    @app_commands.guild_only()
    async def build_server(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        await show_structure_confirmation(
            interaction,
            bot.settings.owner_user_id,
            bot.server_layout,
        )

    @bot.tree.command(name="templates", description="Xem danh sách template hiện có")
    @app_commands.guild_only()
    async def templates(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        lines = [
            f"{template.emoji} **{template.name}** — {template.description}"
            for template in bot.templates.values()
        ]
        embed = discord.Embed(
            title=f"{len(lines)} template có sẵn",
            description="\n".join(lines),
            colour=BRAND_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="kiem-tra", description="Kiểm tra quyền bot trước khi setup")
    @app_commands.guild_only()
    async def preflight(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        guild = interaction.guild
        me = guild.me if guild else None
        administrator = bool(me and me.guild_permissions.administrator)
        embed = discord.Embed(
            title="Kiểm tra trước khi setup",
            colour=discord.Colour.green() if administrator else discord.Colour.red(),
        )
        embed.add_field(
            name="Quyền Administrator",
            value="Đạt" if administrator else "Thiếu",
        )
        embed.add_field(name="Template YAML", value=f"{len(bot.templates)} hợp lệ")
        embed.add_field(name="Chủ bot", value=f"<@{bot.settings.owner_user_id}>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="cap-quyen-carl",
        description="Cấp quyền cho Carl-bot đăng bảng chọn role",
    )
    @app_commands.guild_only()
    async def grant_carl_permissions(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Không tìm thấy server hiện tại.", ephemeral=True
            )
            return

        channel = discord.utils.get(guild.text_channels, name=ROLE_PICKER_CHANNEL_NAME)
        if channel is None:
            await interaction.response.send_message(
                f"Không tìm thấy kênh `{ROLE_PICKER_CHANNEL_NAME}`.", ephemeral=True
            )
            return

        carl = guild.get_member(CARL_BOT_USER_ID)
        if carl is None:
            try:
                carl = await guild.fetch_member(CARL_BOT_USER_ID)
            except discord.NotFound:
                await interaction.response.send_message(
                    "Carl-bot chưa được thêm vào server.", ephemeral=True
                )
                return
            except discord.Forbidden:
                await interaction.response.send_message(
                    "Bot setup không thể đọc thông tin Carl-bot trong server.",
                    ephemeral=True,
                )
                return

        await channel.set_permissions(
            carl,
            view_channel=True,
            send_messages=True,
            embed_links=True,
            read_message_history=True,
            add_reactions=True,
            use_application_commands=True,
            reason="Elvis Setup: cấp quyền cho Carl-bot tạo reaction role",
        )

        embed = discord.Embed(
            title="Đã cấp quyền cho Carl-bot",
            description=(
                f"Carl-bot đã có quyền xem, gửi tin nhắn, đăng embed và thả reaction "
                f"tại {channel.mention}."
            ),
            colour=discord.Colour.green(),
        )
        embed.add_field(
            name="Bước tiếp theo",
            value="Quay lại kênh và tạo reaction role thêm một lần nữa.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="mo-kenh-everyone",
        description="Mở các kênh chung cho toàn bộ thành viên hiện tại",
    )
    @app_commands.guild_only()
    async def open_core_channels(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Không tìm thấy server hiện tại.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        updated_categories = 0
        updated_channels = 0
        missing: list[str] = []

        try:
            for category_spec in bot.base_template.categories:
                if all(channel.access == "admin" for channel in category_spec.channels):
                    continue

                category = discord.utils.get(guild.categories, name=category_spec.name)
                if category is None:
                    missing.append(category_spec.name)
                    continue

                category_overwrite = category.overwrites_for(guild.default_role)
                category_overwrite.view_channel = True
                await category.set_permissions(
                    guild.default_role,
                    overwrite=category_overwrite,
                    reason="Elvis Setup: mở category chung cho @everyone",
                )
                updated_categories += 1

                for channel_spec in category_spec.channels:
                    channel = discord.utils.get(category.channels, name=channel_spec.name)
                    if channel is None:
                        missing.append(channel_spec.name)
                        continue
                    await channel.set_permissions(
                        guild.default_role,
                        overwrite=channel_permission_for(channel_spec),
                        reason="Elvis Setup: mở kênh chung cho @everyone",
                    )
                    updated_channels += 1
        except discord.Forbidden:
            await interaction.followup.send(
                "Bot thiếu quyền Administrator hoặc Manage Channels.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Đã mở kênh chung cho @everyone",
            description=(
                "Thành viên cũ không cần role `Thành viên` vẫn xem được các kênh "
                "thông tin, cộng đồng, chọn role và phòng thoại."
            ),
            colour=discord.Colour.green(),
        )
        embed.add_field(name="Category đã sửa", value=str(updated_categories))
        embed.add_field(name="Kênh đã sửa", value=str(updated_channels))
        embed.add_field(
            name="Vẫn được bảo vệ",
            value="Khu Admin/log và các category sở thích theo role.",
            inline=False,
        )
        if missing:
            embed.add_field(
                name="Không tìm thấy",
                value=", ".join(missing[:10]),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(
        name="xoa-kenh",
        description="Xóa kênh và nhập các ID muốn giữ lại",
    )
    @app_commands.guild_only()
    async def delete_channels(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        await interaction.response.send_modal(DeleteChannelsModal(bot.settings.owner_user_id))

    @bot.tree.command(
        name="xoa-role",
        description="Xóa role và nhập các ID muốn giữ lại",
    )
    @app_commands.guild_only()
    async def delete_roles(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        await interaction.response.send_modal(DeleteRolesModal(bot.settings.owner_user_id))

    @bot.tree.command(
        name="tao-role",
        description="Tạo nhiều role từ danh sách tên cách nhau bằng dấu phẩy",
    )
    @app_commands.guild_only()
    async def create_roles(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        await interaction.response.send_modal(CreateRolesModal(bot.settings.owner_user_id))

    @bot.tree.command(
        name="tao-kenh-game",
        description="Tạo category, kênh chat và voice cho nhiều game",
    )
    @app_commands.guild_only()
    async def create_game_channels(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            CreateGameChannelsModal(bot.settings.owner_user_id)
        )


def run() -> None:
    settings = Settings.from_env()
    report_writer = ReportWriter(ROOT_DIR)
    report_writer.configure_logging(settings.log_level)
    bot = ElvisSetupBot(settings)
    register_commands(bot)
    bot.run(settings.token, log_handler=None)
