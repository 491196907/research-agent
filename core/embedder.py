import numpy as np
import requests

from core import config


class BaseEmbedder:
    """所有后端的"合同"：谁想当后端，就必须实现下面两个方法。

    （这就是"接口"：调用方只需要知道有这两个方法，不关心内部怎么实现。）
    """

    name = "base"                    # ← 类属性：写"这类东西"共有的信息
    default_min_score = 0.0          # 类属性：该后端的分数门槛（不同后端量纲不同，不能共用）


    def available(self):
        """这个后端现在能用吗？返回 True/False。"""
        raise NotImplementedError

    def embed(self, texts):
        """把一批文字变成向量：返回 [[...], [...]]；失败返回 None。"""
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name}>"


class LocalEmbedder(BaseEmbedder):
    """本地 bigram 词频向量：不要 key，永远可用（字面匹配，不是语义）。"""

    name = "local"
    default_min_score = 0.0          # 本地是字面分（0~0.2 量级），门槛保持 0

    def __init__(self, chunks):
        """出厂设置：根据已有片段建一张词表。

        为什么要在这里建？因为"查询"和"片段"必须用**同一张词表**，
        否则向量的每一位对不上号。词表属于"这台机器"，所以存成 self.vocab。
        """
        self.vocab = self._build_vocab(chunks)

    @staticmethod
    def tokenize(text):
        """中文没有空格：用相邻两个字当一个词。"""
        text = "".join(text.split())
        return [text[i:i + 2] for i in range(len(text) - 1)]

    def _build_vocab(self, chunks):
        """（内部方法，下划线开头 = 外部别碰）收集所有词，给每个词编座位号。"""
        vocab = {}
        for _, content in chunks:
            for tok in self.tokenize(content):
                if tok not in vocab:
                    vocab[tok] = len(vocab)
        return vocab

    def available(self):
        return True                              # 本地向量永远可用

    def embed(self, texts):
        """把每段文字变成一个"词频向量"（词表有多大，向量就有多少维）。"""
        vectors = []
        for text in texts:
            vec = np.zeros(len(self.vocab))
            for tok in self.tokenize(text):
                if tok in self.vocab:
                    vec[self.vocab[tok]] += 1    # 出现了就 +1
            vectors.append(vec)
        return vectors


class ApiEmbedder(BaseEmbedder):
    """调用 embedding 服务（真语义）。需要配 key。"""

    name = "api"
    default_min_score = 0.5          # 语义分数的噪音基线约 0.4，所以门槛设 0.5（要用自己的资料校准）
    _CACHE = {}          # ← 类属性：所有 ApiEmbedder 实例共用的一份缓存
                         #   {文本: 向量}；同样的文字不用重复花钱算

    def available(self):
        return bool(config.EMBED_API_KEY)

    def embed(self, texts):
        if not self.available():
            return None

        # ① 先看缓存：哪些文字已经算过了？
        todo = [t for t in texts if t not in self._CACHE]
        if todo:
            fresh = self._call_api(todo)
            if fresh is None:
                return None                      # 调不动 → 交给工厂/调用方降级
            for text, vec in zip(todo, fresh):
                self._CACHE[text] = vec
        return [self._CACHE[t] for t in texts]

    def _call_api(self, texts):
        """（内部方法）真正发请求那一步。"""
        headers = {
            "Authorization": f"Bearer {config.EMBED_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {"model": config.EMBED_MODEL, "input": texts}
        try:
            resp = requests.post(config.EMBED_API_URL, headers=headers, json=body,
                                 timeout=config.REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            print(f"[embedder] 网络出错：{e}")
            return None
        if resp.status_code != 200:
            print(f"[embedder] API 出错 {resp.status_code}：{resp.text[:200]}")
            return None
        data = resp.json()["data"]
        data.sort(key=lambda x: x["index"])      # 保证顺序和输入一一对应
        return [np.array(item["embedding"], dtype=float) for item in data]


class FakeEmbedder(BaseEmbedder):
    """假后端：不联网、结果确定（同样输入永远同样输出），专门用来做离线测试。"""

    name = "fake"

    def __init__(self, dim=16):
        self.dim = dim

    def available(self):
        return True

    def embed(self, texts):
        """把文字里的每个字"散列"到 dim 个座位上。"""
        vectors = []
        for text in texts:
            vec = np.zeros(self.dim)              # ① 先造一个 16 维的全 0 向量
            for ch in text:                       # ② 一个一个字过
                vec[ord(ch) % self.dim] += 1      #    算出座位号，那一格 +1
            vectors.append(vec)                   # ③ 收进结果
        return vectors                            # 返回"和 texts 一一对应"的列表


def get_embedder(chunks, prefer_api=True):
    """工厂：挑一个当前能用的后端。优先 API（更准），不行就退回本地。

    "工厂"就是一个普通函数：把"该用哪个类、怎么创建"这件事收在一处，
    调用方只写 get_embedder(chunks) 就行。
    """
    if prefer_api:
        api = ApiEmbedder()
        if api.available():
            return api
    return LocalEmbedder(chunks)





if __name__ == "__main__":
    # 自测：py -m core.embedder
    demo_chunks = [["a.md#0", "切片策略：把长文档切成小块。"], ["a.md#1", "字典：按名字取到对应的值。"]]
    for emb in [LocalEmbedder(demo_chunks), ApiEmbedder(), FakeEmbedder()]:
        print(f"{emb!r:30} available={emb.available()}")
        if emb.available():
            try:
                vecs = emb.embed(["切片", "字典"])
                print("    向量维度：", len(vecs[0]) if vecs else "None")
            except NotImplementedError as e:
                print("    （还没写）", e)

    chosen = get_embedder(demo_chunks)
    print("工厂挑中的后端：", chosen)
