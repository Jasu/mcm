from datetime import datetime
from dataclasses import dataclass, replace
from operator import is_not, attrgetter
from functools import partial
import operator
from itertools import chain
from enum import Enum, EnumMeta, Flag, auto
from typing import Any, Callable, ClassVar, Iterable, NamedTuple
from rich.protocol import is_renderable
from rich.console import Console
from rich.style import Style
from rich.segment import Segment, Segments
from rich.syntax import Syntax
from rich.table import Column, Table
from rich.text import Text
from rich.theme import Theme
from rich.rule import Rule as RichRule
from types import SimpleNamespace
from glob import iglob
import yaml
import os.path
from os import makedirs, access, R_OK, unlink
from shutil import copyfile, rmtree
from difflib import SequenceMatcher

__all__ = ('as_props', 'as_table', 'pipes', 'commas', 'console', 'Date', 'Field', 'Fields', 'fmt', 'Link', 'PrettyEnum', 'PrettyFlag', 'print', 'spaces', 'Styles', 'Subfields', 'Syms', 'table', 'coalesce', 'parse_yaml_file', 'ensure_empty_dir', 'checkabs', 'syntax', 'syntax_diff', 'cpfile', 'rule', 'Rule')

console = Console(
    emoji=False,
    markup=False,
    color_system='truecolor',
    theme=Theme({
        'repr.indent': 'deep_pink4',
        'rule.line': 'bright_magenta',
        'pretty.string_key': 'orchid',
        'pretty.string_quote': 'bold green_yellow',
        'pretty.string_key_quote': 'bold  pale_turquoise1',
    })
)

print = console.print

StyleIn = Style|str|None

Styles = SimpleNamespace(
    bold=Style.parse('bold'),
    italic=Style.parse('italic'),

    bg_dark_magenta=Style.parse('on dark_magenta'),
    dark_yellow=Style.parse('yellow'),
    blue=Style.parse('bright_blue'),
    blue_bold=Style.parse('bright_blue bold'),
    blue_italic=Style.parse('bright_blue italic'),
    yellow=Style.parse('bright_yellow'),
    yellow_bold=Style.parse('bright_yellow bold'),
    yellow_italic=Style.parse('bright_yellow italic'),
    yellow_bold_italic=Style.parse('bright_yellow bold italic'),
    cyan=Style.parse('bright_cyan'),
    cyan_bold=Style.parse('bright_cyan bold'),
    cyan_bold_italic=Style.parse('bright_cyan bold italic'),
    cyan_italic=Style.parse('bright_cyan italic'),
    dark_cyan=Style.parse('cyan'),
    dark_cyan_bold=Style.parse('cyan bold'),
    dark_cyan_italic=Style.parse('cyan italic'),
    red=Style.parse('bright_red'),
    red_bold=Style.parse('bright_red bold'),
    red_italic=Style.parse('bright_red italic'),
    dark_red=Style.parse('red'),
    dark_red_bold=Style.parse('red bold'),
    green=Style.parse('bright_green'),
    green_bold=Style.parse('bright_green bold'),
    green_italic=Style.parse('bright_green italic'),
    purple=Style.parse('purple'),
    purple_italic=Style.parse('purple italic'),
    dark_grey=Style.parse('grey42'),
    dark_grey_bold=Style.parse('grey42 bold'),
    dark_grey_bold_italic=Style.parse('grey42 bold italic'),
    dark_grey_italic=Style.parse('grey42 italic'),
    grey=Style.parse('grey63'),
    grey_bold=Style.parse('grey63 bold'),
    grey_italic=Style.parse('grey63 italic'),
    magenta=Style.parse('bright_magenta'),
    magenta_bold=Style.parse('bright_magenta bold'),
    magenta_italic=Style.parse('bright_magenta italic'),
    dark_magenta=Style.parse('magenta'),
    dark_magenta_bold=Style.parse('magenta bold'),
    dark_magenta_italic=Style.parse('magenta italic'),
    orange=Style.parse('orange1'),
    orange_bold=Style.parse('orange1 bold'),
    orange_italic=Style.parse('orange1 italic'),

    gold_dim=Style.parse('gold3'),
    yellow_dim=Style.parse('wheat4'),
    yellow_dim_italic=Style.parse('wheat4 italic'),

    header=Style.parse('bright_cyan bold'),
    num_pos=Style.parse('bright_green italic'),
    num_neg=Style.parse('bright_red italic'),
    num_zero=Style.parse('grey63 italic'),
    ellipsis=Style.parse('bright_yellow bold'),

    fmt_unknown = Style.parse('wheat4 italic'),

    warn_bg=Style.parse('black bold on bright_yellow')
)

