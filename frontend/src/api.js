// 所有接口都返回 { success, data, error }。这里统一拆信封：成功返回 data，失败抛出带中文原因的错误。
// 凭证存 localStorage；401 时用 refresh 静默换一次并重放原请求，再失败清存储跳登录页。

export class ApiError extends Error {}

const STORAGE_KEY = 'chemai.auth'

export function loadAuth() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function saveAuth(auth) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(auth))
}

export function clearAuth() {
  localStorage.removeItem(STORAGE_KEY)
}

export function redirectToLogin() {
  const from = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.assign(`/login?from=${from}`)
}

// 刷新单飞：并发 401 共享同一次刷新调用，不重复请求
let refreshing = null

async function refreshAccessToken() {
  const current = loadAuth()
  if (!current?.refreshToken) throw new Error('没有长期凭证')
  const res = await fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${current.refreshToken}` },
  })
  let body
  try {
    body = await res.json()
  } catch {
    throw new Error(`刷新凭证失败（${res.status}）`)
  }
  if (!body.success) throw new Error(body.error || '登录已过期，请重新登录')
  // 后端不轮换长期凭证：只更新 access，refresh 保留
  saveAuth({ ...current, accessToken: body.data.access_token, user: body.data.user })
  return body.data.access_token
}

async function request(path, options = {}, { allowRefresh = true } = {}) {
  const auth = loadAuth()
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (auth?.accessToken) headers.Authorization = `Bearer ${auth.accessToken}`

  let res
  try {
    res = await fetch(`/api${path}`, { ...options, headers })
  } catch {
    throw new ApiError('连不上服务器，请确认后端已启动')
  }

  if (res.status === 401 && allowRefresh && auth?.refreshToken) {
    try {
      refreshing ||= refreshAccessToken().finally(() => {
        refreshing = null
      })
      const token = await refreshing
      // 重放原请求：body 是调用方传的字符串，可以直接复用
      res = await fetch(`/api${path}`, {
        ...options,
        headers: { ...headers, Authorization: `Bearer ${token}` },
      })
    } catch {
      // 刷新失败：先清刷新标志，再清存储跳登录，不循环重试
      refreshing = null
      clearAuth()
      redirectToLogin()
      throw new ApiError('登录已过期，请重新登录')
    }
  }

  if (res.status === 401) {
    // 没有长期凭证可刷（或登录/刷新接口本身 401）：清掉残留凭证回登录页
    if (allowRefresh) {
      clearAuth()
      redirectToLogin()
    }
    let body = null
    try {
      body = await res.json()
    } catch {
      // 没有信封就走下面的通用提示
    }
    throw new ApiError(body?.error || '请先登录')
  }

  let body
  try {
    body = await res.json()
  } catch {
    throw new ApiError(`服务器返回异常（${res.status}）`)
  }

  if (!body.success) {
    throw new ApiError(body.error || '操作失败，请重试')
  }
  return body.data
}

export const login = async (username, password) => {
  const data = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  }, { allowRefresh: false })
  saveAuth({ accessToken: data.access_token, refreshToken: data.refresh_token, user: data.user })
  return data.user
}

export const currentUser = () => loadAuth()?.user ?? null

export const logout = () => {
  clearAuth()
  redirectToLogin()
}

export const listQuestions = ({ difficulty, status, q, page } = {}) => {
  const params = new URLSearchParams()
  if (difficulty) params.set('difficulty', difficulty)
  if (status) params.set('status', status)
  if (q) params.set('q', q)
  if (page) params.set('page', page)
  const query = params.toString()
  return request(`/questions${query ? `?${query}` : ''}`)
}

export const createQuestion = (question) =>
  request('/questions', { method: 'POST', body: JSON.stringify(question) })

export const updateQuestion = (id, question) =>
  request(`/questions/${id}`, { method: 'PUT', body: JSON.stringify(question) })

export const changeQuestionStatus = (id, status) =>
  request(`/questions/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) })

export const getQuestionUsage = (id) => request(`/questions/${id}/usage`)

export const deleteQuestion = (id) => request(`/questions/${id}`, { method: 'DELETE' })

// ---- 考试：老师组卷与发布 ----

export const listPapers = () => request('/papers')

export const createPaper = (title) =>
  request('/papers', { method: 'POST', body: JSON.stringify({ title }) })

export const getPaper = (id) => request(`/papers/${id}`)

export const listQuestionPool = ({ difficulty, q } = {}) => {
  const params = new URLSearchParams()
  if (difficulty) params.set('difficulty', difficulty)
  if (q) params.set('q', q)
  const query = params.toString()
  return request(`/papers/pool${query ? `?${query}` : ''}`)
}

export const listClasses = () => request('/classes')

export const addPaperQuestion = (paperId, questionId) =>
  request(`/papers/${paperId}/questions`, {
    method: 'POST',
    body: JSON.stringify({ question_id: questionId }),
  })

export const removePaperQuestion = (paperId, questionId) =>
  request(`/papers/${paperId}/questions/${questionId}`, { method: 'DELETE' })

export const publishPaper = (paperId, classId) =>
  request(`/papers/${paperId}/publish`, {
    method: 'POST',
    body: JSON.stringify({ class_id: classId }),
  })

// ---- 考试：学生作答 ----

export const listAttempts = () => request('/attempts')

export const getAttempt = (id) => request(`/attempts/${id}`)

export const startAttempt = (id) => request(`/attempts/${id}/start`, { method: 'POST' })

export const submitAttempt = (id, answers) =>
  request(`/attempts/${id}/submit`, {
    method: 'POST',
    body: JSON.stringify({ answers }),
  })

export const retryGrading = (id) =>
  request(`/attempts/${id}/retry-grading`, { method: 'POST' })

export const listWrongQuestions = () => request('/wrong-questions')

// ---- 复习与报告 ----

export const listReviewTasks = (scope = 'due') =>
  request(`/review/tasks?scope=${encodeURIComponent(scope)}`)

export const answerReviewTask = (id, studentAnswer) =>
  request(`/review/tasks/${id}/answer`, {
    method: 'POST',
    body: JSON.stringify({ student_answer: studentAnswer }),
  })

export const getWeakReport = () => request('/reports/weak')

// ---- 知识点：两层树、建/改/合并 ----

export const listKnowledgePoints = () => request('/knowledge-points')

export const createKnowledgePoint = ({ name, parentId = null, aliases = [] }) =>
  request('/knowledge-points', {
    method: 'POST',
    body: JSON.stringify({ name, parent_id: parentId, aliases }),
  })

export const updateKnowledgePoint = (id, { name, aliases }) =>
  request(`/knowledge-points/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ name, aliases }),
  })

export const mergeKnowledgePoint = (id, targetId) =>
  request(`/knowledge-points/${id}/merge`, {
    method: 'POST',
    body: JSON.stringify({ target_id: targetId }),
  })

// ---- 练习：自适应出题与作答 ----

export const getNextPracticeQuestion = () => request('/practice/next')

export const answerPracticeQuestion = (questionId, answer, difficulty) =>
  request('/practice/answers', {
    method: 'POST',
    body: JSON.stringify({ question_id: questionId, answer, difficulty }),
  })
