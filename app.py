r"""app.py —— 网页界面（Streamlit）。

跑法：
    cd E:\Deepseek工作区\ai学习\git仓库\项目\research-agent
    py -m streamlit run app.py

浏览器会自动打开；想停止就在终端按 Ctrl+C。
"""

import csv
import glob
import io
import os
from datetime import datetime

import streamlit as st

from core import agent, config, retriever, store, tools

st.set_page_config(page_title="AI 研究助手", page_icon="🔎", layout="wide")

# ============================================================
# 访问口令（可选）：支持"每人一个口令"，见 core/config.py 的 check_password
# 配了以后，使用记录里能看出"谁研究了什么"
# ============================================================
# 云端（Streamlit Cloud）偶尔会"只更新一半"：新的 app.py 已经跑起来了，
# 但进程里缓存的 core/config.py 还是旧的 —— 这时直接调 config.check_password
# 就会甩给用户一个 AttributeError 红屏。所以先探一下，再决定怎么校验。
CONFIG_VERSION = getattr(config, "APP_VERSION", None)      # 新 config 才有
HAS_CHECK_PASSWORD = callable(getattr(config, "check_password", None))
STALE_CODE = not (CONFIG_VERSION and HAS_CHECK_PASSWORD)


def _check_password(entered):
    """校验口令：对就返回"访问者名字"，不对返回 None。

    优先用 core/config.py 里的实现（支持"每人一个口令"）；
    万一读到的是旧 config（没有这个函数），就退回旧的单个口令逻辑 —— 不把用户锁在门外。
    """
    if HAS_CHECK_PASSWORD:
        return config.check_password(entered)
    table = getattr(config, "ACCESS_PASSWORDS", None) or {}
    if table:
        return table.get((entered or "").strip())
    old = getattr(config, "ACCESS_PASSWORD", None)
    if old:
        return "访客" if entered == old else None
    return "访客"          # 没配任何口令 = 不设门


GATE_ON = bool(getattr(config, "ACCESS_PASSWORD", None) or getattr(config, "ACCESS_PASSWORDS", None))

if "visitor" not in st.session_state:
    st.session_state["visitor"] = None

if GATE_ON:
    if not st.session_state["visitor"]:
        entered = st.text_input("🔒 请输入访问口令", type="password")
        name = _check_password(entered) if entered else None
        if name:
            st.session_state["visitor"] = name
            st.rerun()
        if STALE_CODE:
            st.warning("⚠️ 云端正在跑**半新半旧**的代码（新的 app.py + 旧的 core/config.py）。"
                       "点右下角 **Manage app → Reboot** 重启一次就正常了。")
        st.info("这是一个私人部署的 AI 研究助手。需要访问口令，请找分享给你的人要。")
        st.stop()

visitor = st.session_state["visitor"] or "访客"


with st.sidebar:
    st.title("🔎 AI 研究助手")
    st.caption("给一个主题，它自己查资料、做笔记、写带来源的报告")
    st.divider()

    st.subheader("运行设置")
    max_steps = st.slider("最多走几步（防死循环）", 2, 20, config.MAX_STEPS)
    use_plan = st.checkbox("先做研究计划", value=True)
    st.caption(f"对话模型：{config.MODEL}")
    st.caption("语义检索：" + ("已开启 ✅" if config.EMBED_API_KEY else "未配置（用字面检索）"))

    st.divider()
    st.subheader("📚 资料库")
    files = retriever.list_files()
    if files:
        for name in files:
            st.write(f"- {name}")
    else:
        st.info("资料库是空的：往 资料库/ 里放 .md 或 .txt")

    st.divider()
    st.subheader("🗂 已存要点")
    st.metric("条数", store.count_notes())
    st.caption("存进 outputs/research.db，重启不丢")

    st.divider()
    st.caption(f"当前访问者：**{visitor}**")
    st.metric("研究次数", len(store.list_runs(1000)))
    st.caption(f"代码版本：{CONFIG_VERSION or '旧版（云端缓存没刷新，Reboot 一下）'}")


    st.divider()
    with st.expander("🔧 自检（配置对不对）"):
        st.write("对话模型 key：", "✅ 已配" if config.API_KEY else "❌ 没读到")
        st.write("语义检索 key：", "✅ 已配（真语义检索）" if config.EMBED_API_KEY else "⚠️ 未配（用字面检索）")
        st.write("联网搜索 key：", "✅ 已配（走 API）" if config.SEARCH_API_KEY else "⚠️ 未配（走 Bing 网页版）")
        if st.button("测试联网搜索"):
            with st.spinner("正在搜索…"):
                st.text(tools.call_tool("web_search", {"query": "人工智能", "max_results": 2})[:600])


