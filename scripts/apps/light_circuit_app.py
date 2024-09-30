import threading
import traceback
import typing

import appdaemon.plugins.hass.hassapi
import appdaemon.plugins.hass.hassplugin
import appdaemon.utils
import hass_module


class LightCircuitApp(appdaemon.plugins.hass.hassapi.Hass):
    _ws: hass_module.HomeAssistantWebSocket
    _device_registry: hass_module.HomeAssistantDeviceRegistry
    _entity_registry: hass_module.HomeAssistantEntityRegistry
    _area_id: str
    _lights: list[hass_module.HomeAssistantDevice]
    _switches: list[hass_module.HomeAssistantDevice]
    _zha_coordinator: hass_module.HomeAssistantDevice | None
    _lock: threading.Lock

    async def initialize(self) -> None:
        self._ws = hass_module.HomeAssistantWebSocket(self)
        self._device_registry = hass_module.HomeAssistantDeviceRegistry(self)
        self._entity_registry = hass_module.HomeAssistantEntityRegistry(self)
        self._lock = threading.Lock()

        await self._load_devices()

        self.run_every(self._configure_circuit, "now", 60 * 60)
        self.run_every(self._healthcheck, "now", 60)

    async def get_lights(self) -> list[hass_module.HomeAssistantDevice]:
        return self._lights

    async def get_switches(self) -> list[hass_module.HomeAssistantDevice]:
        return self._switches

    async def get_friendly_name(self) -> str:
        return self._camelcase(self.name)

    async def _load_devices(self):
        if not self._lock.acquire(blocking=False):
            return

        self._lights = []
        self._switches = []

        if "TODO" in str(self.args):
            raise ValueError("Please configure the app with the correct devices")

        try:
            for light_args in self.args.get("lights", []):
                light = await self._device_registry.get_device(light_args["id"])
                light.args = light_args
                self._lights.append(light)

            for switch_args in self.args.get("switches", []):
                switch = await self._device_registry.get_device(switch_args["id"])
                switch.args = switch_args
                self._switches.append(switch)

            self._zha_coordinator = await self._device_registry.get_zha_coordinator()
        finally:
            self._lock.release()

    async def _configure_circuit(self, cb_args):
        for index, switch in enumerate(self._switches):
            try:
                suffix = chr(97 + index) if len(self._switches) > 1 else None
                await self._configure_switch(switch, suffix)
                self.log(f"Configured switch {switch.name}")
            except Exception as e:
                self.error(f"Error configuring switch {switch.name} ({switch.id})")
                traceback.print_exception(e)

        for index, light in enumerate(self._lights):
            try:
                suffix = chr(97 + index) if len(self._lights) > 1 else None
                await self._configure_light(light, suffix)
                self.log(f"Configured light {light.name}")
            except Exception as e:
                self.error(f"Error configuring light {light.name} ({switch.id})")
                traceback.print_exception(e)

    async def _configure_switch(
        self, switch: hass_module.HomeAssistantDevice, suffix: str | None
    ):
        await self._configure_switch_bindings(switch)
        await self._configure_switch_settings(switch)
        await self._configure_switch_naming_and_area(switch, suffix)

    async def _configure_switch_bindings(self, switch: hass_module.HomeAssistantDevice):
        is_smart_bulb_switch = len(self._lights) > 0

        bind_to: list[hass_module.HomeAssistantDevice] = []

        if is_smart_bulb_switch:
            for light in self._lights:
                bind_to.append(light)

            await self._configure_device_entity_by_key(
                switch, "relay_click_in_on_off_mode", False
            )

        for other_switch in self._switches:
            if other_switch.id != switch.id:
                bind_to.append(other_switch)

        await self._bind_to_devices(from_=switch, to=bind_to)

    async def _configure_switch_settings(self, switch: hass_module.HomeAssistantDevice):
        await self._configure_device_entity_by_key(switch, "button_delay", 0)

        always_powered = len(self._lights) > 0 or switch.args["type"] == "remote"
        await self._configure_device_entity_by_key(
            switch,
            "smart_bulb_mode",
            always_powered,
        )

        await self._configure_device_entity_by_key(switch, "output_mode", "Dimmer")

    async def _configure_switch_naming_and_area(
        self, device: hass_module.HomeAssistantDevice, suffix: str | None
    ):
        name = self.args["area"]["id"]
        if "name_override" in device.args:
            name = device.args["name_override"]
        await self._configure_device_naming_and_area(
            device, f"{name}_switch{f'_{suffix}' if suffix else ''}"
        )

    async def _configure_light(
        self, light: hass_module.HomeAssistantDevice, suffix: str | None
    ):
        await self._configure_light_bindings(light)
        await self._configure_light_naming_and_area(light, suffix)

    async def _configure_light_bindings(self, switch: hass_module.HomeAssistantDevice):
        await self._bind_to_devices(from_=switch, to=[])

    async def _configure_light_naming_and_area(
        self, device: hass_module.HomeAssistantDevice, suffix: str | None
    ):
        name_without_plural = self.name[:-1] if self.name.endswith("s") else self.name
        await self._configure_device_naming_and_area(
            device, f"{name_without_plural}{f'_{suffix}' if suffix else ''}"
        )

    async def _configure_device_naming_and_area(
        self, device: hass_module.HomeAssistantDevice, api_name: str
    ):
        friendly_name = self._camelcase(api_name)

        if device.name != friendly_name:
            self.log(f'Updating device "{device.name}" name to "{friendly_name}"')
            await self._device_registry.set_device_name(friendly_name, device)

        if device.area_id != self.args["area"]["id"]:
            self.log(
                f'Updating device "{device.name}" area to {self.args["area"]["id"]}'
            )
            await self._device_registry.set_device_area(self.args["area"]["id"], device)

        for entity in device.entities:
            entity_type = entity.key
            entity_id = f"{entity.domain}.{api_name}_{entity_type}"
            entity_name = f"{friendly_name} {self._camelcase(entity_type) if entity_type != 'light' else ''}"

            if entity.entity_id != entity_id:
                self.log(f'Updating entity "{entity.name}" ID to {entity_id}')
                await self._entity_registry.set_entity_id(entity_id, entity)

            if entity.name != entity_name:
                self.log(f'Updating entity "{entity.name}" name to {entity_name}')
                await self._entity_registry.set_entity_name(entity_name, entity)

    async def _bind_to_devices(
        self,
        from_: hass_module.HomeAssistantDevice,
        to: list[hass_module.HomeAssistantDevice],
    ):
        devices_by_ieee = {device.ieee: device for device in to}
        desired_bindings = set([device.ieee for device in to if device.ieee])
        existing_bindings = await self._get_bindings(from_)

        for ieee in desired_bindings.difference(existing_bindings):
            self.log(
                f"Binding {from_.name} to {devices_by_ieee[ieee].name if ieee in devices_by_ieee else ieee}"
            )
            await self._ws.call(
                "zha/devices/bind",
                source_ieee=from_.ieee,
                target_ieee=ieee,
            )

        for ieee in existing_bindings.difference(desired_bindings):
            if self._zha_coordinator and ieee == self._zha_coordinator.ieee:
                # don't remove bindings to the coordinator
                continue

            self.log(
                f"Unbinding {from_.name} from {devices_by_ieee[ieee].name if ieee in devices_by_ieee else ieee}"
            )
            await self._ws.call(
                "zha/devices/unbind",
                source_ieee=from_.ieee,
                target_ieee=ieee,
            )

    async def _get_bindings(self, from_: hass_module.HomeAssistantDevice) -> set[str]:
        raw_bindings = await self._ws.call(
            "execute_script",
            sequence=[
                {
                    "action": "zha_toolkit.binds_get",
                    "data": {"ieee": from_.ieee},
                    "response_variable": "service_result",
                },
                {"stop": "done", "response_variable": "service_result"},
            ],
        )
        # zha manages which clusters/endpoints are bound; just return unique ieee addresses
        try:
            return set(
                [
                    binding["dst"]["dst_ieee"]
                    for _, binding in raw_bindings["response"]["result"].items()
                ]
            )
        except KeyError:
            return set()

    async def _configure_device_entity_by_key(
        self, device: hass_module.HomeAssistantDevice, key: str, value: typing.Any
    ):
        entity = self._get_device_entity_by_key(device, key)
        if not entity:
            self.error(
                f"Could not find entity {key} for device {device.name}, will not update"
            )
            return
        existing_state = await self.get_state(entity.entity_id)

        domain = entity.domain
        request: dict[str, typing.Any] = {"domain": domain}

        if domain == "number":
            if existing_state == str(value):
                return

            request["service"] = "set_value"
            request["service_data"] = {"entity_id": entity.entity_id, "value": value}
        elif domain == "select":
            if existing_state == value:
                return

            request["service"] = "select_option"
            request["service_data"] = {"option": value}
            request["target"] = {"entity_id": entity.entity_id}
        elif domain == "switch":
            value = "on" if value else "off"
            if existing_state == value:
                return

            request["service"] = "turn_on" if value else "turn_off"
            request["service_data"] = {"entity_id": entity.entity_id}

        self.log(f"Setting {device.name} {key} to {value}")
        await self._ws.call("call_service", **request)

    def _get_device_entity_by_key(
        self, device: hass_module.HomeAssistantDevice, key: str
    ) -> hass_module.HomeAssistantEntity | None:
        try:
            return [entity for entity in device.entities if entity.key == key][0]
        except IndexError:
            return None

    def _camelcase(self, snake_case: str) -> str:
        return " ".join(word.capitalize() for word in snake_case.split("_"))

    async def _healthcheck(self, cb_args: typing.Any) -> None:
        if not self._lock.acquire(blocking=False):
            return

        try:
            await self._fix_non_synced_lights()

        finally:
            self._lock.release()

    async def _fix_non_synced_lights(self) -> None:
        primary_switch = [
            switch for switch in self._switches if switch.args["type"] == "hardwired"
        ][0]
        primary_switch_entity = self._get_device_entity_by_key(primary_switch, "light")
        if not primary_switch_entity:
            self.error(
                f"No primary switch light entity found for device {primary_switch.name}, will not update"
            )
            return

        current_state = await self.get_state(
            entity_id=primary_switch_entity.entity_id, attribute="all"
        )
        if (
            current_state is None
            or current_state["state"] == "unavailable"
            or current_state["state"] == "unknown"
        ):
            self.error(
                f"Primary switch {primary_switch.name} has unknown state, not syncing other lights"
            )
            return

        for light in self._lights:
            await self._update_device_light_entity_to_match(current_state, light)

        for switch in self._switches:
            if switch.id == primary_switch.id:
                continue

            await self._update_device_light_entity_to_match(current_state, switch)

    async def _update_device_light_entity_to_match(
        self, state: dict[str, typing.Any], device: hass_module.HomeAssistantDevice
    ) -> None:
        light_entity = self._get_device_entity_by_key(device, "light")
        if not light_entity:
            self.error(
                f"No light entity found for device {device.name}, will not update"
            )
            return

        existing_state = await self.get_state(
            entity_id=light_entity.entity_id, attribute="all"
        )
        if (
            existing_state is None
            or existing_state["state"] != state["state"]
            or existing_state["attributes"].get("brightness", None)
            != state["attributes"].get("brightness", None)
        ):
            self.log(f"Updating {device.name} light entity to match primary switch")
            await self._ws.call(
                "call_service",
                domain="light",
                service=f"turn_{state['state']}",
                return_response=False,
                service_data={
                    "entity_id": light_entity.entity_id,
                    **(
                        {"brightness": state["attributes"]["brightness"]}
                        if state["state"] == "on"
                        else {}
                    ),
                },
            )


"""
 - Ensure that all switches are bound to all lights
 - Ensure all secondary switches are bound to all primary switches
 - Ensure all devices are assigned to the area
 - Add to HomeKit integration
 - Various config options
   - Fix naming
   - Make button delay short
   - Turn on smart bulb mode
   - Turn on relay click
   - Maybe: disable irrelevant entities
 - Health check
   - Available - Is light responding to pings? If not, mark unavailable
   - In Sync - Is light same state as switch? If not, update
   - Set light on switch to reflect status
 - Add all lights to adaptive lights
   - Include the switch 
     - Maybe: only the switch?
   - 
"""
