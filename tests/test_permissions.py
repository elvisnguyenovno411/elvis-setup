import asyncio
from types import SimpleNamespace

from elvis_setup.models import CategorySpec, ChannelSpec, ServerTemplate
from elvis_setup.reporting import SetupReport
from elvis_setup.setup_engine import SetupEngine, channel_permission_for


def test_public_text_channel_allows_everyone_to_chat() -> None:
    spec = ChannelSpec(name="chat", kind="text", access="member")
    permission = channel_permission_for(spec)

    assert permission.view_channel is True
    assert permission.send_messages is True
    assert permission.embed_links is True


def test_read_only_channel_is_visible_but_cannot_be_written() -> None:
    spec = ChannelSpec(name="announcements", kind="text", access="member_read_only")
    permission = channel_permission_for(spec)

    assert permission.view_channel is True
    assert permission.send_messages is False


def test_core_channel_targets_everyone_instead_of_member_role() -> None:
    everyone = object()
    admin = object()
    member = object()
    engine = object.__new__(SetupEngine)
    engine.guild = SimpleNamespace(default_role=everyone)
    spec = ChannelSpec(name="chat", kind="text", access="member")

    overwrites = engine._overwrites(spec, admin, member, {}, ())

    assert everyone in overwrites
    assert member not in overwrites
    assert overwrites[everyone].view_channel is True


def test_topic_channel_remains_gated_by_interest_role() -> None:
    everyone = object()
    admin = object()
    member = object()
    interest = object()
    engine = object.__new__(SetupEngine)
    engine.guild = SimpleNamespace(default_role=everyone)
    spec = ChannelSpec(name="music", kind="text", access="member")

    overwrites = engine._overwrites(
        spec,
        admin,
        member,
        {"Mê Nhạc": interest},
        ("Mê Nhạc",),
    )

    assert overwrites[everyone].view_channel is False
    assert overwrites[interest].view_channel is True
    assert member not in overwrites


def test_structure_only_keeps_old_structure_and_moves_template_to_top() -> None:
    class ExistingResource:
        def __init__(self, name: str) -> None:
            self.name = name
            self.deleted = False

        async def delete(self, **_: object) -> None:
            self.deleted = True

    class FakeGuild:
        def __init__(self) -> None:
            self.owner_id = 123
            self.me = SimpleNamespace(
                guild_permissions=SimpleNamespace(administrator=True),
                top_role=object(),
            )
            self.channels = [ExistingResource("old-channel")]
            self.categories: list[object] = []
            self.roles = [ExistingResource("role-phai-duoc-giu")]
            self.created_kwargs: list[dict[str, object]] = []
            self.created_categories: list[object] = []

        async def create_category(self, name: str, **kwargs: object) -> object:
            self.created_kwargs.append(kwargs)
            category = SimpleNamespace(name=name, positions=[])

            async def edit(**edit_kwargs: object) -> None:
                category.positions.append(edit_kwargs["position"])

            category.edit = edit
            self.created_categories.append(category)
            return category

        async def create_text_channel(self, name: str, **kwargs: object) -> object:
            self.created_kwargs.append(kwargs)
            return SimpleNamespace(name=name)

    guild = FakeGuild()
    template = ServerTemplate(
        key="server",
        name="Server",
        description="",
        emoji="✨",
        color=0,
        categories=(
            CategorySpec(
                key="chat",
                name="│ CHAT ZONE",
                channels=(ChannelSpec(name="💬・MAIN-CHAT", kind="text", access="member"),),
            ),
            CategorySpec(
                key="voice",
                name="│ VOICE",
                channels=(ChannelSpec(name="🔊 Voice", kind="text", access="member"),),
            ),
        ),
    )
    report = SetupReport(1, "Test", "server-no-roles")
    engine = SetupEngine(guild, owner_user_id=123)  # type: ignore[arg-type]

    asyncio.run(engine.apply_structure_only(template, report))

    assert guild.channels[0].deleted is False
    assert guild.roles[0].deleted is False
    assert report.roles_created == []
    assert all("overwrites" not in kwargs for kwargs in guild.created_kwargs)
    assert guild.created_categories[0].positions == [0]
    assert guild.created_categories[1].positions == [1]
