import appdaemon.plugins.hass.hassapi
import appdaemon.plugins.hass.hassplugin
import appdaemon.utils
import appdaemon.appdaemon


import yaml
import os
import json


class ConfigureLightCircuits(appdaemon.plugins.hass.hassapi.Hass):

    async def initialize(self):
        with open(os.path.join(self.app_dir, "lights.yaml")) as file:
            self.config = yaml.safe_load(file)

        # for circuit in self.config["circuits"]:
        # self.log(circuit["area"])

        self.adapi = self.get_ad_api()
        # for entity in self.get_state():
        #   if "main_bedroom_switch" in str(entity):
        #     self.log(entity)

        # for entity_id, entity in self.get_state().items():
        #   if "main_bedroom_ceiling" in entity_id:
        #     self.log(entity)

        self.hass = await self.AD.plugins.get_plugin_object("default")
        # self.log(hass.session.get(""))
        ws = await self.hass.create_websocket()
        _id = 1
        sub = json.dumps({"id": _id, "type": "config/device_registry/list"})
        await appdaemon.utils.run_in_executor(self, ws.send, sub)
        result = json.loads(ws.recv())
        for device in result["result"]:
            if "b4:3a:31:ff:fe:26:f9:96" in str(device):
                self.log(device)


class HomeAssistantWebSocket:
    def __init__(self, AD: appdaemon.appdaemon.AppDaemon):
        self.hass = await self.AD.plugins.get_plugin_object("default")
        self.ws = await self.hass.create_websocket()
        self._id = 1
        

    async def call(self, type: string, **kwargs):
        id = self._id
        self._id += 1
        await appdaemon.utils.run_in_executor(
            self,
            ws.send,
            json.dumps({"id": id, "type": type, **kwargs}),
        )
        result = json.loads(ws.recv())
        if not result["success"]:
            raise Exception(f"Received a WebSocket error from Home Assistant: {result['error']}")
        return result["result"]

