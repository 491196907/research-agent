r"""核心模块的单元测试。

跑法（在项目根目录）：
    py -m pytest tests -v

为什么值得写测试？
    · 改代码怕改坏 → 跑一遍测试就知道有没有破坏旧功能
    · 不用每次手动敲一堆命令验证
    · 测试本身就是"这个函数该怎么用"的文档

三个最常用的写法：
    assert 结果 == 期望       断言（不对就测试失败）
    pytest.approx(1.0)       浮点数比较（别用 == 比小数）
    monkeypatch.setattr(...)  临时替换掉某个东西（比如配置、网络请求）
"""

import os
import sys

import numpy as np
import pytest

# 让测试文件能找到 core 包（项目根目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import agent, config, embedder, llm, report, retriever, store, tools  # noqa: E402


# ==================== embedding 后端 ====================
def test_本地后端_维度等于词表大小且结果稳定():
    chunks = [["a.md#0", "切片策略：把长文档切成小块。"]]
    emb = embedder.LocalEmbedder(chunks)
    v1 = emb.embed(["切片"])[0]
    v2 = emb.embed(["切片"])[0]
    assert len(v1) == len(emb.vocab)
    assert (v1 == v2).all()


def test_假后端_维度正确且结果确定():
    fake = embedder.FakeEmbedder(dim=8)
    v1 = fake.embed(["测试"])[0]
    assert len(v1) == 8
    assert (fake.embed(["测试"])[0] == v1).all()


def test_工厂_没有key时用本地后端(monkeypatch):
    monkeypatch.setattr(config, "EMBED_API_KEY", None)
    assert isinstance(embedder.get_embedder([]), embedder.LocalEmbedder)


def test_三种后端_接口一致():
    """这就是"接口统一"的意义：用法完全一样。"""
    chunks = [["a.md#0", "字典：按名字取到值。"]]
    for emb in [embedder.LocalEmbedder(chunks), embedder.FakeEmbedder()]:
        vecs = emb.embed(["切片", "字典"])
        assert len(vecs) == 2, f"{emb} 没有按输入数量返回向量"
        assert emb.available() is True


# ==================== 相似度计算 ====================
def test_余弦_方向相同是1():
    assert retriever.cosine(np.array([1, 1, 0]), np.array([5, 5, 0])) == pytest.approx(1.0)


def test_余弦_垂直是0():
    assert retriever.cosine(np.array([1, 0]), np.array([0, 1])) == pytest.approx(0.0)


def test_余弦_零向量不报错():
    """查询词一个都不在词表里时，不能除以 0 崩掉。"""
    assert retriever.cosine(np.zeros(3), np.array([1.0, 2.0, 3.0])) == 0.0


# ==================== 检索 ====================
@pytest.fixture
def 临时资料库(tmp_path, monkeypatch):
    """把资料库指向一个临时目录。

    为什么必须这么做？
      真实 资料库/ 里的内容会变（你自己加笔记、Agent 抓网页），
      如果测试直接读它，**别人一改资料，测试就红** —— 这叫"脆弱的测试"。
      用临时目录隔离，测试就永远稳定。
    """
    d = tmp_path / "lib"
    d.mkdir()
    (d / "a.md").write_text("## 切片策略\n把长文档切成小块，块太大容易混话题。\n\n## 字典\n按名字取到对应的值。",
                            encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", str(d))
    return d


def test_检索能返回带来源的片段(临时资料库):
    hits = retriever.search("切片", top_k=2)
    assert hits, "临时资料里应该有和『切片』相关的片段"
    score, source, content = hits[0]
    assert score > 0
    assert "#" in source, "来源应该是 文件名#序号 的格式"


def test_检索无结果时返回空列表(临时资料库):
    assert retriever.search("鲸鱼xyz完全不存在的词") == []


def test_检索结果按分数从高到低(临时资料库):
    hits = retriever.search("切片", top_k=3)
    scores = [h[0] for h in hits]
    assert scores == sorted(scores, reverse=True)


# ==================== 工具层 ====================
def test_工具名不存在_返回人话():
    assert "没有这个工具" in tools.call_tool("send_email", {})


def test_参数缺失_不崩且返回人话():
    out = tools.call_tool("search_notes", {})
    assert isinstance(out, str)
    assert "执行出错" in out


def test_空query_被参数校验拦住():
    assert "检索失败" in tools.call_tool("search_notes", {"query": "   "})


def test_空内容_不落库():
    assert "保存失败" in tools.call_tool("save_note", {"content": "  ", "source": "x"})


# ==================== 抓网页工具（不联网，靠 monkeypatch）====================
def test_抓网页_非http开头被拒绝():
    assert "抓取失败" in tools.call_tool("fetch_web", {"url": "ftp://example.com"})


def test_抓网页_网络错误返回人话(monkeypatch):
    import requests as _rq

    def boom(*args, **kwargs):
        raise _rq.exceptions.ConnectionError("假装断网")

    monkeypatch.setattr(tools.requests, "get", boom)
    out = tools.call_tool("fetch_web", {"url": "https://example.com"})
    assert "抓取失败" in out
    assert "本地资料" in out, "要提示模型继续用本地资料，而不是卡住"


class _FakeResp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"


def test_抓网页_成功会写进资料库并去掉脚本(monkeypatch, tmp_path):
    html = ("<html><body><h1>标题</h1><p>" + "正文内容" * 40 +
            "</p><script>evil()</script></body></html>")
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: _FakeResp(html))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    out = tools.call_tool("fetch_web", {"url": "https://example.com/a"})
    assert "已抓取并存入资料库" in out
    files = os.listdir(tmp_path)
    assert len(files) == 1
    content = open(os.path.join(tmp_path, files[0]), encoding="utf-8").read()
    assert "正文内容" in content
    assert "evil()" not in content, "script 里的内容必须被清掉"


