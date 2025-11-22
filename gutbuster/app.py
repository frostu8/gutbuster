import discord
import asyncio
import logging
import inspect
import re
from sqlalchemy.ext.asyncio import AsyncEngine
from discord import app_commands
from discord.ext import tasks
from gutbuster.servers import ServerWatcher
from typing import Awaitable, List, Any, Self, ClassVar, Optional

logger = logging.getLogger(__name__)


CAMEL_CASE_REGEX = re.compile(r"(?<!^)(?=[A-Z])")


def _to_kebab_case(text: str) -> str:
    return CAMEL_CASE_REGEX.sub("-", text).lower()


class ModuleMeta(type):
    """
    Metaclass for defining modules.
    """

    def __new__(cls, *args: Any, **kwargs: Any):
        name, bases, attrs = args

        try:
            group_name = kwargs.pop("name")
        except KeyError:
            group_name = _to_kebab_case(name)

        attrs["__group_name__"] = group_name
        attrs["__group_default_permissions__"] = kwargs.pop("default_permissions", None)

        # Register group information
        description = kwargs.pop("description", None)
        if description is None:
            description = inspect.cleandoc(attrs.get("__doc__", ""))

        attrs["__group_description__"] = description

        module_app_commands = {}

        new_cls = super().__new__(cls, name, bases, attrs, **kwargs)
        for base in reversed(new_cls.__mro__):
            for elem, value in base.__dict__.items():
                is_static_method = isinstance(value, staticmethod)

                if isinstance(value, (app_commands.Group, app_commands.Command)):
                    if is_static_method:
                        raise TypeError(
                            f"Command in method {base}.{elem!r} must not be staticmethod."
                        )

                    module_app_commands[elem] = value

        new_cls.__app_commands__ = list(module_app_commands.values())

        return new_cls


class Module(metaclass=ModuleMeta):
    """
    Compartmentalized commands.

    This is meant to be a lightweight form of discordpy's Cogs.
    """

    __app_commands__: List[app_commands.Command[Self, ..., Any]]
    __is_app_command_group__: ClassVar[bool] = False
    __app_commands_group__: Optional[app_commands.Group]
    __group_name__: str
    __group_description__: str
    __group_default_permissions__: Optional[discord.Permissions]

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        self = super().__new__(cls)

        if cls.__is_app_command_group__:
            group = app_commands.Group(
                name=cls.__group_name__,
                description=cls.__group_description__,
                parent=None,
                default_permissions=cls.__group_default_permissions__,
            )
        else:
            group = None

        self.__app_commands_group__ = group

        # Register application commands
        commands = []

        for command in cls.__app_commands__:
            copy = command._copy_with(parent=None, binding=self)

            if copy._attr:
                setattr(self, copy._attr, copy)

            commands.append(copy)

        self.__app_commands__ = commands
        if self.__app_commands_group__:
            self.__app_commands_group__.module = cls.__module__
            mapping = {cmd.name: cmd for cmd in commands}
            if len(mapping) > 25:
                raise TypeError(
                    "maximum number of application command children exceeded"
                )

            self.__app_commands_group__._children = mapping

        return self


class GroupModule(Module):
    __is_app_command_group__: ClassVar[bool] = True


class App(discord.Client):
    """
    Application.

    This sets up all the bot hooks, event listeners and Everything Else:tm: to
    make the thing work.
    """

    user: discord.ClientUser
    tree: app_commands.CommandTree

    db: AsyncEngine
    watcher: ServerWatcher

    modules: List[Module]

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)

        # Create an instance of a command tree, which will hold all of our
        # application commands.
        self.tree = app_commands.CommandTree(self)
        self.modules = []

    def add_module(self, module: Module):
        self.modules.append(module)

    async def setup_hook(self) -> None:
        # Connects to a database.
        # self.db = create_async_engine("sqlite+aiosqlite:///dev_gutbuster.sqlite")
        self.watcher = ServerWatcher(db=self.db)

        # Registers all modules.
        for module in self.modules:
            if module.__is_app_command_group__:
                if module.__app_commands_group__ is not None:
                    self.tree.add_command(module.__app_commands_group__)
            else:
                for command in module.__app_commands__:
                    self.tree.add_command(command)

        # Syncs the current commands with Discord
        await self.tree.sync()

        await self.watcher.load()
        self.knock_servers.start()

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user}")

    @tasks.loop(seconds=30.0)
    async def knock_servers(self) -> None:
        for server in self.watcher.iter():
            await server.knock()
