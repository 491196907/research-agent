
import os
from datetime import datetime, timedelta, timezone


def _secret(name, default=None):
    """读一个"机密"：先看环境变量，再看 Streamlit 的 Secrets。

    为什么两边都看？
      · 本地开发：`setx XXX "..."` → 走 os.environ
      · 部署到 Streamlit Community Cloud：在网页上配的 Secrets → 走 st.secrets
    这样**同一份代码，本地和云端都能跑**，不用改来改去。
    """
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st          # 只有 Streamlit 环境里才有这个包
        return st.secrets.get(name, default)
    except Exception:                    # 不在 Streamlit 里，或者没配这项
        return default



# 代码版本号：界面上会显示它。
# 为什么需要这个？云端（Streamlit Cloud）偶尔会出现"app.py 已经更新、core/config.py 还是旧的"
# 半新半旧状态 —— 有了版本号，界面上就能一眼看出"云端还在跑旧代码，该 Reboot 了"。
APP_VERSION = "1.2"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "资料库")     # 本地资料放这里
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")  # 生成的报告放这里


# ============ 时间（报告文件名、使用记录都用它）============
# 云端容器里的"本地时间"其实是 UTC：直接用 datetime.now() 会比你手机上的时间慢 8 小时。
# 所以统一用「UTC + 固定偏移」来算时间 —— 在哪里跑，显示的都是同一个时刻。
TZ_OFFSET_HOURS = 8      # 北京 = UTC+8；换时区只改这一行


def now():
    """当前时间（按 TZ_OFFSET_HOURS 偏移，带时区信息）。"""
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=TZ_OFFSET_HOURS)))


def now_str(fmt="%Y-%m-%d %H:%M:%S"):
    """当前时间的字符串形式，例如 2026-09-17 16:05:03。"""
    return now().strftime(fmt)


API_KEY = _secret("DEEPSEEK_API_KEY")
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"

# ================= 运行参数（以后 Agent 会用到）=================
MAX_STEPS = 20          # Agent 最多走几步，防止死循环（联网研究步骤多，给宽一点）
REQUEST_TIMEOUT = 60    # 单次请求最多等多少秒
DEBUG = True            # True：打印更多过程信息，方便学习
TEMPERATURE = 0.3       # 越低越稳定（Agent 场景建议 0.2~0.5）；调高会更"发散"
RETRY_TIMES = 3         # 网络失败时最多重试几次
RETRY_BASE_DELAY = 1.0  # 重试等待基准秒数，指数退避：1s → 2s → 4s


EMBED_API_KEY = _secret("SILICONFLOW_API_KEY")
EMBED_API_URL = "https://api.siliconflow.cn/v1/embeddings"
EMBED_MODEL = "BAAI/bge-m3"


SEARCH_API_KEY = _secret("TAVILY_API_KEY")


ACCESS_PASSWORD = _secret("ACCESS_PASSWORD")


def _parse_passwords(raw):
    """把 "口令=名字, 口令2=名字2" 解析成 {口令: 名字}。

    为什么要"每人一个口令"？
      共享一个口令时，你只知道"有人来过"，不知道是谁；
      每人发一个（口令不同、名字不同），使用记录里就能看到"小明研究了 X、小红研究了 Y"。
    """
    table = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            pwd, name = item.split("=", 1)
            table[pwd.strip()] = name.strip() or "访客"
        else:
            table[item] = "访客"
    return table


# Secrets 里可以这样配多人口令（名字随便起）：
#   ACCESS_PASSWORDS = "yaoyi=我自己, abc123=小明, def456=小红"
ACCESS_PASSWORDS = _parse_passwords(_secret("ACCESS_PASSWORDS"))


def check_password(entered):
    """校验口令：对就返回"访问者名字"，不对返回 None。"""
    if ACCESS_PASSWORDS:
        return ACCESS_PASSWORDS.get((entered or "").strip())
    if ACCESS_PASSWORD:
        return "访客" if entered == ACCESS_PASSWORD else None
    return "访客"          # 没配任何口令 = 不设门，谁都能进
SEARCH_API_URL = "https://api.tavily.com/search"


