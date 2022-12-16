from .utils import Field, Fields, print, pipes, Subfields, commas, Styles, Syms
from .serialize import deserialize
from dataclasses import dataclass, field
from rich.text import Text
from typing import Callable, ClassVar
from rich import box
from rich.columns import Columns
from rich.table import Table
from rich.console import Group
from functools import partial, reduce, total_ordering
from asyncio import Task
from enum import Enum
import operator

SYM_FORGE = Text.styled('forge', Styles.blue_italic) + Syms.colon

@total_ordering
class Key(tuple):
    __slots__ = ()
    def __new__(cls, *args):
        match args:
            case (Key() as key, ): return key
            case ("minecraft", str() as loc): return tuple.__new__(cls, (loc, ))
            case (str(), str()): return tuple.__new__(cls, args)
            case (str() as key, ):
              ns, sep, loc = key.rpartition(':')
              if not sep or ns == 'minecraft': return tuple.__new__(cls, (loc, ))
              return tuple.__new__(cls, (ns, loc))
        raise TypeError(f'Invalid arguments for Key: Key{args!r}')

    def get_namespace(self) -> str: return 'minecraft' if len(self) == 1 else self[0]
    def get_location(self) -> str: return self[-1]

    @property
    def namespace(self) -> str: return self.get_namespace()
    @property
    def location(self) -> str: return self[-1]

    def serialize(self) -> str: return str(self)

    @classmethod
    def deserialize(cls, s) -> str: return cls(s)

    def astuple(self) -> tuple[str, str]: return  tuple(self) if len(self) == 2 else ("minecraft", self[0])
    def __lt__(self, other) -> str:
        match other:
            case Key(): return self.astuple() < other.astuple()
            case str(): return self.astuple() < Key(other).astuple()
            case _: return NotImplemented
    def __str__(self) -> str: return  f'{self[0]}:{self[1]}' if len(self) == 2 else f'minecraft:{self[0]}'
    def __repr__(self) -> str: return  f'Key({", ".join(self)})'
    def __rich_text__(self): 
        if len(self) == 1: return Text.styled(self[0], Styles.gold_dim)
        name = Text.styled(self[-1], Styles.orange_bold)
        if self[0] == 'forge': return SYM_FORGE + name
        return Text.styled(self[0], Styles.cyan_italic) + Syms.colon + name
    def __rich__(self): return self.__rich_text__()

@total_ordering
@dataclass(slots=True)
class Tag:
    key: Key
    content: frozenset[Key]|Task|None = None
    @property
    def is_resolved(self) -> bool: return isinstance(self.content, frozenset)
    def __str__(self): return f'#{self.key}'
    def __rich__(self): return Text.styled(f'#{self.key}', Styles.orange_italic)

    def resolve(self, resolver):
        match self.content:
            case frozenset(): return
            case Task(): resolver.wait_for(self)
            case None: resolver.resolve(self)
            case _: raise Exception(f'Unknown tag state {self.content!r}')

    def __eq__(self, other):
        match other:
            case Tag(): return self.key == other.key
            case Key(): return self.key == other
            case str(): return self.key == Key(other)
            case _: return NotImplemented
    def __lt__(self, other):
        match other:
            case Tag(): return self.key < other.key
            case Key(): return self.key < other
            case str(): return self.key < Key(other)
            case _: return NotImplemented
    def __hash__(self): return hash(self.key) + 1
    def __contains__(self, other):
        if not self.is_resolved: raise Exception(f'Unresolved tag {self} accessed')
        match other:
            case Key(): return other in self.content
            case Item(): return other.key in self.content
            case _: return NotImplemented
    def __len__(self): return len(self.content)
    def __bool__(self): return bool(self.content)
    def __iter__(self): return iter(self.content)

@dataclass(slots=True)
class FoodInfo:
    fast_food: bool
    meat: bool
    can_always_eat: bool
    has_effects: bool
    nutrition: int
    saturation: float

    FIELDS = Fields(Field('Fast food?', 'fast_food', 'ff'), Field('Meat?', 'meat', 'fm'),
                    Field('Can always eat', 'can_always_eat', 'fa'), Field('Effects?', 'has_effects', 'fe'),
                    Field('Nutrition', 'nutrition', 'fn'), Field('Saturation', 'saturation', 'fs'))


