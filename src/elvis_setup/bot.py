from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .config import ROOT_DIR, Settings
from .reporting import ReportWriter
from .template_loader import TemplateLoader
from .views import BRAND_COLOR, DeleteChannelsView, TopicPickerView

LOGGER = logging.getLogger(__name__)
CARL_BOT_USER_ID = 235148962103951360
ROLE_PICKER_CHANNEL_NAME = "🎭・chon-role"


class ElvisSetupBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        loader = TemplateLoader(ROOT_DIR / "templates")
        self.base_template = loader.load_base()
        self.templates = loader.load_all()
        self.report_writer = ReportWriter(ROOT_DIR)
        self._guild_commands_synced = False

    async def setup_hook(self) -> None:
        LOGGER.info("Đã nạp %s slash command.", len(self.tree.get_commands()))

    async def on_ready(self) -> None:
        if self.user is not None:
            LOGGER.info("Đã đăng nhập: %s (%s)", self.user, self.user.id)
            await self.change_presence(activity=discord.Game(name="/setup • Elvis Setup"))
        if not self._guild_commands_synced:
            for guild in self.guilds:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                LOGGER.info("Đã đồng bộ %s command tức thời cho %s.", len(synced), guild.name)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            LOGGER.info("Đã xóa bộ command global để tránh hiển thị trùng lặp.")
            self._guild_commands_synced = True


def _is_owner(interaction: discord.Interaction, settings: Settings) -> bool:
    return interaction.user.id == settings.owner_user_id


def register_commands(bot: ElvisSetupBot) -> None:
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

    @bot.tree.command(name="xoa-kenh", description="Xóa toàn bộ channel và category trong server")
    @app_commands.guild_only()
    async def delete_channels(interaction: discord.Interaction) -> None:
        if not _is_owner(interaction, bot.settings):
            await interaction.response.send_message(
                "Công cụ này chỉ nhận lệnh từ chủ bot.", ephemeral=True
            )
            return
        guild = interaction.guild
        channel_count = len(guild.channels) if guild else 0
        embed = discord.Embed(
            title="Xóa toàn bộ kênh",
            description=(
                f"Server hiện có **{channel_count}** channel/category. "
                "Role và thành viên sẽ được giữ nguyên."
            ),
            colour=discord.Colour.red(),
        )
        embed.add_field(
            name="Cảnh báo",
            value="Tin nhắn trong các kênh đã xóa không thể khôi phục.",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=DeleteChannelsView(bot.settings.owner_user_id),
            ephemeral=True,
        )


def run() -> None:
    settings = Settings.from_env()
    report_writer = ReportWriter(ROOT_DIR)
    report_writer.configure_logging(settings.log_level)
    bot = ElvisSetupBot(settings)
    register_commands(bot)
    bot.run(settings.token, log_handler=None)
