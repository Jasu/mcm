from .utils import PrettyEnum, PrettyFlag, Styles, Syms
from dataclasses import dataclass, replace
from functools import partial, total_ordering
from itertools import zip_longest
import regex
import os.path
from rich.text import Text
from typing import Any, ClassVar
from types import SimpleNamespace

__all__ = ('License', 'LicenseType', 'Loader', 'Side', 'SideSupport', 'Source',
           'Type', 'McVer', 'McVerMatch', 'McVerType', 'Ver', 'VerMatch', 'VerType')

class Type(str, PrettyEnum):
    MOD = 'mod' / pretty(Styles.magenta, 'Mod')
    SHADERPACK = 'shaderpack' / pretty(Styles.yellow, 'Shaderpack')
    DATAPACK = 'datapack' / pretty(Styles.cyan, 'Datapack')
    RESOURCEPACK = 'resourcepack' / pretty(Styles.green, 'Resourcepack')

    def serialize(self): return None if self == Type.MOD else self.value
    @classmethod
    def deserialize(cls, val):
        if not val: return cls.MOD
        return cls(val.lower())

class Loader(str, PrettyEnum):
    FORGE      = 'forge' / pretty(Styles.green, 'Forge')
    FABRIC     = 'fabric' / pretty(Styles.orange, 'Fabric')
    LITELOADER = 'liteloader' / pretty(Styles.red, 'LiteLoader')
    MODLOADER  = 'modloader' / pretty(Styles.red, 'ModLoader')
    QUILT      = 'quilt' / pretty(Styles.red, 'Quilt')
    RIFT       = 'rift' / pretty(Styles.red, 'Rift')

class LicenseType(str, PrettyEnum):
    CLOSED     = 'closed' / pretty(Styles.orange)
    PERMISSIVE = 'permissive' / pretty(Styles.green)
    COPYLEFT   = 'copyleft' / pretty(Styles.cyan)
    LGPL       = 'lgpl' / pretty(Styles.yellow_dim)
    CUSTOM     = 'custom' / pretty(Styles.orange_bold)
    DANGEROUS  = 'dangerous' / pretty(Styles.red_bold)

class McVerType(int, PrettyEnum):
    RELEASE  = 4 / pretty(Styles.green)
    RC       = 3 / pretty(Styles.cyan)
    SNAPSHOT = 2 / pretty(Styles.red)
    PRE      = 1 / pretty(Styles.yellow)
    UNKNOWN  = 0 / pretty(Styles.red_italic)

class VerType(int, PrettyEnum):
    RELEASE = 3 / pretty(Styles.green)
    BETA    = 2 / pretty(Styles.yellow)
    ALPHA   = 1 / pretty(Styles.red)
    @classmethod
    def deserialize(cls, t):
        if t.__class__ is int: return cls(t)
        match (t or '').lower():
            case 'release'|'r'|'': return cls.RELEASE
            case 'alpha'|'a': return cls.ALPHA
            case 'beta'|'b': return cls.BETA
            case _: raise ValueError(t)
    def serialize(self):
        return self.name.lower()

class SourceType(str, PrettyEnum):
    MODRINTH   = 'modrinth' / style(Styles.green)
    CURSEFORGE = 'curseforge' / style(Styles.yellow)
    LOCAL      = 'local'  / style(Styles.magenta)

class Side(PrettyFlag):
    NONE =   0 / style(Styles.grey_bold)
    CLIENT = auto(Styles.cyan)
    SERVER = auto(Styles.magenta)
    BOTH =   (CLIENT|SERVER) / style(Styles.yellow_bold)

    @classmethod
    def deserialize(cls, value):
        if not value: return cls.BOTH
        return cls[value.upper()]

    def serialize(self):
        if self == Side.BOTH: return None
        return self.name.lower()

class SideSupport(str, PrettyEnum):
    UNSUPPORTED = "unsupported" / style(Styles.grey)
    OPTIONAL    = "optional" / style(Styles.cyan)
    REQUIRED    = "required" / style(Styles.green_bold)