st.markdown("#### 给它一个主题，它自己查资料、做笔记、写报告。")
st.caption("Agent 会先规划子问题，优先查本地资料库；资料库里没有就联网搜索、抓网页，最后生成带来源的报告。")

tab_run, tab_reports, tab_notes, tab_usage = st.tabs(
    ["🔬 开始研究", "📄 历史报告", "🗂 已存要点", "📊 使用记录"]
)

with tab_run:
    if not config.API_KEY:
        st.error("没读到 DEEPSEEK_API_KEY：请先设置环境变量，然后重启终端和本应用")

    topic = st.text_input("研究主题", placeholder="例如：RAG 的切片策略")
    start = st.button("开始研究", type="primary", disabled=not config.API_KEY)

    if start and topic.strip():
        plan_box = st.container()
        steps_box = st.container()

        def on_step(info):
            """agent 每走一步都会调用这个函数 —— 界面实时显示进度。"""
            if info["type"] == "plan":
                plan_box.markdown(
                    "**研究计划**\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(info["plan"], 1))
                )
            elif info["type"] == "tool":
                with steps_box:
                    with st.expander(f"第 {info['step']} 步：{info['tool']}({info['args']})"):
                        st.text(str(info["result"])[:1500])

        with st.spinner(f"Agent 正在研究（最多 {max_steps} 步）…"):
            answer, trace = agent.run(topic.strip(), max_steps=max_steps,
                                      plan_first=use_plan, on_step=on_step)

        st.success(f"完成！共调用工具 {len(trace)} 次")
        st.markdown("### 结论")
        st.markdown(answer or "（没有拿到结论）")

        reports = sorted(glob.glob(os.path.join(config.OUTPUT_DIR, "研究报告-*.md")), reverse=True)
        latest_name = ""
        if reports:
            latest = reports[0]
            latest_name = os.path.basename(latest)
            with open(latest, encoding="utf-8") as f:
                content = f.read()
            st.download_button("⬇️ 下载这份报告", content,
                               file_name=latest_name, mime="text/markdown")

        # 记一条使用记录（写失败也不影响本次研究）
        status = "提前停止" if str(answer).startswith("⚠") else "完成"
        store.add_run(visitor, topic.strip(), len(trace), status, latest_name)

with tab_reports:
    reports = sorted(glob.glob(os.path.join(config.OUTPUT_DIR, "研究报告-*.md")), reverse=True)
    if not reports:
        st.info("还没有报告 —— 先去「开始研究」跑一次")
    else:
        picked = st.selectbox("选择一份报告", reports, format_func=os.path.basename, index=0)
        with open(picked, encoding="utf-8") as f:
            content = f.read()
        st.download_button("⬇️ 下载", content, file_name=os.path.basename(picked), mime="text/markdown")
        st.markdown(content)

with tab_notes:
    rows = store.list_notes(50)
    if not rows:
        st.info("还没有存任何要点 —— 跑一次研究，Agent 会自己往里存")
    else:
        st.dataframe(
            [{"id": r[0], "要点": r[1], "来源": r[2], "时间": r[3]} for r in rows],
            width="stretch",
        )

with tab_usage:
    st.caption("这里记录每一次研究：谁、什么时候、什么主题、走了几步、成没成。"
               "云端重启后数据库会重置，想要长期保存请点下面的按钮导出 CSV。")
    runs = store.list_runs(500)
    if not runs:
        st.info("还没有使用记录 —— 跑一次研究就会出现")
    else:
        col1, col2 = st.columns(2)
        col1.metric("总研究次数", len(runs))
        col2.metric("参与人数", len(store.runs_summary()))

        st.write("**按访问者统计**")
        st.dataframe([{"访问者": v, "次数": n} for v, n in store.runs_summary()],
                     width="stretch")

        st.write("**明细（最新在前）**")
        detail = [{"时间": r[1], "访问者": r[2], "主题": r[3],
                   "步数": r[4], "状态": r[5], "报告": r[6]} for r in runs]
        st.dataframe(detail, width="stretch")

        # 导出 CSV：用 utf-8-sig，Excel 打开中文才不乱码
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["时间", "访问者", "主题", "步数", "状态", "报告"])
        for row in runs:
            writer.writerow([row[1], row[2], row[3], row[4], row[5], row[6]])
        st.download_button(
            "⬇️ 下载 CSV（可用 Excel 打开）",
            buf.getvalue().encode("utf-8-sig"),
            file_name=f"使用记录-{datetime.now():%Y%m%d-%H%M}.csv",
            mime="text/csv",
        )
