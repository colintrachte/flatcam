import pytest

from flatcam_core import ParserRegistry


@pytest.fixture()
def registry():
    return ParserRegistry()


def test_register_and_parse(registry):
    sentinel = object()
    registry.register("gerber", lambda path, ctx: sentinel)
    result = registry.parse("gerber", "/fake/path.gbr", ctx=None)
    assert result is sentinel


def test_parse_passes_path_and_ctx(registry):
    received = {}

    def capture(path, ctx):
        received["path"] = path
        received["ctx"] = ctx
        return None

    registry.register("excellon", capture)
    registry.parse("excellon", "/board.drl", ctx="fake-ctx")
    assert received["path"] == "/board.drl"
    assert received["ctx"] == "fake-ctx"


def test_parse_unregistered_raises_value_error(registry):
    with pytest.raises(ValueError, match="No parser registered for 'gerber'"):
        registry.parse("gerber", "/path", ctx=None)


def test_parse_error_lists_available_types(registry):
    registry.register("excellon", lambda p, c: None)
    with pytest.raises(ValueError, match="excellon"):
        registry.parse("gerber", "/path", ctx=None)


def test_supported_types_sorted(registry):
    registry.register("svg", lambda p, c: None)
    registry.register("gerber", lambda p, c: None)
    registry.register("excellon", lambda p, c: None)
    assert registry.supported_types() == ["excellon", "gerber", "svg"]


def test_supported_types_empty(registry):
    assert registry.supported_types() == []


def test_contains_registered(registry):
    registry.register("gerber", lambda p, c: None)
    assert "gerber" in registry


def test_contains_unregistered(registry):
    assert "gerber" not in registry


def test_case_insensitive_register(registry):
    registry.register("Gerber", lambda p, c: "result")
    # Lookup must work with lowercase key.
    result = registry.parse("gerber", "/path", ctx=None)
    assert result == "result"


def test_case_insensitive_parse_key(registry):
    registry.register("gerber", lambda p, c: "result")
    result = registry.parse("GERBER", "/path", ctx=None)
    assert result == "result"


def test_case_insensitive_contains(registry):
    registry.register("GERBER", lambda p, c: None)
    assert "gerber" in registry
