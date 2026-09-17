import time

import requests

from core import config
from core.log_setup import get_logger

log = get_logger(__name__)


def _repair_tool_messages(messages):
    """体检并修复消息序列：每个 assistant 的 tool_calls 后面，必须紧跟对应的 tool 消息。

    为什么需要它？DeepSeek 会拒绝这种序列：
        assistant(tool_calls=[c1,c2]) → tool(c1) → user(别的消息) → tool(c2)
    报错长这样：
        An assistant message with tool_calls must be followed by tool messages
        responding to each tool_call_id. (insufficient tool messages following tool_calls message)
    一旦发生，请求直接 400，整个 Agent 就卡住了。所以发请求前统一体检一次。
    """
    moved = 0
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            need = {tc.get("id") for tc in m["tool_calls"]}
            j = i + 1
            while j < len(messages) and need:
                mm = messages[j]
                if mm.get("role") == "tool" and mm.get("tool_call_id") in need:
                    need.discard(mm.get("tool_call_id"))
                    j += 1
                    continue
                # 这条消息夹在了 tool_calls 和它的回复中间 → 挪到末尾，保住全部 tool 回复的连续性
                messages.append(messages.pop(j))
                moved += 1
            i = j
            continue
        i += 1
    if moved:
        log.warning("消息序列不合法，已自动挪走 %s 条夹在中间的无关消息（否则 API 会返回 400）", moved)
    return messages


def _post_with_retry(headers, body, tries=None):
    """发 POST 请求，失败自动重试（指数退避）。

    返回：成功的 resp；全失败返回 None（由调用方决定怎么"降级"）。
    为什么不在这里直接返回错误文字？因为它同时被 chat 和 chat_with_tools 用，
    两者需要的错误形状不同（字符串 vs 字典）。**助手只负责"把请求发出去并重试"。**
    """
    tries = tries or config.RETRY_TIMES
    for attempt in range(1, tries + 1):
        try:
            return requests.post(config.API_URL, headers=headers, json=body,
                                 timeout=config.REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            if attempt == tries:
                log.error("网络请求失败，已重试 %s 次：%s", tries, e)
                return None
            wait = config.RETRY_BASE_DELAY * (2 ** (attempt - 1))   # 1s → 2s → 4s
            log.warning("第 %s 次请求失败（%s），%.1f 秒后重试", attempt, e, wait)
            time.sleep(wait)


def chat(messages):
    """传入消息列表，返回模型回答的文字（字符串）。

    messages 长这样（每条消息 = 角色 + 内容）：
        [
            {"role": "system", "content": "你是一个严谨的研究助手"},
            {"role": "user",   "content": "什么是向量检索？"},
        ]

    角色有三种：
        system —— 设定人设和规矩（模型最听它的）
        user   —— 用户说的话
        assistant —— 模型自己说过的话
    """

    headers = {
    "Authorization": f"Bearer {config.API_KEY}",   # 工牌
    "Content-Type": "application/json",     # 我发的是 JSON 格式
    }

    body = {
    "model": config.MODEL,
    "messages": messages,
    "temperature": config.TEMPERATURE,      # 降低随机性：同一个问题两次结果更一致
    }


    resp = _post_with_retry(headers, body)          # 失败自动重试
    if resp is None:
        return "网络出错了：多次重试都失败（详情见日志）"
    


    if resp.status_code != 200:
        return f"API 出错 {resp.status_code}：{resp.text}"


    data = resp.json()                                 
    text = data["choices"][0]["message"]["content"]    
    return text
    


def chat_with_tools(messages, tools):
    """带"工具说明书"的对话：把 tools 一起交给模型，让它自己决定要不要调工具。

    和 chat() 的两个区别：
      1) body 里多一个键："tools": tools
      2) 返回值是**整个 message 字典**，不是文字
         —— 因为要拿到 message["tool_calls"]；文字在 message["content"] 里

    返回约定（故意设计成这样，想一想为什么）：
      正常：{"role": "assistant", "content": "...", "tool_calls": [...] 或 None}
      出错：{"role": "assistant", "content": "错误：...", "tool_calls": None}
      → 两种情况的"形状"一样，上层就能统一写 if message.get("tool_calls"):
    """

    headers = {
    "Authorization": f"Bearer {config.API_KEY}",   # 工牌
    "Content-Type": "application/json",     # 我发的是 JSON 格式
    }     

    body = {
    "model": config.MODEL,
    "messages": messages,
    "tools": tools,
    "temperature": config.TEMPERATURE,      # 降低随机性：工具选择更稳定
    }

    _repair_tool_messages(messages)                 # 发请求前体检：防止 400

    resp = _post_with_retry(headers, body)          # 失败自动重试
    if resp is None:
        return {"role": "assistant", "content": "网络出错了：多次重试都失败（详情见日志）", "tool_calls": None}
    

    if resp.status_code != 200:
            return {"role": "assistant", "content": f"API 出错 {resp.status_code}：{resp.text}", "tool_calls": None}

 
    data = resp.json()                                 
    message = data["choices"][0]["message"]  
    return message

if __name__ == "__main__":

    print(chat([{"role": "user", "content": "用一句话介绍你自己"}]))
