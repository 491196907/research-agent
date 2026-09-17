import os
import sqlite3

from core import config
from core.log_setup import get_logger

log = get_logger(__name__)

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
    # 使用记录：谁、什么时候、研究了什么主题、走了几步、成没成
    # 用途：部署成公开/半公开的应用后，能知道"都有谁在用、都在研究什么"
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            visitor    TEXT,
            topic      TEXT,
            steps      INTEGER,
            status     TEXT,
            report     TEXT
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

        conn.execute(
            "INSERT INTO notes (content, source, created_at) VALUES (?, ?, ?)",
            (content, source, config.now_str()),        # 自己写时间：SQLite 默认给的是 UTC
        )
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


def add_run(visitor, topic, steps=0, status="", report=""):
    """记一条使用记录。写失败也不影响研究本身（只记日志）。"""
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO runs (created_at, visitor, topic, steps, status, report) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (config.now_str(), visitor or "访客", topic, int(steps or 0), status, report or ""),
        )
        conn.commit()
        conn.close()
        return True
    except (sqlite3.Error, TypeError, ValueError) as e:
        log.warning("使用记录写入失败（不影响本次研究）：%s", e)
        return False


def list_runs(limit=200):
    """最近的使用记录：[(id, 时间, 访问者, 主题, 步数, 状态, 报告), ...]"""
    try:
        limit = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        limit = 200
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, created_at, visitor, topic, steps, status, report "
        "FROM runs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def runs_summary():
    """按访问者统计次数：[("小明", 3), ("小红", 1), ...]（次数多的在前）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT visitor, COUNT(*) AS n FROM runs GROUP BY visitor ORDER BY n DESC"
    ).fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    print("数据库文件：", DB_PATH)
    print("现在有", count_notes(), "条要点")
    print(add_note("测试：切片别太小", "示例-RAG检索笔记.md#1"))
    print("存完之后有", count_notes(), "条")
    for row in list_notes(3):
        print("   ", row)