Syms = SimpleNamespace(
    warn     = Text.styled(' WARN ', Styles.warn_bg),

    nl       = Text('\n'),
    lparen   = Text.styled('(', Styles.bold),
    rparen   = Text.styled(')', Styles.bold),
    colon    = Text.styled(':', Styles.bold),
    any      = Text.styled('*', Styles.grey_bold),
    at       = Text.styled('@', Styles.bold),
    nullset  = Text.styled('∅', Styles.grey_bold),
    arrow    = Text.styled('→', Styles.bold),
    comma    = Text.styled(', ', Styles.bold),
    dot    = Text.styled('.', Styles.bold),
    space    = Text(' '),
    true     = Text.styled('True', Styles.num_pos),
    false    = Text.styled('False', Styles.num_neg),
    none     = Text.styled('None', Styles.num_zero),
    ellipsis = Text.styled('…', Styles.yellow_bold),
    pipe     = Text.styled('|', Styles.bold),
    rule_prefix = Text.styled('─── ', style='rule.line')
)

def to_style(style: StyleIn) -> Style|None:
    if style.__class__ is str:
        return getattr(Styles, style, None) or Style.parse(style)
    return style

def yield_texts(arg: Any, style: Style|None = None):
    if hasattr(arg, '__rich_text__'):
        yield arg.__rich_text__()
    elif not isinstance(arg, (str, bytes)) and isinstance(arg, Iterable):
        for ch in arg: yield from yield_texts(ch, style)
    else:
        yield fmt(arg, style)

def commas(*args, style: StyleIn = None) -> Text:
    return Syms.comma.join(yield_texts(args, to_style(style)))
def pipes(*args, style: StyleIn = None) -> Text:
    return Syms.pipe.join(yield_texts(args, to_style(style)))
def spaces(*args, style: StyleIn = None) -> Text:
    return Syms.space.join(yield_texts(args, to_style(style)))

def num_style(val: float) -> Style:
    if val > 0: return Styles.num_pos
    return Styles.num_neg if val else Styles.num_zero

def fmt(val: Any, style: StyleIn = None) -> Text:
    if hasattr(val, '__rich_text__'): return val.__rich_text__()
    if hasattr(val, '__rich__'): return val.__rich__()
    match val:
        case None: return Syms.none
        case True: return Syms.true
        case False: return Syms.false
        case Text(): return val
        case int(): return Text.styled(str(val), style or num_style(val))
        case float(): return Text.styled(f'{val:.4f}', style or num_style(val))
        case set()|frozenset()|list()|tuple():
            return commas(val)
        case datetime(): return Text.styled(val.isoformat(), style) if style else Text(val.isoformat())
        case str(): return Text.styled(val, style) if style else Text(val)
        case _:
            if is_renderable(val): return val
            return Text.styled(str(val), style or Styles.fmt_unknown)

def parse_col(col: str|Style|tuple[str, Style], kwargs) -> Column:
    justify, style = None, None
    match col:
        case str()|Text(): pass
        case Style() as style: col = ''
        case (str()|Text() as col, Style() as style): pass
        case _: raise ValueError(f'Unsupported column type {col} ({type(col)})')
    conf = ()
    if col.__class__ is str and ':' in col:
        label, _, conf = col.rpartition(':')
        for c in conf:
            match c:
                case '<': justify='left'
                case '>': justify='right'
                case '!':
                    justify=justify or 'right'
                    style = style or Styles.header
    else:
        label = col
    if label: kwargs['show_header'] = True
    return Column(label, style=style, justify=justify or 'left')

