from .provider import CompatibleProviderError, factory

__all__ = [
    "CompatibleProviderError",
    "deepseek",
    "qwen",
    "siliconflow",
    "zhipu",
]

def deepseek(): return factory("deepseek")
def qwen(): return factory("qwen")
def zhipu(): return factory("zhipu")
def siliconflow(): return factory("siliconflow")
