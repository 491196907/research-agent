import html as html_lib
import hashlib
import os
import re

import requests
from urllib.parse import urlsplit

from core import config, retriever, store
from core.log_setup import get_logger

log = get_logger(__name__)

USER_AGENT = "research-agent/1.0 (personal study project)"   # 礼貌：让别人知道是谁在访问
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
BING_SEARCH_URL = "https://cn.bing.com/search"
SO_SEARCH_URL = "https://www.so.com/s"          # 备用引擎（Bing 被拦时顶上）


def list_sources():
    """列出资料库里有哪些资料文件。"""

    names = retriever.list_files()          # ← 换成这一行，下面 4 行保持不变
    if not names:
        return "资料库是空的（请把 .md/.txt 放进 资料库/ 目录）"
    return f"资料库里共有 {len(names)} 个文件：\n" + "\n".join("- " + n for n in names)




def search_notes(query, top_k=3):
   

    if not query or not query.strip():
        return "检索失败：query 不能为空"

    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 3
    top_k = max(1, min(10, top_k))

    hits = retriever.search(query, top_k)

    if not hits:
        return f"没有找到和「{query}」相关的资料"
    return "\n---\n".join(f"[来源: {src}] {content}" for _, src, content in hits)


def save_note(content, source):
    """把一条提炼好的要点保存进数据库（SQLite）。

    注意分工：**参数校验和"人话"由 store 负责**，tools 只做转发。
    （校验规则只有一处，不会出现"tools 说能存、store 说不能"的矛盾。）
    """
    return store.add_note(content, source)


def _html_to_text(raw):
    """把 HTML 变成纯文本：去掉脚本样式、去掉标签、解码 &amp; 这类实体。"""
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", "\n", raw)          # 标签换成换行
    text = html_lib.unescape(raw)                     # &amp; → &
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)        # 去掉空行


def fetch_web(url):
    """抓一个网页的正文，存进资料库，之后就能被 search_notes 检索到。

    注意三件事：
      · 公司网络可能拦截外部网站 → 失败时返回人话，Agent 会继续用本地资料
      · JS 动态渲染的网页抓不到正文 → 会明确告诉你"没提取到正文"
      · 礼貌：只抓一次、带 User-Agent、不循环轰炸（学习项目够用）
    """
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "抓取失败：url 必须以 http:// 或 https:// 开头"

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                            timeout=config.REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        log.warning("抓取失败：%s", e)
        return f"抓取失败：网络不通或对方拒绝（{type(e).__name__}）。可以继续用本地资料。"

    if resp.status_code != 200:
        return f"抓取失败：对方返回 {resp.status_code}（可能需要登录或被限制访问）"

    resp.encoding = resp.apparent_encoding or resp.encoding
    text = _html_to_text(resp.text)
    if len(text) < 50:
        return "抓取失败：没提取到正文（这个网页可能是 JS 动态渲染的）"

    tag = re.sub(r"\W+", "", url)[-24:] or "page"
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    filename = f"网页-{tag}-{digest}.md"
    path = os.path.join(config.DATA_DIR, filename)
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# 网页：{url}\n\n{text}")
    except OSError as e:
        return f"抓取到了内容，但写入资料库失败：{e}"

    log.info("已抓取网页并存入资料库：%s（%s 字）", filename, len(text))
    return f"已抓取并存入资料库：{filename}（{len(text)} 字）。现在可以用 search_notes 检索它。"


def _parse_bing_results(html, limit):
    """从 Bing 搜索结果页里抠出 (标题, 链接, 摘要)。"""
    out = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = m.group(1)
        title = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = html_lib.unescape(re.sub(r"<[^>]+>", "", p.group(1))).strip() if p else ""
        out.append((title, url, snippet[:150]))
        if len(out) >= limit:
            break
    return out


def _parse_generic_links(html, limit):
    """通用兜底解析：不管哪个搜索引擎，只要页面里有"结果链接"就尽量抠出来。

    为什么需要它？搜索引擎改版/换结构时，按类名抠会一条都抠不到；
    这个兜底不依赖类名，粗但能用。
    """
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.S):
        url = m.group(1)
        title = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if not (6 <= len(title) <= 80):
            continue
        host = urlsplit(url).netloc.lower()
        if any(bad in host for bad in ("bing.com", "microsoft", "msn.com", "so.com", "360.cn", "baidu.com/link")):
            continue
        if host in seen:                       # 同一站点只留一条，避免刷屏
            continue
        seen.add(host)
        out.append((title, url, ""))
        if len(out) >= limit:
            break
    return out


