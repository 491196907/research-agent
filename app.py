r"""app.py —— 网页界面（Streamlit）。

跑法：
    cd E:\Deepseek工作区\ai学习\git仓库\项目\research-agent
    py -m streamlit run app.py

浏览器会自动打开；想停止就在终端按 Ctrl+C。
"""

import glob
import os

import streamlit as st

from core import agent, config, retriever, store, tools

st.set_page_config(page_title="AI 研究助手", page_icon="🔎", layout="wide")


if config.ACCESS_PASSWORD:
    entered = st.text_input("🔒 请输入访问口令", type="password")
    if entered != config.ACCESS_PASSWORD:
        st.info("这是一个私人部署的 AI 研究助手。需要访问口令，请找分享给你的人要。")
        st.stop()


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
    with st.expander("🔧 自检（配置对不对）"):
        st.write("对话模型 key：", "✅ 已配" if config.API_KEY else "❌ 没读到")
        st.write("语义检索 key：", "✅ 已配（真语义检索）" if config.EMBED_API_KEY else "⚠️ 未配（用字面检索）")
        st.write("联网搜索 key：", "✅ 已配（走 API）" if config.SEARCH_API_KEY else "⚠️ 未配（走 Bing 网页版）")
        if st.button("测试联网搜索"):
            with st.spinner("正在搜索…"):
                st.text(tools.call_tool("web_search", {"query": "人工智能", "max_results": 2})[:600])


st.markdown("#### 给它一个主题，它自己查资料、做笔记、写报告。")
st.caption("Agent 会先规划子问题，优先查本地资料库；资料库里没有就联网搜索、抓网页，最后生成带来源的报告。")

tab_run, tab_reports, tab_notes = st.tabs(["🔬 开始研究", "📄 历史报告", "🗂 已存要点"])

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
        if reports:
            latest = reports[0]
            with open(latest, encoding="utf-8") as f:
                content = f.read()
            st.download_button("⬇️ 下载这份报告", content,
                               file_name=os.path.basename(latest), mime="text/markdown")

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
            use_container_width=True,
        )
