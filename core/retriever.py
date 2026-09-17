import os
import re

import numpy as np

from core import config

from core import embedder


SKIP_FILES = {"README.md"}

# 抓下来的网页文件，第一行是 "# 网页：<原始网址>" —— 解析出来，附在每个片段的来源后面
_PAGE_URL_RE = re.compile(r"^#\s*网页：\s*(\S+)")


def list_files():
    """列出资料库里所有"算资料"的文件名（已排序，跳过 SKIP_FILES 和非 md/txt）。

    注意：返回的是**列表**，不是给模型看的字符串 —— 排版是 tools.py 的事。
    """
    if not os.path.isdir(config.DATA_DIR):
        return []
    names = []
    for filename in sorted(os.listdir(config.DATA_DIR)):
        if filename in SKIP_FILES:
            continue
        if not filename.endswith((".md", ".txt")):
            continue
        names.append(filename)
    return names

def load_chunks():
    """读资料库 → [(来源, 内容), ...]"""
    chunks = []
    for filename in list_files():                    # ← 改用 list_files()，过滤规则只留一份
        path = os.path.join(config.DATA_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        m = _PAGE_URL_RE.match(text)                 # 网页文件 → 带上原始网址
        url = f"（{m.group(1)}）" if m else ""
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        for i, part in enumerate(parts):
            chunks.append((f"{filename}#{i}{url}", part))
    return chunks






def cosine(a, b):
    """余弦相似度：两个向量方向的接近程度，0~1（分量非负时）。"""
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    na = np.linalg.norm(a)          # 模长（长度）
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:          # 零向量没有方向，直接判 0，避免除以 0
        return 0.0
    return float(a @ b / (na * nb))  # a @ b 是点积（对应位置相乘再相加）



def search(query, top_k=3, min_score=None):
    """检索：统一走 embedder 的接口，不再关心是哪个后端。"""
    chunks = load_chunks()
    if not chunks:
        return []

    emb = embedder.get_embedder(chunks)               # 工厂挑一个能用的
    if min_score is None:
        min_score = emb.default_min_score             # 门槛也由后端自己决定

    chunk_vecs = emb.embed([c for _, c in chunks])
    query_vecs = emb.embed([query])
    if not chunk_vecs or not query_vecs:
        return []

    q = np.array(query_vecs[0], dtype=float)
    scored = []
    for (source, content), v in zip(chunks, chunk_vecs):
        score = cosine(q, np.array(v, dtype=float))
        if score > min_score:                         # 丢掉低于门槛的噪音
            scored.append((score, source, content))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]

if __name__ == "__main__":
    for score, source, content in search("切片", top_k=2):
        print(f"{score:.4f}  [来源: {source}] {content[:40]}...")