def _fetch_engine(url, query, limit):
    """抓一个"搜索页"并解析。返回 (结果列表, 失败原因)。"""
    try:
        resp = requests.get(url, params={"q": query},
                            headers={"User-Agent": BROWSER_UA}, timeout=config.REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return None, f"{type(e).__name__}"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    resp.encoding = resp.apparent_encoding or resp.encoding
    results = _parse_bing_results(resp.text, limit)
    if not results:
        results = _parse_generic_links(resp.text, limit)   # 兜底解析
    if not results:
        return None, "页面里没解析出结果（可能被反爬／要验证码／改版了）"
    return results, None


def _search_via_api(query, limit):
    """配了 key：走搜索 API（Tavily 格式），更稳。返回 (结果, 失败原因)。"""
    try:
        resp = requests.post(config.SEARCH_API_URL,
                             json={"api_key": config.SEARCH_API_KEY,
                                   "query": query, "max_results": limit},
                             timeout=config.REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return None, f"{type(e).__name__}"
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    results = [(r.get("title", ""), r.get("url", ""), (r.get("content") or "")[:150])
               for r in resp.json().get("results", [])[:limit]]
    return (results, None) if results else (None, "API 返回 0 条结果")


def web_search(query, max_results=5):
    """在互联网上搜索，返回「标题 + 链接 + 摘要」。

    什么时候用：本地资料库查不到、而主题又需要外部信息时。
    搜完拿到链接后，用 fetch_web 抓正文（会自动存进资料库），再用 search_notes 检索。
    """
    query = str(query or "").strip()
    if not query:
        return "搜索失败：query 不能为空"
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(8, max_results))

    # 依次尝试：有 key 先走 API，否则依次试 Bing / 360（任一成功就停）
    attempts = []          # [(来源, 失败原因), ...] —— 失败时给用户看，方便定位
    results = None

    if config.SEARCH_API_KEY:
        results, reason = _search_via_api(query, max_results)
        attempts.append(("搜索API", reason))
    if not results:
        for name, url in (("Bing", BING_SEARCH_URL), ("360搜索", SO_SEARCH_URL)):
            results, reason = _fetch_engine(url, query, max_results)
            attempts.append((name, reason))
            if results:
                break

    if not results:
        detail = "；".join(f"{n}：{why}" for n, why in attempts if why) or "未知原因"
        log.warning("搜索全部失败：%s", detail)
        return (f"搜索失败（{detail}）。"
                "接下来可以：① 改用本地资料；② 如果你知道权威网址（例如官网、百科条目），"
                "直接用 fetch_web 抓它；③ 凭已有知识作答，但必须注明「没有外部来源」。")

    lines = [f"搜索「{query}」得到 {len(results)} 条结果（想细看就用 fetch_web 抓取它的链接）："]
    for i, (title, url, snippet) in enumerate(results, 1):
        lines.append(f"{i}. {title}\n   链接：{url}\n   摘要：{snippet}")
    return "\n".join(lines)


TOOL_FUNCS = {
    "list_sources": list_sources,
    "search_notes": search_notes,
    "save_note": save_note,
    "fetch_web": fetch_web,
    "web_search": web_search,
}


def call_tool(name, args):
    """按名字找到工具并调用（分发）。Agent 循环用它执行模型"点"的工具。

    name：模型点的那道"菜"（工具名）
    args：模型填的参数，**已经 json.loads 过**的字典
    """
    if name not in TOOL_FUNCS:
        return f"没有这个工具：{name}"
    try:
        result = TOOL_FUNCS[name](**args)
    except Exception as e:
        log.exception("工具 %s 执行出错，参数：%s", name, args)   # 自动带完整调用栈
        return f"工具 {name} 执行出错：{e}"       # ← 给"模型"看的：一句人话
    return str(result)                          # 统一返回字符串


if __name__ == "__main__":
    # 自测：py -m core.tools
    print(call_tool("list_sources", {}))
    print()
    print(call_tool("search_notes", {"query": "切片"}))
    print()
    print(call_tool("call_tool", {}))          # 故意写错名字，看错误处理
