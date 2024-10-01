import threading

import appdaemon.plugins.hass.hassapi
import appdaemon.plugins.hass.hassplugin
import appdaemon.utils
import hass_module
import pydantic
import utils_module


class _LightProfileConfig(pydantic.BaseModel):
    name: str
    model: str
    friendly_name: str

    brightness_function: str  # 8.15 + 16.6 * log(x, e)
    power_function: str | None = None  # 0.0536 * x + 0.728

    def map_brightness(self, brightness: int) -> int:
        x = brightness
        from math import e, log

        try:
            mapped = eval(self.brightness_function)
            return int(mapped)
        except ValueError:
            return 0

    def map_power(self, brightness: int) -> float:
        if self.power_function is None:
            return 0.0

        x = brightness
        from math import e, log

        power = eval(self.power_function)
        return power


class _LightProfile:
    _config: _LightProfileConfig
    _mapped_brightness_by_brightness: dict[int, int]
    _power_by_brightness: dict[int, float]

    def __init__(self, config: _LightProfileConfig):
        self._config = config

        self._mapped_brightness_by_brightness = {
            brightness: config.map_brightness(brightness)
            for brightness in range(0, 256)
        }

        self._power_by_brightness = {
            brightness: config.map_power(brightness) for brightness in range(0, 256)
        }

    def get_name(self) -> str:
        return self._config.name

    def get_friendly_name(self) -> str:
        return self._config.friendly_name

    def get_model(self) -> str:
        return self._config.model

    def get_mapped_brightness(self, brightness: int) -> int:
        return self._mapped_brightness_by_brightness[brightness]

    def get_power(self, brightness: int) -> float:
        return self._power_by_brightness[brightness]


@utils_module.singleton
class LightProfilesApp(appdaemon.plugins.hass.hassapi.Hass):
    _profiles_by_model: dict[str, _LightProfile]
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    async def initialize(self) -> None:
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    profiles = [
                        _LightProfile(_LightProfileConfig(name=name, **config))
                        for name, config in self.args["models"].items()
                    ]
                    self._profiles_by_model = {
                        profile.get_model(): profile for profile in profiles
                    }

    async def get_expected_power_consumption(
        self, brightness: int, lights: list[hass_module.HomeAssistantDevice]
    ) -> float:
        model = self._extract_model(lights)
        return self._profiles_by_model[model].get_power(brightness) * len(lights)

    async def get_mapped_brightness(
        self, brightness: int, lights: list[hass_module.HomeAssistantDevice]
    ) -> int:
        model = self._extract_model(lights)
        return self._profiles_by_model[model].get_mapped_brightness(brightness)

    def _extract_model(self, lights: list[hass_module.HomeAssistantDevice]) -> str:
        models = {light.model for light in lights}
        if len(models) != 1:
            raise ValueError(
                "There are lights with different models, cannot map brightness"
            )
        model = models.pop()
        if model not in self._profiles_by_model:
            raise ValueError(
                f'Light model "{model}" is unsupported, used by lights {", ".join(light.name for light in lights)}'
            )
        return model
