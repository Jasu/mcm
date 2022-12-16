from dataclasses import dataclass, field, KW_ONLY
from typing import Callable, ClassVar
from rich.text import Text
from .utils import print, PrettyEnum, Styles

__all__ = ('OpType', 'OpAssoc', 'INFIX', 'PREFIX', 'POSTFIX', 'ASSOC_LEFT', 'ASSOC_RIGHT', 'Op', 'Paren', 'PrecedenceParser')

class OpType(PrettyEnum):
    INFIX = auto(Styles.green, 'Infix')
    PREFIX = auto(Styles.yellow, 'Prefix')
    POSTFIX = auto(Styles.red, 'Postfix')

class OpAssoc(PrettyEnum):
    LEFT = auto(Styles.green, 'LeftAssoc')
    RIGHT = auto(Styles.red, 'RightAssoc')

INFIX, PREFIX, POSTFIX = OpType.INFIX, OpType.PREFIX, OpType.POSTFIX
ASSOC_LEFT, ASSOC_RIGHT = OpAssoc.LEFT, OpAssoc.RIGHT

@dataclass
class Op:
    name: str
    type: OpType
    precedence: int|tuple[int, int]
    reducer: Callable[[object, ...], object]
    _: KW_ONLY
    associativity: OpAssoc = ASSOC_LEFT
    def __str__(self): return self.__rich__().plain
    def __rich__(self):
        s = self.type.__rich__() + in_parens(self.name, style=Styles.bold) 
        return s if self.associativity is ASSOC_LEFT else spaces(s, self.associativity)
    def __post_init__(self):
        if self.precedence.__class__ is not tuple:
            self.precedence = (self.precedence, self.precedence)
    def has_lower_precedence(self, left) -> bool:
        if left.__class__ is Paren: return False
        lhs = left.precedence[1]
        rhs = self.precedence[0]
        if lhs == rhs: return self.associativity is ASSOC_LEFT
        return lhs > rhs

@dataclass(slots=True)
class Paren:
    is_left: bool
    parens: str
    def matches(self, other):
        return self.is_left == (not other.is_left) and self.parens == other.parens
    def __str__(self): return repr(self.parens[0 if self.is_left else 1])
    def __rich__(self): return txt(str(self), Styles.orange)

class PrecedenceParser:
    __slots__ = ('op_stack', 'expr_stack', 'was_prev_expr_or_postfix')

    op_stack: list[Op|Paren]
    expr_stack: list
    was_prev_expr_or_postfix: bool

    LeftParen: ClassVar[Paren] = Paren(True, '()')
    RightParen: ClassVar[Paren] = Paren(False, '()')
    LeftBracket: ClassVar[Paren] = Paren(True, '[]')
    RightBracket: ClassVar[Paren] = Paren(False, '[]')
    LeftBrace: ClassVar[Paren] = Paren(True, '{}')
    RightBrace: ClassVar[Paren] = Paren(False, '{}')

    def __init__(self, expr = None):
        self.op_stack = []
        self.expr_stack = [expr] if expr else []
        self.was_prev_expr_or_postfix = bool(expr)

    @property
    def cur_op(self) -> Op|Paren: return self.op_stack[-1] if self.op_stack else None

    def pop_expr(self):
        self._reduce_expr()
        self.was_prev_expr_or_postfix = False
        return self.expr_stack.pop()

    def push(self, item):
        self._check_push_type(item)
        match item:
            case Op(type=OpType.INFIX):
                # print('Infix')
                self._reduce_before(item)
                self.was_prev_expr_or_postfix = False
                self.op_stack.append(item)
            case Op(type=OpType.POSTFIX):
                # print('Postfix')
                self._reduce_before(item)
                self.expr_stack[-1] = item.reducer(self.expr_stack[-1])
            case Op()|Paren(is_left=True):
                # print('Other op', item)
                self.op_stack.append(item)
            case Paren():
                # print('Parwn', item)
                self._push_right_paren(item)
            case _:
                # print('Default', item)
                self.was_prev_expr_or_postfix = True
                self.expr_stack.append(item)

    def _push_right_paren(self, item: Paren) -> None:
        while self.op_stack:
            match self.op_stack[-1]:
              case Op(): self._reduce_top()
              case Paren(is_left=True, parens=item.parens):
                  self.op_stack.pop()
                  return
              case _:
                  raise ValueError(f'Mismatching parens {self.op_stack[-1]} and {item}')
        raise ValueError(f'No left paren for {item}')

    def _reduce_expr(self) -> None:
        if not self.was_prev_expr_or_postfix:
            raise Exception(f'Tried to reduce expr when {self.cur_op} was on top.')
        while self.op_stack and self.op_stack[-1].type is POSTFIX:
            self.expr_stack[-1] = self.op_stack.pop().reducer(self.expr_stack[-1])
        while self.op_stack and self.op_stack[-1].type is PREFIX:
            self.expr_stack[-1] = self.op_stack.pop().reducer(self.expr_stack[-1])

    def _reduce_top(self) -> None:
        op = self.op_stack.pop()
        rhs = (self.expr_stack.pop(),) if op.type is OpType.INFIX else ()
        self.expr_stack[-1] = op.reducer(self.expr_stack[-1], *rhs)

    def _reduce_before(self, op: Op) -> None:
        while self.op_stack and op.has_lower_precedence(self.op_stack[-1]): self._reduce_top()

    def finish(self):
        while self.op_stack: self._reduce_top()
        if len(self.expr_stack) != 1:
            raise ValueError(f'Precedence parser contained {len(self.expr_stack)} expressions, expected one.')
        return self.expr_stack[0]

    def _check_push_type(self, item) -> None:
        match item:
            case Op(type=OpType.INFIX)|Op(type=OpType.POSTFIX)|Paren(is_left=False): ok = self.was_prev_expr_or_postfix
            case Op(type=OpType.PREFIX)|Paren(): ok = not self.was_prev_expr_or_postfix
            case _: ok = not self.was_prev_expr_or_postfix
        if not ok: raise ValueError(f'Unexpectedly pushed {item}', item)

    def dump(self):
        print(Text.styled('Operator stack:', Styles.yellow_bold))
        for i, op in reversed(enumerate(list(self.op_stack))):
            print('    ', i, op.type, op.associativity, op.name, op.reducer, op.precedence)
        print(Text.styled('Expression stack:', Styles.green_bold))
        for i, expr in reversed(list(enumerate(self.expr_stack))):
            print('    ', i, item)
