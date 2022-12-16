from .modpakyml import parse_modpak_yml, ModConf
from .utils import as_props, as_table, coalesce, print, Styles, Syms, syntax, syntax_diff, ensure_empty_dir, cpfile, rule
from .backend import *
from functools import wraps
from itertools import chain
from .purkka import Purkka, EventListener 
from .search import SearchIndex
from .cache import CacheMode 
from .mcdata import Item 
from .config import Config, InstDir, InstType
from .infomanager import ModInfoManager
from .common import Loader, McVer, McVerMatch, SourceType, Type, VerMatch
from .recipematch import parse_recipe_matcher
from .serialize import deserialize
from .modinfo import ModDesc, ModInfo, ModVer, ModVerMatch
from .modconfs import ModConfType, ModConfFileCopy, ModConfFileOverwrite, ModConfFileEdit
from .resolve import resolve as resolve_modpak, ResolvedMod, ResolveResult
from .modrinth import Modrinth
from .cliutils import *
from .build import build as build_modpak, check as check_modpak
from rich.text import Text
import asyncclick as click
from shutil import copytree
import os

@click.group()
@click.pass_context
async def cli(ctx):
    ctx.obj = GlobalCtx()

@cli.group()
@click.option('--modpak', '-m')
@click.pass_context
async def modpak(ctx, modpak: str|None = None):
    ctx.obj = ModpakCtx(ctx.obj, coalesce(modpak, os.getcwd()))

@modpak.command()
@click.option('--fields', '-f', default= 'name,ver,type,side,source')
@click.option('--build-type', '-b')
@click.pass_obj
def dump(ctx: ModpakCtx, fields: str, build_type: str|None = None):
    if build_type:
        build_type = ctx.modpak.build_types[build_type]
        mods = ctx.modpak.build_type_mods(build_type) 
    else:
        mods = ctx.modpak.enabled_mods
    print(as_table(ModConf, mods, fields))

@modpak.command()
@click.argument('build_type')
@click.pass_obj
async def resolve(ctx: ModpakCtx, build_type: str):
    async with ModInfoManager() as manager:
        resolved = await resolve_modpak(manager, ctx.modpak, build_type)
    print(as_table(ResolvedMod, resolved.downloaded, 'name,e,d,v.ver,v.mcver'))
    print(as_table(ModConf, resolved.local, 'name,side,src'))
    print(resolved.warnings)

@modpak.command()
@click.argument('build_type')
@click.pass_obj
async def check(ctx: ModpakCtx, build_type: str):
    async with ModInfoManager() as manager:
        resolutions = await resolve_modpak(manager, ctx.modpak, build_type)
        errors = await check_modpak(ctx.modpak, build_type, resolutions,
                                    ctx.modpak_dir, ctx.output_dir)
        for error in errors: print(f'Error: {error}')
        print(resolutions.warnings)

@modpak.command()
@click.argument('build_type')
@click.pass_obj
async def build(ctx: ModpakCtx, build_type: str):
    async with ModInfoManager() as manager:
        resolutions = await resolve_modpak(manager, ctx.modpak, build_type)
        await build_modpak(manager, ctx.modpak, build_type, resolutions,
                           ctx.modpak_dir, ctx.output_dir)
        print(resolutions.warnings)

@cli.command()
@loader_opt
@type_opt
@click.option('--mcver', type=Deserialized(McVerMatch), default=McVerMatch.ANY)
@click.option('--sort', '-s')
@click.option('--limit', '-l', type=int, default=100)
@click.option('--category', '-c')
@click.option('--category-not', '-n')
@click.argument('query', nargs=-1)
async def search(query: list[str], loader: Loader, mcver: McVerMatch, type: Type, limit: int=100, category: str|None = None, category_not: str|None = None, sort: str|None = None):
    async with Modrinth() as modrinth:
        if category_not:
            category_not = category_not.split(',')
            cats = await modrinth.get_categories(type)
            cats = [c for c in cats if c not in category_not]
            category = ','.join(cats)
        criteria = SearchCriteria.create(query, type, category, sort, limit, mcver, loader if type is Type.MOD else None)
        print(await modrinth.search(criteria))

def with_purkka(at: str):
    def wrap(fn):
        @click.option('--client-url', default = 'http://localhost:8010')
        @click.option('--server-url', default = 'http://localhost:8010')
        @wraps(fn)
        async def wrapped(*args, client_url: str = 'http://localhost:8010', server_url: str = 'http://localhost:8010', **kwargs):
            async with Purkka(client_url, server_url) as purkka:
                return await fn(*args, **(kwargs | { at: purkka }))
        return wrapped
    return wrap

