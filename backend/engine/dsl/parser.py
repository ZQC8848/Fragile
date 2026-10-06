"""Author-layer rule expressions -> JSON Logic.

Authors (humans and the proposer LLM) write readable strings such as

    story_phase == 'early' and may_zone in [guest_table, bar] and glass == 'on_table'
    near(may, poisoned_glass)
    has(revealed, 'debt') or count(beat_history) >= 4
    played('the_bottle')                      a beat id appears in beat_history (completed or aborted)

At beat-load time these compile to JSON Logic (https://jsonlogic.com) which is what
the engine stores and evaluates (engine/dsl/evaluate.py) and what the frontend Console
can evaluate with json-logic-js to explain why a beat is not eligible.

Grammar (precedence low -> high):
    or_expr   := and_expr ('or' and_expr)*
    and_expr  := not_expr ('and' not_expr)*
    not_expr  := 'not' not_expr | cmp_expr
    cmp_expr  := add_expr (('==' | '!=' | '<' | '<=' | '>' | '>=' | 'in' | 'not' 'in') add_expr)?
    add_expr  := unary (('+' | '-') unary)*
    unary     := '-' unary | primary
    primary   := NUMBER | STRING | 'true' | 'false' | 'null'
               | IDENT '(' args ')'            function call
               | IDENT                         state variable (dotted paths allowed)
               | '[' items ']'                 list literal; bare identifiers inside are strings
               | '(' or_expr ')'

Nothing else is supported on purpose: no assignment, no arbitrary calls, no attribute
access beyond dotted variable paths. A generated beat can therefore never execute code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

JsonLogic = Any  # dict | list | str | int | float | bool | None

FUNCTIONS = {"near", "has", "count", "len", "min", "max", "abs", "played"}

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>-?\d+(?:\.\d+)?)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<op>==|!=|<=|>=|<|>|\+|-|\(|\)|\[|\]|,)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_.]*)
    """,
    re.VERBOSE,
)

KEYWORDS = {"and", "or", "not", "in", "true", "false", "null"}


@dataclass(frozen=True)
class Token:
    kind: str  # number | string | op | ident | kw | eof
    value: str
    pos: int


class DSLSyntaxError(ValueError):
    pass


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if not m:
            raise DSLSyntaxError(f"unexpected character {src[pos]!r} at {pos} in {src!r}")
        kind = m.lastgroup
        text = m.group()
        pos = m.end()
        if kind == "ws":
            continue
        if kind == "ident" and text in KEYWORDS:
            kind = "kw"
        tokens.append(Token(kind, text, m.start()))
    tokens.append(Token("eof", "", len(src)))
    return tokens