def test_抓网页_正文太短算失败(monkeypatch):
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: _FakeResp("<html>短</html>"))
    assert "没提取到正文" in tools.call_tool("fetch_web", {"url": "https://x.com"})


# ==================== 联网搜索（不联网，靠 monkeypatch）====================
def test_搜索_空query被拒绝():
    assert "搜索失败" in tools.call_tool("web_search", {"query": "  "})


def test_搜索_解析Bing结果页(monkeypatch):
    html = """<li class="b_algo"><h2><a href="https://a.com/x">标题A</a></h2>
              <p>摘要A的内容</p></li>
              <li class="b_algo"><h2><a href="https://b.com/y">标题B</a></h2>
              <p>摘要B的内容</p></li>"""
    monkeypatch.setattr(config, "SEARCH_API_KEY", None)          # 走"不用 key"的 Bing 路子
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: _FakeResp(html))
    out = tools.call_tool("web_search", {"query": "测试"})
    assert "标题A" in out and "https://a.com/x" in out and "摘要B的内容" in out


def test_搜索_网络失败返回人话并提示降级(monkeypatch):
    import requests as _rq

    def boom(*a, **k):
        raise _rq.exceptions.ConnectionError("假装断网")

    monkeypatch.setattr(config, "SEARCH_API_KEY", None)
    monkeypatch.setattr(tools.requests, "get", boom)
    out = tools.call_tool("web_search", {"query": "测试"})
    assert "搜索失败" in out
    assert "注明" in out, "要提醒模型：没有外部来源时必须注明"


def test_搜索_失败时说明试过哪些引擎并给下一步建议(monkeypatch):
    import requests as _rq

    def boom(*a, **k):
        raise _rq.exceptions.ConnectionError("假装断网")

    monkeypatch.setattr(config, "SEARCH_API_KEY", None)
    monkeypatch.setattr(tools.requests, "get", boom)
    out = tools.call_tool("web_search", {"query": "测试"})
    assert "搜索失败" in out
    assert "Bing" in out and "360" in out, "要告诉用户试过哪些引擎"
    assert "fetch_web" in out, "要给出可操作的下一步（直接抓已知网址）"


def test_搜索_引擎改版时能用通用兜底解析(monkeypatch):
    html = '<div><a href="https://a.com/x">一个看起来像结果的标题A</a></div>'
    monkeypatch.setattr(config, "SEARCH_API_KEY", None)
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: _FakeResp(html))
    out = tools.call_tool("web_search", {"query": "测试"})
    assert "https://a.com/x" in out, "类名抠不到时要能兜底抠出链接"


# ==================== 数据库（用临时库，别污染真库）====================
@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "test.db"))
    return store


def test_存一条要点(tmp_store):
    before = tmp_store.count_notes()
    assert "已保存" in tmp_store.add_note("测试要点", "a.md#1")
    assert tmp_store.count_notes() == before + 1
    assert tmp_store.list_notes(1)[0][1] == "测试要点"


