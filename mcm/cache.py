from .utils import checkabs
from xdg import xdg_cache_home
from typing import Callable, Iterable
from dataclasses import dataclass, field
from enum import Flag
from os import access, makedirs, unlink, R_OK
from hashlib import sha1
from typing import ClassVar
import json
import os.path

def hash_path(path: str): return sha1(path.encode('utf8')).hexdigest()[0:20]

@dataclass(slots=True, init=False)
class CacheFileManager:
    path: str
    realpath: str
    cache_key_mapper: Callable[[str], str]|None

    _ROOT: ClassVar[object] = None

    @classmethod
    def root(cls):
        if cls._ROOT is None:
            cls._ROOT = cls(os.path.join(xdg_cache_home(), 'mcm'))
        return cls._ROOT

    def __init__(self, path: str, cache_key_mapper: Callable[[str], str]|None = None):
        self.path = checkabs(path)
        self.realpath = os.path.realpath(path)
        self.cache_key_mapper = cache_key_mapper 
        makedirs(self.path, exist_ok=True)

    @classmethod
    def hashed(cls, path: str):
        return cls(path, hash_path)

    def check_below_root(self, path: str) -> str:
        if os.path.commonpath([self.realpath, os.path.realpath(path)]) != self.realpath:
            raise Exception(f'Invalid cache path {path}, not below {self.realpath}')
        return checkabs(path)

    def get_cache_path(self, key: str) -> str:
        if self.cache_key_mapper:
            key = self.cache_key_mapper(key)
        path = os.path.join(self.path, key)
        return self.check_below_root(path)

    def delete_file(self, path: str) -> None:
        os.unlink(self.get_cache_path(path))

    def child(self, key: str):
        return CacheFileManager(self.get_cache_path(key), self.cache_key_mapper)

    def child_unhashed(self, key: str):
        return CacheFileManager(self.get_cache_path(key))

    def child_hashed(self, key: str, cache_key_mapper=hash_path):
        return CacheFileManager(self.get_cache_path(key), cache_key_mapper)

    def subdir(self, key: str) -> str:
        path = self.get_cache_path(key)
        makedirs(path, exist_ok=True)
        return path

    def delete_subdir(self, key: str):
        path = self.get_cache_path(key)
        shutil.rmtree(path)

    def delete_self(self):
        shutil.rmtree(self.path)

class CacheMode(int, Flag):
    NONE = 0
    READ = 1
    WRITE = 2
    FULL = 3

@dataclass(slots=True, init=False)
class DirBackedJsonCache:
    file_cache: CacheFileManager
    local_cache: dict
    changed_keys: set

    SENTINEL: ClassVar[object] = object()

    def __init__(self, file_cache: CacheFileManager):
        self.file_cache = file_cache
        self.local_cache = {}
        self.changed_keys = set()

    def get(self, key: str, default=None):
        if (result := self.local_cache.get(key, self.SENTINEL)) is not self.SENTINEL:
            return result
        path = self.file_cache.get_cache_path(key)
        if not os.access(path, R_OK): return default
        with open(path, 'rb') as f:
            try:
                result = json.load(f)
                self.local_cache[key] = result
                return result
            except json.decoder.JSONDecodeError:
                return default

    def call_cached(self, key: str, fn: Callable, *args, mode=CacheMode.FULL, **kwargs):
        if CacheMode.READ in mode and (result := self.get(key, self.SENTINEL)) is not self.SENTINEL:
            return result
        result = fn(*args, **kwargs)
        if CacheMode.WRITE in mode:
            self.put_persist(key, result)
        return result

    async def call_cached_async(self, key: str, fn: Callable, *args,
                                cache_mode=CacheMode.FULL,
                                serializer=None,
                                deserializer=None,
                                **kwargs):
        if CacheMode.READ in cache_mode and (result := self.get(key, self.SENTINEL)) is not self.SENTINEL:
            return deserializer(result) if deserializer else result
        result = await fn(*args, **kwargs)
        if CacheMode.WRITE in cache_mode:
            self.put_persist(key, serializer(result) if serializer else result)
        return result

    def put(self, key: str, value) -> None:
        self.local_cache[key] = value
        self.changed_keys.add(key)

    def put_persist(self, key: str, value) -> None:
        self.changed_keys.discard(key)
        self.local_cache[key] = value
        path = self.file_cache.get_cache_path(key)
        with open(path, 'w') as f: json.dump(self.local_cache[key], f)

    def persist(self) -> None:
        for key in self.changed_keys:
            path = self.file_cache.get_cache_path(key)
            with open(path, 'w') as f: json.dump(self.local_cache[key], f)
        self.changed_keys.clear()

    def delete(self, key: str) -> None:
        del self.local_cache[key]
        self.file_cache.delete_file(key)
        self.changed_keys.remove(key)


    def delete_self(self) -> None:
        self.local_cache = {}
        self.file_cache.delete_self(key)
        self.changed_keys.clear()

    # def read_file_as_str(self, path: str, *, default=None) -> str|None:
    #     path = self.get_cache_path(path)
    #     if not os.access(path, R_OK): return default
    #     with open(path, 'r') as f: return f.read()

    # def write_file_as_str(self, path: str, value: str) -> None:
    #     path = self.get_cache_path(path)
    #     with open(path, 'w') as f: return f.write(value)

    # def read_file_as_bytes(self, path: str, *, default=None) -> bytes|None:
    #     path = self.get_cache_path(path)
    #     if not os.access(path, R_OK): return default
    #     with open(path, 'rb') as f: return f.read()

    # def write_file_as_bytes(self, path: str, value: bytes) -> None:
    #     path = self.get_cache_path(path)
    #     with open(path, 'wb') as f: return f.write(value)
