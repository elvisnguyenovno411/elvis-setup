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


class ElvisSetupBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        loader = TemplateLoader(ROOT_DIR / "templates")
        self.base_template = loader.load_base()
        self.templates = loader.load_all()
        self.report_writer = ReportWriter(ROOT_DIR)

    async def setup_hook(self) -> None:
        synced = await self.tree.sync()
        LOGGER.info("Đã đồng bộ %s slash command.", len(synced))

    async def on_ready(self) -> None:
        if self.user is not None:
            LOGGER.info("Đã đăng nhập: %s (%s)", self.user, self.user.id)
            await self.change_presence(activity=discord.Game(name="/setup • Elvis Setup"))


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
