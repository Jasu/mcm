from dataclasses import dataclass, field
from .mcdata import Key, Tag, Recipe, RecipeType, RecipeInfo, RecipeField, RecipeFieldType, IngredientInfo
from .precedence import INFIX, PREFIX, POSTFIX, Op, PrecedenceParser
from typing import Callable
from enum import Enum
import regex

class IngredientOp(str, Enum):
    MATCHES = 'matches'
    MATCHES_ALL = 'matches-all'
    REFERENCES = 'references'
    REFERENCES_SOME_ITEM = 'references-some-item'
    REFERENCES_SOME_TAG = 'references-some-tag'
    REFERENCES_ALL_ITEMS = 'references-all-items'
    REFERENCES_ALL_TAGS = 'references-all-tags'

@dataclass(slots=True)
class PrimitiveIngredientMatcher:
    op: IngredientOp
    value: Key|frozenset[Key]

    def __call__(self, info: IngredientInfo):
        match self.op, self.value:
            case IngredientOp.MATCHES, Key() as key: return key in info.matched_items
            case IngredientOp.MATCHES, frozenset() as keys: return not keys.isdisjoint(info.matched_items)
            case IngredientOp.MATCHES_ALL, frozenset() as keys: return keys.issubset(info.matched_items)
            case IngredientOp.REFERENCES, Key() as key: return key in info.referenced_items
            case IngredientOp.REFERENCES, Tag() as key: return key in info.referenced_tags
            case IngredientOp.REFERENCES_SOME_ITEM, frozenset() as keys: return not keys.isdisjoint(info.referenced_items)
            case IngredientOp.REFERENCES_ALL_ITEMS, frozenset() as keys: return keys.issubset(info.referenced_items)
            case IngredientOp.REFERENCES_SOME_TAG, frozenset() as keys: return not keys.isdisjoint(info.referenced_tags)
            case IngredientOp.REFERENCES_ALL_TAGS, frozenset() as keys: return keys.issubset(info.referenced_tags)
            case _: raise TypeError(f'Unsupported IngredientMatcher {self.op.name} {self.value.__class__.__name__}')

@dataclass(slots=True)
class NotMatcher:
    expr: Callable
    def __call__(self, info): return not self.expr(info)

@dataclass(slots=True)
class AndMatcher:
    lhs: Callable
    rhs: Callable
    def __call__(self, info): return self.lhs(info) and self.rhs(info)

@dataclass(slots=True)
class OrMatcher:
    lhs: Callable
    rhs: Callable
    def __call__(self, info): return self.lhs(info) or self.rhs(info)

IngredientMatcher = PrimitiveIngredientMatcher|NotMatcher|AndMatcher|OrMatcher

@dataclass(slots=True)
class RecipeIngredientMatcher:
    field: RecipeField
    matcher: IngredientMatcher

    def __call__(self, info: RecipeInfo):
        return self.matcher(info[self.field])

@dataclass(slots=True)
class RecipeTypeMatcher:
    type: str
    def __call__(self, info: RecipeInfo):
        return self.type == info.type

RecipeMatcher = RecipeIngredientMatcher|RecipeTypeMatcher|NotMatcher|AndMatcher|OrMatcher
match_ws = regex.compile('[ \t]+').match
match_item = regex.compile('%[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)?').match
match_tag = regex.compile('#[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*(?:/[a-z][a-z0-9_]*)?)?').match
match_field = regex.compile(r'\$(?:in|out|aux)').match
match_subfield = regex.compile(r'\[[a-z_][a-z0-9_]*\]').match
match_bool_op = regex.compile(r'and|or|not').match
match_ingredient_op = regex.compile(r'(?:(all) +)?(in|refby)').match

def op_index(name: str):
    def apply_op_index(lhs):
        nonlocal name
        if lhs.__class__ is not RecipeField: raise ValueError(f'Unexpected LHS for [{name}]: {lhs!r}')
        if lhs.name: raise ValueError(f'Only one level of [{name}] allowed')
        return RecipeField(lhs.type, name)
    return Op('index', POSTFIX, 0, apply_op_index)


NOT_OP = Op('not', PREFIX, 2, NotMatcher)
AND_OP = Op('and', INFIX, 3, AndMatcher)
OR_OP = Op('or', INFIX, 4, OrMatcher)

def has_tag(s: frozenset): return any(i.__class__ is Tag for i in s)
def has_item(s: frozenset): return any(i.__class__ is Key for i in s)
def make_ingredient_op_matches(lhs, op: IngredientOp):
    match lhs:
        case Key(): return PrimitiveIngredientMatcher(IngredientOp.MATCHES, lhs)
        case frozenset():
            if has_tag(lhs): raise ValueError(f'Tags not allowed in "all in"')
            return PrimitiveIngredientMatcher(op, lhs)
        case _: raise ValueError(f'Unexpected LHS for all in: {lhs!r}')
