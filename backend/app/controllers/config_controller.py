from app.core import audit, tunables
from app.core.exceptions import InvalidInput
from app.models.auth_schemas import CurrentUser
from app.models.config_schemas import ConfigGroup, ConfigItem, ConfigResponse


def get_config() -> ConfigResponse:
    groups = []
    for key, label, help_text in tunables.GROUPS:
        items = []
        for t in (t for t in tunables.CATALOG if t.group == key):
            value, default = tunables.current(t.key), tunables.DEFAULTS[t.key]
            items.append(ConfigItem(key=t.key, label=t.label, help=t.help, kind=t.kind, unit=t.unit, minimum=t.minimum,
                                    maximum=t.maximum, value=value, default=default, changed=value != default))
        groups.append(ConfigGroup(key=key, label=label, help=help_text, items=items))
    return ConfigResponse(groups=groups)


def _record(changed: dict, user: CurrentUser, action: str) -> None:
    for key, (old, new) in changed.items():
        audit.record(
            action, actor_user_id=user.user_id, actor_username=user.username,
            target_type="config", target_id=key, detail={"from": old, "to": new},
        )


def save_config(values: dict, user: CurrentUser) -> ConfigResponse:
    try:
        changed = tunables.save(values, user.username)
    except tunables.InvalidSetting as exc:
        raise InvalidInput(str(exc)) from exc
    _record(changed, user, "config.change")
    return get_config()


def reset_config(keys: list[str] | None, user: CurrentUser) -> ConfigResponse:
    try:
        changed = tunables.reset(keys, user.username)
    except tunables.InvalidSetting as exc:
        raise InvalidInput(str(exc)) from exc
    _record(changed, user, "config.reset")
    return get_config()
