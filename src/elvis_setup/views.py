from __future__ import annotations

import logging
from collections.abc import Iterable

import discord

from .models import CategorySpec, ServerTemplate
from .reporting import ReportWriter, SetupReport
from .setup_engine import SetupEngine

LOGGER = logging.getLogger(__name__)
BRAND_COLOR = discord.Colour.from_rgb(44, 62, 80)


def _short(text: str, limit: int = 100) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def template_embed(template: ServerTemplate) -> discord.Embed:
    channel_count = sum(len(category.channels) for category in template.categories)
    embed = discord.Embed(
        title=f"{template.emoji} {template.name}",
        description=template.description,
        colour=discord.Colour(template.color),
    )
    embed.add_field(name="Danh mục", value=str(len(template.categories)))
    embed.add_field(name="Kênh", value=str(channel_count))
    embed.add_field(name="Quyền", value="Admin / Thành viên")
    embed.set_footer(text="Chọn Quick Setup hoặc Custom Setup để tiếp tục")
    return embed


class OwnerView(discord.ui.View):
    def __init__(self, owner_user_id: int, *, timeout: float = 300) -> None:
        super().__init__(timeout=timeout)
        self.owner_user_id = owner_user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_user_id:
            return True
        await interaction.response.send_message(
            "Bạn không có quyền điều khiển công cụ setup này.", ephemeral=True
        )
        return False