def maybe_fmt(val: Any, col: Column):
    if val.__class__ in (str, Text): return val or None
    if isinstance(val, (PrettyFlag, PrettyEnum)): return val.__rich__()
    if col.style is None: return fmt(val)
    if not col.style.color: return fmt(val, col.style)
    match val:
        case int()|bool()|None: return str(val)
        case float(): return f'{val:.4f}'
        case ()|[]: return None
        case (inner, )|[inner]: return maybe_fmt(inner, col)
        case _: return fmt(val, col.style)

def table(rows, /, *cols, **kwargs):
    kwargs = kwargs | dict(show_header=bool(cols))
    cols = [parse_col(col, kwargs) for col in cols]
    t = Table(*cols, **kwargs, header_style=Styles.header)
    for row in rows:
        row_style = None
        if row[0].__class__ is Style:
            row_style, *row = row
        t.add_row(*map(maybe_fmt, row, cols), style=row_style)
    return t

class PrettyWrapper(NamedTuple):
    value: Any
    name: str|None
    style: StyleIn
    def __truediv__(self, value): return PrettyWrapper(self.value, value.name or self.name, value.style or self.style)
    def __rtruediv__(self, value): return PrettyWrapper(value, self.name, self.style)

class PrettyEnumDict:
    __slots__ = ('target', 'styles')
    helper_funcs: ClassVar[dict[str, Callable[..., PrettyWrapper]]] = {
        'pretty': lambda style = None, name = None: PrettyWrapper(None, name, style),
        'auto': lambda style = None, name = None: PrettyWrapper(auto(), name, style),
        'style': lambda style: PrettyWrapper(None, None, style),
        'color': lambda style: PrettyWrapper(None, None, style),
        'name': lambda name: PrettyWrapper(None, name, None),
    }
    def __init__(self, target):
        object.__setattr__(self, 'target', target)
        object.__setattr__(self, 'styles', [])

    def __getitem__(self, key): return PrettyEnumDict.helper_funcs.get(key) or self.target[key]
    def __setitem__(self, name, value):
        if not name.startswith('_') and not callable(value) and not hasattr(value, '__get__'):
            pretty_name = name
            pretty_style = Styles.cyan
            if value.__class__ is PrettyWrapper:
                pretty_name = value.name or pretty_name
                pretty_style = value.style or pretty_style
                value = value.value
                pretty_style = Style.parse(pretty_style) if isinstance(pretty_style, str) else pretty_style
            self.styles.append((name, pretty_name, pretty_style, Text.styled(pretty_name, pretty_style)))
        return self.target.__setitem__(name, value)
    def __contains__(self, name): return name in PrettyEnumDict.helper_funcs or name in self.target
    def __delitem__(self, name): return self.target.__delitem__(name)
    def __missing__(self, name): return self.target.__missing__(name)
    def __iter__(self): return self.target.__iter__()
    def __len__(self): return self.target.__len__()
    def __bool__(self): return self.target.__bool__()
    def __getattr__(self, attr): return getattr(self.target, attr)
    def __setattr__(self, attr, value): return setattr(self.target, attr, value)

class PrettyEnumMeta(EnumMeta):
    @classmethod
    def __prepare__(metacls, cls, bases, **kwds):
        return PrettyEnumDict(EnumMeta.__prepare__(cls, bases, **kwds))
    def __new__(cls, name, bases, members):
        styles = members.styles
        result = EnumMeta.__new__(cls, name, bases, members.target)
        max_width = 0
        for k, short_name, style, name_text in styles:
            result[k].short_name = short_name
            result[k].style = style
            result[k].name_text = name_text
        return result

class PrettyEnum(Enum, metaclass=PrettyEnumMeta):
    def __repr__(self): return f'{self.__class__.__qualname__}.{self.name}'
    def __str__(self): return self.short_name
    def __rich__(self): return self.name_text

class PrettyFlag(Flag, metaclass=PrettyEnumMeta):
    def _get_components(self):
        cls = self.__class__
        return [cls[s] for s in Flag.__str__(self).removeprefix(cls.__name__ + '.').split('|')]

    def __repr__(self):
        if self.name: return f'{self.__class__.__qualname__}.{self.name}'
        return '|'.join(map(repr, self._get_components()))

    def _init(self):
        components = self._get_components()
        self.short_name = '|'.join(map(str, components))
        self.style = components[0].style
        self.name_text = Syms.pipe.join(s.name_text for s in components)
    def __str__(self):
        if not hasattr(self, 'short_name'): self._init()
        return self.short_name
    def __rich__(self):
        if not hasattr(self, 'name_text'): self._init()
        return self.name_text

