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

// 登录后的落地页：老师和管理员进题库，学生进考试页（第 03 章是占位页）
export const HOME_BY_ROLE = {
  teacher: '/teacher/questions',
  admin: '/teacher/questions',
  student: '/student/exams',
}

export const homeFor = (role) => HOME_BY_ROLE[role] ?? '/login'