@dataclass(slots=True)
class Item:
    key: Key
    description_id: str
    tags: list[Key]
    name: str|None = None
    food_info: FoodInfo|None = None
    @property
    def fast_food(self): return self.food_info and self.food_info.fast_food
    @property
    def meat(self): return self.food_info and self.food_info.meat
    @property
    def can_always_eat(self): return self.food_info and self.food_info.can_always_eat
    @property
    def has_effects(self): return self.food_info and self.food_info.has_effects
    @property
    def nutrition(self): return self.food_info and self.food_info.nutrition
    @property
    def saturation(self): return self.food_info and self.food_info.saturation

    FIELDS = Fields(Field('Key', 'key', 'k'), Field('Desc. Id', 'description_id', 'did'), Field('Tags', 'tags', 't'), Field('Name', 'name', 'n'), Subfields(FoodInfo, 'food_info'))

    @classmethod
    def deserialize(cls, o):
        fp = None
        if of := o.get('foodInfo'):
            fp = FoodInfo(of['fastFood'], of['meat'], of['canAlwaysEat'], of['hasEffects'], of['nutrition'], of['saturation'])
        return Item(Key(o['key']), o['descriptionId'], list(map(Key, o['tags'])), o.get('name'), fp)

    def serialize(self):
        if fi := self.food_info:
            fp = dict(fastFood=fi.fast_food, meat=fi.meat, canAlwaysEat=fi.can_always_eat, hasEffects=fi.has_effects, nutrition=fi.nutrition,
                      saturation=fi.saturation)
        else: fp = None
        return dict(key=str(self.key), descriptionId=self.description_id, tags=list(map(str, self.tags)), foodInfo=fp, name=self.name)

    async def translate(self, translate: Callable): self.name = await translate(self.description_id)

@dataclass(slots=True)
class IngredientInfo:
    matched_items: frozenset[Key] = frozenset(())
    referenced_items: frozenset[Key] = frozenset(())
    referenced_tags: frozenset[Key] = frozenset(())
    EMPTY: ClassVar[object]

    def __or__(self, other):
        if type(other) is not IngredientInfo: return NotImplemented
        return IngredientInfo(self.matched_items|other.matched_items,
                              self.referenced_items|other.referenced_items,
                              self.referenced_tags|other.referenced_tags)

IngredientInfo.EMPTY = IngredientInfo()

@dataclass
class Ingredient:
    cached_info: IngredientInfo|None = field(init=False, default=None)

    def __rich__(self):
        result = self.rich_format()
        return result if self.count == 1 else Text.styled(f'{self.count} x ', Styles.cyan) + result;

    def get_info(self):
        if self.cached_info is None:
            self.cached_info = self.compute_info()
        return self.cached_info

    def resolve(self, resolver): pass

    @staticmethod
    def deserialize(o):
        match o:
            case None: return NilIngredient.INSTANCE
            case list():
                return deserialize(UnionIngredient, o)
            case dict():
                if 'tag' in o:
                    return deserialize(TagIngredient, o)
                if 'item' in o:
                    return deserialize(ItemIngredient, o, default=True)
                return UnknownIngredient(o)
            case _: raise ValueError(f'Invalid ingredient {o!r}')

@dataclass
class NilIngredient(Ingredient):
    def rich_format(self): return Syms.nullset
    def __rich__(self): return Syms.nullset
    def has_item(self, item): return False
    def compute_info(self): return IngredientInfo.EMPTY
NilIngredient.INSTANCE = NilIngredient()


@dataclass
class TagIngredient(Ingredient):
    tag: Tag|Key
    count: int = 1

    @classmethod
    def deserialize(cls, o): return cls(Key(o['tag']), o.get('count', 1))

    def rich_format(self): return Text.styled(f'#{self.tag}', Styles.orange_italic)
    def has_item(self, item): return item in self.tag
    def resolve(self, resolver):
        if isinstance(self.tag, Key):
            self.tag = resolver.get_tag(self.tag)
        self.tag.resolve(resolver)
    def compute_info(self):
        return IngredientInfo(self.tag.content, referenced_tags=frozenset((self.tag, )))


@dataclass
class UnknownIngredient(Ingredient):
    data: dict
    count: int = 1
    def rich_format(self): return Text.styled('Unknown', Styles.red_italic)

    async def has_item(self, item):
        print(f'Warning: recipe custom data {self.data}')
        return False
    def compute_info(self): return IngredientInfo.EMPTY

@dataclass
class ItemIngredient(Ingredient):
    item: Key = None
    count: int = 1
    nbt: str|None = None
    def rich_format(self):
        if self.nbt:
            return self.item.__rich__() + Text.styled(self.nbt, Styles.magenta_italic)
        return self.item.__rich__()
    async def has_item(self, item): return self.item == item
    def compute_info(self):
        item = frozenset((self.item, ))
        return IngredientInfo(item, item)

get_infos = partial(map, partial(operator.methodcaller('get_info')))
merge_infos = partial(reduce, operator.or_)

@dataclass
class UnionIngredient(Ingredient):
    items: list[Ingredient]
    count: int = 1
    def rich_format(self): return pipes(self.items)
    @classmethod
    def deserialize(cls, o): return cls(list(map(Ingredient.deserialize, o)))

    def has_item(self, item):
        for ing in self.items:
            if ing.has_item(item):
                return True
        return False
    def compute_info(self):
        infos = list(get_infos(self.items))
        return merge_infos(infos) if infos else IngredientInfo.EMPTY
    def resolve(self, resolver):
        for item in self.items: item.resolve(resolver)

