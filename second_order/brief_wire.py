"""A branch-free provider format for briefs (brief-wire-0.1), decoded before application validation.

The provider rejected brief-prompt-7's compiled grammar even within its published counts. This format has no unions,
enums or optional properties. A nullable application value is explicitly a list of zero or one values: [] is None,
[value] is that value. Closed choices stay in the instructions and are checked here before the unchanged brief and
economic validators. Missing fields, extra fields, bad types and multiple values are refused, never repaired.

This reduces grammar branching; it does not prove live provider acceptance. Historical stored content stays in the
application's original shape. ``encode`` is the inverse projection for complete synthetic provider fixtures.
"""
import math

from .model_draft import DraftRefused

VERSION = "brief-wire-0.1"
SCALARS = {"string": str, "number": (int, float), "integer": int, "boolean": bool}


def _nullable(schema: dict) -> dict | None:
    branches = schema.get("anyOf")
    if branches is None:
        return None
    if len(branches) != 2 or sum(branch.get("type") == "null" for branch in branches) != 1:
        raise ValueError("The brief wire contract only maps value-or-null unions.")
    return next(branch for branch in branches if branch.get("type") != "null")


def output_format(schema: dict) -> dict:
    """A fixed structure: no choice branches, length/count constraints or optional properties sent to the provider."""
    nullable = _nullable(schema)
    if nullable is not None:
        return {"type": "array", "items": output_format(nullable)}
    kind = schema["type"]
    if kind == "object":
        properties = {name: output_format(child) for name, child in schema["properties"].items()}
        return {"type": "object", "additionalProperties": False, "required": list(properties),
                "properties": properties}
    if kind == "array":
        return {"type": "array", "items": output_format(schema["items"])}
    if kind not in SCALARS:
        raise ValueError(f"Unsupported brief wire scalar: {kind}")
    return {"type": kind}


def instructions(schema: dict) -> str:
    """List the explicit absence representation and every closed choice outside the compiled grammar."""
    nullable, choices = [], []

    def walk(node: dict, path: str) -> None:
        value = _nullable(node)
        if value is not None:
            nullable.append(path)
            walk(value, path + "[0]")
            return
        if "enum" in node:
            choices.append(f"{path}: {', '.join(node['enum'])}.")
        for name, child in node.get("properties", {}).items():
            walk(child, path + "." + name)
        if "items" in node:
            walk(node["items"], path + "[]")

    walk(schema, "reply")
    return (f"Transport contract {VERSION}: reply in the exact object structure of the output format. Every field is "
            "required. The following fields use a list containing zero or one value: " + "; ".join(nullable) +
            ". For these fields only, write [] for null/not supplied and [value] for a supplied value; never write "
            "null, a bare value or more than one item. For example, an explained story has change: [{stage: ..., "
            "instrument: ..., text: ..., basis: [...]}], while insufficient_evidence has change: [], significance: "
            "[] and main_uncertainty: []. For all other lists, retain their ordinary meaning. These wire rules "
            "override references to null in the content instructions; they do not change what the fields mean. "
            "Use exactly these allowed choices (case-sensitive; the application refuses every other value): " +
            " ".join(choices))


def decode(value: object, schema: dict, path: str = "reply") -> object:
    """Check all required keys, scalar types and choices, and decode explicit nullable lists. No coercion/defaults."""
    def refuse(detail: str) -> None:
        raise DraftRefused(f"Invalid brief wire output at {path}: {detail}")

    nullable = _nullable(schema)
    if nullable is not None:
        if not isinstance(value, list) or len(value) > 1:
            refuse("a nullable field is a list containing zero or one value")
        return None if not value else decode(value[0], nullable, path + "[0]")
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            refuse("expected an object")
        properties = schema["properties"]
        if set(value) != set(properties):
            missing = ", ".join(sorted(set(properties) - set(value))) or "none"
            extra = ", ".join(sorted(set(value) - set(properties))) or "none"
            refuse(f"missing fields: {missing}; extra fields: {extra}")
        return {name: decode(value[name], child, path + "." + name) for name, child in properties.items()}
    if kind == "array":
        if not isinstance(value, list):
            refuse("expected a list")
        return [decode(item, schema["items"], f"{path}[{index}]") for index, item in enumerate(value)]
    allowed = SCALARS[kind]
    if not isinstance(value, allowed) or kind in ("number", "integer") and isinstance(value, bool):
        refuse(f"expected {kind}")
    if kind in ("number", "integer"):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            refuse("expected a finite number")
    if "enum" in schema and value not in schema["enum"]:
        refuse("value is not one of the application's allowed choices")
    return value


def encode(value: object, schema: dict) -> object:
    """Project a complete application-shaped fixture onto the wire; no missing fields or values are invented.

    This is not validation: malformed fixture values remain malformed so negative tests can exercise the decoder.
    """
    nullable = _nullable(schema)
    if nullable is not None:
        return [] if value is None else [encode(value, nullable)]
    if schema["type"] == "object" and isinstance(value, dict):
        properties = schema["properties"]
        return {name: encode(item, properties[name]) if name in properties else item for name, item in value.items()}
    if schema["type"] == "array" and isinstance(value, list):
        return [encode(item, schema["items"]) for item in value]
    return value
