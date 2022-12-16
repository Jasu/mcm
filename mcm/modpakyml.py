from .common import *
from .utils import coalesce, Fields, Field, checkabs
from .modconfs import parse_edits, ModConfFiles, ModConfType
from .serialize import deserialize
from collections import UserList
from typing import Callable
from dataclasses import astuple, dataclass, field, replace
from functools import partial
import yaml
import os.path

__all__ = ('ModConf', 'ModGroup', 'parse_modpak_yml')

@dataclass(slots=True, match_args=False)
class TargetDirs:
    datapacks: str = 'datapacks'
    resourcepacks: str = 'resourcepacks'
    shaderpacks: str = 'shaderpacks'
    mods: str = 'mods'
    defaultconfig: str = 'defaultconfigs'
    config: str = 'config'

    @property
    def paths(self): return astuple(self)

    def resolve(self, base: str):
        return TargetDirs(*map(partial(os.path.join, base), self.paths))

    def get_dir(self, t: Type):
        match t:
            case Type.MOD: p = self.mods
            case Type.RESOURCEPACK: p = self.resourcepacks
            case Type.DATAPACK: p = self.datapacks
            case Type.SHADERPACK: p = self.shaderpacks
            case _: raise ValueError(f'Unknown type {t!r}')
        return checkabs(p)

@dataclass(slots=True, match_args=False)
class BuildType:
    name: str
    side: Side
    title: str|None = None

    @property
    def has_client(self) -> bool: return Side.CLIENT in self.side
    @property
    def has_server(self) -> bool: return Side.SERVER in self.side

@dataclass(slots=True, match_args=False)
class ModConf:
    name: str
    version: VerMatch = VerMatch.ANY
    match: str|None = None
    mcver: McVerMatch|None = None
    fallback_mcver: McVerMatch|None = None
    type: Type|None = None
    side: Side|None = None
    source: Source|None = None
    comment: str|None = None
    disabled: bool|str = False
    in_builds: list[str]|None = None
    not_in_builds: list[str]|None = None
    common_conf: ModConfFiles|None = None
    client_conf: ModConfFiles|None = None
    server_conf: ModConfFiles|None = None

    def __post_init__(self):
        name = self.name
        if not self.source:
            source, _, name = name.rpartition('/')
            if source:
                self.source = Source.deserialize(source)
                self.name = name
        name, _, ver = name.partition(':')
        if ver:
            self.version = VerMatch.deserialize(ver)
            self.name = name
        if self.mcver and not self.fallback_mcver:
            self.fallback_mcver = self.mcver

    def get_conf(self, type: ModConfType):
        match type:
            case ModConfType.COMMON: return self.common_conf
            case ModConfType.CLIENT: return self.client_conf
            case ModConfType.SERVER: return self.server_conf
            case _: raise ValueError(repr(type))
        
    def is_enabled_for(self, build_type: BuildType):
        return (bool(self.side & build_type.side)
                and (self.in_builds is None or build_type.name in self.in_builds)
                and (self.not_in_builds is None or build_type.name not in self.not_in_builds))
    def replace(self, **kwargs): return replace(self, **kwargs)
    def with_defaults(self, other):
        side = self.side
        source = self.source
        match self.type:
            case Type.SHADERPACK:
                side = coalesce(side, Side.CLIENT)
                source = coalesce(source, Source.CURSEFORGE)
            case Type.RESOURCEPACK:
                side = coalesce(side, Side.CLIENT)

        return replace(self,
                       mcver=coalesce(self.mcver, other.mcver),
                       fallback_mcver=coalesce(self.fallback_mcver, other.fallback_mcver),
                       type=coalesce(self.type, other.type),
                       side=coalesce(side, other.side),
                       source=coalesce(source, other.source))
                       

    @classmethod
    def from_str(cls, val: str): return cls(val)

    FIELDS = Fields(
        Field('Name', 'name', 'n'),
        Field('Version', 'version', 'ver', 'v'),
        Field('Type', 'type', 't'),
        Field('Side', 'side', 's'),
        Field('Source', 'source', 'src'),
        Field('Comment', 'comment', 'c'),
        Field('Disabled', 'disabled', 'd'))