@cli.command()
@click.option('--filter', '-f', default = None)
@with_purkka('purkka')
async def recipes(purkka: Purkka, filter: str|None = None):
    for r in await (purkka.get_all_recipes() if filter is None else purkka.get_recipes_matching(parse_recipe_matcher(filter))):
        print(r)

@cli.command()
@click.option('--server', is_flag=True, default=False)
@click.option('--fields', '-f', default = 'method,string,type')
@click.argument('event', nargs=1)
@with_purkka('purkka')
async def event_listeners(event: str, purkka: Purkka, fields = 'method,string', server: bool = False):
    for r in await (purkka.get_server_event_listeners if server else purkka.get_client_event_listeners)(event):
        if r.type == 'class net.minecraftforge.eventbus.api.EventPriority':
            rule(f'Priority {r.string}')
        else:
            print(as_props(r, fields))
        print()

def with_cache_mode(at: str):
    def wrap(fn):
        @click.option('--cache', is_flag=True)
        @click.option('--clear-cache', is_flag=True)
        @wraps(fn)
        async def wrapped(*args, cache: bool = False, clear_cache: bool = False, **kwargs):
            match clear_cache, cache:
                case True, _: cache_mode = CacheMode.WRITE
                case False, True: cache_mode = CacheMode.FULL
                case False, False: cache_mode = CacheMode.NONE
            return await fn(*args, **(kwargs | { at: cache_mode }))
        return wrapped
    return wrap

@cli.command()
@with_cache_mode('cache_mode')
@click.option('--food', is_flag=True)
@click.option('--duplicates')
@with_purkka('purkka')
async def items(purkka: Purkka, cache_mode: CacheMode, food: bool = False, duplicates: str|None = None):
    def is_dupe(l: list):
        if len(l) < 2: return False
        if len({i.key.namespace for i in l}) == 1: return False
        return True
    items = await purkka.get_all_items(cache_mode=cache_mode)
    items = sorted(items, key=lambda x: x.key.location)
    if food:
        items = [v for v in items if v.food_info]
    if duplicates:
        by_name = {}
        for i in items:
            key = i.name if duplicates == 'name' else i.key.location
            by_name.setdefault(key, []).append(i)
        items = chain.from_iterable(filter(is_dupe, by_name.values()))
    print(as_table(Item, items, 'k,n,tags,ff,fe,fn,fs' if food else 'k,n,tags'))

@cli.command()
@click.argument('query', nargs=1)
@click.option('--unfuzzy', is_flag=True)
@with_purkka('purkka')
async def search_items(purkka, query: str, unfuzzy: bool = False):
    if unfuzzy: max_edit_distance=0
    else: max_edit_distance = (1,0,1) if len(query) < 6 else (2,1,1)

    idx = SearchIndex(field_boost=(1,4,3), max_edit_distance=max_edit_distance, match_transform=SearchIndex.NONALPHA_PUNCTUATION)
    for item in (await purkka.get_all_items()).values():
        idx.append(item, item.key.namespace, item.key.location, item.name)
    results = idx.search(query)
    print(as_table(Item, results, 'k,n,tags'))

@cli.command()
@with_purkka('purkka')
async def recipes_with(item, purkka: Purkka):
    for r in await purkka.get_recipes_with_item(item): print(r)

@cli.command()
@click.argument('type', nargs=1, type=EnumParam(Type), default=Type.MOD)
async def categories(type: Type):
    async with Modrinth() as modrinth:
        for c in await modrinth.get_categories(type):
            print(c)

@cli.command()
@click.option('--versions', is_flag=True)
@click.option('--fields', default='n,t,s,sc,ss,li,ls,lw,ld,lic,du,dc,c') #,v.version,v.loaders,v.mcver
@with_mod_opts
async def get(manager, mvm, name: str, source: SourceType, type: Type, fields: str|None = None, versions: bool = False):
    info = await manager.get_modinfo(SourceType(source), type, name)
    print(as_props(info, fields))
    if versions:
        print(as_table(ModVer, info.get_versions(mvm), 'version,version_string,published,mcversions'))

@cli.command()
@click.option('--fields', default='title,version,loaders,published,mcver,changelog,filename,hash')
@with_mod_opts
async def version(manager, mvm, name: str, source: SourceType, type: Type, fields: str|None = None):
    info = await manager.get_modinfo(source, type, name)
    ver = info.get_latest_version(mvm)
    ver = await manager.get_version_info(source, info, ver)
    print(as_props(ver, fields))

