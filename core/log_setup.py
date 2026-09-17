import logging
import os

from core import config

LOG_DIR = os.path.join(config.OUTPUT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "research-agent.log")

_configured = False          # 模块级开关：只配置一次，避免重复输出


def setup(level=None):
    """配置一次：同时输出到「控制台 + 文件」。

    关键设计：
      · logger 自己收下所有级别（DEBUG 起）
      · 控制台的级别由参数决定（想少看就调高）
      · 文件永远记 DEBUG 起 —— 事后排查靠它
    """
    global _configured
    if _configured:
        return
    if level is None:              # 不传就用配置决定：config.DEBUG 控制详略
        level = logging.DEBUG if config.DEBUG else logging.INFO
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger("research_agent")
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name):
    """给每个模块发一个"带名字"的 logger。"""

    setup()                                        # ① 确保配置过（内部有开关，重复调用无害）
    return logging.getLogger(f"research_agent.{name}")   # ② 发一个"带名字"的 logger


if __name__ == "__main__":
    # 自测：py -m core.log_setup
    log = get_logger("自测")
    log.debug("DEBUG：这句话只会在文件里")
    log.info("INFO：正常进展")
    log.warning("WARNING：注意一下")
    log.error("ERROR：出错了")
    print("日志文件：", LOG_FILE)
