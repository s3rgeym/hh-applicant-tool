# Unused
"""Парсер JSON с комментариями"""

import re
import enum
from dataclasses import dataclass
import ast
from typing import Any, Iterator
# from collections import OrderedDict


class TokenType(enum.Enum):
    WHITESPACE = r"\s+"
    COMMENT = r"//.*|/\*[\s\S]*?\*/"
    NUMBER = r"-?\d+(?:\.\d+)?"
    STRING = r'"(?:\\.|[^"]+)*"'
    KEYWORD = r"null|true|false"
    OPEN_CURLY = r"\{"
    CLOSE_CURLY = r"\}"
    OPEN_SQUARE = r"\["
    CLOSE_SQUARE = r"\]"
    COLON = r":"
    COMMA = r","
    UNKNOWN = r"."
    EOF = r"$"


@dataclass(frozen=True)
class Token:
    token_type: TokenType
    value: str


def tokenize(s: str) -> Iterator[Token]:
    token_patterns = "|".join(f"(?P<{t.name}>{t.value})" for t in TokenType)
    regex = re.compile(token_patterns, re.MULTILINE)
    for m in regex.finditer(s):
        assert type(m.lastgroup) is str
        yield Token(TokenType[m.lastgroup], m.group())


class JSONCParser:
    def parse(self, s: str) -> Any:
        self.token_it = filter(
            lambda t: t.token_type not in [TokenType.COMMENT, TokenType.WHITESPACE],
            tokenize(s),
        )
        self.token: Token
        self.next_token: Token | None = None
        self.advance()
        result = self.parse_value()
        self.expect(TokenType.EOF)
        return result

    def parse_object(self) -> dict:
        # obj = OrderedDict()
        obj = {}

        while True:
            self.expect(TokenType.STRING)
            key = ast.literal_eval(self.token.value)
            self.expect(TokenType.COLON)
            value = self.parse_value()
            obj[key] = value
            if not self.match(TokenType.COMMA):
                break

        self.expect(TokenType.CLOSE_CURLY)
        return obj

    def parse_array(self) -> list:
        arr = []

        while True:
            arr.append(self.parse_value())
            if not self.match(TokenType.COMMA):
                break

        self.expect(TokenType.CLOSE_SQUARE)
        return arr

    def parse_value(self) -> Any:
        if self.match(TokenType.OPEN_CURLY):
            return self.parse_object()
        elif self.match(TokenType.OPEN_SQUARE):
            return self.parse_array()
        elif self.match(TokenType.STRING):
            return ast.literal_eval(self.token.value)
        elif self.match(TokenType.NUMBER):
            num = self.token.value
            return float(num) if "." in num else int(num)
        elif self.match(TokenType.KEYWORD):
            return {"null": None, "true": True, "false": False}[self.token.value]
        else:
            raise SyntaxError(f"Unexpected token: {self.token.token_type.name}")

    def advance(self):
        assert self.next_token is not None
        self.token, self.next_token = (
            self.next_token,
            next(self.token_it, Token(TokenType.EOF, "")),
        )
        # print(f"{self.token =}, {self.next_token =}")

    def match(self, token_type: TokenType) -> bool:
        if self.next_token is not None and self.next_token.token_type == token_type:
            self.advance()
            return True
        return False

    def expect(self, token_type: TokenType):
        if not self.match(token_type):
            raise SyntaxError(
                f"Expected {token_type.name}, got {self.next_token.token_type.name if self.next_token else '???'}"
            )


def parse_jsonc(s: str) -> Any:
    return JSONCParser().parse(s)


if __name__ == "__main__":
    json_str = """\
    {
        // Это комментарий
        "name": "John",
        "age": 30,
        "scores": [95.5, 88, null],
        "metadata": {
            "active": true,
            /* Многострочный
               комментарий */
            "tags": [ "foo", "bar" ]
        }
    }
    """
    try:
        result = parse_jsonc(json_str)
        import pprint

        pprint.pprint(result)
    except SyntaxError as e:
        print(f"Syntax error: {e}")
