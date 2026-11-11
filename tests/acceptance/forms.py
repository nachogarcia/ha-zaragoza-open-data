"""What a flow's form shows: suggested values and each field's selector."""

from collections.abc import Mapping

import probatio

from homeassistant.data_entry_flow import section


def suggested_values(schema: probatio.Schema | None) -> dict[str, object]:
    """Return what the form shows in each field, sections included."""
    assert schema is not None
    values: dict[str, object] = {}
    for marker, validator in schema.schema.items():
        if isinstance(validator, section):
            values[marker.schema] = suggested_values(validator.schema)
        else:
            values[marker.schema] = marker.description["suggested_value"]
    return values


def field_config(schema: probatio.Schema | None, name: str) -> Mapping[str, object]:
    """Return the selector configuration of the field ``name``."""
    assert schema is not None
    validator = next(v for m, v in schema.schema.items() if m.schema == name)
    config = validator.config
    assert isinstance(config, Mapping)
    return config


def field_options(schema: probatio.Schema | None, name: str) -> list[object]:
    """Return the options a select field offers."""
    options = field_config(schema, name)["options"]
    assert isinstance(options, list)
    return options


def field_names(schema: probatio.Schema | None) -> list[str]:
    """Return the names of the form's fields, in order (none without a schema)."""
    return [] if schema is None else [marker.schema for marker in schema.schema]
