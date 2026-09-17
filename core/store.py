import os
import sqlite3

from core import config

DB_PATH = os.path.join(config.OUTPUT_DIR, "research.db")


def init_db(conn):
    """建表。用 IF NOT EXISTS，所以重复调用也安全。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            content    TEXT NOT NULL,
            source     TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def get_conn():
    """连上数据库，并保证表已经建好。"""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    return conn


def add_note(content, source):
    """存一条要点。返回一句人话（这句话会被交给模型看）。"""
    if not content or not content.strip():
        return "保存失败：内容为空"
    try:
        conn = get_conn()

        conn.execute("INSERT INTO notes (content, source) VALUES (?, ?)", (content, source))
        conn.commit()                     # 不 commit 等于没写进去
        conn.close()
    except sqlite3.Error as e:
        return f"保存失败：{e}"
    return f"已保存要点（来源：{source}）"


def list_notes(limit=10):
    """取出最近的要点，返回**数据**：[(id, content, source, created_at), ...]"""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(50, limit))
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, content, source, created_at FROM notes ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def count_notes():
    """一共有多少条要点 —— 用来验证"数据真的存进去了"。"""
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    conn.close()
    return n


if __name__ == "__main__":
    print("数据库文件：", DB_PATH)
    print("现在有", count_notes(), "条要点")
    print(add_note("测试：切片别太小", "示例-RAG检索笔记.md#1"))
    print("存完之后有", count_notes(), "条")
    for row in list_notes(3):
        print("   ", row)
