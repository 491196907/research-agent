import json

from core import config, llm, report, tool_schema, tools

from core.log_setup import get_logger
log = get_logger(__name__)   

SYSTEM_PROMPT = """你是一个研究助手。你会拿到一批工具，请自己决定下一步做什么。

工作方式：
1. 先用 list_sources 看看手头有哪些资料；
2. 用 search_notes 检索相关资料（一次查一个关键词；没查到就换个更短的词再试）；
3. 把有价值的要点用 save_note 存下来（每条单独存一次，务必带上来源）；
   如果资料库里确实没有，可以联网找资料：先用 web_search 搜（例如 web_search("英语学习方法 零基础")），
   挑最相关的 2~3 条用 fetch_web 抓下来（它会自动存进资料库），再用 search_notes 检索这些网页；
   外部网站可能被网络拦截 —— 搜索失败两次就不要再试了：如果你知道权威网址（学校官网、百科条目等），
   直接用 fetch_web 抓它；否则改用本地资料，或者凭你自己的知识作答，
   但这种情况必须在结论里明确写「以下内容没有外部来源，来自模型自身知识」；
4. 信息够了就停下来，用中文给出结论；**每个结论后面都要标出来源**，格式：[来源: 文件名#片段号]；
5. 资料里没有的内容，明确说「资料未覆盖」，不要编造。
"""


PLAN_PROMPT = """把下面的研究主题拆成 3 个具体的子问题，便于逐个检索资料。
只输出 JSON 数组，不要别的文字。例如：["子问题1", "子问题2", "子问题3"]

研究主题：{topic}"""

STALL_LIMIT = 5          # 连续这么多次都没捞到有效信息 → 提前收工
STALL_HINT_AT = 2        # 连续失败到几次时，先"提醒"模型换策略（而不是直接放弃）

FINAL_ASK = ("到此为止，请**现在就给出结论**，不要再调用任何工具："
             "① 用你目前已经检索到的信息组织答案；"
             "② 如果信息确实不足，就如实说明「资料覆盖不足」，并列出你还缺哪些信息、"
             "以及用户接下来可以怎么做（例如提供资料或给出具体网址）。")

STALL_HINT = ("注意：本地资料库连续多次没有找到相关内容。"
              "请换一种做法 —— 例如改用 web_search 联网搜索，"
              "或者换更短/更通用一点的关键词；"
              "如果确实找不到，就如实说明「资料未覆盖」，不要再重复同样的检索。")


def make_plan(topic):
    """把研究主题拆成若干子问题；失败时返回空列表，不影响主流程。"""

    try:
        raw = llm.chat([{"role": "user", "content": PLAN_PROMPT.format(topic=topic)}])
        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        plan = json.loads(raw)
        return [q for q in plan if isinstance(q, str) and q.strip()][:5]
    except (ValueError, TypeError) as e:
        log.warning("规划失败（不影响继续）：%s", e)
        return []


def run(topic, max_steps=None, verbose=True, plan_first=True, on_step=None):
    """on_step：可选回调，每走一步就调用一次（界面用它做实时进度显示）。

    回调收到的字典长这样：
        {"type": "plan", "plan": [...]}
        {"type": "tool", "step": 2, "tool": "search_notes", "args": {...}, "result": "…"}
        {"type": "done", "answer": "…", "report": "outputs/研究报告-….md"}
    """
    """跑一次研究任务，返回 (最终回答, 步骤记录 trace, 报告文件路径)。"""
    max_steps = max_steps or config.MAX_STEPS
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"研究主题：{topic}"},
    ]
    trace = []
    stall = 0            # 连续"没捞到有效信息"的步数
    plan = []            # 研究计划（先给个空值，plan_first=False 时也不会 NameError）

    if plan_first:
        plan = make_plan(topic)
        if plan:
            messages.append({
                "role": "user",
                "content": "请围绕下面这几个子问题逐个检索资料，最后汇总成结论：\n"
                           + "\n".join(f"- {q}" for q in plan),
            })
            log.info("研究计划（%s 个子问题）：%s", len(plan), "；".join(plan))
            if on_step:
                on_step({"type": "plan", "plan": plan})
        else:
            log.warning("没拿到研究计划，直接开始（不影响运行）")

    for step in range(1, max_steps + 1):


        message = llm.chat_with_tools(messages, tool_schema.TOOL_SCHEMAS)


        tool_calls = message.get("tool_calls")
        if not tool_calls:
            if verbose:
                log.info("[第 %s 步] 模型不再调用工具 → 结束循环", step)
            answer = message.get("content")
            report_path = report.save_report(topic, answer, trace, plan=plan)   # 完成后自动落盘
            if on_step:
                on_step({"type": "done", "answer": answer, "report": report_path})
            return answer, trace, report_path


        messages.append(message)


        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])   # 字符串 → 字典
            except (TypeError, ValueError):
                args = {}
            result = tools.call_tool(name, args)


            if verbose:
                log.info("[第 %s 步] 调用 %s(%s)", step, name, args)
                log.debug("          工具返回：%s", str(result)[:120])

            if str(result).startswith(("没有", "检索失败", "保存失败", "工具 ")):
                stall += 1
                log.warning("工具 %s 返回了问题信息（连续第 %s 次）：%s",
                            name, stall, str(result)[:60])
            else:
                stall = 0                       # 拿到有效信息 → 计数器归零

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],        # 必须和上面那条对得上号
                "content": str(result),
            })
            trace.append({"step": step, "tool": name, "args": args,
                          "result": str(result)[:200]})
            if on_step:
                on_step({"type": "tool", "step": step, "tool": name,
                         "args": args, "result": str(result)})


        if stall == STALL_HINT_AT:
            log.warning("连续 %s 次没捞到有效信息 → 提醒模型换策略（联网 / 换词）", stall)
            messages.append({"role": "user", "content": STALL_HINT})

        if stall >= STALL_LIMIT:                 # 提醒过还是不行 → 不再硬撑，改成"强制收尾"
            log.warning("连续 %s 次没捞到有效信息 → 要求模型立刻收尾", stall)
            messages.append({"role": "user", "content": FINAL_ASK})
            final = llm.chat_with_tools(messages, tool_schema.TOOL_SCHEMAS)
            answer = final.get("content") or "⚠ 资料覆盖不足，暂时给不出结论"
            report_path = report.save_report(topic, answer, trace, plan=plan)
            if on_step:
                on_step({"type": "done", "answer": answer, "report": report_path})
            return answer, trace, report_path


    log.warning("到达最大步数 %s，模型还在点菜 —— 强制停止", max_steps)
    answer = f"⚠ 到达最大步数（{max_steps}），任务未完成"
    report_path = report.save_report(topic, answer, trace, plan=plan)   # 半成品也存下来，方便排查
    return answer, trace, report_path


if __name__ == "__main__":

    answer, trace = run("RAG 的切片策略", max_steps=6)
    print("\n===== 最终回答 =====")
    print(answer)
    print(f"\n共用 {len(trace)} 步")