def make_recipe_ingr_op(ingr_op: PrimitiveIngredientMatcher, rhs, opname: str):
    if rhs.__class__ is not RecipeField:
        raise ValueError(f'Expected $out/in/aux got {rhs!r} in {opname}')
    return RecipeIngredientMatcher(rhs, ingr_op)

def apply_op_all_in(lhs, rhs):
    return make_recipe_ingr_op(make_ingredient_op_matches(lhs, IngredientOp.MATCHES_ALL), rhs, 'all in')
def apply_op_in(lhs, rhs):
    return make_recipe_ingr_op(make_ingredient_op_matches(lhs, IngredientOp.MATCHES), rhs, 'in')
def make_refby_op(lhs, rhs, multi_tag, multi_item):
    match lhs:
        case Key()|Tag(): op = IngredientOp.REFERENCES
        case frozenset(): op = multi_tag if has_tag(lhs) else multi_item
        case _: raise ValueError(f'Unexpected LHS for refby: {lhs!r}')
    op = PrimitiveIngredientMatcher(op, lhs)
    return make_recipe_ingr_op(op, rhs, 'refby')

def apply_op_refby(lhs, rhs):
    return make_refby_op(lhs, rhs, IngredientOp.REFERENCES_SOME_TAG, IngredientOp.REFERENCES_SOME_ITEM)
def apply_op_all_refby(lhs, rhs):
    return make_refby_op(lhs, rhs, IngredientOp.REFERENCES_ALL_TAG, IngredientOp.REFERENCES_ALL_ITEM)
        
IN_OP = Op('in', INFIX, 5, apply_op_in)
ALL_IN_OP = Op('all in', INFIX, 1, apply_op_all_in)
REFBY_OP = Op('refby', INFIX, 1, apply_op_refby)
ALL_REFBY_OP = Op('all refby', INFIX, 1, apply_op_all_refby)
        
def apply_op_union(lhs, rhs):
    match lhs, rhs:
        case frozenset(), frozenset(): pass
        case frozenset(), Key()|Tag(): rhs = frozenset((rhs, ))
        case Key()|Tag(), frozenset(): lhs = frozenset((lhs, ))
        case Key(), Key(): return frozenset((lhs, rhs))
        case Tag(), Tag(): return frozenset((lhs, rhs))
        case _: raise ValueError(f'Unsupported set union operands {lhs!r} and {rhs!r}')
    assert has_item(lhs) == has_item(rhs)
    assert has_tag(lhs) == has_tag(rhs)
    return lhs|rhs

UNION_OP = Op('|', INFIX, 0, apply_op_union)

def matcher_wrapper(matcher):
    def wrapper(recipe: Recipe|RecipeInfo):
        if isinstance(recipe, Recipe):
            return matcher(recipe.get_info())
        return matcher(recipe)
    return wrapper
def parse_recipe_matcher(string: str):
    at = 0
    l = len(string)
    prec = PrecedenceParser()
    while at != l:
        assert at < l
        ch = string[at]
        match ch:
            case '(':
                prec.push(PrecedenceParser.LeftParen)
                at += 1
                continue
            case ')':
                prec.push(PrecedenceParser.RightParen)
                at += 1
                continue
            case '|':
                prec.push(UNION_OP)
                at += 1
                continue
            case ' '|'\t': m = match_ws(string, pos=at)
            case '%':
                m = match_item(string, pos=at)
                prec.push(Key(m.group()[1:]))
            case '#':
                m = match_tag(string, pos=at)
                prec.push(Tag(m.group()[1:]))
            case '$':
                m = match_field(string, pos=at)
                match m.group():
                    case '$in': prec.push(RecipeField.INPUTS)
                    case '$out': prec.push(RecipeField.OUTPUTS)
                    case '$aux': prec.push(RecipeField.AUX)
                    case _: raise ValueError(f'Unexpected variable {m.group()}')
            case '[':
                m = match_subfield(string, pos=at)
                prec.push(op_index(m.group()[1:-1]))
            case _:
                if m := match_bool_op(string, pos=at):
                    match m.group():
                        case 'and': prec.push(AND_OP)
                        case 'or': prec.push(OR_OP)
                        case 'not': prec.push(NOT_OP)
                        case _: raise ValueError('Unexpected bool op {m.group()}')
                elif m := match_ingredient_op(string, pos=at):
                    match m.group(1), m.group(2):
                        case 'all', 'in': prec.push(ALL_IN_OP)
                        case _, 'in': prec.push(IN_OP)
                        case 'all', 'refby': prec.push(ALL_REFBY_OP)
                        case _, 'refby': prec.push(REFBY_OP)
                        case _: raise ValueError(f'Unexpected binary op {m.group(1)} {m.group(2)}')
                else:
                    raise ValueError(f'Unknown token after {string[:at]!r} at {string[at:]!r}')
        at = m.end()
        m = None

    return matcher_wrapper(prec.finish())
