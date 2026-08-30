from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .config import ROOT_DIR, Settings
from .reporting import ReportWriter
from .template_loader import TemplateLoader
from .views import BRAND_COLOR, TemplatePickerView

LOGGER = logging.getLogger(__name__)


class ElvisSetupBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.templates = TemplateLoader(ROOT_DIR / "templates").load_all()
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
            title="Elvis Setup",
            description=(
                "Chọn một template bên dưới. Bạn có thể dựng nhanh toàn bộ hoặc "
                "tùy chọn từng khu vực."
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
            view=TemplatePickerView(bot.settings.owner_user_id, bot.templates),
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


def run() -> None:
    settings = Settings.from_env()
    report_writer = ReportWriter(ROOT_DIR)
    report_writer.configure_logging(settings.log_level)
    bot = ElvisSetupBot(settings)
    register_commands(bot)
    bot.run(settings.token, log_handler=None)
