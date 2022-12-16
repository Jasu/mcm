from aiohttp import ClientSession
from .cache import *
import asyncio
import os.path
from .utils import commas, spaces, console, Field, Fields, print, pipes, Subfields, commas, Styles, Syms
from .recipematch import *
from functools import partial
from .mcdata import *
import json
from rich.text import Text
from urllib.parse import quote
from typing import Callable, Iterable
from dataclasses import dataclass, field
from .serialize import deserialize, serialize, serialize_by_type
from hashlib import md5
from xdg import xdg_cache_home
from os import makedirs


KeyIn = Key|str

@dataclass(slots=True)
class FnInfo:
    is_static: bool
    cls: str
    method: str
    return_type: str
    param_types: list[str]

    def __rich__(self):
        result = spaces(Text.styled(self.return_type, Styles.orange),
                        Text.styled(self.cls, Styles.cyan) + Syms.dot + Text.styled(self.method, Styles.green_bold),
                        Syms.lparen,
                        commas(self.param_types, style=Styles.orange),
                        Syms.rparen)
        if self.is_static: return Text.styled("static ", Styles.grey_italic) + result
        return result
    def __str__(self): return self.__rich__().plain()

@dataclass(slots=True)
class EventListener:
    type: str
    string: str
    method: FnInfo|None = None

    @property
    def methodstr(self): return str(self.method) if self.method else ""
    @property
    def methodrich(self): return self.method.__rich__() if self.method else Text()

    FIELDS = Fields(Field('Type', 'type', 't'), Field('String', 'string', 'str', 's'), Field('Method', 'methodrich', 'method', 'm'))

@dataclass(slots=True)
class PurkkaConnection:
    cache_parent: ClassVar[CacheFileManager|None] = None

    @classmethod
    def get_cache_parent(cls):
        if cls.cache_parent is None:
            cls.cache_parent = CacheFileManager.root().child_hashed('purkka')
        return cls.cache_parent

    base_url: str
    session: ClientSession|None = field(default=None, init=False)
    cache: DirBackedJsonCache = field(init=False)

    def __post_init__(self):
        self.session = ClientSession(self.base_url)
        self.cache = DirBackedJsonCache(self.get_cache_parent().child_hashed(self.base_url))

    async def get_json(self, path: str):
        async with self.session.get(path) as res:
            return await res.json()

    async def get_registry_keys(self, registry: KeyIn):
        return list(map(Key, await self.get_json(f'/registries/{quote(str(registry))}')))

    async def get_tag_contents(self, registry: KeyIn, tag: KeyIn):
        assert self.session
        return list(map(Key, await self.get_json(f'/registries/{quote(str(registry))}/tags/{quote(str(tag))}')))

    async def close(self):
        self.cache.persist()
        if self.session:
            session = self.session
            self.session = None
            await session.close()

@dataclass(slots=True)
class TagResolver:
    purkka: PurkkaConnection
    registry: object
    waits: set[Tag] = field(default_factory=set, init=False)
    def wait_for(self, tag: Tag):
        assert(isinstance(tag.content, Task))
        self.waits.add(tag)

    async def do_resolve(self, tag: Tag):
        content = frozenset(await self.purkka.get_tag_contents(self.registry.key, str(tag.key)))
        tag.content = content
        return content

    def get_tag(self, key: KeyIn):
        return self.registry.get_tag(key)
    def resolve(self, tag: Tag):
        assert(self.purkka)
        assert(self.registry)
        self.waits.add(tag)
        tag.content = asyncio.create_task(self.do_resolve(tag))
    async def apply(self):
        if not self.waits: return
        await asyncio.gather(*[tag.content for tag in self.waits])

@dataclass(slots=True)
class Registry:
    purkka: PurkkaConnection
    key: Key
    tags: dict[Key, Tag] = field(default_factory=dict, init=False)
    all_loaded: bool = field(default=False, init=False)

    async def load_keys(self):
        if self.all_loaded:
            return
        keys = await self.purkka.get_registry_keys(self.key)
        for k in keys:
            if k not in seelf.tags: self.tags[k] = Tag(k)

    async def get_keys(self):
        await self.load_keys()
        return sorted(list(self.tags.keys()))

    async def get_tags(self):
        await self.load_keys()
        return sorted(list(self.tags.values()))

    def get_tag(self, key: KeyIn):
        key = Key(key)
        if result := self.tags.get(key):
            return result
        if self.all_loaded: raise KeyError(f'Tag {key} does not exist')
        result = Tag(key)
        self.tags[key] = result
        return result

    async def resolve_tag(self, tag: Tag):
        if tag.is_resolved: return tag
        resolver = self.get_resolver()
        tag.resolve(resolver)
        await resolver.apply()
        return tag
    
    async def get_tag_with_content(self, key: KeyIn):
        tag = self.get_tag(key)
        return await self.resolve_tag(tag)

    def get_resolver(self):
        assert(self.purkka)
        return TagResolver(self.purkka, self)

