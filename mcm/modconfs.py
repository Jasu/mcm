from ast import literal_eval
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import chain, starmap
import tomlkit
from glob import iglob
from .utils import checkabs, PrettyEnum, Styles, cpfile
import regex
import json
import os

__all__ = ('parse_edits', 'ModConfFile', 'ModConfFileCopy', 'ModConfFileOverwrite', 'ModConfFileEdit', 'ModConfFiles')

@dataclass(slots=True)
class Wrapper:
    coll: dict|list
    def maybe_child(self, key): return Cursor(self, key) if self.has_key(key) else None
    def maybe_child_iterable(self, key): return (Cursor(self, key), ) if self.has_key(key) else ()
    def child(self, key): return Cursor(self, key)
    def children(self, keys = None): return map(self.child, coalesce(keys, self.keys()))
    @staticmethod
    def create(coll: dict|list): return DictWrapper(coll) if isinstance(coll, dict) else ListWrapper(coll)

@dataclass(slots=True)
class DictWrapper(Wrapper):
    def keys(self): return self.coll.keys()
    def items(self): return self.coll.items()
    def has_key(self, key): return key in self.coll
    def concat(self, value): raise ValueError(f'Tried to concat to a dict ({self.coll!r})')
    def append(self, value): raise ValueError(f'Tried to append to a dict ({self.coll!r})')
    def remove_value(self, value): del self.coll[next(k for k,v in self.coll.items() if v == value)]

@dataclass(slots=True)
class ListWrapper(Wrapper):
    def keys(self): return range(len(self.coll))
    def items(self): return enumerate(self.coll)
    def has_key(self, key): return key.__class__ is int and key >= 0 and key < len(self.coll)
    def concat(self, value): self.coll.extend(value)
    def append(self, value): self.coll.append(value)
    def remove_value(self, value): self.coll.remove(value)

@dataclass(slots=True)
class Cursor:
    wrapper: Wrapper
    index: object

    def read(self): return self.wrapper.coll[self.index]
    def assign(self, value): self.wrapper.coll[self.index] = value
    def concat(self, value): self.wrap().concat(value)
    def append(self, value): self.wrap().append(value)
    def delete(self): del self.wrapper.coll[self.index]
    def wrap(self): return Wrapper.create(self.read())
    def maybe_child(self, key): return self.wrap().maybe_child(key)
    def maybe_child_iterable(self, key): return self.wrap().maybe_child_iterable(key)
    def child(self, key): return self.wrap().child(key)
    def children(self, keys = None): return self.wrap().children(keys)
    def apply(self, fn, *args): self.assign(fn(self.read, *args))
    def remove_value(self, value): self.wrap().remove_value(value)

class Cursors(list):
    __slots__ = ()

    def maybe_child(self, key): return Cursors(chain.from_iterable(c.maybe_child_iterable(key) for c in self))
    def child(self, key): return Cursors(c.child(key) for c in self)
    def children(self, keys = None): return Cursors(chain.from_iterable(c.children(keys) for c in self))
    def append(self, value):
        for c in self: c.append(value)
    def concat(self, value):
        for c in self: c.concat(value)
    def delete(self):
        for c in self: c.delete()
    def assign(self, value):
        for c in self: c.assign(value)
    def apply(self, fn, *args):
        for c in self: c.apply(value, fn, *args)
    def remove_value(self, value):
        for c in self: c.remove_value(value)

match_name = regex.compile('[a-zA-Z_][a-zA-Z_0-9]*').match
match_dstr = regex.compile(r'"(?:[^\\"]+|\\.)"').match
match_sstr = regex.compile(r"'(?:[^\\']+|\\.)'").match
match_num = regex.compile(r'-?[0-9]+').match

def parse_key(path: str, at: int):
    ch = path[at]
    if ch in "'\"":
        m = (match_dstr if ch == '"' else match_sstr)(path, pos=at)
        return literal_eval(m.group()), m.end()
    if m := match_name(path, pos=at):
        return m.group(), m.end()
    m = match_num(path, pos=at)
    return int(m.group()), m.end()

def parse_attr(value, path: str, at: int):
    if path[at] == '*':
        return value.children(), at + 1
    key, at = parse_key(path, at)
    return value.child(key), at

def parse_brackets(value, path: str, at: int):
    if path[at] == '*':
        keys = None
        at += 1
    else:
        at, key = parse_key(path, at)
        keys = [key]
        while path[at] == ',':
            key, at = parse_key(path, at + 1)
            keys.append(key)
    assert(path[at] == ']')
    return value.children(keys), at + 1

def apply_path(value, path: str):
    at = 0
    l = len(path)
    while at < l:
        if path[at] == '[':
            value, at = parse_brackets(value, path, at + 1)
        elif at == 0:
            value, at = parse_attr(value, path, at)
        else:
            assert path[at] == '.'
            value, at = parse_attr(value, path, at + 1)
    return value

