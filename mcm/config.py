from enum import Enum
from dataclasses import dataclass, field, replace
from .serialize import deserialize
from .utils import parse_yaml_file
from os import listdir
import os.path
from xdg import xdg_config_home

__all__ = ('InstType', 'InstDir', 'McInstance', 'Config')

class InstType(str, Enum):
    SINGLE_PLAYER = 'single-player'
    SERVER = 'server'
    CLIENT = 'client'

class InstDir(str, Enum):
    ROOT           = './'
    RESOURCEPACKS  = 'resourcepacks/'
    SHADERPACKS    = 'shaderpacks/'
    MODS           = 'mods/'
    CRASHREPORTS   = 'crash-reports/'
    LOGS           = 'logs/'
    CONFIG         = 'config/'
    WORLD          = 'WORLD'
    SERVERCONFIG   = 'SERVERCONFIG'
    DEFAULTCONFIG  = 'DEFAULTCONFIG'
    SAVES          = 'SAVES'

@dataclass(slots=True)
class McInstance:
    path: str
    type: InstType
    world: str|None = None

    def __post_init__(self):
        self.path = os.path.expanduser(self.path)
        assert os.path.isabs(self.path)

    def with_world(self, world: str): return replace(self, world=world)

    def get_world_dir(self, world: str|None = None, path: str|None = None):
        match self.type:
            case InstType.SERVER: return os.path.join(self.path, 'world')
            case InstType.CLIENT: return None
            case InstType.SINGLE_PLAYER: pass
            case _: raise ValueError(self.type)
        world = world or self.world
        if not world: return None
        p = os.path.join(self.path, 'saves', world)
        assert os.path.basename(p) == world
        return p if path is None else os.path.join(p, path)

    def get_dir(self, type: InstDir, world: str|None = None):
        match type, self.type:
            case (InstDir.ROOT|InstDir.RESOURCEPACKS|InstDir.SHADERPACKS|
                  InstDir.MODS|InstDir.CRASHREPORTS|InstDir.LOGS|InstDir.CONFIG), _:
                return os.path.join(self.path, type.value)
            case InstDir.WORLD, _: return self.get_world_dir(world)
            case InstDir.SERVERCONFIG, _: return self.get_world_dir(world, 'serverconfig')
            case InstDir.DEFAULTCONFIG, InstType.CLIENT: return None
            case InstDir.DEFAULTCONFIG, _: return os.path.join(self.path, 'defaultconfigs')
            case InstDir.SAVES, InstType.SINGLE_PLAYER: return os.path.join(self.path, 'saves')
            case InstDir.SAVES, _: return None
            case _: raise ValueError(f'Unknown directory type {type}')

    def list_worlds(self):
        worlds_dir = self.get_dir(InstDir.SAVES)
        return os.listdir(worlds_dir) if worlds_dir else []

@dataclass(slots=True)
class Config:
    mc_instances: dict[str, McInstance] = field(default_factory=dict)
    default_instance: str|None = None

    def get_instance(self, instance: str|None = None, world: str|None = None):
        if instance is None: instance = self.default_instance
        if instance is None: return None
        instance = self.mc_instances[instance]
        if world: return instance.with_world(world)
        return instance

    @classmethod
    def load(cls):
        path = os.path.join(xdg_config_home(), 'mcm', 'config.yml')
        if data := parse_yaml_file(path, default=None):
            return deserialize(Config, data)
        return Config()
