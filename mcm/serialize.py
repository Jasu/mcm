from collections.abc import Collection, Sequence, Iterable, Mapping
from dataclasses import fields, MISSING
from datetime import datetime
from dateutil.parser import isoparse
from enum import Enum, Flag
from functools import cache, partial
from types import UnionType
import types
from typing import get_origin

__all__ = ('deserialize', 'serialize', 'serialize_by_type')

def dictdiff(a: dict, b: dict) -> dict: return {k: v for k,v in a.items() if b[k] != v}
def defaults(a): return {f.name: f.default for f in fields(a)}
def values(a): return {f.name: getattr(a, f.name) for f in fields(a)}

COLLECTION_TYPES = {
    list: list,
    set: set,
    frozenset: frozenset,
    tuple: tuple,
    Collection: tuple,
    Sequence: tuple,
    Iterable: tuple,
}
MAPPING_TYPES = {dict: dict, Mapping: dict}

def get_collection_type(origin, type) -> tuple[type, type|None]|None:
    if seq := COLLECTION_TYPES.get(origin):
        return seq, type.__args__[0]
    if seq := COLLECTION_TYPES.get(type):
        return seq, None
    return None

def get_mapping_type(origin, type) -> tuple[type, type|None, type|None]|None:
    if mapping := MAPPING_TYPES.get(origin):
        return mapping, type.__args__[0], type.__args__[1]
    if mapping := MAPPING_TYPES.get(type):
        return mapping, None, None
    return None

def get_optional_type(origin, type) -> type|None:
    if origin is not UnionType: return None
    match type.__args__:
        case (types.NoneType, t): return t
        case (t, types.NoneType): return t
        case _: return None

PRIMITIVE_TYPES = (int, float, str, bool)
def is_primitive(type, origin):
    if type in PRIMITIVE_TYPES: return True
    return origin is UnionType and all(a in PRIMITIVE_TYPES for a in type.__args__)

def identity(v): return v

def _name(name: str, fn):
    fn.__name__ = name
    return fn

def _get_parser(type, *, default: bool = False):
    if type is datetime: return isoparse
    if not default and hasattr(type, 'deserialize'):
        return type.deserialize
    origin = get_origin(type)
    if is_primitive(type, origin):
        return identity
    if origin is None:
        if issubclass(type, (Enum, Flag)):
            if issubclass(type, str): return type
            return lambda x: type[x]
        ps = parsers(type)
        def pss(x):
            nonlocal ps, type
            return type(**{k: (v() if k not in x else v(x[k])) for k, v in ps})
        return _name(f'parse_{type.__name__}', pss)
    if opt := get_optional_type(origin, type):
        p = _get_parser(opt)
        return _name(f'parse_opt_{opt.__name__}', lambda x: (None if x is None else p(x)))
    if collection := get_collection_type(origin, type):
        collection, type = collection
        _par = _get_parser(type)
        return _name(f'parse_{collection.__name__}_{_par.__name__}', lambda x: collection(map(_par, x)))
    if mapping := get_mapping_type(origin, type):
        mapping, key, value = mapping
        key = _get_parser(key)
        value = _get_parser(value)
        return _name(f'parse_{mapping.__name__}_{key.__name__}_{value.__name__}', lambda x: mapping((key(k), value(v)) for k,v in x.items()))
    raise ValueError(f'Unhandled origin {origin!r} for type {type!r}')

@cache
def get_parser(type, default):
    origin = get_origin(type)
    if opt := get_optional_type(origin, type):
        type = opt
        default = None if default is MISSING else default
    parser = _get_parser(type)
    if default is MISSING: return parser
    return lambda *args: parser(*args) if args else default
    
OMIT = object()

def _get_serializer(type, *, default: bool = False):
    if type is datetime: return datetime.isoformat
    origin = get_origin(type)
    if is_primitive(type, origin): return identity
    if origin is None:
        if issubclass(type, (Enum, Flag)): return lambda x: x.value
        if not default and hasattr(type, 'serialize'): return type.serialize
        sers = serializers(type)
        def ser(obj):
            nonlocal sers
            result = {}
            for k, s in sers:
                v = s(getattr(obj, k))
                if v is not OMIT:
                    result[k] = v
            return result
        return ser
    if collection := get_collection_type(origin, type):
        collection, type = collection
        ser = _get_serializer(type)
        return lambda x: list(map(ser, x))
    if mapping := get_mapping_type(origin, type):
        mapping, key, value = mapping
        key = _get_serializer(key)
        value = _get_serializer(value)
        return lambda x: {key(k): value(v) for k, v in x.items()}
    raise ValueError(f'Unhandled origin {origin!r} for type {type!r}')

@cache
def get_serializer(type, default):
    origin = get_origin(type)
    if opt := get_optional_type(origin, type):
        type = opt
        default = None if default is MISSING else default
    serializer = _get_serializer(type)
    if default is MISSING: return serializer
    return lambda arg: serializer(arg) if arg != default else OMIT

def get_types(cls, type, default):
    collection = None
    origin = get_origin(type)
    if origin is UnionType:
        match type.__args__:
            case (types.NoneType, t): return get_types(cls, t, None if default is MISSING else default)
            case (t, types.NoneType): return get_types(cls, t, None if default is MISSING else default)
            case _: raise ValueError(f'Unsupported union {type}')
    else:
        collection = ORIGIN_TYPES[origin]
        type = type.__args__[0]
    return type, collection, default

def parser(cls, type, default):
    type, collection, default = get_types(cls, type, default)
    parse_unit = partial(deserialize, type)
    if collection:
        parse = lambda x: collection(map(parse_unit, x))
    else:
        parse = parse_unit
    return parse if default is MISSING else lambda x: parse(x) if x is not None else default

def serializer(cls, type, default):
    type, collection, default = get_types(cls, type, default)
    if collection:
        return lambda x: list(map(serialize, x))
    else:
        return serialize

@cache
def parsed_fields(cls):
    return [f for f in fields(cls) if f.init]

@cache
def parsers(cls): return [(f.name, get_parser(f.type, f.default)) for f in parsed_fields(cls)]

@cache
def serializers(cls): return [(f.name, get_serializer(f.type, f.default)) for f in parsed_fields(cls)]

def serialize(o, *, default: bool = False):
    return _get_serializer(o.__class__, default=default)(o)
def serialize_by_type(cls, o, *, default: bool = False):
    return _get_serializer(cls, default=default)(o)
def deserialize(cls, value, *, default=False):
    return _get_parser(cls, default=default)(value)