def format_grid(input: list[Text], *, start: int, width: int, height: int, **_):
    tbl = Table(padding=(0,1), box=box.MINIMAL, show_header=False, show_lines=True)
    for i in range(width): tbl.add_column();
    for i in range(start, start + width * height, width): tbl.add_row(*input[i:i+width])
    return tbl
def format_single(input: list[Text], *, start: int, **_): return input[start]
def format_rest(input: list[Text], *, start: int, **_): return commas(input[start:])
def format_layout_item(input: list[Text], *, name: str, type: str, **kwargs):
    match type:
        case 'single': elem = format_single(input, **kwargs)
        case 'rest': elem = format_rest(input, **kwargs)
        case 'grid': elem = format_grid(input, **kwargs)
        case err: raise ValueError(f'Unsupported layout type {type} in {name}')
    return Group(Text.styled(name, Styles.yellow_bold), elem)
def format_layout(items: list[dict], input: list[Ingredient|None], *, title: str):
    if not items: return None
    input = [i.__rich__() for i in input]
    return Group(
        Text.styled(title, Styles.cyan_bold),
        Columns((format_layout_item(input, **i) for i in items)))

class RecipeFieldType(str, Enum):
    INPUTS = 'inputs'
    OUTPUTS = 'outputs'
    AUX = 'auxiliary'

@dataclass(slots=True)
class RecipeField:
    type: RecipeFieldType
    name: str|None = None

    INPUTS: ClassVar[object]
    OUTPUTS: ClassVar[object]
    AUX: ClassVar[object]

    def __getitem__(self, other):
        if other.__class__ is not str or self.name is not None: return NotImplemented
        return RecipeField(self.type, other)

RecipeField.INPUTS = RecipeField(RecipeFieldType.INPUTS)
RecipeField.OUTPUTS = RecipeField(RecipeFieldType.OUTPUTS)
RecipeField.AUX = RecipeField(RecipeFieldType.AUX)

@dataclass(slots=True)
class RecipeTypeField:
    formatter: Callable
    names: list[str]
    def __init__(self, fields: list[dict], title: str):
        self.formatter = partial(format_layout, fields, title=title)
        self.names = [i['name'] for i in fields]
    def index(self, name: str): return self.names.index(name)

@dataclass(slots=True)
class RecipeType:
    name: str
    inputs: RecipeTypeField
    aux: RecipeTypeField
    outputs: RecipeTypeField

    def format(self, inputs, aux, outputs):
        return Group(*filter(None, [self.inputs.formatter(inputs), self.aux.formatter(aux), self.outputs.formatter(outputs)]))

    def index(self, field: RecipeField): return getattr(self, field.type.value).index(field.name)

    @classmethod
    def deserialize(cls, o):
        return RecipeType(o['name'],
                          RecipeTypeField(o['inputs'], 'Inputs'),
                          RecipeTypeField(o.get('aux', []), 'Aux'),
                          RecipeTypeField(o['outputs'], 'Outputs'))

@dataclass(slots=True)
class RecipeInfo:
    recipe_type: RecipeType
    inputs: list[IngredientInfo]
    aux: list[IngredientInfo]
    outputs: list[IngredientInfo]

    def __getitem__(self, other):
        if other.__class__ is not RecipeField: return NotImplemented
        infos = getattr(self, other.type.value)
        if other.name is not None:
            return infos[self.recipe_type.index(other)]
        return merge_infos(infos) if infos else IngredientInfo.EMPTY

@dataclass(slots=True)
class Recipe:
    type: str
    id: str
    special: bool
    inputs: list[Ingredient]
    outputs: list[Ingredient]
    aux: list[Ingredient] = field(default_factory=list, init=False) #TODO INIT
    recipe_type: RecipeType = field(init=False)

    def get_info(self):
        return RecipeInfo(self.recipe_type,
                          list(get_infos(self.inputs)),
                          list(get_infos(self.aux)),
                          list(get_infos(self.outputs)))

    def __rich__(self):
        return Group(Text.styled(self.id, Styles.bold),
            self.recipe_type.format(self.inputs, self.aux, self.outputs))

    def resolve(self, resolver):
        for i in self.inputs: i.resolve(resolver)
        for i in self.aux: i.resolve(resolver)
        for i in self.outputs: i.resolve(resolver)

    async def has_item_as_input(self, item, tag_cb):
        for ing in self.inputs:
            if ing and await ing.has_item(item, tag_cb):
                return True
        return False
    async def has_item_as_output(self, item, tag_cb):
        for ing in self.outputs:
            if ing and await ing.has_item(item, tag_cb):
                return True
        return False

    async def has_item(self, item, tag_cb):
        return (await self.has_item_as_input(item, tag_cb)
                or await self.has_item_as_output(item, tag_cb))
