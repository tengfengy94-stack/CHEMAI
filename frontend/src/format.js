// 学生页共用的显示格式

export const optionLetter = (index) => String.fromCharCode(65 + index)

export const timeText = (value) =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : ''

// 到期日只写“今天/明天/几月几日”：设计/05 §4.4
// 服务端按固定 UTC+8 业务日期判断到期，这里也按 UTC+8 比较，避免浏览器时区不同导致文案错位。
export const dueLabel = (isoDate) => {
  if (!isoDate) return '已出队'
  const [year, month, day] = isoDate.split('-').map(Number)
  const now = new Date()
  const utc8Now = new Date(now.getTime() + 8 * 3600 * 1000)
  const today = Date.UTC(
    utc8Now.getUTCFullYear(),
    utc8Now.getUTCMonth(),
    utc8Now.getUTCDate(),
  )
  const due = Date.UTC(year, month - 1, day)
  const diff = Math.round((due - today) / 86400000)
  if (diff === 0) return '今天'
  if (diff === 1) return '明天'
  if (diff < 0) return `逾期 ${-diff} 天`
  return `${month}月${day}日`
}

export const formatPercent = (value) => `${Number(value ?? 0).toFixed(1)}%`
