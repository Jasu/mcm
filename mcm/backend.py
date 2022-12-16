from .common import *
from .serialize import deserialize
from .modinfo import ModInfo
from .utils import Styles
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from enum import Enum
from rich.console import Group
from rich.text import Text
from rich.table import Table

__all__ = ('Category', 'SearchCriteria', 'SearchResult', 'SearchResults')

def parse_set(t: type, val: str|None):
    if val is None: return val
    return frozenset(map(partial(deserialize, t), val.split(',')))
    
class Sort(str, Enum):
    RELEVANCE = 'relevance'
    DOWNLOADS = 'downloads'
    UPDATED = 'updated'

@dataclass(slots=True, match_args=False, frozen=True, unsafe_hash=True)
class Category:
    id: str
    name: str|None = field(default=None, compare=False)
    def __str__(self): return self.id
    def __rich__(self):
        r = Text.styled(self.name or self.id, Styles.green_bold)
        return r + Text.styled(f' ({self.id})', Styles.orange_italic) if self.name else r

@dataclass(slots=True, match_args=False)
class SearchCriteria:
    query: str
    sort: Sort
    limit: int
    type: Type
    mcver: McVerMatch
    categories: frozenset[str]|None = None
    loader: Loader|None = None

    @staticmethod
    def create(query: list[str]|str, type: Type, category: str|None, sort: str|None, limit: int|None, mcver: McVerMatch, loader: Loader|None):
        return SearchCriteria(
            query if query.__class__ is str else ' '.join(query),
            Sort(sort) if sort else Sort.RELEVANCE,
            limit,
            type,
            mcver,
            frozenset(category.split(',')) if category else None,
            loader)


@dataclass(slots=True, match_args=False)
class SearchResult:
    id: str
    name: str
    downloads: int
    date_updated: datetime
    title: str
    short_desc: str|None
    type: Type
    url: str

    def to_row(self, i: int) -> tuple:
        row = [Text.styled(self.title, Styles.cyan_bold)]
        if self.short_desc: row.append(Text.styled(self.short_desc, Styles.bold))
        row.append(Text.styled(f'<{self.url}>', Styles.yellow_italic))
        return (Text.styled(f'#{i}', Styles.yellow_bold) + Text.styled(f' - {self.name}', Styles.bold),
                Group(Text(f'{self.downloads} DLs', Styles.yellow_dim_italic),
                      Text(f'Upd.: {self.date_updated.strftime("%d.%m.%y %H:%M")}', Styles.green_italic),
                      self.type),
                Group(*row))

@dataclass(slots=True, match_args=False)
class SearchResults:
    results: list[SearchResult]
    total: int

    def __rich__(self) -> Table:
        t = Table.grid(padding=1)
        for i,r in reversed(list(enumerate(self.results, 1))): t.add_row(*r.to_row(i))
        return Group(t, Text.styled(str(self.total), Styles.cyan_bold_italic) + Text.styled(' results total'))

