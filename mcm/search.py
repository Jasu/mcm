import regex
from dataclasses import dataclass, field
from typing import Callable, ClassVar
from functools import partial
import operator

sort_key = operator.itemgetter(0)
strip_results = partial(map, operator.itemgetter(1))
def identity(s): return s

@dataclass(slots=True)
class SearchIndex:
    matches: list[tuple[str, ...]] = field(init=False, default_factory=list)
    field_boost: tuple[int, ...]|None = None
    match_transform: Callable[[str], str] = identity
    results: list = field(init=False, default_factory=list)
    max_edit_distance: int|tuple[int,int,int] = 0

    REMOVE_NONALPHA: ClassVar[Callable[[str], str]] = partial(regex.compile(r'[^a-z]').sub, '')
    REMOVE_NONALNUM: ClassVar[Callable[[str], str]] = partial(regex.compile(r'[^a-z0-9]').sub, '')
    NONALNUM_PUNCTUATION: ClassVar[Callable[[str], str]] = partial(regex.compile(r'[^a-z0-9]+').sub, ' ')
    NONALPHA_PUNCTUATION: ClassVar[Callable[[str], str]] = partial(regex.compile(r'[^a-z]+').sub, ' ')
        
    def __post_init__(self):
        if self.max_edit_distance == (0, 0, 0):
            self.max_edit_distance = 0
        elif self.max_edit_distance and isinstance(self.max_edit_distance, int):
            self.max_edit_distance = (self.max_edit_distance, self.max_edit_distance, self.max_edit_distance)

    def append(self, value, *texts: str):
        self.matches.append(tuple(map(self.match_transform, map(str.lower, texts))))
        self.results.append(value)

    def search(self, keyword: str):
        keyword = self.match_transform(keyword.lower())
        if self.max_edit_distance:
            match_str = self.compile_regex(keyword).search
            max_dist = sum(self.max_edit_distance) + 1
            score_str = lambda m, s: (max_dist - sum(m.fuzzy_counts)) + (2 if m.start() == 0 else (1 if s[m.start()] == ' ' else 0)) + (3 if m.end() == len(s) else (2 if s[m.end()] == ' ' else 0))
        else:
            match_str = lambda s: keyword in s
            score_str = lambda _, s: 3 if s.startswith(keyword) else (2 if s.endswith(keyword) else 1)
        lnm = partial(map, match_str)
        results = []
        for i, ln in enumerate(self.matches):
            score = 0
            for f, b in zip(ln, self.field_boost):
                m = match_str(f)
                if m: score += b * score_str(m, f)
            if score: results.append((score, self.results[i])) 
        return list(strip_results(sorted(results, reverse=True, key=sort_key)))
            
    def compile_regex(self, keyword: str):
        i, d, e = self.max_edit_distance
        return regex.compile(f'(?:{regex.escape(keyword)})''{'f'i<={i},d<={d},e<={e}''}', regex.BESTMATCH)


    

