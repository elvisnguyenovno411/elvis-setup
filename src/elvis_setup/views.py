from __future__ import annotations

import logging
import re
import unicodedata

import discord

from .models import CategorySpec, ServerTemplate
from .reporting import ReportWriter, SetupReport
from .setup_engine import SetupEngine

LOGGER = logging.getLogger(__name__)
BRAND_COLOR = discord.Colour.from_rgb(44, 62, 80)
_BOLD_ALPHANUMERIC = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗",
)


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


def parse_preserved_role_ids(raw_value: str) -> set[int]:
    """Đọc danh sách ID role phân cách bằng dấu phẩy; 0 nghĩa là không giữ role nào."""
    value = raw_value.strip()
    if value == "0":
        return set()
    if not value:
        raise ValueError("Hãy nhập ID role hoặc nhập 0.")

    result: set[int] = set()
    for raw_item in value.split(","):
        item = raw_item.strip()
        if item.startswith("<@&") and item.endswith(">"):
            item = item[3:-1]
        if not item.isdecimal() or int(item) <= 0:
            raise ValueError(f"`{raw_item.strip()}` không phải ID role hợp lệ.")
        result.add(int(item))
    return result


def parse_role_names(raw_value: str) -> list[str]:
    """Đọc tên role phân cách bằng dấu phẩy; số 0 vẫn là một tên role hợp lệ."""
    names: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_value.split(","):
        name = raw_item.strip()
        if not name:
            continue
        if len(name) > 100:
            raise ValueError(f"Tên role `{_short(name, 50)}` dài quá 100 ký tự.")
        normalized = name.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        names.append(name)

    if not names:
        raise ValueError("Hãy nhập ít nhất một tên role.")
    if len(names) > 50:
        raise ValueError("Mỗi lần chỉ có thể tạo tối đa 50 role.")
    return names


def stylize_game_name(game_name: str) -> str:
    """Đổi tên game sang kiểu chữ serif đậm đang dùng trong template."""
    compact = re.sub(r"\s+", "-", game_name.strip().upper()).strip("-")
    decomposed = unicodedata.normalize("NFD", compact)
    return decomposed.translate(_BOLD_ALPHANUMERIC)


def build_game_channel_names(game_name: str) -> tuple[str, str, str]:
    """Tạo tên category, text và voice đồng bộ với phong cách server."""
    styled = stylize_game_name(game_name)
    category_name = f"🎮┊『{styled}』"
    text_name = f"💬┊『𝐂𝐇𝐀𝐓-{styled}』"
    voice_name = f"🔊┊『𝐕𝐎𝐈𝐂𝐄-{styled}』"
    if any(len(name) > 100 for name in (category_name, text_name, voice_name)):
        raise ValueError(f"Tên game `{_short(game_name, 50)}` quá dài để tạo kênh Discord.")
    return category_name, text_name, voice_name


