"""Models used by multiple MQTT modules."""
from __future__ import annotations

from ast import literal_eval
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
import datetime as dt
from typing import TYPE_CHECKING, Any, TypedDict, Union

import attr

from homeassistant.const import ATTR_ENTITY_ID, ATTR_NAME
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import template
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.service_info.mqtt import ReceivePayloadType
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, TemplateVarsType

if TYPE_CHECKING:
    from .client import MQTT, Subscription
    from .debug_info import TimestampedPublishMessage
    from .device_trigger import Trigger

_SENTINEL = object()

ATTR_THIS = "this"

PublishPayloadType = Union[str, bytes, int, float, None]


@attr.s(slots=True, frozen=True)
class PublishMessage:
    """MQTT Message."""

    topic: str = attr.ib()
    payload: PublishPayloadType = attr.ib()
    qos: int = attr.ib()
    retain: bool = attr.ib()


@attr.s(slots=True, frozen=True)
class ReceiveMessage:
    """MQTT Message."""

    topic: str = attr.ib()
    payload: ReceivePayloadType = attr.ib()
    qos: int = attr.ib()
    retain: bool = attr.ib()
    subscribed_topic: str = attr.ib(default=None)
    timestamp: dt.datetime = attr.ib(default=None)


AsyncMessageCallbackType = Callable[[ReceiveMessage], Coroutine[Any, Any, None]]
MessageCallbackType = Callable[[ReceiveMessage], None]


class SubscriptionDebugInfo(TypedDict):
    """Class for holding subscription debug info."""

    messages: deque[ReceiveMessage]
    count: int


class EntityDebugInfo(TypedDict):
    """Class for holding entity based debug info."""

    subscriptions: dict[str, SubscriptionDebugInfo]
    discovery_data: DiscoveryInfoType
    transmitted: dict[str, dict[str, deque[TimestampedPublishMessage]]]


class TriggerDebugInfo(TypedDict):
    """Class for holding trigger based debug info."""

    device_id: str
    discovery_data: DiscoveryInfoType


class MqttCommandTemplate:
    """Class for rendering MQTT payload with command templates."""

    def __init__(
        self,
        command_template: template.Template | None,
        *,
        hass: HomeAssistant | None = None,
        entity: Entity | None = None,
    ) -> None:
        """Instantiate a command template."""
        self._template_state: template.TemplateStateFromEntityId | None = None
        self._command_template = command_template
        if command_template is None:
            return

        self._entity = entity

        command_template.hass = hass

        if entity:
            command_template.hass = entity.hass

    @callback
    def async_render(
        self,
        value: PublishPayloadType = None,
        variables: TemplateVarsType = None,
    ) -> PublishPayloadType:
        """Render or convert the command template with given value or variables."""

        def _convert_outgoing_payload(
            payload: PublishPayloadType,
        ) -> PublishPayloadType:
            """Ensure correct raw MQTT payload is passed as bytes for publishing."""
            if isinstance(payload, str):
                try:
                    native_object = literal_eval(payload)
                    if isinstance(native_object, bytes):
                        return native_object

                except (ValueError, TypeError, SyntaxError, MemoryError):
                    pass

            return payload

        if self._command_template is None:
            return value

        values: dict[str, Any] = {"value": value}
        if self._entity:
            values[ATTR_ENTITY_ID] = self._entity.entity_id
            values[ATTR_NAME] = self._entity.name
            if not self._template_state:
                self._template_state = template.TemplateStateFromEntityId(
                    self._command_template.hass, self._entity.entity_id
                )
            values[ATTR_THIS] = self._template_state

        if variables is not None:
            values.update(variables)
        return _convert_outgoing_payload(
            self._command_template.async_render(values, parse_result=False)
        )


class MqttValueTemplate:
    """Class for rendering MQTT value template with possible json values."""

    def __init__(
        self,
        value_template: template.Template | None,
        *,
        hass: HomeAssistant | None = None,
        entity: Entity | None = None,
        config_attributes: TemplateVarsType = None,
    ) -> None:
        """Instantiate a value template."""
        self._template_state: template.TemplateStateFromEntityId | None = None
        self._value_template = value_template
        self._config_attributes = config_attributes
        if value_template is None:
            return

        value_template.hass = hass
        self._entity = entity

        if entity:
            value_template.hass = entity.hass

    @callback
    def async_render_with_possible_json_value(
        self,
        payload: ReceivePayloadType,
        default: ReceivePayloadType | object = _SENTINEL,
        variables: TemplateVarsType = None,
    ) -> ReceivePayloadType:
        """Render with possible json value or pass-though a received MQTT value."""
        if self._value_template is None:
            return payload

        values: dict[str, Any] = {}

        if variables is not None:
            values.update(variables)

        if self._config_attributes is not None:
            values.update(self._config_attributes)

        if self._entity:
            values[ATTR_ENTITY_ID] = self._entity.entity_id
            values[ATTR_NAME] = self._entity.name
            if not self._template_state and self._value_template.hass:
                self._template_state = template.TemplateStateFromEntityId(
                    self._value_template.hass, self._entity.entity_id
                )
            values[ATTR_THIS] = self._template_state

        if default == _SENTINEL:
            return self._value_template.async_render_with_possible_json_value(
                payload, variables=values
            )

        return self._value_template.async_render_with_possible_json_value(
            payload, default, variables=values
        )


@dataclass
class MqttData:
    """Keep the MQTT entry data."""

    client: MQTT | None = None
    config: ConfigType | None = None
    debug_info_entities: dict[str, EntityDebugInfo] = field(default_factory=dict)
    debug_info_triggers: dict[tuple[str, str], TriggerDebugInfo] = field(
        default_factory=dict
    )
    device_triggers: dict[str, Trigger] = field(default_factory=dict)
    discovery_registry_hooks: dict[tuple[str, str], CALLBACK_TYPE] = field(
        default_factory=dict
    )
    last_discovery: float = 0.0
    reload_dispatchers: list[CALLBACK_TYPE] = field(default_factory=list)
    reload_entry: bool = False
    reload_handlers: dict[str, Callable[[], Coroutine[Any, Any, None]]] = field(
        default_factory=dict
    )
    reload_needed: bool = False
    subscriptions_to_restore: list[Subscription] = field(default_factory=list)
    updated_config: ConfigType = field(default_factory=dict)
