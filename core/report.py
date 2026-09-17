import os
import re

from core import config
from core.log_setup import get_logger

log = get_logger(__name__)


def collect_sources(trace):
    """从 trace 里收集所有出现过的来源（去重、保持出现顺序）。"""
    sources = []
    for item in trace:
        found = re.findall(r"\[来源:\s*([^\]]+)\]", str(item.get("result", "")))
        for s in found:
            s = s.strip()
            if s and s not in sources:
                sources.append(s)
    return sources


def count_tools(trace):
    """统计每个工具被调用了多少次。"""
    counts = {}
    for item in trace:
        name = item.get("tool", "?")
        counts[name] = counts.get(name, 0) + 1
    return counts


def save_report(topic, answer, trace, plan=None):
    """写一份报告到 outputs/，返回文件路径（写失败返回 None，不影响主流程）。"""
    try:
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        stamp = config.now_str("%Y%m%d-%H%M%S")
        safe_topic = re.sub(r"[^\w\u4e00-\u9fa5-]+", "_", topic)[:30] or "未命名"
        path = os.path.join(config.OUTPUT_DIR, f"研究报告-{safe_topic}-{stamp}.md")

        sources = collect_sources(trace)
        counts = count_tools(trace)
        lines = [
            f"# 研究报告：{topic}",
            "",
            f"- 生成时间：{config.now_str()}",
            f"- 工具调用：{len(trace)} 次"
            + ("（" + "、".join(f"{k} × {v}" for k, v in counts.items()) + "）" if counts else ""),
            f"- 引用来源：{len(sources)} 处",
        ]
        if plan:
            lines.append("- 研究计划：")
            lines += [f"  {i}. {q}" for i, q in enumerate(plan, 1)]
        lines += [
            "",
            "## 结论",
            "",
            answer or "（模型没有给出结论）",
            "",
            "## 引用来源",
            "",
        ]
        lines += [f"- {s}" for s in sources] if sources else ["- （本次没有引用到任何资料片段）"]
        lines += ["", "## 运行轨迹", ""]
        for item in trace:
            lines.append(f"{item.get('step', '?')}. `{item.get('tool', '?')}({item.get('args', {})})`")
        lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        log.info("报告已保存：%s", path)
        return path
    except OSError as e:
        log.error("报告保存失败（不影响本次研究）：%s", e)
        return None


if __name__ == "__main__":
    # 自测：py -m core.report
    demo_trace = [
        {"step": 1, "tool": "search_notes", "args": {"query": "切片"},
         "result": "[来源: 示例-RAG检索笔记.md#1] 切片别太大……"},
        {"step": 2, "tool": "save_note", "args": {"content": "切片 200~500 字"},
         "result": "已保存要点（来源：示例-RAG检索笔记.md#1）"},
    ]
    p = save_report("演示主题", "结论：切片控制在 200~500 字。【来源: 示例-RAG检索笔记.md#1】",
                    demo_trace, plan=["切片多大合适", "要不要重叠"])
    print("生成的文件：", p)
    print(open(p, encoding="utf-8").read())
