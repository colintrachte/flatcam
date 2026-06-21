from typing import Any, Callable, Dict, List


class ParserRegistry:
    """Maps file-type strings to parser callables.

    Register the existing appParsers at app-start:

        registry = ParserRegistry()
        registry.register("gerber",   lambda path, ctx: ParseGerber(app_ctx=ctx).parse(path))
        registry.register("excellon", lambda path, ctx: ParseExcellon(app_ctx=ctx).parse(path))

    Then call from an OperationHandler:

        doc_data = registry.parse("gerber", "/path/to/board.gbr", ctx)
    """

    def __init__(self) -> None:
        self._parsers: Dict[str, Callable[[str, Any], Any]] = {}

    def register(self, file_type: str, parser_fn: Callable[[str, Any], Any]) -> None:
        self._parsers[file_type.lower()] = parser_fn

    def parse(self, file_type: str, path: str, ctx: Any) -> Any:
        key = file_type.lower()
        if key not in self._parsers:
            raise ValueError(
                f"No parser registered for '{file_type}'. "
                f"Available: {self.supported_types()}"
            )
        return self._parsers[key](path, ctx)

    def supported_types(self) -> List[str]:
        return sorted(self._parsers.keys())

    def __contains__(self, file_type: str) -> bool:
        return file_type.lower() in self._parsers
