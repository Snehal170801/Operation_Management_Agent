from typing import Union

from pydantic import BaseModel

Value = Union[bool, int, float]


class ConfigItem(BaseModel):
    key: str
    label: str
    help: str
    kind: str
    unit: str
    minimum: float
    maximum: float
    value: Value
    default: Value
    changed: bool


class ConfigGroup(BaseModel):
    key: str
    label: str
    help: str
    items: list[ConfigItem]


class ConfigResponse(BaseModel):
    groups: list[ConfigGroup]


class SaveConfigRequest(BaseModel):
    values: dict[str, Union[bool, int, float, str]]


class ResetConfigRequest(BaseModel):
    keys: list[str] | None = None
