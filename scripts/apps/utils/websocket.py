import appdaemon.plugins.hass.hassapi
import appdaemon.plugins.hass.hassplugin
import appdaemon.utils
import appdaemon.appdaemon


import json


class HomeAssistantWebSocket:
    _hass_plugin: appdaemon.plugins.hass.hassplugin.HassPlugin | None = None

    def __init__(self, _appdaemon: appdaemon.appdaemon.AppDaemon):
        self._initialized = False
        self._appdaemon = _appdaemon
    
    async def initialize(self):
        if not self._initialized:
            self._hass_plugin = await self._appdaemon.plugins.get_plugin_object("default") # type: ignore
            self._id = 1
            self._initialized = True

    async def call(self, type: str, **kwargs):
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

