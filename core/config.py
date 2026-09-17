
import os


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



BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "资料库")     # 本地资料放这里
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")  # 生成的报告放这里


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
SEARCH_API_URL = "https://api.tavily.com/search"


