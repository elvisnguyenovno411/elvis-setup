from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord

from .models import CategorySpec, ChannelSpec, ServerTemplate
from .reporting import SetupReport

LOGGER = logging.getLogger(__name__)


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
        await self._purge_existing()
        admin_role, member_role = await self._create_roles(report)

        categories = list(base_template.categories)
        base_keys = {category.key for category in base_template.categories}
        for topic in selected_topics:
            categories.extend(
                category for category in topic.categories if category.key not in base_keys
            )
        for category_spec in categories:
            await self._create_category(category_spec, admin_role, member_role, report)

        owner = self.guild.get_member(self.owner_user_id)
        if owner is None:
            owner = await self.guild.fetch_member(self.owner_user_id)
        await owner.add_roles(admin_role, reason="Elvis Setup: cấp quyền quản trị cho chủ bot")

    async def _purge_existing(self) -> None:
        reason = "Elvis Setup: làm sạch server trước khi áp dụng template"
        for channel in list(self.guild.channels):
            if not isinstance(channel, discord.CategoryChannel):
                await channel.delete(reason=reason)
        for category in list(self.guild.categories):
            await category.delete(reason=reason)

        me = self.guild.me
        for role in reversed(self.guild.roles):
            if role.is_default() or role.managed or (me is not None and role >= me.top_role):
                continue
            await role.delete(reason=reason)

    async def _create_roles(self, report: SetupReport) -> tuple[discord.Role, discord.Role]:
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
        return admin, member

    async def _create_category(
        self,
        spec: CategorySpec,
        admin: discord.Role,
        member: discord.Role,
        report: SetupReport,
    ) -> None:
        overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            admin: discord.PermissionOverwrite(view_channel=True),
        }
        category = await self.guild.create_category(spec.name, overwrites=overwrites)
        self.created.categories.append(category)
        report.categories_created.append(category.name)

        for channel_spec in spec.channels:
            channel = await self._create_channel(category, channel_spec, admin, member)
            self.created.channels.append(channel)
            report.channels_created.append(channel.name)

    async def _create_channel(
        self,
        category: discord.CategoryChannel,
        spec: ChannelSpec,
        admin: discord.Role,
        member: discord.Role,
    ) -> discord.abc.GuildChannel:
        overwrites = self._overwrites(spec, admin, member)
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
    ) -> dict[discord.Role, discord.PermissionOverwrite]:
        overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            admin: discord.PermissionOverwrite(view_channel=True),
        }
        if spec.access == "admin":
            return overwrites
        if spec.kind == "voice":
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True
            )
        elif spec.access == "member_read_only":
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=False,
                add_reactions=False,
            )
        else:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                add_reactions=True,
                attach_files=True,
                embed_links=True,
            )
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
