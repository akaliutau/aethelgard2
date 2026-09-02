class AethelgardError(RuntimeError):
    pass


class VaultNotInitialized(AethelgardError):
    pass


class ModelAccessError(AethelgardError):
    pass


class PluginNotFound(AethelgardError):
    pass
