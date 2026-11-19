// 所有接口都返回 { success, data, error }。这里统一拆信封：成功返回 data，失败抛出带中文原因的错误。

export class ApiError extends Error {}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new ApiError('连不上服务器，请确认后端已启动')
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

export const listQuestions = () => request('/questions')

export const createQuestion = (question) =>
  request('/questions', { method: 'POST', body: JSON.stringify(question) })
