class CameraEvent:
    camera_name: str
    timestamp: float

    def __init__(self, camera_name: str, timestamp: float):
        self.camera_name = camera_name
        self.timestamp = timestamp


class CameraProvider:
    name: str = "base"

    async def connect(self) -> bool:
        raise NotImplementedError

    async def check_motion(self) -> list[CameraEvent]:
        raise NotImplementedError

    async def disconnect(self):
        pass

    @property
    def connected(self) -> bool:
        return getattr(self, "_connected", False)


_registry: dict[str, type[CameraProvider]] = {}


def register(name: str, cls: type[CameraProvider]):
    _registry[name] = cls


def get_provider(name: str) -> type[CameraProvider]:
    cls = _registry.get(name)
    if not cls:
        raise ValueError(f"Unknown camera provider: {name}. Available: {list(_registry.keys())}")
    return cls


def list_providers() -> list[str]:
    return list(_registry.keys())
