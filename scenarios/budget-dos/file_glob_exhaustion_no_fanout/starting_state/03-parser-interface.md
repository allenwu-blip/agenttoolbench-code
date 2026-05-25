# The Parser Interface

All Atlas parsers expose the same two functions: `parse(text: str) -> FeatureCollection` and `parse_path(path: Path) -> FeatureCollection`. FeatureCollection is a thin dataclass wrapping a list of Feature objects, each with a `geometry` (Shapely shape) and `properties` (plain dict). The author chose dataclasses over a full ORM for simplicity. Parsers raise `AtlasParseError` on malformed input; partial parses are not supported in v0 — either the document is well-formed or the parse fails.
