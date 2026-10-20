from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord

from .models import CategorySpec, ChannelSpec, ServerTemplate
from .reporting import SetupReport

LOGGER = logging.getLogger(__name__)


def channel_permission_for(spec: ChannelSpec) -> discord.PermissionOverwrite:
    """Trả về quyền kênh dành cho nhóm người được phép truy cập."""
    if spec.kind == "voice":
        return discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
    if spec.access == "member_role_picker":
        return discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            add_reactions=True,
            embed_links=True,
            use_application_commands=True,
            use_external_apps=True,
        )
    if spec.access == "member_read_only":
        return discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            add_reactions=False,
        )
    return discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=True,
        add_reactions=True,
        attach_files=True,
        embed_links=True,
    )


@dataclass(slots=True)
class CreatedResources:
    channels: list[discord.abc.GuildChannel] = field(default_factory=list)
    categories: list[discord.CategoryChannel] = field(default_factory=list)
    roles: list[discord.Role] = field(default_factory=list)


class SetupEngine:
    def __init__(self, guild: discord.Guild, owner_user_id: int) -> None:
        self.guild = guild
        self.owner_user_id = owner_user_id
        self.created = CreatedResources()

    def validate_permissions(self) -> None:
        me = self.guild.me
        if me is None or not me.guild_permissions.administrator:
            raise PermissionError("Bot cần quyền Administrator để setup server.")
        if self.guild.owner_id != self.owner_user_id:
            LOGGER.warning(
                "Người cấu hình không phải server owner; OWNER_USER_ID vẫn được ưu tiên."
            )

    async def apply(
        self,
        base_template: ServerTemplate,
        selected_topics: list[ServerTemplate],
        report: SetupReport,
    ) -> None:
        self.validate_permissions()
        await self._purge_channels()
        await self._purge_roles()
        admin_role, member_role, interest_roles = await self._create_roles(report, selected_topics)

        owner = self.guild.get_member(self.owner_user_id)
        if owner is None:
            owner = await self.guild.fetch_member(self.owner_user_id)
        await owner.add_roles(admin_role, reason="Elvis Setup: cấp quyền quản trị cho chủ bot")

        categories = list(base_template.categories)
        base_keys = {category.key for category in base_template.categories}
        for topic in selected_topics:
            categories.extend(
                category for category in topic.categories if category.key not in base_keys
            )
        for category_spec in categories:
            await self._create_category(
                category_spec,
                admin_role,
                member_role,
                interest_roles,
                report,
            )

    async def apply_structure_only(
        self,
        template: ServerTemplate,
        report: SetupReport,
    ) -> None:
        """Dựng category/channel và giữ nguyên toàn bộ role cùng permission của server."""
        self.validate_permissions()
        await self._purge_channels()
        for category_spec in template.categories:
            await self._create_unmanaged_category(category_spec, report)

    async def _purge_channels(self) -> None:
        reason = "Elvis Setup: làm sạch server trước khi áp dụng template"
        for channel in list(self.guild.channels):
            if not isinstance(channel, discord.CategoryChannel):
                await channel.delete(reason=reason)
        for category in list(self.guild.categories):
            await category.delete(reason=reason)

    async def _purge_roles(self) -> None:
        reason = "Elvis Setup: làm sạch role trước khi áp dụng template"
        me = self.guild.me
        for role in reversed(self.guild.roles):
            if role.is_default() or role.managed or (me is not None and role >= me.top_role):
                continue
            await role.delete(reason=reason)

    async def _create_unmanaged_category(
        self,
        spec: CategorySpec,
        report: SetupReport,
    ) -> None:
        reason = "Elvis Setup: dựng cấu trúc để người dùng tự phân quyền"
        category = await self.guild.create_category(spec.name, reason=reason)
        self.created.categories.append(category)
        report.categories_created.append(category.name)

        for channel_spec in spec.channels:
            if channel_spec.kind == "voice":
                channel = await self.guild.create_voice_channel(
                    channel_spec.name,
                    category=category,
                    reason=reason,
                )
            else:
                channel = await self.guild.create_text_channel(
                    channel_spec.name,
                    category=category,
                    topic=channel_spec.topic,
                    reason=reason,
                )
            self.created.channels.append(channel)
            report.channels_created.append(channel.name)

    async def _create_roles(
        self,
        report: SetupReport,
        selected_topics: list[ServerTemplate],
    ) -> tuple[discord.Role, discord.Role, dict[str, discord.Role]]:
        member = await self.guild.create_role(
            name="Thành viên",
            colour=discord.Colour.from_rgb(149, 165, 166),
            permissions=discord.Permissions.none(),
            reason="Elvis Setup: tạo role Thành viên",
        )
        self.created.roles.append(member)
        report.roles_created.append(member.name)

        admin = await self.guild.create_role(
            name="Admin",
            colour=discord.Colour.from_rgb(52, 73, 94),
            permissions=discord.Permissions(administrator=True),
            reason="Elvis Setup: tạo role Admin",
        )
        self.created.roles.append(admin)
        report.roles_created.append(admin.name)

        interest_roles: dict[str, discord.Role] = {}
        for topic in selected_topics:
            for role_spec in topic.roles:
                if role_spec.name in interest_roles:
                    continue
                role = await self.guild.create_role(
                    name=role_spec.name,
                    colour=discord.Colour(role_spec.color),
                    permissions=discord.Permissions.none(),
                    reason="Elvis Setup: tạo role sở thích",
                )
                interest_roles[role.name] = role
                self.created.roles.append(role)
                report.roles_created.append(role.name)
        return admin, member, interest_roles

    async def _create_category(
        self,
        spec: CategorySpec,
        admin: discord.Role,
        member: discord.Role,
        interest_roles: dict[str, discord.Role],
        report: SetupReport,
    ) -> None:
        is_public_category = not spec.access_roles and any(
            channel.access != "admin" for channel in spec.channels
        )
        overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=is_public_category),
            admin: discord.PermissionOverwrite(view_channel=True),
        }
        for role_name in spec.access_roles:
            role = interest_roles.get(role_name)
            if role is None:
                raise ValueError(f"Category {spec.key} tham chiếu role chưa được tạo: {role_name}")
            overwrites[role] = discord.PermissionOverwrite(view_channel=True)
        category = await self.guild.create_category(spec.name, overwrites=overwrites)
        self.created.categories.append(category)
        report.categories_created.append(category.name)

        for channel_spec in spec.channels:
            channel = await self._create_channel(
                category,
                channel_spec,
                admin,
                member,
                interest_roles,
                spec.access_roles,
            )
            self.created.channels.append(channel)
            report.channels_created.append(channel.name)

    async def _create_channel(
        self,
        category: discord.CategoryChannel,
        spec: ChannelSpec,
        admin: discord.Role,
        member: discord.Role,
        interest_roles: dict[str, discord.Role],
        access_roles: tuple[str, ...],
    ) -> discord.abc.GuildChannel:
        overwrites = self._overwrites(spec, admin, member, interest_roles, access_roles)
        reason = "Elvis Setup: áp dụng template"
        if spec.kind == "voice":
            return await self.guild.create_voice_channel(
                spec.name,
                category=category,
                overwrites=overwrites,
                reason=reason,
            )
        return await self.guild.create_text_channel(
            spec.name,
            category=category,
            topic=spec.topic,
            overwrites=overwrites,
            reason=reason,
        )

    def _overwrites(
        self,
        spec: ChannelSpec,
        admin: discord.Role,
        member: discord.Role,
        interest_roles: dict[str, discord.Role],
        access_roles: tuple[str, ...],
    ) -> dict[discord.Role, discord.PermissionOverwrite]:
        overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            admin: discord.PermissionOverwrite(view_channel=True),
        }
        if spec.access == "admin":
            return overwrites
        # Kênh lõi mở trực tiếp cho @everyone để thành viên cũ không cần
        # được cấp role "Thành viên". Category sở thích vẫn khóa theo role.
        targets = [self.guild.default_role]
        if access_roles:
            targets = [interest_roles[name] for name in access_roles]
        permission = channel_permission_for(spec)
        for target in targets:
            overwrites[target] = permission
        return overwrites

    async def rollback(self) -> None:
        reason = "Elvis Setup: hoàn tác tài nguyên được tạo sau lỗi"
        for channel in reversed(self.created.channels):
            try:
                await channel.delete(reason=reason)
            except discord.HTTPException:
                LOGGER.exception("Không thể xóa kênh %s khi hoàn tác", channel.name)
        for category in reversed(self.created.categories):
            try:
                await category.delete(reason=reason)
            except discord.HTTPException:
                LOGGER.exception("Không thể xóa category %s khi hoàn tác", category.name)
        for role in reversed(self.created.roles):
            try:
                await role.delete(reason=reason)
            except discord.HTTPException:
                LOGGER.exception("Không thể xóa role %s khi hoàn tác", role.name)
