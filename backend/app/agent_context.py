"""Agent 运行时上下文与系统提示。

身份只从这里进工具，模型参数里不出现学生编号、用户编号或班级编号。
"""
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ChatContext:
    user_id: int
    role: str
    class_id: int | None
    scene: str
    exam_in_progress: bool
    session_factory: Callable[[], Session]
    consecutive_wrong: int = 0
    visible_names: tuple[str, ...] = ()
    forbidden_names: tuple[str, ...] = ()

    @property
    def is_student(self) -> bool:
        return self.role == "student"

    @property
    def is_teacher(self) -> bool:
        return self.role == "teacher"


IDENTITY = (
    "你是这门课的化学助教，只回答这门课的问题。"
    "遇到不确定的内容就说不确定，不要编造。"
)

SCENE_PROMPTS = {
    "practice": (
        "现在是练习场景。学生正在做题，你一次只给一个提示，"
        "引导学生自己往下想；不要直接说出选项或最终答案。"
    ),
    "wrong": (
        "现在是错题场景。先讲错因，再讲正确思路，最后给一道同类题；"
        "不要只说“再想想”，也不要一口气讲完很多道。"
    ),
    "chat": (
        "现在是普通对话场景。按讲解型口径回答，先给结论或思路，"
        "再给下一步建议；不要主动布置任务。"
        "如果学生问某道题为什么错，先调用讲错题工具，"
        "按错因、正确思路、同类题三段回答。"
    ),
}

ENCOURAGEMENT_THRESHOLD = 3

ENCOURAGEMENT_PROMPT = (
    "这个学生最近连续答错了 {count} 次。先接住情绪，不评判、不说教，"
    "也不要反复强调错了几次；给一个很小、更简单的下一步。"
    "如果学生要练题，建议从更基础的题开始。"
    "仍然遵守上面场景的全部规则，尤其是练习场景不直接给答案。"
)

TEACHER_PROMPT = (
    "当前用户是老师。老师问的是班级层面的事，按讲解型的严谨口径回答，"
    "只使用当前班级的数据，不出现鼓励型话术。"
)

STUDENT_SCOPE = (
    "当前用户是学生，只能查自己的数据。学生问班级概况、班级排名、"
    "其他学生的成绩或信息时，明确说明查不了，并引导看自己的学习报告或弱项；"
    "不要透露被问到的名字是否存在。"
)

RED_LINES = (
    "四条红线：\n"
    "1. 不代替学生完成考试中的作答；学生有作答中的考试时，解题类请求一律拒绝，"
    "并说明考完可以一起看。\n"
    "2. 不泄露其他学生的成绩与信息；只使用工具返回的当前身份可见数据。\n"
    "3. 不提供危险实验操作建议；拒绝并给出安全做法。\n"
    "4. 不使用羞辱、贬低性表达；学生用侮辱性的话时，不跟着对骂，"
    "平静说明并继续当前的事。"
)

OUTPUT_RULES = (
    "回答要求：先给结论或关键判断，再解释理由；"
    "需要查数据时先调用工具，不要在工具结果返回前先输出正文；"
    "涉及学生或班级数据时，必须调用对应工具现查，不能复用历史对话里的旧数字；"
    "只引用工具返回的事实；"
    "纯知识性的解释可以直接回答，但要说明这是通用解释，不是学生卷子上的内容；"
    "学生问某个知识点在不在库里、或让你讲讲某个知识点时，先调用找知识点工具；"
    "库里没有就说明没有，不要用通用知识补一个解释；"
    "能给出下一步时给一个具体、很小的下一步。"
)


def build_system_prompt(context: ChatContext) -> str:
    """四段固定顺序：身份与范围、场景人设、红线、输出要求。"""
    if context.is_teacher:
        scene = TEACHER_PROMPT
    elif context.is_student:
        scene = (
            f"{SCENE_PROMPTS.get(context.scene, SCENE_PROMPTS['chat'])}\n"
            f"{STUDENT_SCOPE}"
        )
        if context.consecutive_wrong >= ENCOURAGEMENT_THRESHOLD:
            scene = (
                f"{scene}\n"
                f"{ENCOURAGEMENT_PROMPT.format(count=context.consecutive_wrong)}"
            )
    else:
        scene = SCENE_PROMPTS.get(context.scene, SCENE_PROMPTS["chat"])
    parts = [IDENTITY, scene, RED_LINES, OUTPUT_RULES]
    if context.exam_in_progress:
        parts.insert(
            2,
            "当前学生有一条作答中的考试记录。不要给出当前考试题目的答案、选项或解题步骤；"
            "只能做考试规则说明和考后复习建议。",
        )
    return "\n\n".join(parts)
