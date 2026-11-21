// 题型：设计/02-题库与考试.md §4.1
export const QUESTION_TYPES = {
  single: '单选',
  multiple: '多选',
  blank: '填空',
}

// 题目审核状态与标签颜色：设计/05-页面与选型.md §4.4（灰、橙、绿）
export const REVIEW_STATUS = {
  draft: { label: '草稿', color: 'default' },
  pending: { label: '待复核', color: 'orange' },
  approved: { label: '已通过', color: 'green' },
}

export const DIFFICULTIES = [1, 2, 3]

// 卷子状态：设计/05 §4.4（灰、绿）
export const PAPER_STATUS = {
  draft: { label: '草稿', color: 'default' },
  published: { label: '已发布', color: 'green' },
}

// 作答状态：设计/05 §4.4（灰、蓝、橙、绿）
export const ATTEMPT_STATUS = {
  pending: { label: '待作答', color: 'default' },
  in_progress: { label: '作答中', color: 'blue' },
  submitted: { label: '已交卷', color: 'orange' },
  graded: { label: '已判分', color: 'green' },
}

// 错题来源：设计/02 §4.8；本章只有考试，练习与复习在后面的章节产生
export const WRONG_SOURCE_LABELS = {
  exam: '考试',
}

// 登录后的落地页：老师和管理员进题库，学生进考试页（第 03 章是占位页）
export const HOME_BY_ROLE = {
  teacher: '/teacher/questions',
  admin: '/teacher/questions',
  student: '/student/exams',
}

export const homeFor = (role) => HOME_BY_ROLE[role] ?? '/login'
