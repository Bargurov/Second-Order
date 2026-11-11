"""An offline check of a JSON output format before it is put in a paid request (output-schema-check-0.1).

It checks the structured-outputs rules of the Claude API documentation and the official Python SDK's schema rule, both
read on 2026-10-27, and one conservative project rule. Passing it does not show that the provider accepts a request:
the provider compiles the schema itself, with limits it does not fully publish. Only a sent request can show that.

- Documented (STRUCTURED_OUTPUTS): the supported keywords; additionalProperties false on every object; minItems only 0
  or 1; enum members only strings, numbers, booleans or null; at most 16 union-type parameters (anyOf or a type array)
  and 24 optional parameters across a request's strict schemas.
- SDK (SDK_TRANSFORM): the official Python SDK's transform_schema, which "transforms a JSON schema to ensure it conforms
  to the API's expectations", refuses a node without a type, anyOf, oneOf or allOf. The documentation page does not
  state this rule; a format that breaks it is one the official SDK would never send.
- Project (PROJECT_RULE): no union inside another union's branch. The documentation says unions are "especially
  expensive because they create exponential compilation cost"; nesting them is avoided as a precaution, not because a
  documented limit forbids it.
"""
CHECK_VERSION = "output-schema-check-0.1"
STRUCTURED_OUTPUTS = "https://platform.claude.com/docs/en/build-with-claude/structured-outputs"
SDK_TRANSFORM = "https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/lib/_parse/_transform.py"
PROJECT_RULE = "project rule (a precaution, not a documented limit)"
KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "enum", "const", "anyOf", "allOf",
            "default", "format", "minItems", "description", "title"}  # $ref and $defs are supported but not resolved here.
TYPES = {"string": (str,), "number": (int, float), "integer": (int,), "boolean": (bool,), "null": (type(None),)}
MAX_UNIONS, MAX_OPTIONAL = 16, 24


def _matches(value: object, kind: object) -> bool:
    kinds = kind if isinstance(kind, list) else [kind]
    for name in kinds:
        allowed = TYPES.get(name)
        if allowed and isinstance(value, allowed) and not (name in ("number", "integer") and isinstance(value, bool)):
            return True
    return False


def _walk(node: object, path: str, in_union: bool, found: list[dict], counts: dict) -> None:
    if not isinstance(node, dict):
        found.append({"rule": "not_a_schema", "path": path, "source": STRUCTURED_OUTPUTS,
                      "detail": "Every schema node is a JSON object."})
        return

    def problem(rule: str, source: str, detail: str) -> None:
        found.append({"rule": rule, "path": path, "source": source, "detail": detail})

    for key in sorted(set(node) - KEYWORDS):
        problem("unsupported_keyword", STRUCTURED_OUTPUTS, f"{key} is not a supported keyword here.")
    kind = node.get("type")
    union = "anyOf" in node or isinstance(kind, list)
    if not any(key in node for key in ("type", "anyOf", "allOf")):
        problem("sdk_node_type", SDK_TRANSFORM, "The node has no type, anyOf or allOf (an enum alone has no type).")
    if union:
        counts["unions"] += 1
        if in_union:
            counts["nested_unions"] += 1
            problem("nested_union", PROJECT_RULE, "A union inside another union's branch.")
    if "enum" in node:
        members = node["enum"]
        if not isinstance(members, list) or not members or \
                any(isinstance(value, (dict, list)) for value in members):
            problem("complex_enum", STRUCTURED_OUTPUTS, "enum members are strings, numbers, booleans or null.")
        elif kind is not None and not all(_matches(value, kind) for value in members):
            problem("enum_type", STRUCTURED_OUTPUTS, f"An enum member is not of the node's type ({kind}).")
    if "minItems" in node and node["minItems"] not in (0, 1):
        problem("min_items", STRUCTURED_OUTPUTS, "minItems is only 0 or 1.")
    if kind == "object" or "properties" in node:
        properties = node.get("properties", {})
        required = node.get("required", [])
        if node.get("additionalProperties") is not False:
            problem("additional_properties", STRUCTURED_OUTPUTS, "An object sets additionalProperties to false.")
        unknown = [name for name in required if name not in properties]
        if unknown:
            problem("required_unknown", STRUCTURED_OUTPUTS, f"required names no property: {', '.join(unknown)}.")
        counts["optional"] += len([name for name in properties if name not in required])
        for name, child in properties.items():
            _walk(child, f"{path}.properties.{name}", in_union, found, counts)
    if "items" in node:
        _walk(node["items"], f"{path}.items", in_union, found, counts)
    for combinator in ("anyOf", "allOf"):
        for index, child in enumerate(node.get(combinator, [])):
            _walk(child, f"{path}.{combinator}[{index}]", in_union or combinator == "anyOf", found, counts)


def _run(schema: dict) -> tuple[list[dict], dict]:
    found: list[dict] = []
    counts = {"unions": 0, "nested_unions": 0, "optional": 0}
    _walk(schema, "$", False, found, counts)
    if counts["unions"] > MAX_UNIONS:
        found.append({"rule": "too_many_unions", "path": "$", "source": STRUCTURED_OUTPUTS,
                      "detail": f"{counts['unions']} union-type parameters; the limit is {MAX_UNIONS}."})
    if counts["optional"] > MAX_OPTIONAL:
        found.append({"rule": "too_many_optional", "path": "$", "source": STRUCTURED_OUTPUTS,
                      "detail": f"{counts['optional']} optional parameters; the limit is {MAX_OPTIONAL}."})
    return found, counts


def problems(schema: dict) -> list[dict]:
    """Every rule the format breaks, each with where and the source of the rule; empty when it passes."""
    return _run(schema)[0]


def profile(schema: dict) -> dict:
    """The format's counts the rules bound: unions, unions nested in another union, optional parameters."""
    return _run(schema)[1]
