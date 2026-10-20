from __future__ import annotations

import logging

import discord

from .models import CategorySpec, ServerTemplate
from .reporting import ReportWriter, SetupReport
from .setup_engine import SetupEngine

LOGGER = logging.getLogger(__name__)
BRAND_COLOR = discord.Colour.from_rgb(44, 62, 80)


def _short(text: str, limit: int = 100) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def parse_preserved_channel_ids(raw_value: str) -> set[int]:
    """Đọc danh sách ID phân cách bằng dấu phẩy; 0 nghĩa là không giữ kênh nào."""
    value = raw_value.strip()
    if value == "0":
        return set()
    if not value:
        raise ValueError("Hãy nhập ID kênh hoặc nhập 0.")

    result: set[int] = set()
    for raw_item in value.split(","):
        item = raw_item.strip()
        if item.startswith("<#") and item.endswith(">"):
            item = item[2:-1]
        if not item.isdecimal() or int(item) <= 0:
            raise ValueError(f"`{raw_item.strip()}` không phải ID kênh hợp lệ.")
        result.add(int(item))
    return result


def expand_preserved_channel_ids(guild: discord.Guild, requested_ids: set[int]) -> set[int]:
    """Giữ category cha của kênh, hoặc toàn bộ con khi người dùng giữ category."""
    preserved_ids = set(requested_ids)
    for category in guild.categories:
        if category.id in requested_ids:
            preserved_ids.update(channel.id for channel in category.channels)
    for channel in guild.channels:
        category_id = getattr(channel, "category_id", None)
        if channel.id in requested_ids and category_id is not None:
            preserved_ids.add(category_id)
    return preserved_ids


def _topic_categories(
    base_template: ServerTemplate, topics: list[ServerTemplate]
) -> list[CategorySpec]:
    base_keys = {category.key for category in base_template.categories}
    result: list[CategorySpec] = []
    for topic in topics:
        result.extend(category for category in topic.categories if category.key not in base_keys)
    return result


async def _send_setup_result(
    interaction: discord.Interaction,
    engine: SetupEngine,
    *,
    embed: discord.Embed,
    report_path,
    view: discord.ui.View | None = None,
) -> None:
    log_channel = next(
        (
            channel
            for channel in engine.created.channels
            if isinstance(channel, discord.TextChannel) and channel.name == "📋・nhat-ky"
        ),
        None,
    )
    try:
        if log_channel is not None:
            await log_channel.send(
                content=interaction.user.mention,
                embed=embed,
                view=view,
                file=discord.File(report_path),
            )
        else:
            await interaction.user.send(
                embed=embed,
                view=view,
                file=discord.File(report_path),
            )
    except discord.HTTPException:
        LOGGER.exception("Không thể gửi kết quả setup trong Discord; báo cáo vẫn lưu trên máy.")


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


class TopicSelect(discord.ui.Select):
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
            placeholder="Chọn một hoặc nhiều chủ đề…",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, TopicPickerView)
        view.selected_keys = set(self.values)
        chosen = [self.templates[key].name for key in self.values]
        embed = view.build_embed(f"Đã chọn: **{', '.join(chosen)}**")
        await interaction.response.edit_message(embed=embed, view=view)