@dataclass(slots=True)
class PurkkaCommonClient:
    connection: PurkkaConnection

    async def get_event_listeners(self, event: str):
        if not event.startswith('net.minecraftforge.'):
            event = f'net.minecraftforge.{event}'
        result = await self.connection.get_json(f'/event/{quote(event)}/listeners')
        return deserialize(list[EventListener], result)

    registries: dict[Key, Registry] = field(default_factory=dict, init=False)
    items: dict[Key, Item]|None = field(default=None, init=False)

    def get_registry(self, key: KeyIn):
        assert(self.connection)
        key = Key(key)
        if result := self.registries.get(key): return result
        result = Registry(self.connection, key)
        self.registries[key] = result
        return result

    async def get_all_items(self):
        if self.items is None:
            self.items = {k: deserialize(Item, v) for k, v in (await self.connection.get_json('/items')).items()}
        return self.items

@dataclass(slots=True)
class PurkkaServerClient:
    connection: PurkkaConnection

    recipe_types: dict[str, RecipeType] = field(init=False, default=None)

    async def initialize_recipe_types(self):
        if self.recipe_types is None:
            self.recipe_types = {
                k: RecipeType.deserialize(v)
                for k,v in (await self.connection.get_json('/recipe-types')).items()
            }

    async def get_all_recipes(self):
        await self.initialize_recipe_types()
        json = await self.connection.get_json('/recipes')
        return list(map(self.deserialize_recipe, json))

    def deserialize_recipe(self, recipe_json):
        r = deserialize(Recipe, recipe_json)
        r.recipe_type = self.recipe_types[r.type]
        return r


@dataclass(slots=True)
class PurkkaClientClient:
    connection: PurkkaConnection
    translation_cache: dict[str, str] = field(init=False)

    def __post_init__(self):
        self.translation_cache = self.connection.cache.get('translation', {})

    async def translate_string(self, string: str):
        if (t := self.translation_cache.get(string)) is not None:
            return t
        t = await self.connection.get_json(f'/translate/{quote(string)}')
        self.translation_cache[string] = t
        self.connection.cache.put('translation', self.translation_cache)
        return t

    async def translate_items(self, items: Iterable):
        it = items.values() if isinstance(items, dict) else items
        t = self.translate_string
        for v in it: await v.translate(t)
        return items

@dataclass(slots=True)
class Purkka:
    server_url: str|None
    client_url: str|None

    client_connection: PurkkaConnection|None = field(default=None, init=False)
    server_connection: PurkkaConnection|None = field(default=None, init=False)

    server: PurkkaServerClient|None = field(default=None, init=False)
    client: PurkkaClientClient|None = field(default=None, init=False)

    server_common: PurkkaCommonClient|None = field(default=None, init=False)
    client_common: PurkkaCommonClient|None = field(default=None, init=False)

    async def get_client_event_listeners(self, event: str):
        return await self.client_common.get_event_listeners(event)
    async def get_server_event_listeners(self, event: str):
        return await self.client_common.get_event_listeners(server)

    async def get_all_items_uncached(self):
        items = list((await self.client_common.get_all_items()).values())
        await self.client.translate_items(items)
        return items

    async def get_all_items(self, *, cache_mode: CacheMode = CacheMode.NONE):
        return await self.client_connection.cache.call_cached_async(
            'items', self.get_all_items_uncached, cache_mode=cache_mode,
            serializer=partial(serialize_by_type, list[Item]), deserializer=partial(deserialize, list[Item]))

    async def get_all_recipes(self):
        recipes = await self.server.get_all_recipes()
        item_reg = self.server_common.get_registry('item')
        for r in recipes:
            res = item_reg.get_resolver()
            r.resolve(res)
            await res.apply()
        return recipes

    async def get_recipes_matching(self, matcher: RecipeMatcher):
        recipes = await self.server.get_all_recipes()
        item_reg = self.server_common.get_registry('item')
        for r in recipes:
            res = item_reg.get_resolver()
            r.resolve(res)
            await res.apply()
        return list(filter(matcher, recipes))

    async def __aenter__(self):
        if self.client_connection or self.server_connection: raise Exception('Session already open')
        client_connection = client_common = client = None
        server_connection = server_common = client = None
        if self.client_url is not None:
            client_connection = PurkkaConnection(self.client_url)
            client_common = PurkkaCommonClient(client_connection)
            client = PurkkaClientClient(client_connection)
        if self.server_url is not None:
            if self.server_url == self.client_url:
                server_connection = client_connection
                server_common = client_common
            else:
                server_connection = PurkkaConnection(self.server_url)
                server_common = PurkkaCommonClient(server_connection)
            server = PurkkaServerClient(server_connection)

        self.client_connection = client_connection
        self.server_connection = server_connection
        self.client_common = client_common
        self.server_common = server_common
        self.client = client
        self.server = server

        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_value:
            print('Exception when closing session', exc_value)
            print_exception(exc_value)
        if self.client_connection:
            client_connection = self.client_connection
            self.client_connection = None
            if self.server_connection == client_connection:
                self.server_connection = None
            await client_connection.close()
        if self.server_connection:
            await server_connection.close()
            self.server_connection = None
        self.server = None
        self.client = None
        self.server_common = None
        self.client_common = None
