import typing

import appdaemon.plugins.hass.hassapi
import appdaemon.plugins.hass.hassplugin
import appdaemon.utils
import hass_module
import light_circuit_app
import pydantic


class LightCircuit(pydantic.BaseModel):
    name: str
    friendly_name: str
    lights: list[hass_module.HomeAssistantDevice]
    switches: list[hass_module.HomeAssistantDevice]


class DebugLightsDashboardApp(appdaemon.plugins.hass.hassapi.Hass):
    _ws: hass_module.HomeAssistantWebSocket
    _circuits: list[LightCircuit]

    async def initialize(self) -> None:
        self._ws = hass_module.HomeAssistantWebSocket(self)

        await self._load_circuits()

        await self._update_dashboard()

    async def _load_circuits(self) -> None:
        light_circuit_apps: list[light_circuit_app.LightCircuitApp] = [
            await self.get_app(app)
            for app in self.args["dependencies"]
            if isinstance(await self.get_app(app), light_circuit_app.LightCircuitApp)
        ]

        self._circuits = [
            LightCircuit(
                name=app.name,
                friendly_name=await app.get_friendly_name(),
                lights=await app.get_lights(),
                switches=await app.get_switches(),
            )
            for app in light_circuit_apps
        ]

    async def _update_dashboard(self) -> None:
        existing_dashboard = await self._ws.call("lovelace/config", url_path=None)
        try:
            existing_debug_view: dict[str, typing.Any] | None = [
                view
                for view in existing_dashboard["views"]
                if view.get("path", None) == self.args["dashboard_view_path"]
            ][0]
        except IndexError:
            existing_debug_view = None

        generated_debug_view = self._generate_debug_view_config()

        if existing_debug_view != generated_debug_view:
            new_views = [
                (
                    generated_debug_view
                    if view.get("path", None) == self.args["dashboard_view_path"]
                    else view
                )
                for view in existing_dashboard["views"]
            ]
            existing_dashboard["views"] = new_views

            await self._ws.call(
                "lovelace/config/save", url_path=None, config=existing_dashboard
            )

            self.log(f"Updated dashboard with {len(self._circuits)} circuits")

    def _generate_debug_view_config(self) -> dict[str, typing.Any]:
        return {
            "title": "Debug Lights",
            "path": self.args["dashboard_view_path"],
            "icon": "mdi:bug",
            "cards": [
                self._generate_debug_view_card_config(circuit)
                for circuit in self._circuits
            ],
        }

    def _generate_debug_view_card_config(
        self, circuit: LightCircuit
    ) -> dict[str, typing.Any]:
        return {
            "title": circuit.friendly_name,
            "type": "vertical-stack",
            "cards": [
                *[
                    {
                        "type": "entity",
                        "entity": self._get_light_entity(light).entity_id,
                        "state_color": True,
                    }
                    for light in circuit.lights
                ],
                *[
                    {
                        "type": "entity",
                        "entity": self._get_light_entity(switch).entity_id,
                        "state_color": True,
                    }
                    for switch in circuit.switches
                ],
                {
                    "type": "history-graph",
                    "entities": [
                        *[
                            {
                                "entity": self._get_light_entity(light).entity_id,
                            }
                            for light in circuit.lights
                        ],
                        *[
                            {
                                "entity": self._get_light_entity(switch).entity_id,
                            }
                            for switch in circuit.switches
                        ],
                    ],
                    "hours_to_show": 12,
                },
            ],
        }

    def _get_light_entity(
        self, device: hass_module.HomeAssistantDevice
    ) -> hass_module.HomeAssistantEntity:
        return [entity for entity in device.entities if entity.key == "light"][0]