def format_link(s, style: Style|None = None): return Text(f'<{s}>', style or Styles.yellow_italic)
def format_date(s, style: Style|None = None): return Text(f'{s.strftime("%d.%m.%y %H:%M")}', style or Styles.green_italic)

@dataclass(slots=True, init=False)
class Field:
    title: str
    keys: tuple[str]
    getter: Callable
    formatter: Callable[..., Text|None]
    style: Style|None

    def __init__(self, title: str, getter: str|Callable[[Any], Any], *keys: str, formatter: Callable[..., Text|None] = fmt, style: Style|None = None):
        self.title = title
        self.keys = keys + (getter, ) if getter.__class__ is str else keys
        self.getter = getter if callable(getter) else attrgetter(getter)
        self.formatter = formatter
        self.style = style

    def __call__(self, obj): 
        v = self.getter(obj)
        if hasattr(v, '__rich__') or hasattr(v, '__rich_console__'):
            return v
        return v if v is None else self.formatter(v, self.style)

    def as_subobject(self, getter: Callable, prefix: str, title: str):
        oldgetter = self.getter
        def wrapped_getter(o):
            nonlocal getter, oldgetter
            o = getter(o)
            return o if o is None else oldgetter(o)
        return Field(title + self.title, wrapped_getter, *(prefix + k for k in self.keys), formatter=self.formatter, style=self.style)

    def collect(self): return [self]

Link = partial(Field, formatter = format_link)
Date = partial(Field, formatter = format_date)

@dataclass(slots=True)
class Subfields:
    title: str|None
    cls: type
    getter: Callable
    prefix: str

    def __init__(self, cls: type, getter: str|Callable[[Any], Any], prefix: str = '', *, title: str|None = None):
        self.title = f'{title} ' if title else ''
        self.cls = cls
        self.getter = getter if callable(getter) else attrgetter(getter)
        self.prefix = prefix

    def collect(self): return [f.as_subobject(self.getter, self.prefix, self.title) for f in self.cls.FIELDS.collect()]

@dataclass(slots=True)
class Fields:
    fields: tuple[Field|Subfields]

    def __init__(self, *fields):
        self.fields = fields

    def collect(self):
        return chain.from_iterable(f.collect() for f in self.fields)

    def by_key(self):
        result = {}
        for f in self.collect():
            result.update(dict.fromkeys(f.keys, f))
        return result

    def get_fields(self, fields: str|Iterable[str]|None):
        if fields is None: return self.collect()
        if fields.__class__ is str: fields = fields.split(',')
        by_key = self.by_key()
        return [by_key[f] for f in fields]

    def table(self, fields: str|Iterable[str]|None, objs: Iterable):
        fields = self.get_fields(fields)
        return table([[f(o) for f in fields] for o in objs], *(f.title for f in fields))

    def props(self, fields: str|Iterable[str]|None, obj):
        fields = self.get_fields(fields)
        table = Table.grid(padding=(0,1))
        for f in fields:
            if v := f(obj): table.add_row(Text.styled(f.title + ':', Styles.cyan_bold), f(obj))
        return table

def as_props(obj, fields): return obj.FIELDS.props(fields, obj)
def as_table(cls, objs, fields): return cls.FIELDS.table(fields, objs)

is_not_none = partial(is_not, None)
filter_not_none = partial(filter, is_not_none)
def coalesce(*args): return next(filter_not_none(args), None)

SENTINEL = object()
def parse_yaml_file(p: str, *, default = SENTINEL):
    if default is not SENTINEL and not access(p, R_OK): return default
    with open(p, 'r') as f: return yaml.safe_load(f)

def checkabs(path: str):
    if not os.path.isabs(path): raise Exception(f'Path {path} is not absolute')
    return path

def cpfile(src: str, dst: str):
    checkabs(src)
    checkabs(dst)
    if src.endswith('/'): raise ValueError('Path to file ends with /')
    if dst.endswith('/'): raise ValueError('Path to file ends with /')
    parent = os.path.dirname(dst)
    makedirs(parent, exist_ok=True)
    copyfile(src, dst, follow_symlinks=False)