@dataclass(frozen=True, unsafe_hash=True, slots=True, match_args=False, repr=False)
class Source:
    type: SourceType
    path: str|None = None

    MODRINTH: ClassVar[Any]
    CURSEFORGE: ClassVar[Any]

    @property
    def islocal(self): return self.type is SourceType.LOCAL
    def __repr__(self):
        if self == Source.MODRINTH: return 'Source.MODRINTH'
        if self == Source.CURSEFORGE: return 'Source.CURSEFORGE'
        assert self.path is not None
        return f'Source({self.type!r}, {self.path!r})'

    def __str__(self):
        if self == Source.MODRINTH: return 'modrinth'
        if self == Source.CURSEFORGE: return 'curseforge'
        return os.path.expanduser(self.path)

    def __rich__(self): return Text.styled(str(self), self.type.style)

    def serialize(self) -> str: return None if self == Source.MODRINTH else str(self)

    @classmethod
    def deserialize(cls, val):
        match (val or '').lower():
            case ''|'modrinth': return Source.MODRINTH
            case 'curse'|'curseforge': return Source.CURSEFORGE
            case _: return Source(SourceType.LOCAL, val)
Source.MODRINTH = Source(SourceType.MODRINTH)
Source.CURSEFORGE = Source(SourceType.CURSEFORGE)

@dataclass(frozen=True, unsafe_hash=True, slots=True, match_args=False, repr=False)
class License:
    type: LicenseType
    name: str
    STD: ClassVar[dict]
    def __repr__(self):
        for k,v in License.STD.items():
            if v == self:
                return f'License.STD[{k!r}]'
        return f'License({self.type!r}, {self.name!r})'
    def __str__(self): return self.name
    def __rich__(self): return Text.styled(self.name, self.type.style)
    def serialize(self) -> str|list:
        for k,v in License.STD.items():
            if v == self: return k
        return [self.type.value, self.name]

    @classmethod
    def deserialize(cls, val):
        if val.__class__ is str: return License.STD[val]
        return License(LicenseType(val[0]), val[1])

License.STD = dict(
    Closed = License(LicenseType.CLOSED, 'Closed'),

    PD = License(LicenseType.PERMISSIVE, 'Public Domain'),
    MIT = License(LicenseType.PERMISSIVE, 'MIT'),
    BSD = License(LicenseType.PERMISSIVE, 'BSD'),
    ISC = License(LicenseType.PERMISSIVE, 'ISC'),
    zlib = License(LicenseType.PERMISSIVE, 'zlib'),
    Apache = License(LicenseType.PERMISSIVE, 'Apache'),
    CC0 = License(LicenseType.PERMISSIVE, 'CC0'),
    Unlicense = License(LicenseType.PERMISSIVE, 'Unlicense'),

    GPL = License(LicenseType.COPYLEFT, 'GPL'),

    CC = License(LicenseType.LGPL, 'CreativeCommons'),
    MPL = License(LicenseType.LGPL, 'MPL'),
    LGPL = License(LicenseType.LGPL, 'LGPL'),

    AGPL = License(LicenseType.DANGEROUS, 'AGPL')
)

@total_ordering
@dataclass(frozen=True, unsafe_hash=True, slots=True, match_args=False, repr=False)
class McVer:
    major: int
    minor: int
    patch: int
    suffix: str = ''
    snapshot: str = ''

    SNAPSHOTS: ClassVar[list]
    VERSIONS: ClassVar[list]

    @property
    def type(self) -> McVerType:
        if self.snapshot: return McVerType.SNAPSHOT
        if not self.suffix: return McVerType.RELEASE
        if self.suffix.startswith('rc'): return McVerType.RC
        if self.suffix.startswith('pre'): return McVerType.PRE
        return McVerType.UNKNOWN


    def __repr__(self):
        sn = f', {self.snapshot}' if self.snapshot else ''
        return f'McVer({self.major}, {self.minor}, {self.patch}{sn})'

    def __str__(self):
        r = f'{self.major}.{self.minor}'
        if self.patch: r = f'{r}.{self.patch}'
        if self.suffix: r = f'{r}-{self.suffix}'
        return f'{r}-{self.snapshot}' if self.snapshot else r

    def __rich__(self): return Text.styled(str(self), self.type.style)

    @property
    def cmp(self): return (self.major, self.minor, self.patch, self.suffix or 'release', self.snapshot or 'zzzzzz')

    def __lt__(self, other):
        if other.__class__ is not McVer: return NotImplemented
        return self.cmp < other.cmp

    def serialize(self) -> str:
        if self.snapshot: return self.snapshot
        return str(self)

    @classmethod
    def deserialize(cls, ver: str):
        ver, _, suffix = ver.partition('-')
        if '.' in ver:
            parts = list(map(int, ver.split('.')))
            if len(parts) == 2: parts = [*parts, 0]
            return McVer(*parts, suffix)
        for v in cls.SNAPSHOTS:
            if v.snapshot <= ver:
                return replace(v, snapshot=ver)
        raise ValueError(f'Unknown snapshot {ver}')