def test_数据真的持久化(tmp_path, monkeypatch):
    """关掉再打开，数据还在 —— 这是 SQLite 相比内存缓存的价值。"""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "p.db"))
    store.add_note("持久化测试", "b.md#2")
    assert store.count_notes() == 1
    assert store.list_notes(1)[0][1] == "持久化测试"


# ==================== Agent 循环（用假模型，不花 API 钱）====================
def _fake_tool_call(name, args_json, cid="c1"):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": cid, "type": "function",
                            "function": {"name": name, "arguments": args_json}}]}


def test_循环_模型直接回答就结束(monkeypatch):
    monkeypatch.setattr(agent, "make_plan", lambda topic: [])
    monkeypatch.setattr(agent.report, "save_report", lambda *a, **k: None)
    fakes = [{"role": "assistant", "content": "直接给结论"}]
    monkeypatch.setattr(llm, "chat_with_tools", lambda m, t: fakes.pop(0))
    answer, trace = agent.run("测试", max_steps=3, verbose=False)
    assert answer == "直接给结论"
    assert trace == []


def test_循环_会执行工具并回灌(monkeypatch, 临时资料库):
    monkeypatch.setattr(agent, "make_plan", lambda topic: [])
    monkeypatch.setattr(agent.report, "save_report", lambda *a, **k: None)
    fakes = [
        _fake_tool_call("list_sources", "{}"),
        {"role": "assistant", "content": "看过资料了"},
    ]
    monkeypatch.setattr(llm, "chat_with_tools", lambda m, t: fakes.pop(0))
    answer, trace = agent.run("测试", max_steps=3, verbose=False)
    assert answer == "看过资料了"
    assert len(trace) == 1
    assert trace[0]["tool"] == "list_sources"


def test_循环_连续查不到会强制收尾并给出结论(monkeypatch, 临时资料库):
    """连续失败后不该只丢一句「提前停止」—— 要让模型基于已有信息给个结论或说明。"""
    monkeypatch.setattr(agent, "make_plan", lambda topic: [])
    monkeypatch.setattr(agent.report, "save_report", lambda *a, **k: None)
    fakes = [_fake_tool_call("search_notes", '{"query": "鲸鱼xyz"}', f"c{i}")
             for i in range(agent.STALL_LIMIT)]
    fakes.append({"role": "assistant",
                  "content": "资料覆盖不足：资料库里没有相关内容，建议补充资料或给出网址。"})
    monkeypatch.setattr(llm, "chat_with_tools", lambda m, t: fakes.pop(0))
    answer, trace = agent.run("不存在的主题", max_steps=20, verbose=False)
    assert "资料覆盖不足" in answer, "应该把模型收尾的结论原样交给用户"
    assert len(trace) == agent.STALL_LIMIT


def test_消息序列体检_把夹在中间的消息挪走():
    """这是那个 400 报错的根治：assistant(tool_calls) 后面必须紧跟全部 tool 消息。"""
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "x", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "结果1"},
        {"role": "user", "content": "夹在中间的提示"},        # ← 非法位置
        {"role": "tool", "tool_call_id": "c2", "content": "结果2"},
    ]
    llm._repair_tool_messages(messages)
    assert [m["role"] for m in messages][:4] == ["assistant", "tool", "tool", "user"]


def test_循环_失败后会提示模型换策略(monkeypatch, 临时资料库):
    """连续失败时不该直接放弃 —— 先往对话里插一条「换策略」提示（可联网/换词）。"""
    monkeypatch.setattr(agent, "make_plan", lambda topic: [])
    monkeypatch.setattr(agent.report, "save_report", lambda *a, **k: None)
    monkeypatch.setattr(tools, "call_tool", lambda name, args: "没有找到相关资料（模拟）")

    fakes = [_fake_tool_call("search_notes", '{"query": "A"}', f"c{i}") for i in range(3)]
    fakes.append({"role": "assistant", "content": "结束"})
    saw_hint = []

    def fake_chat(messages, tools_mod):
        saw_hint.append(any("换一种做法" in str(m.get("content", "")) for m in messages))
        return fakes.pop(0)

    monkeypatch.setattr(llm, "chat_with_tools", fake_chat)
    agent.run("测试", max_steps=6, verbose=False)

    assert False in saw_hint, "前几次调用时不该有提示"
    assert True in saw_hint, "连续失败之后必须注入换策略提示"