class _Parser:
    def __init__(self, src: str):
        self.src = src
        self.toks = tokenize(src)
        self.i = 0

    # -- helpers ---------------------------------------------------------
    def peek(self, offset: int = 0) -> Token:
        return self.toks[min(self.i + offset, len(self.toks) - 1)]

    def next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def accept(self, kind: str, value: str | None = None) -> Token | None:
        t = self.peek()
        if t.kind == kind and (value is None or t.value == value):
            return self.next()
        return None

    def expect(self, kind: str, value: str | None = None) -> Token:
        t = self.accept(kind, value)
        if t is None:
            got = self.peek()
            raise DSLSyntaxError(
                f"expected {value or kind} at {got.pos} but found {got.value!r} in {self.src!r}"
            )
        return t

    # -- grammar ---------------------------------------------------------
    def parse(self) -> JsonLogic:
        node = self.or_expr()
        if self.peek().kind != "eof":
            t = self.peek()
            raise DSLSyntaxError(f"trailing input at {t.pos}: {t.value!r} in {self.src!r}")
        return node

    def or_expr(self) -> JsonLogic:
        parts = [self.and_expr()]
        while self.accept("kw", "or"):
            parts.append(self.and_expr())
        return parts[0] if len(parts) == 1 else {"or": parts}

    def and_expr(self) -> JsonLogic:
        parts = [self.not_expr()]
        while self.accept("kw", "and"):
            parts.append(self.not_expr())
        return parts[0] if len(parts) == 1 else {"and": parts}

    def not_expr(self) -> JsonLogic:
        if self.accept("kw", "not"):
            return {"!": [self.not_expr()]}
        return self.cmp_expr()

    def cmp_expr(self) -> JsonLogic:
        left = self.add_expr()
        t = self.peek()
        if t.kind == "op" and t.value in ("==", "!=", "<", "<=", ">", ">="):
            self.next()
            right = self.add_expr()
            return {t.value: [left, right]}
        if t.kind == "kw" and t.value == "in":
            self.next()
            right = self.add_expr()
            return {"in": [left, right]}
        if t.kind == "kw" and t.value == "not" and self.peek(1).kind == "kw" and self.peek(1).value == "in":
            self.next()
            self.next()
            right = self.add_expr()
            return {"!": [{"in": [left, right]}]}
        return left

    def add_expr(self) -> JsonLogic:
        node = self.unary()
        while True:
            t = self.peek()
            if t.kind == "op" and t.value in ("+", "-"):
                self.next()
                rhs = self.unary()
                node = {t.value: [node, rhs]}
            else:
                return node

    def unary(self) -> JsonLogic:
        if self.accept("op", "-"):
            inner = self.unary()
            if isinstance(inner, (int, float)):
                return -inner
            return {"-": [inner]}
        return self.primary()

    def primary(self) -> JsonLogic:
        t = self.next()
        if t.kind == "number":
            return float(t.value) if "." in t.value else int(t.value)
        if t.kind == "string":
            return _unquote(t.value)
        if t.kind == "kw":
            if t.value == "true":
                return True
            if t.value == "false":
                return False
            if t.value == "null":
                return None
            raise DSLSyntaxError(f"unexpected keyword {t.value!r} at {t.pos} in {self.src!r}")
        if t.kind == "op" and t.value == "(":
            node = self.or_expr()
            self.expect("op", ")")
            return node
        if t.kind == "op" and t.value == "[":
            items: list[JsonLogic] = []
            if not self.accept("op", "]"):
                while True:
                    items.append(self.list_item())
                    if self.accept("op", "]"):
                        break
                    self.expect("op", ",")
            return items
        if t.kind == "ident":
            if self.accept("op", "("):
                if t.value not in FUNCTIONS:
                    raise DSLSyntaxError(f"unknown function {t.value!r} at {t.pos}; allowed: {sorted(FUNCTIONS)}")
                args: list[JsonLogic] = []
                if not self.accept("op", ")"):
                    while True:
                        args.append(self.or_expr())
                        if self.accept("op", ")"):
                            break
                        self.expect("op", ",")
                return {t.value: args}
            return {"var": t.value}
        raise DSLSyntaxError(f"unexpected token {t.value!r} at {t.pos} in {self.src!r}")

    def list_item(self) -> JsonLogic:
        """Inside a list literal a bare identifier is a string, so `[guest_table, bar]` reads naturally."""
        t = self.peek()
        if t.kind == "ident" and not (self.peek(1).kind == "op" and self.peek(1).value == "("):
            self.next()
            return t.value
        return self.or_expr()


def _unquote(s: str) -> str:
    body = s[1:-1]
    return body.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


def compile_expr(src: str | None) -> JsonLogic:
    """Compile an author-layer expression to JSON Logic. Empty/None compiles to `true`."""
    if src is None or not str(src).strip():
        return True
    return _Parser(str(src)).parse()


def referenced_vars(node: JsonLogic) -> set[str]:
    """All state variables a compiled rule reads (for schema checks and Console explanations)."""
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "var":
                out.add(str(v).split(".")[0])
            elif k == "near":
                continue  # near() takes names, not variables
            else:
                out |= referenced_vars(v)
    elif isinstance(node, list):
        for v in node:
            out |= referenced_vars(v)
    return out
