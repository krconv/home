import json
import threading
import typing

import appdaemon.adapi
import appdaemon.appdaemon
import appdaemon.plugins.hass.hassapi
import appdaemon.plugins.hass.hassplugin
import appdaemon.utils
import pydantic
import utils_module

_ZHA_COORDINATOR_IEEE = "00:12:4b:00:2b:48:6a:bb"


@utils_module.singleton
class HomeAssistantWebSocket:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, adapi: appdaemon.adapi.ADAPI):
        self._plugin: appdaemon.plugins.hass.hassplugin.HassPlugin = (
            adapi.AD.plugins.plugin_objs["default"]["object"]
        )
        self._adapi = adapi
        self._send_lock = threading.Lock()
        self._id = 1
        self._initialized = False

    async def initialize(self):
        if not self._initialized:
            self._adapi.log("Initializing HomeAssistant websocket...")
            self._ws = await self._plugin.create_websocket()
            self._initialized = True
            self._adapi.run_every(self._keep_alive, "now+30", 30)

    async def _keep_alive(self, cb_args):
        await self.call("ping")

    async def call(self, type: str, **kwargs):
        with self._send_lock:
            id = self._id
            self._id += 1

            await self.initialize()

            self._ws.send(json.dumps({"id": id, "type": type, **kwargs}))

            data = json.loads(self._ws.recv())

            if "success" in data and not data["success"]:
                raise Exception(data["error"])
            return data["result"] if "result" in data else {}


class HomeAssistantEntity(pydantic.BaseModel):
    id: str
    entity_id: str
    device_id: str | None = None
    name: str | None = None
    area_id: str | None = None

    key: str

    @pydantic.computed_field
    @property
    def domain(self) -> str:
        return self.entity_id.split(".")[0]

    @pydantic.model_validator(mode="before")
    @classmethod
    def pick_best_key(cls, data: typing.Any) -> typing.Any:
        if data["translation_key"]:
            data["key"] = data["translation_key"]
        elif data["original_name"]:
            data["key"] = "_".join(data["original_name"].lower().split())
        else:
            data["key"] = data["entity_id"].split(".")[0]
        return data


class HomeAssistantDevice(pydantic.BaseModel):
    id: str
    name: str
    identifiers: typing.Annotated[
        dict[str, str | int],
        pydantic.BeforeValidator(lambda l: {t[0]: t[1] for t in l}),
    ]
    entities: list[HomeAssistantEntity]

    area_id: str | None = None

    args: dict[str, typing.Any] = {}

    @pydantic.computed_field
    @property
    def ieee(self) -> str | None:
        return str(self.identifiers.get("ieee")) if "ieee" in self.identifiers else None

    @pydantic.model_validator(mode="before")
    @classmethod
    def pick_best_name(cls, data: typing.Any) -> typing.Any:
        if data["name_by_user"]:
            data["name"] = data["name_by_user"]
        return data


@utils_module.singleton
class HomeAssistantEntityRegistry:
    def __init__(self, adapi: appdaemon.adapi.ADAPI):
        self._ws = HomeAssistantWebSocket(adapi)
        self._lock = threading.Lock()
        self._initialized = False
        self._entities_by_id: dict[str, HomeAssistantEntity] = {}

    async def initialize(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    entities = await self._ws.call("config/entity_registry/list")

                    self._entities_by_id = {
                        entity["id"]: HomeAssistantEntity.model_validate(
                            {
                                **entity,
                            }
                        )
                        for entity in entities
                    }

                    self._initialized = True

    async def get_all_entities(self) -> list[HomeAssistantEntity]:
        await self.initialize()

        return [entity for entity in self._entities_by_id.values()]

    async def set_entity_id(self, entity_id: str, entity: HomeAssistantEntity):
        await self._set_entity_property("new_entity_id", entity_id, entity)
        entity.entity_id = entity_id

    async def set_entity_name(self, name: str, entity: HomeAssistantEntity):
        await self._set_entity_property("name", name, entity)
        entity.name = name

    async def _set_entity_property(
        self, name: str, value: typing.Any, entity: HomeAssistantEntity
    ):
        await self._ws.call(
            "config/entity_registry/update", entity_id=entity.entity_id, **{name: value}
        )


@utils_module.singleton
class HomeAssistantDeviceRegistry:
    def __init__(self, adapi: appdaemon.adapi.ADAPI):
        self._ws = HomeAssistantWebSocket(adapi)
        self._entity_registry = HomeAssistantEntityRegistry(adapi)
        self._lock = threading.Lock()
        self._initialized = False
        self._devices_by_id: dict[str, HomeAssistantDevice] = {}
        self._zha_coordinator_id: HomeAssistantDevice | None = None

    async def initialize(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    devices = await self._ws.call("config/device_registry/list")

                    entities_by_device_id = {}
                    for entity in await self._entity_registry.get_all_entities():
                        device_id = entity.device_id
                        try:
                            entities_by_device_id[device_id].append(entity)
                        except KeyError:
                            entities_by_device_id[device_id] = [entity]

                    self._devices_by_id = {
                        device["id"]: HomeAssistantDevice.model_validate(
                            {
                                "entities": (
                                    entities_by_device_id[device["id"]]
                                    if device["id"] in entities_by_device_id
                                    else []
                                ),
                                **device,
                            }
                        )
                        for device in devices
                    }

                    try:
                        self._zha_coordinator_id = [
                            device.id
                            for device in self._devices_by_id.values()
                            if device.ieee == _ZHA_COORDINATOR_IEEE
                        ][0]
                    except IndexError:
                        self._zha_coordinator_id = None

                    self._initialized = True

    async def get_device(self, id) -> HomeAssistantDevice | None:
        await self.initialize()

        return self._devices_by_id.get(id)

    async def set_device_name(self, name: str, device: HomeAssistantDevice) -> None:
        await self._set_device_property("name_by_user", name, device)
        device.name = name

    async def set_device_area(self, area_id: str, device: HomeAssistantDevice) -> None:
        await self._set_device_property("area_id", area_id, device)
        device.area_id = area_id

    async def _set_device_property(
        self, name: str, value: typing.Any, device: HomeAssistantDevice
    ):
        await self._ws.call(
            "config/device_registry/update", device_id=device.id, **{name: value}
        )

    async def get_zha_coordinator(self) -> HomeAssistantDevice | None:
        if self._zha_coordinator_id:
            return await self.get_device(self._zha_coordinator_id)
        return None