def parse_game_names(raw_value: str) -> list[str]:
    """Đọc danh sách game phân cách bằng dấu phẩy và loại tên trùng."""
    names: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_value.split(","):
        name = raw_item.strip()
        if not name:
            continue
        normalized = name.casefold()
        if normalized in seen:
            continue
        build_game_channel_names(name)
        seen.add(normalized)
        names.append(name)

    if not names:
        raise ValueError("Hãy nhập ít nhất một tên game.")
    if len(names) > 25:
        raise ValueError("Mỗi lần chỉ có thể tạo tối đa 25 chủ đề game.")
    return names


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
            if isinstance(channel, discord.TextChannel) and channel.name == "📋┊『𝐍𝐇𝐀̣̂𝐓-𝐊𝐘́』"
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
            if self.structure_only:
                button.label = "XÁC NHẬN THÊM TEMPLATE"
                button.style = discord.ButtonStyle.success
            else:
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
            embed.set_footer(text="Kênh cũ được giữ nguyên và đẩy xuống dưới; không tạo/xóa role.")
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
        name="Giữ nguyên server hiện tại",
        value=(
            "Bot **không xóa channel, category hoặc role hiện có** và không đặt permission riêng. "
            "Mọi kênh mới kế thừa quyền mặc định để bạn tự chỉnh."
        ),
        inline=False,
    )
    embed.add_field(
        name="Cách sắp xếp",
        value=(
            "Template mới sẽ được đưa lên đầu server theo đúng thứ tự. "
            "Các category và kênh cũ được giữ lại phía dưới."
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


class DeleteRolesModal(discord.ui.Modal):
    def __init__(self, owner_user_id: int) -> None:
        super().__init__(title="Xóa role có chọn lọc")
        self.owner_user_id = owner_user_id
        self.role_ids = discord.ui.TextInput(
            label="ID role muốn giữ (cách nhau bằng dấu phẩy)",
            placeholder="Ví dụ: 123456789, 987654321 — nhập 0 để xóa hết",
            default="0",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
        )
        self.add_item(self.role_ids)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Bạn không có quyền điều khiển công cụ xóa role này.", ephemeral=True
            )
            return
        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return

        try:
            preserved_ids = parse_preserved_role_ids(str(self.role_ids.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        roles_by_id = {role.id: role for role in guild.roles}
        missing_ids = sorted(preserved_ids - roles_by_id.keys())
        if missing_ids:
            missing_text = ", ".join(str(role_id) for role_id in missing_ids)
            await interaction.response.send_message(
                f"Không tìm thấy ID role trong server này: `{_short(missing_text, 900)}`.",
                ephemeral=True,
            )
            return

        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Bot thiếu quyền Manage Roles.", ephemeral=True
            )
            return

        deletable = [
            role
            for role in guild.roles
            if role.id != guild.default_role.id
            and not role.managed
            and role.position < me.top_role.position
            and role.id not in preserved_ids
        ]
        explicitly_preserved = [
            roles_by_id[role_id]
            for role_id in preserved_ids
            if role_id in roles_by_id
        ]
        protected = [
            role
            for role in guild.roles
            if role.id == guild.default_role.id
            or role.managed
            or role.position >= me.top_role.position
        ]

        preserved_text = (
            "\n".join(
                f"• `{role.name}` — `{role.id}`"
                for role in sorted(
                    explicitly_preserved,
                    key=lambda item: item.position,
                    reverse=True,
                )
            )
            if explicitly_preserved
            else "• Không giữ thêm role nào"
        )
        embed = discord.Embed(
            title="Xác nhận xóa role",
            description=(
                f"Sẽ xóa **{len(deletable)}** role mà bot có thể quản lý và giữ theo yêu cầu "
                f"**{len(explicitly_preserved)}** role."
            ),
            colour=discord.Colour.red(),
        )
        embed.add_field(
            name="Role bạn yêu cầu giữ",
            value=_short(preserved_text, 1000),
            inline=False,
        )
        embed.add_field(
            name="Tự động được bảo vệ",
            value=(
                f"{len(protected)} role hệ thống, role bot/tích hợp hoặc role ngang/cao hơn "
                "role cao nhất của bot sẽ không bị xóa."
            ),
            inline=False,
        )
        embed.add_field(
            name="Cảnh báo",
            value="Role đã xóa và quyền gắn với role đó không thể khôi phục tự động.",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=DeleteRolesView(self.owner_user_id, preserved_ids),
            ephemeral=True,
        )


class DeleteRolesView(OwnerView):
    def __init__(self, owner_user_id: int, preserved_ids: set[int] | None = None) -> None:
        super().__init__(owner_user_id)
        self.preserved_ids = frozenset(preserved_ids or set())
        self.stage = 1

    @discord.ui.button(label="Tôi hiểu, tiếp tục", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.stage == 1:
            self.stage = 2
            button.label = "XÁC NHẬN XÓA CÁC ROLE"
            await interaction.response.edit_message(view=self)
            return

        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Bot thiếu quyền Manage Roles.", ephemeral=True
            )
            return

        await interaction.response.edit_message(
            content="Đang xóa các role đã chọn…", embed=None, view=None
        )
        reason = "Elvis Setup: xóa role có chọn lọc theo yêu cầu của chủ bot"
        errors: list[str] = []
        deleted_count = 0
        roles = sorted(guild.roles, key=lambda role: role.position, reverse=True)
        for role in roles:
            if role.id == guild.default_role.id:
                continue
            if role.id in self.preserved_ids:
                continue
            if role.managed or role.position >= me.top_role.position:
                continue
            try:
                await role.delete(reason=reason)
                deleted_count += 1
            except discord.HTTPException as exc:
                errors.append(f"{role.name}: {exc}")

        if errors:
            LOGGER.error("Không thể xóa một số role: %s", "; ".join(errors))
            result = (
                f"Đã xóa **{deleted_count}** role, nhưng có **{len(errors)}** lỗi. "
                "Xem log trên máy để biết chi tiết."
            )
        else:
            result = (
                f"Đã xóa **{deleted_count}** role và giữ lại các ID bạn đã nhập. "
                "Role hệ thống, role bot/tích hợp và role cao hơn bot không bị ảnh hưởng."
            )
        await interaction.edit_original_response(content=result, embed=None, view=None)

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Đã hủy xóa role.", embed=None, view=None)


class CreateRolesModal(discord.ui.Modal):
    def __init__(self, owner_user_id: int) -> None:
        super().__init__(title="Tạo nhiều role")
        self.owner_user_id = owner_user_id
        self.role_names = discord.ui.TextInput(
            label="Tên role (cách nhau bằng dấu phẩy)",
            placeholder="Ví dụ: Thành viên, VIP, Khách, 0",
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True,
        )
        self.add_item(self.role_names)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Bạn không có quyền điều khiển công cụ tạo role này.", ephemeral=True
            )
            return
        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return

        try:
            role_names = parse_role_names(str(self.role_names.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Bot thiếu quyền Manage Roles.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        created: list[discord.Role] = []
        errors: list[str] = []
        reason = "Elvis Setup: tạo role theo yêu cầu của chủ bot"
        for role_name in role_names:
            try:
                role = await guild.create_role(
                    name=role_name,
                    permissions=discord.Permissions.none(),
                    reason=reason,
                )
                created.append(role)
            except discord.HTTPException as exc:
                errors.append(f"{role_name}: {exc}")

        created_text = (
            "\n".join(f"• {role.mention} — `{role.name}`" for role in created)
            if created
            else "• Không tạo được role nào"
        )
        embed = discord.Embed(
            title="Đã tạo role",
            description=f"Tạo thành công **{len(created)}/{len(role_names)}** role.",
            colour=discord.Colour.green() if not errors else discord.Colour.orange(),
        )
        embed.add_field(
            name="Danh sách",
            value=_short(created_text, 1000),
            inline=False,
        )
        embed.add_field(
            name="Quyền mặc định",
            value="Các role mới chưa có quyền đặc biệt; bạn có thể tự chỉnh trong Server Settings.",
            inline=False,
        )
        if errors:
            LOGGER.error("Không thể tạo một số role: %s", "; ".join(errors))
            embed.add_field(
                name="Không tạo được",
                value=_short("\n".join(f"• {error}" for error in errors), 1000),
                inline=False,
            )
        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class CreateGameChannelsModal(discord.ui.Modal):
    def __init__(self, owner_user_id: int) -> None:
        super().__init__(title="Tạo kênh theo chủ đề game")
        self.owner_user_id = owner_user_id
        self.game_names = discord.ui.TextInput(
            label="Tên game (cách nhau bằng dấu phẩy)",
            placeholder="Ví dụ: Minecraft, AOV, GTA V, Play Together",
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True,
        )
        self.add_item(self.game_names)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_user_id:
            await interaction.response.send_message(
                "Bạn không có quyền điều khiển công cụ tạo kênh game này.", ephemeral=True
            )
            return
        guild = interaction.guild
        if not isinstance(guild, discord.Guild):
            await interaction.response.send_message("Lệnh chỉ dùng trong server.", ephemeral=True)
            return

        try:
            game_names = parse_game_names(str(self.game_names.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "Bot thiếu quyền Manage Channels.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        reason = "Elvis Setup: tạo category và kênh theo chủ đề game"
        status_lines: list[str] = []
        errors: list[str] = []
        created_categories = 0
        created_channels = 0

        for game_name in game_names:
            category_name, text_name, voice_name = build_game_channel_names(game_name)
            category = discord.utils.get(guild.categories, name=category_name)
            game_created = 0
            try:
                if category is None:
                    category = await guild.create_category(category_name, reason=reason)
                    created_categories += 1
                    game_created += 1

                text_channel = discord.utils.get(category.text_channels, name=text_name)
                if text_channel is None:
                    await guild.create_text_channel(
                        text_name,
                        category=category,
                        topic=f"Kênh trò chuyện dành cho {game_name}",
                        reason=reason,
                    )
                    created_channels += 1
                    game_created += 1

                voice_channel = discord.utils.get(category.voice_channels, name=voice_name)
                if voice_channel is None:
                    await guild.create_voice_channel(
                        voice_name,
                        category=category,
                        reason=reason,
                    )
                    created_channels += 1
                    game_created += 1
            except discord.HTTPException as exc:
                errors.append(f"{game_name}: {exc}")
                status_lines.append(f"❌ **{game_name}** — chưa hoàn tất")
                continue

            if game_created:
                status_lines.append(f"✅ **{game_name}** — tạo {game_created} mục")
            else:
                status_lines.append(f"♻️ **{game_name}** — đã tồn tại đầy đủ")

        embed = discord.Embed(
            title="Đã tạo khu vực game",
            description=_short("\n".join(status_lines), 4000),
            colour=discord.Colour.green() if not errors else discord.Colour.orange(),
        )
        embed.add_field(name="Category mới", value=str(created_categories))
        embed.add_field(name="Kênh mới", value=str(created_channels))
        embed.add_field(
            name="Quyền truy cập",
            value="Các kênh mới kế thừa quyền mặc định của server để bạn tự chỉnh sau.",
            inline=False,
        )
        if errors:
            LOGGER.error("Không thể tạo một số khu vực game: %s", "; ".join(errors))
            embed.add_field(
                name="Lỗi",
                value=_short("\n".join(f"• {error}" for error in errors), 1000),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)
