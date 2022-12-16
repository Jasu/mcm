from .common import *
from .utils import Date, Field, Fields, Link, PrettyEnum, Styles, Subfields
from dataclasses import dataclass, replace
from datetime import datetime
from functools import total_ordering
from typing import ClassVar
from rich.text import Text
from os import access, R_OK
import hashlib
import regex

__all__ = ('Dep', 'Hash', 'HashType', 'ModDesc', 'ModFile', 'ModInfo', 'ModVer', 'ModVerInfo', 'ModVerPair', 'ModVerMatch')
class HashType(str, PrettyEnum):
    MD5    = 'md5' / pretty(Styles.red, 'MD5')
    SHA1   = 'sha1' / pretty(Styles.red, 'SHA-1')
    SHA256 = 'sha256' / pretty(Styles.yellow, 'SHA-256')
    SHA512 = 'sha512' / pretty(Styles.green, 'SHA-512')
    
    def get_hash(self): return hashlib.new(self.value)

    def hash(self, data: bytes) -> str:
        h = self.get_hash()
        h.update(data)
        return h.hexdigest()

@dataclass(slots=True, match_args=False, frozen=True, unsafe_hash=True)
class Hash:
    type: HashType
    value: str

    def hash_file(self, p: str) -> str:
        with open(p, 'rb') as f: return self.hash(f.read())
    def hash(self, data: bytes) -> str:
        return self.type.hash(data)
    def check(self, data: bytes) -> bool:
        return self.value == self.hash(data)
    def check_file(self, p: str) -> bool:
        if not access(p, R_OK): return False
        return self.value == self.hash_file(p)
    def __rich__(self):
        return Text.styled(self.type.name + ' ' +self.value, self.type.style)

@dataclass(slots=True, match_args=False, frozen=True, unsafe_hash=True)
class ModFile:
    filename: str
    size: int|None
    hash: Hash
    url: str|None

    FIELDS = Fields(Field('File', 'filename', 'f', 'fn'),
                    Field('Size', 'size', 'sz', 'fs', 'filesize'),
                    Field('Hash', 'hash', 'fh'),
                    Link('Download', 'url', 'download', 'dl', 'fd', 'fu', 'lf'))

@dataclass(slots=True, match_args=False, frozen=True, unsafe_hash=True)
class Dep:
    is_required: bool
    id: str
    ver_id: str|None = None

@dataclass(slots=True, match_args=False, frozen=True, unsafe_hash=True)
class ModVerInfo:
    file: ModFile
    dependencies: list[Dep]
    changelog: str|None = None

    FIELDS = Fields(Field('Changelog', 'changelog', 'log', 'change', 'chg', 'c'), Subfields(ModFile, 'file'))

def is_ver_ok(s: str):
    return bool(regex.search(r'\d\.\d', s))

def maybe_int(s: str): return int(s) if s.isnumeric() else s
def strip_mcver(s: str, vers):
    s = regex.sub(r'\.[a-z]{3}$', '', s.lower())
    def ver_base(ver): return f'{ver.major}\\.{ver.minor}'
    for base in set(map(ver_base, vers)):
        for r in [base + r'\.\d', base]:
            r = r'(?<![0-9.])' + r + r'(?![0-9.])'
            new = regex.sub(r, '', s)
            if is_ver_ok(new): s = new
    return tuple(map(maybe_int, regex.findall(r'[a-z_-]+|\d+', regex.sub(r'^[a-z_.+-]+', '', regex.sub(r'forge|rift|fabric|alpha|beta|rc|release|pre|mc', '', s)).replace('-', '.'))))


@total_ordering
@dataclass(slots=True, match_args=False, frozen=True, unsafe_hash=True)
class ModVer:
    id: str
    version_string: str
    version_type: VerType
    title: str|None
    loaders: frozenset[Loader]
    published: datetime
    mcversions: frozenset[McVer]

    @property
    def version(self):
        return Ver(strip_mcver(self.version_string, self.mcversions), self.version_type)

    def __lt__(self, other):
        if other.__class__ is not ModVer: return NotImplemented
        return self.published < other.published if self.version == other.version else self.version < other.version

    FIELDS = Fields(
        Field('Id', 'id', 'i'),
        Field('Title', 'title', 'vt', 'vertitle'),
        Field('Version', 'version', 'ver', 'v'),
        Field('Orig. Version', 'version_string'),
        Field('Loaders', 'loaders', 'l', 'loader'),
        Date('Published', 'published', 'p', 'dp'),
        Field('Mc vers.', 'mcversions', 'mc', 'mcver', 'mv'))

