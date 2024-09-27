import json
import appdaemon.utils
import typing
import appdaemon.plugins.hass.hassapi
import appdaemon.plugins.hass.hassplugin


class LightCircuitApp(appdaemon.plugins.hass.hassapi.Hass):
    _area_id: str
    _lights: list[dict[str, typing.Any]]
    _switches: dict[str, typing.Any]

    async def initialize(self) -> None:
        hass_plugin: appdaemon.plugins.hass.hassplugin.HassPlugin = (
            await self.AD.plugins.get_plugin_object("hass")
        )
        self.ws = await hass_plugin.create_websocket()
        self._id = 1

        await appdaemon.utils.run_in_executor(
            self,
            self.ws.send,
            json.dumps({"id": self._id, "type": "config/device_registry/list"}),
        )
        all_devices = json.loads(self.ws.recv())["result"]
        self._id += 1

        await appdaemon.utils.run_in_executor(
            self,
            self.ws.send,
            json.dumps({"id": self._id, "type": "config/entity_registry/list"}),
        )
        all_entities = json.loads(self.ws.recv())["result"]
        self._id += 1

        light_ids = set([light["id"] for light in self.args["lights"]])
        self._lights = [{**device, "entities": [entity for entity in all_entities if entity["device_id"] == device["id"]]} for device in all_devices if device["id"] in light_ids]  # type: ignore

        switch_ids = set([switch["id"] for switch in self.args["switches"]])
        self._switches = [{**device, "entities": [entity for entity in all_entities if entity["device_id"] == device["id"]]} for device in all_devices if device["id"] in switch_ids]  # type: ignore

        self.run_every(self.check_lights, "now", 60)

    async def check_lights(self, cb_args):
        self.log("checking lights")
        for light in self._lights:
            light_entity = [
                entity
                for entity in light["entities"]
                if entity["entity_id"].startswith("light")
            ][0]
            ieee = [id[1] for id in light["identifiers"] if id[0] == "zha"][0]
            await appdaemon.utils.run_in_executor(
                self,
                self.ws.send,
                json.dumps(
                    {
                        "type": "zha/devices/clusters/attributes/value",
                        "ieee": ieee,
                        "endpoint_id": 8,
                        "cluster_id": 6,
                        "cluster_type": "in",
                        "attribute": 0,
                        "id": self._id,
                    }
                ),
            )
            light_result = json.loads(self.ws.recv())
            self._id += 1
            if not light_result["success"]:
                self.log(
                    f"Light {light_entity['entity_id']} is unresponsive, marking unavailable"
                )
                await self.set_state(
                    entity_id=light_entity["entity_id"],
                    state="unavailable",
                    namespace="hass",
                )
            else:
                await self.set_state(
                    entity_id=light_entity["entity_id"],
                    state="on" if "true" in light_result["result"] else "off",
                    namespace="hass",
                )
        for switch in self._switches:
            switch_entity = [
                entity
                for entity in switch["entities"]
                if entity["entity_id"].startswith("light")
            ][0]
            ieee = [id[1] for id in switch["identifiers"] if id[0] == "zha"][0]
            await appdaemon.utils.run_in_executor(
                self,
                self.ws.send,
                json.dumps(
                    {
                        "type": "zha/devices/clusters/attributes/value",
                        "ieee": ieee,
                        "endpoint_id": 1,
                        "cluster_id": 6,
                        "cluster_type": "in",
                        "attribute": 0,
                        "id": self._id,
                    }
                ),
            )
            switch_result = json.loads(self.ws.recv())
            self._id += 1
            if not switch_result["success"]:
                self.log(
                    f"Light {switch_entity['entity_id']} is unresponsive, marking unavailable"
                )
                await self.set_state(
                    entity_id=switch_entity["entity_id"],
                    state="unavailable",
                    namespace="hass",
                )
            else:
                await self.set_state(
                    entity_id=switch_entity["entity_id"],
                    state="on" if "true" in switch_result["result"] else "off",
                    namespace="hass",
                )


class Healthcheck:
    async def initialize(self):
        # with open(os.path.join(self.app_dir, "lights.yaml")) as file:
        #     self.config = yaml.safe_load(file)

        # for circuit in self.config["circuits"]:
        # self.log(circuit["area"])

        # self.adapi = self.get_ad_api()

        # for entity in await self.get_state():
        #   if "main_bedroom_switch" in str(entity):
        #     self.log(entity)

        # for entity_id, entity in self.get_state().items():
        #   if "main_bedroom_ceiling" in entity_id:
        #     self.log(entity)

        # self.hass = await self.AD.plugins.get_plugin_object("default")
        # self.log(hass.session.get(""))
        # ws = await self.hass.create_websocket()
        # _id = 1
        # sub = json.dumps({"id": _id, "type": "config/device_registry/list"})
        # await appdaemon.utils.run_in_executor(self, ws.send, sub)
        # result = json.loads(ws.recv())
        # for device in result["result"]:
        #     if "b4:3a:31:ff:fe:26:f9:96" in str(device):
        #         self.log(device)
        pass
