"""四条红线的输出检查：规则表、命中判定与固定替代话术。

规则只兜显式措辞；系统提示仍是第一道。检查不调用模型。
"""
import re
from dataclasses import dataclass

from app.agent_context import ChatContext

# 命中后的固定话术：说明为什么不行，再给出接下来能做什么。
REPLACEMENTS = {
    1: "这道题我不能替你做。考完把卷子拿来，我们一道一道看，那时候讲得透。",
    2: "别人的成绩我查不了。你自己的弱项，我可以现在给你看。",
    3: (
        "这个操作有危险，不能试。实验室里闻气体的正确做法是扇闻："
        "用手在瓶口轻轻扇动，让少量气体飘进鼻孔。"
    ),
    4: "我们一步一步来。先看这道题已经确定的条件，再决定下一步。",
}

# 危险操作按类别给安全做法，避免“品尝/加热”也回“扇闻”。
DANGER_REPLACEMENTS = {
    "smell": REPLACEMENTS[3],
    "taste": (
        "这个操作有危险，不能试。实验室里的试剂不能品尝或饮用；"
        "要判断性质，按实验规范取少量样品做规定测试，或者先问老师。"
    ),
    "heat": (
        "这个操作有危险，不能试。加热要按实验规范使用合适的加热方式，"
        "不能直接用明火加热；先确认仪器和试剂，必要时问老师。"
    ),
}

# 考试中：答案、选项、解题步骤与化学解题术语。
_EXAM_PATTERNS = (
    re.compile(r"(答案|正确选项|选项|应选|选择|选)\s*(?:是|为)?\s*[:：]?\s*[A-DＡ-Ｄ]"),
    re.compile(r"[A-DＡ-Ｄ]\s*(项|选项)?\s*(正确|对|是答案|更合适|最合适)"),
    re.compile(r"(解题步骤|第[一二三四五六七八九十\d]+步)"),
    re.compile(r"(配平|氧化剂|还原剂|得失电子|化合价|化学方程式|离子方程式)"),
    re.compile(r"(先|再|然后|最后)\s*.{0,12}(看|算|求|写|列|配平|代入|判断|比较)"),
)

# 其他学生：姓名 + 分数/排名；姓名不在可见范围即命中。
_SCORE_PATTERN = re.compile(
    r"([\u4e00-\u9fa5]{2,4}?)(?:同学)?\s*(?:这次|上次)?\s*的?\s*"
    r"(?:考了|得了|考得|分数是|成绩是|排名第)\s*"
    r"(\d{1,3}|[一二三四五六七八九十]{1,3})"
)
_SCORE_PRONOUNS = ("你", "您", "这", "该", "本", "此")
# “上次/第一题/最近/考试考了95分”不是姓名，先排除再判断。
_SCORE_NON_NAMES = (
    "上次", "这次", "下次", "前次", "后次", "最近", "每次", "某次",
    "第一", "第二", "第三", "第四", "第五", "第六", "第七", "第八",
    "期中", "期末", "月考", "周测", "模拟", "统考", "联考", "测验",
    "考试", "测试", "全班", "本班", "我们班", "班级",
)
_SCORE_NON_NAME_FIRST = set("一二三四五六七八九十第")

# 危险实验操作：只拦显式操作，知识解释与“扇闻”安全做法不拦。
_DANGEROUS_PATTERNS = (
    (re.compile(r"(直接|凑近|用鼻子|拿鼻子)\s*.{0,4}闻"), "smell"),
    (re.compile(r"(品尝|尝一口|喝一口)"), "taste"),
    (re.compile(r"(直接|明火|用嘴)\s*.{0,4}(加热|吹)"), "heat"),
)

# 羞辱、贬低性表达。
_INSULT_PATTERNS = (
    re.compile(r"这么简单都不会"),
    re.compile(r"(真|太|很)?(笨|蠢|傻|废物|没救了|脑子进水|智商低)"),
)

_NEGATIONS = ("不要", "不能", "别", "禁止", "切勿")

_SENTENCE_END = re.compile(r"[。！？!?；;\n]")
_MAX_SEGMENT = 160


@dataclass(frozen=True)
class GuardHit:
    red_line: int
    replacement: str


def _matches(patterns, text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _danger_hit(text: str) -> str | None:
    for pattern, category in _DANGEROUS_PATTERNS:
        for match in pattern.finditer(text):
            if any(
                word in text[max(0, match.start() - 4):match.start()]
                for word in _NEGATIONS
            ):
                continue
            return category
    return None


def _is_chinese_name(name: str) -> bool:
    return len(name) >= 2 and all("\u4e00" <= char <= "\u9fff" for char in name)


def _other_student_hit(text: str, context: ChatContext) -> bool:
    visible = set(context.visible_names)
    for name in context.forbidden_names:
        # 本班和别班同名学生：当前身份能看到就先放行。
        if name in visible:
            continue
        if _is_chinese_name(name) and name in text:
            return True
    for match in _SCORE_PATTERN.finditer(text):
        name = match.group(1)
        if name.startswith(_SCORE_PRONOUNS):
            continue
        if name.startswith(_SCORE_NON_NAMES) or name[0] in _SCORE_NON_NAME_FIRST:
            continue
        if name not in visible:
            return True
    return False


def scan(text: str, context: ChatContext) -> GuardHit | None:
    """按 1→4 检查一段正文，命中第一条即返回替代话术。"""
    if not text:
        return None
    if context.exam_in_progress and _matches(_EXAM_PATTERNS, text):
        return GuardHit(1, REPLACEMENTS[1])
    if _other_student_hit(text, context):
        return GuardHit(2, REPLACEMENTS[2])
    danger = _danger_hit(text)
    if danger is not None:
        return GuardHit(3, DANGER_REPLACEMENTS[danger])
    if _matches(_INSULT_PATTERNS, text):
        return GuardHit(4, REPLACEMENTS[4])
    return None


class OutputGuard:
    """有状态的句级缓冲：安全片段原样返回，命中后只返回一次替代话术。"""

    def __init__(self, context: ChatContext) -> None:
        self.context = context
        self.hit: GuardHit | None = None
        self._buffer = ""

    @property
    def tripped(self) -> bool:
        return self.hit is not None

    def feed(self, delta: str) -> list[str]:
        """吃进一段模型正文，返回可以立即发给客户端的片段。"""
        if self.tripped:
            return []
        self._buffer += delta
        chunks: list[str] = []
        while True:
            cut = self._next_segment_end()
            if cut is None:
                return chunks
            segment = self._buffer[:cut]
            self._buffer = self._buffer[cut:]
            hit = scan(segment, self.context)
            if hit is not None:
                self.hit = hit
                self._buffer = ""
                chunks.append(hit.replacement)
                return chunks
            chunks.append(segment)

    def flush(self) -> list[str]:
        """流结束时检查残留缓冲。"""
        if self.tripped:
            return []
        segment = self._buffer
        self._buffer = ""
        if not segment:
            return []
        hit = scan(segment, self.context)
        if hit is not None:
            self.hit = hit
            return [hit.replacement]
        return [segment]

    def _next_segment_end(self) -> int | None:
        match = _SENTENCE_END.search(self._buffer)
        if match is not None:
            return match.end()
        if len(self._buffer) >= _MAX_SEGMENT:
            return _MAX_SEGMENT
        return None