class TopicPickerView(OwnerView):
    def __init__(
        self,
        owner_user_id: int,
        base_template: ServerTemplate,
        templates: dict[str, ServerTemplate],
    ) -> None:
        super().__init__(owner_user_id)
        self.base_template = base_template
        self.templates = templates
        self.selected_keys: set[str] = set()
        self.add_item(TopicSelect(templates))

    def build_embed(self, selection_text: str | None = None) -> discord.Embed:
        core = "\n".join(f"• {category.name}" for category in self.base_template.categories)
        embed = discord.Embed(
            title="Elvis Setup — Chọn chủ đề",
            description=(
                "Mỗi chủ đề được chọn sẽ tạo **một category riêng**. "
                "Chủ đề không chọn sẽ không được tạo."
            ),
            colour=BRAND_COLOR,
        )
        embed.add_field(name="Luôn được tạo", value=core, inline=False)
        if selection_text:
            embed.add_field(name="Lựa chọn hiện tại", value=selection_text, inline=False)
        embed.set_footer(text="Tùy chọn • Tất cả chủ đề • Chỉ mặc định")
        return embed

    @discord.ui.button(label="Setup tùy chọn", style=discord.ButtonStyle.primary, row=1)
    async def custom(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.selected_keys:
            await interaction.response.send_message(
                "Hãy chọn ít nhất một chủ đề trong danh sách.", ephemeral=True
            )
            return
        topics = [self.templates[key] for key in self.templates if key in self.selected_keys]
        await show_confirmation(interaction, self.owner_user_id, self.base_template, topics)

    @discord.ui.button(label="Tất cả chủ đề", style=discord.ButtonStyle.secondary, row=1)
    async def all_topics(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_confirmation(
            interaction,
            self.owner_user_id,
            self.base_template,
            list(self.templates.values()),
        )

    @discord.ui.button(label="Chỉ mặc định", style=discord.ButtonStyle.secondary, row=1)
    async def base_only(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await show_confirmation(interaction, self.owner_user_id, self.base_template, [])

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy setup.", embed=None, view=None)


async def show_confirmation(
    interaction: discord.Interaction,
    owner_user_id: int,
    base_template: ServerTemplate,
    topics: list[ServerTemplate],
) -> None:
    topic_categories = _topic_categories(base_template, topics)
    core_lines = [
        f"• {category.name} — {len(category.channels)} kênh"
        for category in base_template.categories
    ]
    topic_lines = [
        f"• {category.name} — {len(category.channels)} kênh" for category in topic_categories
    ]
    description = "**Category mặc định**\n" + "\n".join(core_lines)
    description += "\n\n**Category chủ đề**\n"
    description += "\n".join(topic_lines) if topic_lines else "• Không chọn"

    embed = discord.Embed(
        title="Xem trước cấu trúc server",
        description=description,
        colour=BRAND_COLOR,
    )
    interest_role_names = [role.name for topic in topics for role in topic.roles]
    role_text = ", ".join(["Admin", "Thành viên", *interest_role_names])
    embed.add_field(name="Role được tạo", value=role_text, inline=False)
    embed.add_field(
        name="Cảnh báo",
        value=(
            "Toàn bộ category, channel và role cũ mà bot có thể quản lý sẽ bị xóa. "
            "Tin nhắn trong các kênh cũ không thể khôi phục."
        ),
        inline=False,
    )
    await interaction.response.edit_message(
        embed=embed,
        view=ConfirmView(owner_user_id, base_template, topics),
    )


class ConfirmView(OwnerView):
    def __init__(
        self,
        owner_user_id: int,
        base_template: ServerTemplate,
        topics: list[ServerTemplate],
        *,
        structure_only: bool = False,
    ) -> None:
        super().__init__(owner_user_id)
        self.base_template = base_template
        self.topics = topics
        self.structure_only = structure_only
        self.stage = 1

    @discord.ui.button(label="Tôi hiểu, tiếp tục", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.stage == 1:
            self.stage = 2
            button.label = "XÁC NHẬN XÓA VÀ SETUP"
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
        engine = SetupEngine(guild, self.owner_user_id)
        topic_keys = [topic.key for topic in self.topics]
        report = SetupReport(
            guild.id,
            guild.name,
            "server-no-roles"
            if self.structure_only
            else (",".join(topic_keys) if topic_keys else "base-only"),
        )
        writer: ReportWriter = interaction.client.report_writer  # type: ignore[attr-defined]

        try:
            if self.structure_only:
                await engine.apply_structure_only(self.base_template, report)
            else:
                await engine.apply(self.base_template, self.topics, report)
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
            await _send_setup_result(
                interaction,
                engine,
                embed=embed,
                view=FailureView(self.owner_user_id, engine),
                report_path=report_path,
            )
            return

        report.finish("success")
        report_path = writer.save(report)
        topic_names = (
            "Mẫu cộng đồng không role"
            if self.structure_only
            else (", ".join(topic.name for topic in self.topics) or "Chỉ mặc định")
        )
        embed = discord.Embed(
            title="Setup hoàn tất",
            description=f"Chủ đề đã áp dụng: **{topic_names}**.",
            colour=discord.Colour.green(),
        )
        embed.add_field(name="Category", value=str(len(report.categories_created)))
        embed.add_field(name="Kênh", value=str(len(report.channels_created)))
        embed.add_field(name="Role", value=str(len(report.roles_created)))
        if self.structure_only:
            embed.set_footer(text="Không tạo/xóa role và không đặt permission riêng.")
        else:
            embed.set_footer(text="Kênh chung mở cho @everyone; role Thành viên là tùy chọn.")
        await _send_setup_result(
            interaction,
            engine,
            embed=embed,
            report_path=report_path,
        )


async def show_structure_confirmation(
    interaction: discord.Interaction,
    owner_user_id: int,
    template: ServerTemplate,
) -> None:
    lines = [
        f"• {category.name} — {len(category.channels)} kênh" for category in template.categories
    ]
    embed = discord.Embed(
        title="Xem trước — Làm server không role",
        description="\n".join(lines),
        colour=BRAND_COLOR,
    )
    embed.add_field(
        name="Role và quyền",
        value=(
            "Bot **không tạo, không xóa role** và **không đặt permission riêng**. "
            "Mọi kênh mới kế thừa quyền mặc định để bạn tự chỉnh."
        ),
        inline=False,
    )
    embed.add_field(
        name="Cảnh báo",
        value=(
            "Toàn bộ category và channel cũ sẽ bị xóa. "
            "Tin nhắn trong các kênh cũ không thể khôi phục."
        ),
        inline=False,
    )
    await interaction.response.send_message(
        embed=embed,
        view=ConfirmView(
            owner_user_id,
            template,
            [],
            structure_only=True,
        ),
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


class DeleteChannelsModal(discord.ui.Modal):
    def __init__(self, owner_user_id: int) -> None:
        super().__init__(title="Xóa kênh có chọn lọc")
        self.owner_user_id = owner_user_id
        self.channel_ids = discord.ui.TextInput(
            label="ID muốn giữ (cách nhau bằng dấu phẩy)",
            placeholder="Ví dụ: 123456789, 987654321 — nhập 0 để xóa hết",
            default="0",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
        )
        self.add_item(self.channel_ids)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Bạn không có quyền điều khiển công cụ xóa kênh này.", ephemeral=True
            )
            return
        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return

        try:
            requested_ids = parse_preserved_channel_ids(str(self.channel_ids.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        channels_by_id = {channel.id: channel for channel in guild.channels}
        missing_ids = sorted(requested_ids - channels_by_id.keys())
        if missing_ids:
            missing_text = ", ".join(str(channel_id) for channel_id in missing_ids)
            await interaction.response.send_message(
                f"Không tìm thấy ID trong server này: `{_short(missing_text, 900)}`.",
                ephemeral=True,
            )
            return

        preserved_ids = expand_preserved_channel_ids(guild, requested_ids)
        preserved = [channel for channel in guild.channels if channel.id in preserved_ids]
        preserved_text = (
            "\n".join(f"• `{channel.name}` — `{channel.id}`" for channel in preserved)
            if preserved
            else "• Không giữ kênh nào"
        )
        delete_count = len(guild.channels) - len(preserved)
        embed = discord.Embed(
            title="Xác nhận xóa kênh",
            description=(
                f"Sẽ xóa **{delete_count}** channel/category và giữ lại "
                f"**{len(preserved)}**. Role cùng thành viên không bị ảnh hưởng."
            ),
            colour=discord.Colour.red(),
        )
        embed.add_field(
            name="Được giữ lại",
            value=_short(preserved_text, 1000),
            inline=False,
        )
        embed.add_field(
            name="Cảnh báo",
            value="Tin nhắn trong các kênh bị xóa không thể khôi phục.",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=DeleteChannelsView(self.owner_user_id, preserved_ids),
            ephemeral=True,
        )


class DeleteChannelsView(OwnerView):
    def __init__(self, owner_user_id: int, preserved_ids: set[int] | None = None) -> None:
        super().__init__(owner_user_id)
        self.preserved_ids = frozenset(preserved_ids or set())
        self.stage = 1

    @discord.ui.button(label="Tôi hiểu, tiếp tục", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.stage == 1:
            self.stage = 2
            button.label = "XÁC NHẬN XÓA CÁC KÊNH"
            await interaction.response.edit_message(view=self)
            return

        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "Bot thiếu quyền Manage Channels.", ephemeral=True
            )
            return

        await interaction.response.edit_message(
            content="Đang xóa các kênh đã chọn…", embed=None, view=None
        )
        reason = "Elvis Setup: xóa kênh có chọn lọc theo yêu cầu của chủ bot"
        errors: list[str] = []
        deleted_count = 0
        for channel in list(guild.channels):
            if isinstance(channel, discord.CategoryChannel):
                continue
            if channel.id in self.preserved_ids:
                continue
            try:
                await channel.delete(reason=reason)
                deleted_count += 1
            except discord.HTTPException as exc:
                errors.append(f"{channel.name}: {exc}")
        for category in list(guild.categories):
            if category.id in self.preserved_ids:
                continue
            try:
                await category.delete(reason=reason)
                deleted_count += 1
            except discord.HTTPException as exc:
                errors.append(f"{category.name}: {exc}")

        try:
            if errors:
                LOGGER.error("Không thể xóa một số kênh: %s", "; ".join(errors))
                await interaction.user.send(
                    f"Đã xóa phần lớn kênh, nhưng có {len(errors)} lỗi. Xem log trên máy.",
                )
            else:
                await interaction.user.send(
                    f"Đã xóa **{deleted_count}** channel/category và giữ lại "
                    f"**{len(self.preserved_ids)}**. Role vẫn được giữ nguyên.",
                )
        except discord.HTTPException:
            LOGGER.exception("Không thể gửi DM kết quả xóa kênh.")

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy xóa kênh.", embed=None, view=None)
