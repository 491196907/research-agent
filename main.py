r"""main.py —— 项目入口：给一个研究主题，Agent 自己跑完并生成报告。

用法：
    项目根目录（有 main.py 的那一层）
    py main.py
"""

from core import agent, config


def main():
    print("=" * 56)
    print("  AI 研究助手（自主 Agent）")
    print("=" * 56)

    if not config.API_KEY:
        print("❌ 没读到 DEEPSEEK_API_KEY")
        print('   请先执行：setx DEEPSEEK_API_KEY "sk-..." 然后重开终端')
        return

    topic = input("请输入研究主题（直接回车退出）：").strip()
    if not topic:
        print("-> 你没有输入，已退出")
        return

    print(f"\n开始研究：{topic}")
    print("Agent 会自己决定查什么、记什么，请稍等……\n")

    answer, trace, report_path = agent.run(topic, max_steps=config.MAX_STEPS)

    print("\n" + "=" * 56)
    print("  最终结论")
    print("=" * 56)
    print(answer)
    print(f"\n[本次共调用工具 {len(trace)} 次；报告：{report_path or '（没落盘）'}]")


if __name__ == "__main__":
    main()