def parse_edit(path, action): return parse_path(path, parse_action(action))
def parse_edits(edits):
    fns = tuple(starmap(parse_edit, edits.items()))
    def apply_edits(val):
        val = val.copy()
        val = Wrapper.create(val)
        for fn in fns: fn(val)
        return val
    return apply_edits


class ModConfType(str, PrettyEnum):
    COMMON = 'common' / pretty(Styles.cyan, 'Common conf')
    CLIENT = 'client' / pretty(Styles.green, 'Client conf')
    SERVER = 'server' / pretty(Styles.magenta, 'Server conf')

def get_paths(source_dir: str, type: ModConfType, target_dirs, subdir: str, glob: str):
    target_dir = target_dirs.defaultconfig if type is ModConfType.SERVER else target_dirs.config
    source_dir = os.path.join(source_dir, subdir, type.value)
    return {os.path.join(target_dir, p): os.path.join(source_dir, p) for p in iglob(glob, root_dir=source_dir)}

@dataclass(match_args=False)
class ModConfFile:
    glob: str
    def match_paths(self, path: str):
        checkabs(path)
        return iglob(self.glob, root_dir=path)

    def get_paths(self, type: ModConfType, source_dir: str, target_dirs):
        return (get_paths(source_dir, type, target_dirs, 'defaultconfig', self.glob)
                | get_paths(source_dir, type, target_dirs, 'config', self.glob))

    def apply(self, type: ModConfType, modpak_dir: str, target_dirs):
        for to, src in self.get_paths(type, modpak_dir, target_dirs).items():
            self(src, to)

@dataclass(match_args=False)
class ModConfFileCopy(ModConfFile):
    def __call__(self, src, to): cpfile(src, to)

@dataclass(match_args=False)
class ModConfFileOverwrite(ModConfFile):
    content: str
    def __call__(self, _, to):
        with open(to, 'w') as f: f.write(self.content)

@dataclass(match_args=False)
class ModConfFileEdit(ModConfFile):
    edits: dict
    def load(self, src):
        if src.endswith('.toml'):
            with open(src, 'r') as f: return tomlkit.load(f)
        if src.endswith('.json'):
            with open(src, 'r') as f: return json.load(f)
        raise ValueError(f'Unsupported extension for {src}')
    def save(self, value, dst):
        if dst.endswith('.toml'):
            with open(dst, 'w') as f: return tomlkit.dump(value, f)
        if dst.endswith('.json'):
            with open(dst, 'w') as f: return json.dump(value, f, indent=2)
        raise ValueError(f'Unsupported extension for {dst}')

    def edit_to_str(self, src):
        val = self.edit(src)
        if src.endswith('.toml'): return tomlkit.dumps(val)
        raise ValueError(f'Unsupported extension for {src}')

    def edit(self, src):
        val = Wrapper.create(self.load(src))
        for path, action in self.edits.items():
            target = apply_path(val, path)
            match action:
                case { 'delete': _ }: target.delete()
                case { 'append': value }: target.append(value)
                case { 'concat': value }: target.concat(value)
                case { 'assign': value }: target.assign(value)
                case { 'remove_value': value }: target.remove_value(value)
                case value: target.assign(value)
        return val.coll

    def __call__(self, src, to):
        self.save(self.edit(src), to)

def deserialize_filedict(l, val: dict):
    for k,v in val.items():
        match v:
            case str(): l.append(ModConfFileOverwrite(k, v))
            case dict(): l.append(ModConfFileEdit(k, v))
            case _: raise ValueError(f'Unsupported edit {v!r}')

@dataclass(slots=True, match_args=False)
class ModConfFiles:
    files: list[ModConfFile]

    @classmethod
    def deserialize(cls, val):
        l = []
        match val:
            case str(): l.append(ModConfFileCopy(val))
            case list():
                for item in val:
                    match item:
                        case str(): l.append(ModConfFileCopy(item))
                        case dict(): deserialize_filedict(l, item)
                        case _: raise ValueError(f'Unsupported config {item}')
            case dict(): deserialize_filedict(l, val)
            case _: raise ValueError(f'Unsupported ModConfig {val!r}')
        return ModConfFiles(l)

    def apply(self, type: ModConfType, source_dir: str, target_dirs):
        for f in self.files: f.apply(type, source_dir, target_dirs)

    def get_paths(self, type: ModConfType, source_dir: str, target_dirs):
        paths = {}
        for f in self.files:
            paths |= f.get_paths(type, source_dir, target_dirs)
        return [(src, to) for to, src in paths.items()]

    def match_paths(self, path: str):
        return chain.from_iterable(map(ModConfFile.match_paths, self.files))
    def __iter__(self): return iter(self.files)
    def __len__(self): return len(self.files)
