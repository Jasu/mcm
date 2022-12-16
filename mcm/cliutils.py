import asyncclick as click
from functools import reduce, wraps
from .config import Config
from .modpakyml import ModpakYml, parse_modpak_yml
from dataclasses import dataclass
from .common import Loader, McVerMatch, SourceType, Type
from enum import Flag
from .serialize import deserialize
import operator
import yaml
import os

__all__ = ('Deserialized', 'EnumParam', 'YAML', 'with_mc_ver_opts', 'with_mod_ver_opts', 'with_mod_opts', 'type_opt', 'loader_opt', 'GlobalCtx', 'ModpakCtx')

class YAMLFileParamType(click.ParamType):
    name='yamlfile'
    def convert(self, value, param, ctx):
        if not isinstance(value, str): return value
        try:
            with open(value, 'r') as f: return yaml.safe_load(f)
        except yaml.parser.ParserError as e:
            self.fail(f'Invalid YAML in {value}: {e}', param, ctx)
        except OSError as e:
            self.fail(f'Could not read file {value}: {e}', param, ctx)

YAML = YAMLFileParamType()

class EnumParam(click.ParamType):
    name = 'enum'
    enum: type

    def __init__(self, enum: type):
        click.ParamType.__init__(self)
        self.enum = enum

    def parse_single(self, s: str):
        if s in self.enum.__members__: return self.enum[s]
        try: return self.enum(s)
        except ValueError: self.fail(f'Invalid {self.enum.__name__} value {s}.')

    def get_metavar(self, param: click.Parameter) -> str:
        if issubclass(self.enum.__bases__[0], str):
            choices = [v.value for v in self.enum]
        else:
            choices = [v.name for v in self.enum]
        choices_str = "|".join(choices)

        if param.required and param.param_type_name == "argument":
            return f"{{{choices_str}}}"
        return f"[{choices_str}]"

    def convert(self, value, param, ctx):
        if not isinstance(value, str): return value
        if issubclass(self.enum, Flag):
            return reduce(operator.or_, map(self.parse_single, value.split(',')))
        return self.parse_single(value)

class Deserialized(click.ParamType):
    name = 'deserialized'
    cls: type

    def __init__(self, cls: type):
        click.ParamType.__init__(self)
        self.cls = cls

    def get_metavar(self, param: click.Parameter) -> str:
        return self.cls.__name__.upper()

    def convert(self, value, param, ctx):
        if not isinstance(value, str): return value
        try: return deserialize(self.cls, value)
        except Exception: self.fail(f'Could not parse {value} into {self.cls.__name__}')

mcver_opt = click.option('--mcver', type=Deserialized(McVerMatch))
loader_opt = click.option('--loader', default=Loader.FORGE, type=EnumParam(Loader))
source_opt = click.option('--source', default=SourceType.MODRINTH, type=EnumParam(SourceType))
type_opt = click.option('--type', default=Type.MOD, type=EnumParam(Type))
name_arg = click.argument('name', nargs=1)
def with_mc_ver_opts(fn):
    return mcver_opt(loader_opt(fn))

def with_mod_ver_opts(fn):
    return with_mc_ver_opts(type_opt(source_opt(fn)))

def with_mod_opts(fn):
    @with_mod_ver_opts
    @name_arg
    @wraps(fn)
    async def wrapped(loader, mcver = None, **kwargs):
        mvm = ModVerMatch(VerMatch.ANY, loader, mcver, None, None)
        async with ModInfoManager() as manager:
            return await fn(manager, mvm, *args, **kwargs)
    return wrapped

@dataclass(slots=True)
class GlobalCtx:
    _config: Config|None = None

    @property
    def config(self):
        if self._config is None:
            self._config = Config.load()
        return self._config

@dataclass(slots=True)
class ModpakCtx:
    global_ctx: GlobalCtx
    modpak_dir: str
    output_dir: str
    modpak: ModpakYml

    @property
    def config(self): return self.global_ctx.config

    @property
    def target_dirs(self):
        return self.modpak.get_target_dirs(self.output_dir)

    def __init__(self, ctx: GlobalCtx, path):
        self.global_ctx = ctx
        if path.endswith('.yml') or path.endswith('.yaml'):
            self.modpak_dir = os.path.dirname(path)
        else:
            self.modpak_dir = path
            path = os.path.join('modpak.yml')
        self.modpak = parse_modpak_yml(path)
        self.output_dir = os.path.join(self.modpak_dir, 'build')