class ModList(UserList):
    @staticmethod
    def deserialize_item(o):
        match o:
            case dict() if 'mods' in o: return deserialize(ModGroup, o)
            case str(): return ModConf.from_str(o)
            case _: return deserialize(ModConf, o)

    @classmethod
    def deserialize(cls, o):
        return cls(map(cls.deserialize_item, o))

    def with_defaults(self, default: ModConf):
        return ModList(c.with_defaults(default) for c in self)

    def _flat(self):
        for item in self:
            if item.__class__ is ModConf: yield item
            else: yield from item.mods._flat()

    @property
    def flat_mods(self): return list(self._flat())

    @property
    def enabled_mods(self):
        return list(filter(lambda x: not x.disabled, self._flat()))

@dataclass(slots=True, match_args=False)
class ModGroup:
    name: str
    mods: ModList
    desc: str|None = None
    default_type: Type|None = None
    default_source: Source|None = None
    default_side: Side|None = None
    default_mcver: McVerMatch|None = None

    def with_defaults(self, default: ModConf):
        default = default.replace(
            type=coalesce(self.default_type, default.type),
            source=coalesce(self.default_source, default.source),
            side=coalesce(self.default_side, default.side),
            mcver=coalesce(self.default_mcver, default.mcver))
        return replace(self, mods=self.mods.with_defaults(default))

@dataclass(slots=True, match_args=False)
class ModpakYml:
    mods: ModList
    mc: McVer
    loader: Loader
    target_dirs: TargetDirs
    copy: dict[str, str]
    build_types: dict[str, BuildType]
    moddict: dict[str, ModConf] = field(init=False)

    def __getitem__(self, key): return self.moddict[key]
    def __contains__(self, key): return key in self.moddict
    def get_build_type(self, bt: str|BuildType):
        return bt if bt.__class__ is BuildType else self.build_types[bt]
    @property
    def flat_mods(self): return self.mods.flat_mods
    @property
    def enabled_mods(self): return self.mods.enabled_mods
    def build_type_mods(self, build_type: BuildType|str):
        build_type = self.get_build_type(build_type)
        return [m for m in self.mods.enabled_mods if m.is_enabled_for(build_type)]

    @property
    def default_mcver_match(self): return McVerMatch(self.mc)
    @property
    def default_mcver_fallback_match(self): return McVerMatch(self.mc, '^')

    def get_target_dirs(self, base_dir: str):
        base_dir = os.path.normpath(base_dir)
        if not os.path.isabs(base_dir): raise ValueError(f'Sanity check {base_dir}')
        return self.target_dirs.resolve(base_dir)

    @classmethod
    def deserialize(cls, value):
        mc = deserialize(McVer, value['mc'])
        loader = deserialize(Loader, value['loader']) if 'loader' in value else Loader.FORGE
        default = ModConf('default',
                          mcver=McVerMatch(mc),
                          fallback_mcver=McVerMatch(mc, '^'),
                          type = Type.MOD,
                          side = Side.BOTH,
                          source = Source.MODRINTH)
        result = ModpakYml(deserialize(ModList, value['mods']).with_defaults(default), mc, loader,
                           deserialize(TargetDirs, value['target_dirs']) if 'target_dirs' in value else None,
                           value.get('copy', {}),
                           {k: BuildType(k, deserialize(Side, v['side']), v.get('title')) for k,v in value['build_types'].items()})
        result.moddict = {m.name: m for m in result.flat_mods}
        return result

def parse_modpak_yml(path: str):
    yml = yaml.safe_load(open(path, 'r'))
    return deserialize(ModpakYml, yml)

