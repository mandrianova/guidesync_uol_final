from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedSymbol:
    name: str
    line_number: int
    source_line: str
    symbol_kind: str = "symbol"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedImport:
    module: str
    line_number: int
    source_line: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedFile:
    parser_name: str
    language: str | None
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class CodeParser(Protocol):
    name: str

    def parse(self, path: str, text: str) -> ParsedFile: ...


@dataclass(frozen=True)
class SymbolPattern:
    pattern: re.Pattern[str]
    symbol_kind: str


class RegexCodeParser:
    name = "regex-code-parser"

    symbol_patterns = (
        SymbolPattern(
            re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][\w$]*)\s*\("),
            "function",
        ),
        SymbolPattern(
            re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][\w$]*)\b"),
            "class",
        ),
        SymbolPattern(
            re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_][\w$]*)\b"),
            "interface",
        ),
        SymbolPattern(
            re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_][\w$]*)\b"),
            "type",
        ),
        SymbolPattern(
            re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][\w$]*)\s*="),
            "variable",
        ),
        SymbolPattern(re.compile(r"^\s*def\s+([A-Za-z_][\w]*)\s*\("), "function"),
        SymbolPattern(re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\b"), "class"),
    )
    import_patterns = (
        re.compile(r"^\s*import\s+.+?\s+from\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+"),
        re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)"),
    )

    def parse(self, path: str, text: str) -> ParsedFile:
        symbols: list[ParsedSymbol] = []
        imports: list[ParsedImport] = []
        exports: list[str] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            symbol = self._parse_symbol(line, line_number)
            if symbol is not None:
                symbols.append(symbol)
                if line.lstrip().startswith("export "):
                    exports.append(symbol.name)
            module = self._parse_import(line)
            if module is not None:
                imports.append(
                    ParsedImport(
                        module=module,
                        line_number=line_number,
                        source_line=line.strip(),
                    )
                )
        return ParsedFile(
            parser_name=self.name,
            language=language_for_path(path),
            symbols=symbols,
            imports=imports,
            exports=exports,
            metadata={
                "symbol_count": len(symbols),
                "import_count": len(imports),
                "export_count": len(exports),
            },
        )

    def _parse_symbol(self, line: str, line_number: int) -> ParsedSymbol | None:
        for pattern in self.symbol_patterns:
            match = pattern.pattern.match(line)
            if match:
                return ParsedSymbol(
                    name=match.group(1),
                    line_number=line_number,
                    source_line=line.strip(),
                    symbol_kind=pattern.symbol_kind,
                    metadata={"exported": line.lstrip().startswith("export ")},
                )
        return None

    def _parse_import(self, line: str) -> str | None:
        for pattern in self.import_patterns:
            match = pattern.match(line)
            if match:
                return match.group(1)
        return None


def parse_code_file(path: str, text: str) -> ParsedFile:
    return parser_for_path(path).parse(path, text)


def parser_for_path(_: str) -> CodeParser:
    return RegexCodeParser()


def language_for_path(path: str) -> str | None:
    extension = Path(path).suffix.lower()
    return {
        ".js": "javascript",
        ".jsx": "javascript",
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
    }.get(extension)
