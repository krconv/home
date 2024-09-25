import appdaemon.plugins.hass.hassapi

class Healthcheck(appdaemon.plugins.hass.hassapi.Hass):

    async def initialize(self):
        # with open(os.path.join(self.app_dir, "lights.yaml")) as file:
        #     self.config = yaml.safe_load(file)

        # for circuit in self.config["circuits"]:
        # self.log(circuit["area"])

        # self.adapi = self.get_ad_api()

        self.log("test")
        
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