@cli.command()
@with_mod_opts
async def download(manager, mvm: ModVerMatch, name: str, source: SourceType, type: Type):
    info = await manager.get_modinfo(source, type, name)
    ver = info.get_latest_version(mvm)
    p = await manager.get_file(source, info, ver)
    print(f'File at {p}')

@modpak.command()
@click.option('--dry', '-d', is_flag=True)
@click.option('--type', '-t', multiple=True, type=EnumParam(ModConfType),
              default=[ModConfType.COMMON, ModConfType.SERVER, ModConfType.CLIENT])
@click.argument('instance')
@click.pass_obj
async def get_default_configs(ctx, type, instance: str|None = None, dry: bool = False):
    inst = ctx.config.get_instance(instance)
    config_path = inst.get_dir(InstDir.CONFIG)
    serverconfig_path = inst.get_dir(InstDir.SERVERCONFIG)
    target_dirs = ctx.target_dirs
    did_print = False
    if not dry:
        for t in ModConfType:
            os.makedirs(os.path.join(ctx.modpak_dir, 'defaultconfig', t.value), exist_ok=True)

    for m in ctx.modpak.enabled_mods:
        for t in type:
            if not (c := m.get_conf(t)):
                continue
            src_path = serverconfig_path if t is ModConfType.SERVER else config_path
            dst_path = os.path.join(ctx.modpak_dir, 'defaultconfig', t.value)
            if did_print: print()
            did_print = True
            print(Text.styled(m.name, Styles.yellow_bold), ' - ', t)
            for p in c:
                print('  ', Text.styled(p.glob + ':', t.style))
                for match in p.match_paths(src_path):
                    globbed = Text.styled(match, Styles.cyan_italic)
                    print('    ', Text.styled(src_path, Styles.green_italic) + globbed,
                          Syms.arrow,
                          Text.styled(dst_path + '/', Styles.orange_italic) + globbed)
                    if not dry:
                        cpfile(os.path.join(src_path, match), os.path.join(dst_path, match))

@modpak.command()
@click.option('--type', '-t', multiple=True, type=EnumParam(ModConfType),
              default=[ModConfType.COMMON, ModConfType.SERVER, ModConfType.CLIENT])
@click.argument('name')
@click.pass_obj
async def test_config(ctx, type, name: str):
    m = ctx.modpak[name]
    for t in type:
        if not (c := m.get_conf(t)):
            continue
        for rule in c:
            paths = [(src, dst) for dst, src in rule.get_paths(t, ctx.modpak_dir, ctx.target_dirs).items()]
            match rule:
                case ModConfFileCopy(): print(Text.styled('Copy:', Styles.cyan))
                case ModConfFileOverwrite(): print(Text.styled('Replace files text:', Styles.orange))
                case ModConfFileEdit():
                    print(Text.styled('Edit files:', Styles.magenta))
            for src, dst in paths:
                print('  ', Text.styled(src, Styles.green), Syms.arrow, Text.styled(dst, Styles.orange))
                if rule.__class__ is ModConfFileEdit:
                    with open(src, 'r') as f: old = f.read()
                    print(syntax_diff(old, rule.edit_to_str(src), filename=dst))
            if rule.__class__ is ModConfFileOverwrite:
                print()
                print(syntax(rule.content, filename=paths[0][0]))

@modpak.command()
@click.option('--dry', '-d', is_flag=True)
@click.option('--no-conf', is_flag=True, default=False)
@click.option('--no-mods', is_flag=True, default=False)
@click.argument('build-type')
@click.argument('instance')
@click.pass_obj
async def install(ctx, build_type: str, instance: str|None = None, no_mods: bool = False, no_conf: bool = False, dry: bool = False):
    inst = ctx.config.get_instance(instance)
    build_type = ctx.modpak.get_build_type(build_type)
    build_dir = os.path.join(ctx.output_dir, build_type.name)
    build_dirs = ctx.modpak.get_target_dirs(build_dir)

    # datapacks_path = 
    # resourcepacks_path = inst.get_dir(InstDir.RESOURCEPACKS)

    def copy_dir(src, dst):
        print(f'Emptying/creating directory {dst}')
        if not dry: ensure_empty_dir(dst)
        print(f'Copying {src} to {dst}')
        if not dry: copytree(src, dst, dirs_exist_ok=True)
    if not no_mods: copy_dir(build_dirs.mods, inst.get_dir(InstDir.MODS))
    if not no_conf:
        copy_dir(build_dirs.config, inst.get_dir(InstDir.CONFIG))
        if defaultconfig := inst.get_dir(InstDir.DEFAULTCONFIG):
            copy_dir(build_dirs.defaultconfig, defaultconfig)