McVer.VERSIONS = [
    McVer(1, 12, 0), McVer(1, 12, 1), McVer(1, 12, 2),
    McVer(1, 13, 0), McVer(1, 13, 1), McVer(1, 13, 2),
    McVer(1, 14, 0), McVer(1, 14, 1), McVer(1, 14, 2), McVer(1, 14, 3), McVer(1, 14, 4),
    McVer(1, 15, 0), McVer(1, 15, 1), McVer(1, 15, 2),
    McVer(1, 16, 0), McVer(1, 16, 2), McVer(1, 16, 3), McVer(1, 16, 4), McVer(1, 16, 5),
    McVer(1, 17, 0), McVer(1, 17, 1), 
    McVer(1, 18, 0), McVer(1, 18, 1), McVer(1, 18, 2),
    McVer(1, 19, 0), McVer(1, 19, 1), McVer(1, 19, 2), McVer(1, 19, 3),
]

McVer.SNAPSHOTS = [
  McVer(1, 19, 3, 'pre1', '22w42a'),
  McVer(1, 19, 1, 'pre1', '22w24a'),
  McVer(1, 19, 0, 'pre1', '22w11a'),
  McVer(1, 18, 2, 'pre1', '22w03a'),
  McVer(1, 18, 0, 'pre1', '21w37a'),
  McVer(1, 17, 0, 'pre1', '20w45a'),
  McVer(1, 16, 2, 'pre1', '20w27a'),
  McVer(1, 16, 0, 'pre1', '20w06a'),
  McVer(1, 15, 0, 'pre1', '19w34a'),
  McVer(1, 14, 0, 'pre1', '18w43a'),
  McVer(1, 13, 1, 'pre1', '18w30a'),
  McVer(1, 13, 0, 'pre1', '17w43a'),
  McVer(1, 12, 1, 'pre1', '17w31a'),
  McVer(1, 12, 0, 'pre1', '17w06a'),
  McVer(1, 11, 1, '', '16w50a'),
  McVer(1, 11, 0, 'pre1', '16w32a'),
  McVer(1, 10, 0, 'pre1', '16w20a'),
  McVer(1,  9, 3, 'pre1', '16w14a'),
  McVer(1,  9, 0, 'pre1', '15w31a'),
  McVer(1,  8, 0, 'pre1', '14w02a'),
]

@dataclass(frozen=True, unsafe_hash=True, slots=True, match_args=False, repr=False)
class McVerMatch:
    ver: McVer|None
    operator: str = ''
    ANY: ClassVar[Any]

    def __call__(self, other: McVer) -> bool:
        if not self.ver: return True
        match self.operator:
            case '': return self.ver == other
            case '^': return self.ver >= other and other.minor == self.ver.minor and other.major == self.ver.major
            case _: raise Exception(f'Unknown operator {self.operator}')

    def __bool__(self): return bool(self.ver)
    def __str__(self) -> str:
        if not self.ver: return '*'
        return self.operator + self.ver.serialize()

    def __rich__(self):
        if not self.ver: return Syms.any
        return Text.styled(str(self), Styles.orange if self.operator == '^' else Styles.white)

    def serialize(self) -> str: return str(self)

    @property
    def versions(self) -> list[McVer]: return list(filter(self, McVer.VERSIONS))

    @classmethod
    def deserialize(cls, val: str):
        if val == '*': return McVerMatch.ANY
        if val.startswith('^'): return McVerMatch(McVer.deserialize(val[1:]), '^')
        return McVerMatch(McVer.deserialize(val))

McVerMatch.ANY = McVerMatch(None)