@dataclass(slots=True, match_args=False, frozen=True, unsafe_hash=True)
class ModVerPair:
    ver: ModVer
    info: ModVerInfo|None = None

    @property
    def id(self): return self.ver.id
    @property
    def version(self): return self.ver.version
    @property
    def title(self): return self.ver.title
    @property
    def loaders(self): return self.ver.loaders
    @property
    def published(self): return self.ver.published
    @property
    def mcversions(self): return self.ver.mcversions
    @property
    def file(self): return self.info.file if self.info else None
    @property
    def filename(self): return self.info.file.filename if self.info else None
    @property
    def hash(self): return self.info.file.hash if self.info else None
    @property
    def dependencies(self): return self.info.dependencies if self.info else None
    @property
    def changelog(self): return self.info.changelog if self.info else None

    FIELDS = Fields(Subfields(ModVer, 'ver'), Subfields(ModVerInfo, 'info'))

@dataclass(slots=True, match_args=False)
class ModVerMatch:
    ver: VerMatch
    loader: Loader|None
    mcver: McVerMatch
    mcver_fallback: McVerMatch|None = None
    ver_str_match: str|None = None

    RESULT_FAIL: ClassVar[int] = 0
    RESULT_FALLBACK: ClassVar[int] = 1
    RESULT_SUCCESS: ClassVar[int] = 2

    def test_no_fallback(self, v: ModVer): return self.test(v, fallback=False)
    def test(self, v: ModVer, *, fallback: bool = True):
        if not self.ver(v.version): return self.RESULT_FAIL
        if self.loader and v.loaders and self.loader not in v.loaders: return self.RESULT_FAIL
        if self.ver_str_match and self.ver_str_match.lower() not in v.version_string.lower(): return self.RESULT_FAIL

        if any(map(self.mcver, v.mcversions)):
            return self.RESULT_SUCCESS
        if fallback and self.mcver_fallback and any(map(self.mcver_fallback, v.mcversions)):
            return self.RESULT_FALLBACK
        return self.RESULT_FAIL


@dataclass(slots=True, match_args=False)
class ModDesc:
    id: str
    type: Type
    name: str
    title: str|None = None
    updated: datetime|None = None
    created: datetime|None = None
    license: License|None = None
    short_desc: str|None = None
    desc: str|None = None
    client_side: SideSupport|None = None
    server_side: SideSupport|None = None
    issues_url: str|None = None
    source_url: str|None = None
    wiki_url: str|None = None
    discord_url: str|None = None

    FIELDS = Fields(
        Field('Id', 'id', 'i', style=Styles.grey),
        Field('Type', 'type', 't'),
        Field('Name', 'name', 'n', style=Styles.yellow_italic),
        Field('Title', 'title', 't', style=Styles.yellow_bold),
        Date('Updated', 'updated', 'u', 'du'),
        Date('Created', 'created', 'dc'),
        Field('Desc', 'short_desc', 's'),
        Field('Desc', 'desc', 'd'),
        Field('License', 'license', 'lic', 'l'),
        Field('Client', 'client_side', 'sc'),
        Field('Server', 'server_side', 'ss'),
        Link('Issues', 'issues_url', 'li'),
        Link('Source', 'source_url', 'ls'),
        Link('Wiki', 'wiki_url', 'lw'),
        Link('Discord', 'wiki_url', 'ld'))


@dataclass(slots=True, match_args=False)
class ModInfo:
    checked: datetime
    mod_desc: ModDesc
    versions: list[ModVer]
    version_info: dict[str, ModVerInfo]

    FIELDS = Fields(Date('Checked', 'checked', 'c'), Subfields(ModDesc, 'mod_desc'))

    @property
    def id(self) -> str: return self.mod_desc.id
    @property
    def type(self) -> Type: return self.mod_desc.type
    @property
    def name(self) -> str: return self.mod_desc.name
    @property
    def title(self) -> str: return self.mod_desc.title
    @property
    def short_desc(self) -> str|None: return self.mod_desc.short_desc
    @property
    def desc(self) -> str|None: return self.mod_desc.desc
    @property
    def client_side(self) -> SideSupport|None: return self.mod_desc.client_side
    @property
    def server_side(self) -> SideSupport|None: return self.mod_desc.server_side
    @property
    def issues_url(self) -> str|None: return self.mod_desc.issues_url
    @property
    def source_url(self) -> str|None: return self.mod_desc.source_url
    @property
    def wiki_url(self) -> str|None: return self.mod_desc.wiki_url
    @property
    def discord_url(self) -> str|None: return self.mod_desc.discord_url

    def get_version(self, id: str) -> ModVer|None:
        return next(filter(lambda v: v.id == id, self.versions), None)

    def get_versions(self, mvm: ModVerMatch):
        versions = list(filter(mvm.test_no_fallback, self.versions))
        if not versions: versions = list(filter(mvm.test, self.versions))
        return sorted(versions, reverse=True)
        # return sorted(list(filter(lambda v: (match(v.version) and any(map(mcver, v.mcversions)) and (not loader or not v.loaders or loader in v.loaders)), self.versions)), reverse=True)

    def get_latest_version(self, mvm: ModVerMatch): return next(iter(self.get_versions(mvm)), None)

    def __post_init__(self):
        self.versions.sort(reverse=True)