class TemplateSelect(discord.ui.Select):
    def __init__(self, templates: dict[str, ServerTemplate]) -> None:
        self.templates = templates
        options = [
            discord.SelectOption(
                label=_short(template.name),
                value=key,
                description=_short(template.description),
                emoji=template.emoji,
            )
            for key, template in templates.items()
        ]
        super().__init__(
            placeholder="Chọn chủ đề server…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        template = self.templates[self.values[0]]
        view = ModeView(self.view.owner_user_id, template)  # type: ignore[union-attr]
        await interaction.response.edit_message(embed=template_embed(template), view=view)


class TemplatePickerView(OwnerView):
    def __init__(self, owner_user_id: int, templates: dict[str, ServerTemplate]) -> None:
        super().__init__(owner_user_id)
        self.add_item(TemplateSelect(templates))


class ModeView(OwnerView):
    def __init__(self, owner_user_id: int, template: ServerTemplate) -> None:
        super().__init__(owner_user_id)
        self.template = template

    @discord.ui.button(label="Quick Setup", style=discord.ButtonStyle.primary)
    async def quick(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_confirmation(interaction, self.owner_user_id, self.template, None)

    @discord.ui.button(label="Custom Setup", style=discord.ButtonStyle.secondary)
    async def custom(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        view = CategoryPickerView(self.owner_user_id, self.template)
        embed = discord.Embed(
            title="Chọn khu vực cần tạo",
            description=("Chọn một hoặc nhiều category. Các category bắt buộc sẽ luôn được tạo."),
            colour=BRAND_COLOR,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy setup.", embed=None, view=None)


class CategorySelect(discord.ui.Select):
    def __init__(self, template: ServerTemplate) -> None:
        self.template = template
        selectable = [category for category in template.categories if not category.required]
        options = [
            discord.SelectOption(
                label=_short(category.name),
                value=category.key,
                description=f"{len(category.channels)} kênh",
            )
            for category in selectable
        ]
        super().__init__(
            placeholder="Chọn category…",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, CategoryPickerView)
        view.selected_keys = set(self.values)
        await interaction.response.defer()


class CategoryPickerView(OwnerView):
    def __init__(self, owner_user_id: int, template: ServerTemplate) -> None:
        super().__init__(owner_user_id)
        self.template = template
        self.selected_keys: set[str] = set()
        self.add_item(CategorySelect(template))

    @discord.ui.button(label="Xem trước", style=discord.ButtonStyle.primary, row=1)
    async def preview(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.selected_keys:
            await interaction.response.send_message(
                "Hãy chọn ít nhất một category.", ephemeral=True
            )
            return
        await show_confirmation(interaction, self.owner_user_id, self.template, self.selected_keys)

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy setup.", embed=None, view=None)


def _selected_categories(
    template: ServerTemplate, selected_keys: set[str] | None
) -> Iterable[CategorySpec]:
    if selected_keys is None:
        return template.categories
    return (
        category
        for category in template.categories
        if category.required or category.key in selected_keys
    )


async def show_confirmation(
    interaction: discord.Interaction,
    owner_user_id: int,
    template: ServerTemplate,
    selected_keys: set[str] | None,
) -> None:
    categories = list(_selected_categories(template, selected_keys))
    lines = [f"• {category.name} — {len(category.channels)} kênh" for category in categories]
    embed = discord.Embed(
        title="Xem trước cấu trúc server",
        description="\n".join(lines),
        colour=discord.Colour(template.color),
    )
    embed.add_field(name="Role", value="Admin, Thành viên", inline=False)
    embed.add_field(
        name="Cảnh báo",
        value=(
            "Toàn bộ category, channel và role cũ mà bot có thể quản lý sẽ bị xóa. "
            "Tin nhắn trong các kênh cũ không thể khôi phục."
        ),
        inline=False,
    )
    view = ConfirmView(owner_user_id, template, selected_keys)
    await interaction.response.edit_message(embed=embed, view=view)


class ConfirmView(OwnerView):
    def __init__(
        self,
        owner_user_id: int,
        template: ServerTemplate,
        selected_keys: set[str] | None,
    ) -> None:
        super().__init__(owner_user_id)
        self.template = template
        self.selected_keys = selected_keys
        self.stage = 1

    @discord.ui.button(label="Tôi hiểu, tiếp tục", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.stage == 1:
            self.stage = 2
            button.label = "XÁC NHẬN XÓA VÀ SETUP"
            button.style = discord.ButtonStyle.danger
            await interaction.response.edit_message(view=self)
            return
        await self._execute(interaction)

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy setup.", embed=None, view=None)

    async def _execute(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Đang setup server…",
                description="Vui lòng chờ. Không tắt bot trong quá trình này.",
                colour=BRAND_COLOR,
            ),
            view=None,
        )
        bot = interaction.client
        engine = SetupEngine(guild, self.owner_user_id)
        report = SetupReport(guild.id, guild.name, self.template.key)
        writer: ReportWriter = bot.report_writer  # type: ignore[attr-defined]

        try:
            await engine.apply(self.template, self.selected_keys, report)
        except Exception as exc:  # Discord/API failures must be reported to the owner.
            LOGGER.exception("Setup thất bại")
            report.errors.append(f"{type(exc).__name__}: {exc}")
            report.finish("failed")
            report_path = writer.save(report)
            embed = discord.Embed(
                title="Setup chưa hoàn tất",
                description=f"```{_short(str(exc), 900)}```",
                colour=discord.Colour.red(),
            )
            embed.add_field(
                name="Bạn muốn xử lý phần đã tạo?",
                value="Chọn Giữ lại hoặc Hoàn tác.",
                inline=False,
            )
            await interaction.followup.send(
                embed=embed,
                view=FailureView(self.owner_user_id, engine),
                file=discord.File(report_path),
                ephemeral=True,
            )
            return

        report.finish("success")
        report_path = writer.save(report)
        embed = discord.Embed(
            title="Setup hoàn tất",
            description=f"Đã áp dụng template **{self.template.name}**.",
            colour=discord.Colour.green(),
        )
        embed.add_field(name="Category", value=str(len(report.categories_created)))
        embed.add_field(name="Kênh", value=str(len(report.channels_created)))
        embed.add_field(name="Role", value=str(len(report.roles_created)))
        embed.set_footer(text="Hãy cấu hình bot auto-role bên ngoài cho role Thành viên.")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(report_path),
            ephemeral=True,
        )


class FailureView(OwnerView):
    def __init__(self, owner_user_id: int, engine: SetupEngine) -> None:
        super().__init__(owner_user_id)
        self.engine = engine

    @discord.ui.button(label="Giữ lại", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="Đã giữ lại những tài nguyên tạo thành công.", embed=None, view=None
        )

    @discord.ui.button(label="Hoàn tác", style=discord.ButtonStyle.danger)
    async def rollback(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.engine.rollback()
        await interaction.edit_original_response(
            content="Đã xóa các tài nguyên mới tạo trong phiên setup lỗi.", embed=None, view=None
        )
