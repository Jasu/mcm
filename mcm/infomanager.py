from dataclasses import dataclass, field
from datetime import datetime, timedelta
from random import randrange
from typing import ClassVar
from xdg import xdg_config_home
from .common import SourceType, Type
from .modrinth import Modrinth
from .curseforge import CurseForge
from .serialize import serialize, deserialize
from .modinfo import ModInfo, ModVer, ModVerPair
from os import access, makedirs, symlink, R_OK
from shutil import copyfile
from functools import partialmethod
import os.path as path
import json
__all__ = ('ModInfoManager')

CacheKey = tuple[SourceType, str]

def _path_by(self, by: str, src: SourceType, name: str):
    parent = path.join(self.dirs_by_src[src], by)
    p = path.join(parent, f'{name}.json')
    if path.dirname(p) != parent: raise ValueError(f'Invalid name {name}')
    return p

def _get_by(self, by: str, src: SourceType, id: str):
    key = (by, src, id)
    result = self.cache.get(key, False)
    if result is False:
        p = _path_by(self, by, src, id)
        if not access(p, R_OK):
            result = None
            self.cache[key] = result
        else:
            try:
                result = deserialize(ModInfo, json.load(open(p, 'r')))
                self.cache[('by_id', src, result.id)] = result
                self.cache[('by_name', src, result.name)] = result
            except Exception as e:
                result = e
                self.cache[key] = result

    if isinstance(result, Exception):
        raise result
    return result

@dataclass(slots=True, init=False)
class ModInfoCache:
    basedir: str
    dirs_by_src: dict[SourceType, str]
    cache: dict[CacheKey, ModInfo|Exception]
    file_cache: dict[str, str]

    def __init__(self):
        self.basedir = path.join(xdg_config_home(), 'mcm')
        self.dirs_by_src = {}
        self.cache = {}
        self.file_cache = {}
        makedirs(path.join(self.basedir, 'files'), exist_ok=True)
        for src in SourceType:
            if src is SourceType.LOCAL: continue
            d = path.join(self.basedir, src.value)
            makedirs(path.join(d, 'by_name'), exist_ok=True)
            makedirs(path.join(d, 'by_id'), exist_ok=True)
            self.dirs_by_src[src] = d

    path_by_id = partialmethod(_path_by, 'by_id')
    path_by_name = partialmethod(_path_by, 'by_name')
    get_by_id = partialmethod(_get_by, 'by_id')
    get_by_name = partialmethod(_get_by, 'by_name')
        
    def set(self, src: SourceType, value: ModInfo):
        self.cache[('by_id', src, value.id)] = value
        self.cache[('by_name', src, value.name)] = value
        path_by_id = self.path_by_id(src, value.id)
        path_by_name = self.path_by_name(src, value.name)
        with open(path_by_id, 'w') as f:
            json.dump(serialize(value), f)
        if not access(path_by_name, R_OK):
            symlink(path_by_id, path_by_name)
        return value
        
    def file_path(self, filename: str):
        parent = path.join(self.basedir, f'files')
        result = path.join(parent, filename)
        if path.dirname(result) != parent: raise ValueError(f'Invalid name {filename}')
        return result

    def get_file(self, filename: str):
        result = self.file_cache.get(filename, False)
        if result is False:
            result = self.file_path(filename)
            if not access(result, R_OK):
                result = None
            self.file_cache[filename] = result
        return result

        
@dataclass(slots=True)
class ModInfoManager:
    cache: ModInfoCache = field(default_factory=ModInfoCache, init=False)
    backends: dict = field(default_factory=lambda: {
        SourceType.MODRINTH: Modrinth(),
        SourceType.CURSEFORGE: CurseForge()
    }, init=False)
    RECHECK_INTERVAL_MIN: ClassVar[int] = 6 * 3600
    RECHECK_INTERVAL_MAX: ClassVar[int] = 10 * 3600

    def recheck_interval(self):
        return timedelta(0, randrange(self.RECHECK_INTERVAL_MIN, self.RECHECK_INTERVAL_MAX))

    async def get_modinfo(self, source: SourceType, type: Type, id_or_name: str) -> ModInfo:
        now = datetime.now()
        desc = versions = None
        version_info = {}
        try:
            if info := self.cache.get_by_name(source, id_or_name):
                if now - info.checked < self.recheck_interval():
                    return info
                desc = info.mod_desc
                versions = info.versions
                version_info = info.version_info
        except Exception as e:
            print(e)
            pass
        newdesc = await self.backends[source].get_moddesc(type, id_or_name)
        if not desc or desc.updated != newdesc.updated:
            versions, newverinfo = await self.backends[source].get_versions(newdesc)
            if newverinfo: version_info.update(newverinfo)
        info = ModInfo(now, newdesc, versions, version_info)
        return self.cache.set(source, info)

    async def get_version_info(self, source: SourceType, modinfo: ModInfo, ver: ModVer) -> ModVerPair:
        if info := modinfo.version_info.get(ver.id): return ModVerPair(ver, info)
        info = await self.backends[source].get_version_info(modinfo.mod_desc, ver)
        modinfo.version_info[ver.id] = info
        self.cache.set(source, modinfo)
        return ModVerPair(ver, info)

    async def get_file(self, source: SourceType, modinfo: ModInfo, ver: ModVer) -> str:
        ver = await self.get_version_info(source, modinfo, ver)
        if file := self.cache.get_file(ver.filename):
            return file
        p = self.cache.file_path(ver.filename)
        await self.backends[source].get_file(p, ver)
        assert access(p, R_OK)
        self.cache.file_cache[ver.filename] = p
        return p

    async def copy_file(self, to: str, source: SourceType, modinfo: ModInfo, ver: ModVer):
        if not path.isabs(to): raise ValueError(f'Expected absolute path')
        p = await self.get_file(source, modinfo, ver)
        assert access(p, R_OK)
        copyfile(p, to)

    async def __aenter__(self):
        for be in self.backends.values():
            await be.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        for be in self.backends.values():
            await be.__aexit__(exc_type, exc_value, traceback)

