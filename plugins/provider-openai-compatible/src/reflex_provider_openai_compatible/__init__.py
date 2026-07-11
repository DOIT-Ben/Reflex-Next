from .provider import factory

def deepseek(): return factory("deepseek")
def qwen(): return factory("qwen")
def zhipu(): return factory("zhipu")
def siliconflow(): return factory("siliconflow")