def ensure_empty_dir(dirpath: str, *, delglob: str = '*', recursive: bool = True):
    checkabs(dirpath)
    if not os.path.isdir(dirpath):
        if os.path.exists(dirpath):
            raise Exception(f'{dirpath} exists and is not a directory.')
        makedirs(dirpath)
        return dirpath
    for f in iglob(delglob, root_dir=dirpath):
        p = os.path.join(dirpath, f)
        if recursive and os.path.isdir(p):
            rmtree(p)
        else:
            unlink(p)

def syntax(code: str, *, syntax: str = None, filename: str = None, code_width:int|None = None, background_color='#181228', line_numbers=True):
    if syntax is None:
        if filename:
            _, ext = os.path.splitext(filename)
            match ext:
                case '.py': syntax = 'python'
                case '.toml': syntax = 'toml'
                case '.json': syntax = 'json'
                case '.yml'|'.yaml': syntax = 'yaml'
                case '.ini': syntax = 'ini'
                case _: raise ValueError(f'Unsupported file extension {ext}')
        else:
            syntax = python
            
    return Syntax(code, syntax, theme='github-dark', background_color=background_color, indent_guides=True, line_numbers=line_numbers,
                  code_width=code_width)
    
def syntax_diff(old: str, new: str, **kwargs):
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    lineno_len = len(str(max(len(old_lines), len(new_lines))))
    width = console.width - lineno_len * 2 - 4
    old_syntax = console.render_lines(syntax(old, line_numbers=False, background_color='#501408', code_width = width, **kwargs), pad=False, new_lines=True)
    new_syntax = console.render_lines(syntax(new, line_numbers=False, code_width = width, **kwargs), pad=False, new_lines=True)

    old_style = Style.parse('bright_red on #12061E')
    old_style_bold = Style.parse('bright_red bold on #12061E')
    new_style = Style.parse('bright_green on #12061E')
    new_style_bold = Style.parse('bright_green bold on #12061E')
    dummy_style_bold = Style.parse('#8A30EA bold on #12061E')
    bg_style = Style.parse('on #12061E')

    def format_lineno(n, style):
        n = str(n).rjust(lineno_len)
        return Segment(f' {n} ', style)
    new_lineno_del = Segment(f' {"-" * lineno_len} ', old_style_bold)
    old_lineno_add = Segment(f' {"+" * lineno_len} ', new_style_bold)
    pad_line = [Segment(' ... ' + ' ' * (2 * lineno_len - 3), dummy_style_bold),
                Segment(' ' * width, Style.parse('on #181228')), Segment('\n')]
    empty_lineno = Segment(' ' * (2 + lineno_len), bg_style)
    added_bg = Style.parse('on #186024')

    groups = SequenceMatcher(None, old_lines, new_lines).get_grouped_opcodes(2)
    result = []
    is_first = True
    for chunk in groups:
        if not is_first: result.extend(pad_line)
        is_first = False
        for op, old1, old2, new1, new2 in chunk:
            if op == 'equal':
                for i, j in zip(range(old1, old2), range(new1, new2)):
                    result.extend([format_lineno(i + 1, old_style), format_lineno(j + 1, new_style), *new_syntax[j]])
            if op == 'delete' or op == 'replace':
                for i in range(old1, old2):
                    result.extend([format_lineno(i + 1, old_style_bold), new_lineno_del, *old_syntax[i]])
            if op == 'insert' or op == 'replace':
                for i in range(new1, new2):
                    result.extend([old_lineno_add, format_lineno(i + 1, new_style_bold), *Segment.apply_style(new_syntax[i], post_style=added_bg)])
    return Segments(result)


class Rule:
    def __init__(self, title: Text|str|None = None, *, align='left', **kwargs):
        if title and align == 'left':
            if isinstance(title, str): title = Text.styled(title, Styles.bold)
            title = Syms.rule_prefix + title
        self.rule = RichRule(title, align=align, **kwargs)

    def __rich_console__(self, *_):
        yield Syms.nl
        yield self.rule
    
def rule(title: Text|str|None = None, *, align='left', **kwargs) -> None:
    print(Rule(title, align=align, **kwargs))