strip_ver = partial(regex.compile(r'[ \'":,()_]+|\+?(?:forge|fabric|rift)|\.jar', regex.IGNORECASE).sub, '')
ver_matches = regex.compile(r'[a-z_]+|\d+').findall
@total_ordering
@dataclass(frozen=True, unsafe_hash=True, slots=True, match_args=False, repr=False)
class Ver:
    version: tuple[int|str]
    type: VerType = VerType.RELEASE

    def __str__(self):
        version = '.'.join(map(str, self.version))
        match self.type:
            case VerType.RELEASE: return version
            case VerType.BETA: return f'{version}-BETA'
            case VerType.ALPHA: return f'{version}-ALPHA'
            case _: raise ValueError

    def __rich__(self): return Text.styled(str(self), self.type.style)

    def __repr__(self):
        if self.type is VerType.RELEASE: return f'Ver({self.version!r})'
        return f'Ver({self.version!r}, {self.type!r})'

    def __lt__(self, other):
        if other.__class__ is not Ver: return NotImplemented
        for lhs, rhs in zip_longest(self.version, other.version):
            match lhs, rhs:
                case None, _: return False
                case _, None: return True
                case int(), int():
                  if lhs < rhs: return True
                  if lhs > rhs: return False
                case 'a'|'b', int(): return True
                case int(), 'a'|'b': return False
                case _: return str(lhs) < str(rhs)
        if self.type is VerType.RELEASE: return f'Ver({self.version!r})'
        return f'Ver({self.version!r}, {self.type!r})'

    @classmethod
    def parse(cls, ver: str, type: VerType|str):
        if type.__class__ is str: type = VerType.deserialize(type)
        return Ver(tuple(ver_matches(strip_ver(ver.lower()))), type)

    @classmethod
    def deserialize(cls, ver: str):
        ver, _, type = ver.partition('-')
        def maybeint(s): return int(s) if s.isnumeric() else s
        ver = tuple(map(maybeint, ver.split('.')))
        return cls(ver, VerType.deserialize(type))

    def serialize(self):
        version = '.'.join(map(str, self.version))
        match self.type:
            case VerType.RELEASE: return f'{version}-RELEASE'
            case VerType.BETA: return f'{version}-BETA'
            case VerType.ALPHA: return f'{version}-ALPHA'
            case _: raise ValueError

    

@dataclass(frozen=True, unsafe_hash=True, slots=True, repr=False, order=True)
class VerCmp:
    ver: Ver|None = None
    operator: str = ''
    ANY: ClassVar[object]

    def __bool__(self): return bool(self.ver)

    def __call__(self, other: Ver) -> bool:
        if (ver := self.ver) is None: return True
        match self.operator:
            case '': return ver == other
            case '<': return ver < other
            case '<=': return ver <= other
            case '>': return ver > other
            case '>=': return ver >= other
            case _: raise ValueError(self.operator)

    def __str__(self): return f'{self.operator}{self.ver}' if self.ver else '*'
    def __rich__(self): return (Text.styled(self.operator, Styles.orange_bold) + self.ver.__rich__()) if self.ver else Syms.any

    @classmethod
    def deserialize(cls, val):
        if val == '*': return cls.ANY
        if val.startswith('<=') or val.startswith('>='):
            return cls(deserialize(Ver, val[2:]), val[:2])
        if val.startswith('<') or val.startswith('>'):
            return cls(deserialize(Ver, val[1:]), val[:1])
        return cls(deserialize(Ver, val), '')

    def serialize(self): return str(self)

@dataclass(frozen=True, unsafe_hash=True, slots=True, repr=False, order=True)
class VerMatch:
    criteria: tuple[VerCmp] = ()
    min_ver_type: VerType = VerType.ALPHA
    ANY: ClassVar[Any]

    def __and__(self,  other):
        if other.__class__ is not VerMatch: return NotImplemented
        return VerMatch(self.criteria + other.criteria, max(self.min_ver_type, other.min_ver_type))

    def __bool__(self):
        return bool(self.criteria or self.min_ver_type is not VerType.ALPHA)

    def __str__(self):
        if not self: return '*'
        ver = ' AND '.join(map(str, self.criteria))
        if self.operator: ver = f'{self.operator}{ver}'
        if self.min_ver_type is not VerType.ALPHA: ver = f'{ver}@{self.min_ver_type.name}'
        return ver
             
    def __rich__(self):
        if not self: return Syms.any
        ver = Text.styled(' AND ', Styles.orange_bold).join(map(VerCmp.__rich__, self.criteria))
        if self.min_ver_type is not VerType.ALPHA:
            return ver + Syms.at + self.min_ver_type.name_text
        return ver

    def __call__(self, other: Ver):
        if self.min_ver_type > other.type: return False
        return all(c(other) for c in self.criteria)

    @classmethod
    def deserialize(cls, ver: str):
        if ver == '*' or ver == '': return cls.ANY
        ver, _, type = ver.partition('@')
        match type.lower():
            case ''|'a'|'alpha': type = VerType.ALPHA
            case 'r'|'release': type = VerType.RELEASE
            case 'b'|'beta': type = VerType.BETA
            case _: raise ValueError(type)
        if ver: return cls((VerCmp.deserialize(ver), ), type)
        return cls((), type)

VerMatch.ANY = VerMatch()

