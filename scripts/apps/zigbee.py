import asyncio
import datetime
import json
import random
import typing

import appdaemon.adapi
import appdaemon.plugins.hass.hassapi
import apps.mqtt as mqtt
import apps.utils as utils
import pydantic


class ZigBeeDeviceState(pydantic.BaseModel):
    updated_at: datetime.datetime | None = None
    update: asyncio.Event = pydantic.Field(default_factory=asyncio.Event)

    properties: dict[str, typing.Any] = pydantic.Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


class ZigBeeDevice(pydantic.BaseModel):
    base_topic: str
    type: typing.Literal["Coordinator", "Router", "EndDevice"]
    ieee_address: str
    network_address: int
    friendly_name: str
    interview_completed: bool
    interviewing: bool
    supported: bool
    power_source: str | None = None
    manufacturer: str | None = None
    model_id: str | None = None
    software_build_id: str | None = None
    date_code: str | None = None

    state: ZigBeeDeviceState


class ZigBeeGroup(pydantic.BaseModel):
    base_topic: str
    id: int
    friendly_name: str


@utils.singleton
class ZigBeeClient(appdaemon.plugins.hass.hassapi.Hass):

    _lock = asyncio.Lock()
    _is_initialized: bool = False

    _mqtt: mqtt.MqttClient

    _base_topics: list[str]
    _devices_by_ieee: dict[str, ZigBeeDevice]
    _devices_ieees_by_friendly_name: dict[str, str]
    _groups_by_id: dict[str, ZigBeeGroup]

    def __init__(self, adapi: appdaemon.adapi.ADAPI):
        self.adapi = adapi
        config = adapi.plugin_config["HASS"]
        self._base_topics = config.model_extra["zigbee_base_topics"]

    async def initialize(self) -> None:
        """Initialize the app and its components."""
        if self._is_initialized:
            return

        async with self._lock:
            if self._is_initialized:
                return

            self._mqtt = mqtt.MqttClient(self.adapi)
            await self._mqtt.initialize()

            self._devices_by_ieee = {}
            self._devices_ieees_by_friendly_name = {}
            self._groups_by_id = {}

            for base_topic in self._base_topics:
                received_devices = asyncio.Event()

                def on_devices_received(topic: str, payload: str):
                    """Callback for receiving devices from MQTT."""
                    try:
                        data = json.loads(payload)
                        for device in data:
                            ieee = device.get("ieee_address")
                            if ieee:
                                ieee = ieee.replace("0x", "").lower()
                                ieee = ":".join(
                                    ieee[i : i + 2] for i in range(0, len(ieee), 2)
                                )
                                if ieee in self._devices_by_ieee:
                                    for key, value in device.items():
                                        try:
                                            setattr(
                                                self._devices_by_ieee[ieee], key, value
                                            )
                                        except ValueError:
                                            pass
                                else:
                                    self._devices_by_ieee[ieee] = ZigBeeDevice(
                                        base_topic=base_topic,
                                        **device,
                                        state=ZigBeeDeviceState(update=asyncio.Event()),
                                    )
                                self._devices_ieees_by_friendly_name[
                                    device["friendly_name"]
                                ] = ieee
                        received_devices.set()
                    except json.JSONDecodeError as e:
                        self.adapi.log(f"Error decoding JSON from {topic}: {e}")

                self._mqtt.subscribe(
                    f"{base_topic}/bridge/devices",
                    on_devices_received,
                )

                try:
                    await asyncio.wait_for(received_devices.wait(), 10)
                except asyncio.TimeoutError:
                    self.adapi.log("Failed to receive devices from MQTT within timeout")
                    raise TimeoutError("MQTT devices reception timeout")

                received_groups = asyncio.Event()

                def on_groups_received(topic: str, payload: str):
                    """Callback for receiving devices from MQTT."""
                    try:
                        if not topic.startswith(base_topic):
                            self.adapi.log(
                                f"Received groups on unexpected topic {topic}, expected prefix {base_topic}"
                            )
                            return
                        data = json.loads(payload)
                        for group in data:
                            self._groups_by_id[f"{base_topic[-1]}-{group['id']}"] = (
                                ZigBeeGroup(base_topic=base_topic, **group)
                            )
                        received_groups.set()
                    except json.JSONDecodeError as e:
                        self.adapi.log(f"Error decoding JSON from {topic}: {e}")

                self._mqtt.subscribe(
                    f"{base_topic}/bridge/groups",
                    on_groups_received,
                )

                try:
                    await asyncio.wait_for(received_groups.wait(), 10)
                except asyncio.TimeoutError:
                    self.adapi.log("Failed to receive groups from MQTT within timeout")
                    raise TimeoutError("MQTT devices reception timeout")

                def on_state_received(topic: str, payload: str):
                    """Callback for receiving device state updates."""
                    try:
                        friendly_name = topic.split("/")[-1]
                        if friendly_name not in self._devices_ieees_by_friendly_name:
                            return

                        ieee = self._devices_ieees_by_friendly_name[friendly_name]
                        device = self._devices_by_ieee[ieee]
                        data = json.loads(payload)
                        update = device.state.update
                        device.state.properties = device.state.properties | data
                        device.state.updated_at = datetime.datetime.now()
                        device.state.update = asyncio.Event()
                        update.set()
                    except json.JSONDecodeError as e:
                        self.adapi.log(f"Error decoding JSON from {topic}: {e}")

                self._mqtt.subscribe(
                    f"{base_topic}/+",
                    on_state_received,
                )

        self._is_initialized = True

    def get_device_by_ieee(self, ieee: str) -> ZigBeeDevice:
        """Get a ZigBee device by its IEEE address."""
        return self._devices_by_ieee[ieee]

    def get_devices_by_ieee(self, ieees: list[str]) -> list[ZigBeeDevice]:
        """Get a list of ZigBee devices by their IEEE addresses."""
        return [self._devices_by_ieee[ieee] for ieee in ieees]

    def get_device_by_friendly_name(self, friendly_name: str) -> ZigBeeDevice | None:
        """Get a ZigBee device by its friendly name."""
        ieee = self._devices_ieees_by_friendly_name.get(friendly_name)
        if ieee:
            return self._devices_by_ieee.get(ieee)
        return None

    def get_group_by_id(self, group_id: str) -> ZigBeeGroup:
        """Get a ZigBee group by its ID."""
        return self._groups_by_id[group_id]

    async def set_property(
        self,
        device: ZigBeeDevice | ZigBeeGroup,
        property: str,
        value: typing.Any,
        *,
        transition: int = 0,
    ) -> None:
        data: typing.Any = None
        if property == "brightness":
            data = {
                "command": {
                    "cluster": "genLevelCtrl",
                    "command": "moveToLevel",
                    "payload": {
                        "level": value,
                        "transtime": transition * 10 if transition else 0,
                    },
                }
            }
        elif property == "color_temp":
            data = {
                "command": {
                    "cluster": "lightingColorCtrl",
                    "command": "moveToColorTemp",
                    "payload": {
                        "colortemp": value,
                        "transtime": transition * 10 if transition else 0,
                    },
                }
            }
        else:
            data = {
                property: value,
            }

        self._mqtt.publish(f"{device.base_topic}/{device.friendly_name}/set", data)

    async def set_and_verify_property(
        self,
        device: ZigBeeDevice,
        property: str,
        value: typing.Any,
        *,
        transition: int = 0,
    ):
        """Set a property on a device and verify it was set correctly."""
        for _ in range(3):
            update = device.state.update
            await self.set_property(device, property, value, transition=transition)
            try:
                await asyncio.wait_for(update.wait(), 10)
            except asyncio.TimeoutError:
                self.adapi.log(
                    f"Failed to set {property} on {device.friendly_name} within timeout",
                    level="ERROR",
                )
                continue

            if (
                property in device.state.properties
                and device.state.properties[property] == value
            ):
                return True

        return False

    async def get_ungrouped_devices(
        self,
        group: ZigBeeGroup,
        devices_to_check: list[ZigBeeDevice],
    ) -> list[ZigBeeDevice]:
        updates = [(device, device.state.update) for device in devices_to_check]
        ungrouped_devices: list[ZigBeeDevice] = []

        for attempt in range(120):
            self._mqtt.publish(
                f"{group.base_topic}/{group.friendly_name}/get", {"state": ""}
            )

            ungrouped_devices = [
                devices_to_check[i]
                for i, updated in enumerate(
                    await asyncio.gather(
                        *[self._wait_for(update, 5) for _, update in updates]
                    )
                )
                if not updated
            ]

            if not ungrouped_devices:
                return []

        self.adapi.log(
            f"Devices did not respond to group {group.friendly_name} after {attempt + 1} attempts: {','.join([d.friendly_name for d in ungrouped_devices])}"
        )
        return ungrouped_devices

    async def get_unresponsive_devices(
        self, devices_to_check: list[ZigBeeDevice]
    ) -> list[ZigBeeDevice]:
        return [
            devices_to_check[i]
            for i, responsive in enumerate(
                await asyncio.gather(
                    *[self.is_device_responsive(device) for device in devices_to_check]
                )
            )
            if not responsive
        ]

    async def is_device_responsive(self, device: ZigBeeDevice) -> bool:
        update = device.state.update

        for attempt in range(24):
            self._mqtt.publish(
                f"{device.base_topic}/{device.friendly_name}/get", {"state": ""}
            )

            if await self._wait_for(update, 5):
                return True

        self.adapi.log(
            f"Device {device.friendly_name} is unresponsive after {attempt + 1} attempts"
        )
        return False

    async def permit_join(self, device: ZigBeeDevice, duration: int = 60) -> bool:
        return await self._send_bridge_request(
            device.base_topic,
            "permit_join",
            {
                "time": duration,
                "device": device.friendly_name,
            },
        )

    async def add_to_group(self, device: ZigBeeDevice, group: ZigBeeGroup) -> bool:
        return await self._send_bridge_request(
            device.base_topic,
            "group/members/add",
            {
                "group": group.friendly_name,
                "device": device.friendly_name,
            },
        )

    async def _send_bridge_request(
        self, base_topic: str, topic: str, payload: dict
    ) -> bool:
        for attempt in range(3):
            responded = asyncio.Event()
            transaction = random.randint(1000, 9999)

            def on_response(topic: str, payload: str):
                data = json.loads(payload)
                if data.get("transaction") == transaction:
                    responded.set()

            self._mqtt.subscribe(
                f"{base_topic}/bridge/response/{topic}",
                on_response,
            )

            try:
                self._mqtt.publish(
                    f"{base_topic}/bridge/request/{topic}",
                    payload | {"transaction": transaction},
                )

                if not await self._wait_for(responded, 15):
                    continue

            finally:
                self._mqtt.unsubscribe(
                    f"{base_topic}/bridge/response/{topic}", on_response
                )

            return True
        return False

    async def _wait_for(self, event: asyncio.Event, timeout: int = 10) -> bool:
        """Wait for an update event with a timeout."""
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
