class SprinklerProvider:
    name: str = "base"

    async def connect(self) -> bool:
        raise NotImplementedError

    async def start_zone(self, zone_id: str | int, duration_seconds: int) -> bool:
        raise NotImplementedError

    async def stop_zone(self) -> bool:
        raise NotImplementedError

    async def disconnect(self):
        pass

    @property
    def connected(self) -> bool:
        return getattr(self, "_connected", False)


_registry: dict[str, type[SprinklerProvider]] = {}


def register(name: str, cls: type[SprinklerProvider]):
    _registry[name] = cls


def get_provider(name: str) -> type[SprinklerProvider]:
    cls = _registry.get(name)
    if not cls:
        raise ValueError(f"Unknown sprinkler provider: {name}. Available: {list(_registry.keys())}")
    return cls


def list_providers() -> list[str]:
    return list(_registry.keys())