def test_循环_步数用完时强制停止(monkeypatch):
    """模型一直在点菜但每次都有有效信息 → 不会被 stall 拦住，只会被步数拦住。"""
    monkeypatch.setattr(agent, "make_plan", lambda topic: [])
    monkeypatch.setattr(agent.report, "save_report", lambda *a, **k: None)
    fakes = [_fake_tool_call("list_sources", "{}", f"c{i}") for i in range(20)]
    monkeypatch.setattr(llm, "chat_with_tools", lambda m, t: fakes.pop(0))
    answer, trace = agent.run("测试", max_steps=2, verbose=False)
    assert "最大步数" in answer
    assert len(trace) == 2


def test_on_step_回调依次收到计划_工具_结束(monkeypatch):
    """界面靠这个回调做实时进度显示。"""
    monkeypatch.setattr(agent, "make_plan", lambda topic: ["子问题1"])
    monkeypatch.setattr(agent.report, "save_report", lambda *a, **k: None)
    fakes = [_fake_tool_call("list_sources", "{}"),
             {"role": "assistant", "content": "结论"}]
    monkeypatch.setattr(llm, "chat_with_tools", lambda m, t: fakes.pop(0))
    events = []
    agent.run("测试", max_steps=3, verbose=False, on_step=events.append)
    assert [e["type"] for e in events] == ["plan", "tool", "done"]
    assert events[0]["plan"] == ["子问题1"]
    assert events[1]["tool"] == "list_sources"
    assert events[2]["answer"] == "结论"


# ==================== 报告 ====================
def test_报告包含结论和来源(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    trace = [{"step": 1, "tool": "search_notes", "args": {},
              "result": "[来源: x.md#1] 一段内容"}]
    path = report.save_report("测试主题", "这是结论", trace, plan=["子问题1"])
    text = open(path, encoding="utf-8").read()
    assert "研究报告：测试主题" in text
    assert "这是结论" in text
    assert "x.md#1" in text


# ==================== 使用记录 + 多人口令 ====================
def test_使用记录_写入与读取(tmp_store):
    """每跑一次研究就记一条 —— 公开部署后靠它看"谁在用、在研究什么"。"""
    assert tmp_store.add_run("小明", "RAG 切片", 5, "完成", "研究报告-RAG切片-1.md") is True
    assert tmp_store.add_run("小红", "学英语", 3, "完成", "") is True
    rows = tmp_store.list_runs(10)
    assert len(rows) == 2
    assert rows[0][2] == "小红", "最新的记录要排在最前面"
    # 一行 = (id, 时间, 访问者, 主题, 步数, 状态, 报告)
    assert rows[1][2:7] == ("小明", "RAG 切片", 5, "完成", "研究报告-RAG切片-1.md")


def test_使用记录_按人统计次数(tmp_store):
    for _ in range(3):
        tmp_store.add_run("小明", "主题A")
    tmp_store.add_run("小红", "主题B")
    assert tmp_store.runs_summary() == [("小明", 3), ("小红", 1)]


def test_使用记录_访问者为空时记成访客(tmp_store):
    tmp_store.add_run("", "没登录的主题")
    assert tmp_store.list_runs(1)[0][2] == "访客"


def test_使用记录_非法步数不会写崩(tmp_store):
    """界面传进来的东西不可信，写法要稳（写失败也只是少一条记录）。"""
    assert tmp_store.add_run("小明", "主题", "五步") is False
    assert tmp_store.list_runs(10) == []


def test_多人口令解析_口令对得上名字():
    table = config._parse_passwords("yaoyi=我自己, abc123=小明 , def456")
    assert table == {"yaoyi": "我自己", "abc123": "小明", "def456": "访客"}


def test_多人口令解析_空值不报错():
    assert config._parse_passwords(None) == {}
    assert config._parse_passwords("") == {}


def test_口令校验_多人模式返回对应名字(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_PASSWORDS", {"abc123": "小明"})
    monkeypatch.setattr(config, "ACCESS_PASSWORD", None)
    assert config.check_password("abc123") == "小明"
    assert config.check_password("  abc123 ") == "小明", "前后空格要能容错"
    assert config.check_password("猜的") is None


def test_口令校验_单人模式返回访客(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_PASSWORDS", {})
    monkeypatch.setattr(config, "ACCESS_PASSWORD", "yaoyi")
    assert config.check_password("yaoyi") == "访客"
    assert config.check_password("yaoyi2") is None


def test_口令校验_没配口令就不设门(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_PASSWORDS", {})
    monkeypatch.setattr(config, "ACCESS_PASSWORD", None)
    assert config.check_password("随便") == "访客"
