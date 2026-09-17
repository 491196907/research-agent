TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_sources",
            "description": "列出本地资料库里有哪些资料文件。当你不知道资料库里有什么、或者想先了解资料范围时使用。不需要任何参数。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "在本地资料库里检索与查询词相关的片段，返回最相关的若干条，每条带来源文件名。当你需要为某个主题找资料依据时使用；如果一次没找到，可以换个更短的关键词再试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要检索的关键词或短句，例如：切片策略"},
                    "top_k": {"type": "integer", "description": "返回几条结果，默认 3，最多 10"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_note",
            "description": "把一条提炼好的要点保存进笔记，方便最后写报告时汇总。每提炼出一条独立要点就调用一次（一次只存一条）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要保存的要点内容（一句话说清）"},
                    "source": {"type": "string", "description": "这条要点的来源，格式 文件名#片段号"},
                },
                "required": ["content", "source"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_web",
            "description": "抓取一个网页的正文并存入本地资料库，之后可以用 search_notes 检索它。只有当你确信资料库里没有、并且知道具体网址时才用它。注意：外部网站可能被网络拦截或需要登录，失败时请继续用本地资料，不要反复重试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "完整网址，必须以 http:// 或 https:// 开头"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "在互联网上搜索，返回若干条「标题 + 链接 + 摘要」。当本地资料库查不到、而主题又需要外部信息时使用。搜完请用 fetch_web 抓取最相关的 2~3 个链接，再用 search_notes 检索它们，最后总结。注意：外部搜索可能被网络拦截。搜索失败时不要反复重试 —— 如果你知道权威网址（官网、百科条目等），直接用 fetch_web 抓它；否则改用本地资料，或者凭已有知识作答并在结论里注明「没有外部来源」。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索词，尽量短而具体，例如：英语学习方法 零基础"},
                    "max_results": {"type": "integer", "description": "要几条结果，默认 5，最多 8"},
                },
                "required": ["query"],
            },
        },
    },
]
