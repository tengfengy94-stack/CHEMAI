import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Flex, Input, Select, Space, Spin, Typography } from 'antd'
import { useNavigate } from 'react-router'
import { currentUser, getChatHistory, logout, streamChat } from '../../api.js'
import StudentHeader from './StudentHeader.jsx'

function TeacherHeader() {
  const navigate = useNavigate()
  const user = currentUser()
  return (
    <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        对话
      </Typography.Title>
      <Space>
        <Button onClick={() => navigate('/teacher/questions')}>题库</Button>
        <Button onClick={() => navigate('/teacher/exams')}>组卷</Button>
        <Button onClick={() => navigate('/teacher/knowledge')}>知识点</Button>
        <Button onClick={() => navigate('/teacher/class')}>班级报告</Button>
        <Typography.Text type="secondary">
          {user ? `${user.name}（${user.username}）` : ''}
        </Typography.Text>
        <Button onClick={logout}>退出</Button>
      </Space>
    </Flex>
  )
}

function sceneFromUrl() {
  const scene = new URLSearchParams(window.location.search).get('scene')
  return scene === 'practice' || scene === 'wrong' ? scene : 'chat'
}

export default function Chat() {
  const navigate = useNavigate()
  const user = currentUser()
  const isTeacher = user?.role === 'teacher'
  const classes = Array.isArray(user?.classes) ? user.classes : []
  const initialClassId = isTeacher && classes.length ? classes[0].id : null

  const [classId, setClassId] = useState(initialClassId)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [practicePlan, setPracticePlan] = useState([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const listRef = useRef(null)
  const abortRef = useRef(null)
  const idRef = useRef(0)
  const mountedRef = useRef(true)
  const sendingRef = useRef(false)
  const scene = sceneFromUrl()

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [messages])

  useEffect(() => {
    let cancelled = false
    async function loadHistory() {
      if (isTeacher && classes.length > 1 && classId == null) {
        setHistoryLoading(false)
        return
      }
      setHistoryLoading(true)
      try {
        const data = await getChatHistory(classId)
        if (cancelled) return
        setMessages(
          (data.items || []).map((item) => ({
            id: ++idRef.current,
            role: item.role,
            content: item.content,
            status: 'done',
          })),
        )
        setError('')
      } catch (err) {
        if (!cancelled) setError(err.message || '历史加载失败')
      } finally {
        if (!cancelled) setHistoryLoading(false)
      }
    }
    loadHistory()
    return () => {
      cancelled = true
    }
    // classes.length/classId 是老师切换班级的依赖；学生只加载一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId, isTeacher, classes.length])

  const run = async (text, { appendUser = true, retry = false } = {}) => {
    if (sendingRef.current) return
    if (historyLoading) return
    if (isTeacher && classes.length > 1 && classId == null) {
      setError('请先选择班级')
      return
    }
    sendingRef.current = true
    setSending(true)
    setError('')
    setPracticePlan([])

    const assistantId = ++idRef.current
    setMessages((prev) => [
      ...prev,
      ...(appendUser ? [{ id: ++idRef.current, role: 'user', content: text }] : []),
      { id: assistantId, role: 'assistant', content: '', status: 'streaming' },
    ])

    const controller = new AbortController()
    abortRef.current = controller
    let ended = false

    try {
      await streamChat(text, {
        signal: controller.signal,
        scene,
        classId,
        retry,
        onEvent: ({ event, data }) => {
          if (event === 'tool') {
            if (
              (data?.name === 'assign_practice_result' ||
                data?.name === 'similar_question_result') &&
              Array.isArray(data.questions)
            ) {
              setPracticePlan(data.questions)
              return
            }
            const hint = {
              id: ++idRef.current,
              role: 'tool',
              content: data?.label || '正在查资料',
            }
            setMessages((prev) => {
              const index = prev.findIndex((item) => item.id === assistantId)
              if (index === -1) return [...prev, hint]
              return [...prev.slice(0, index), hint, ...prev.slice(index)]
            })
          } else if (event === 'text') {
            const delta = data?.delta
            if (!delta) return
            setMessages((prev) =>
              prev.map((item) =>
                item.id === assistantId ? { ...item, content: item.content + delta } : item,
              ),
            )
          } else if (event === 'end') {
            ended = true
            setMessages((prev) =>
              prev.map((item) => (item.id === assistantId ? { ...item, status: 'done' } : item)),
            )
          }
        },
      })
      if (!ended) throw new Error('回答中断了，请重试')
    } catch (err) {
      if (controller.signal.aborted) return
      setMessages((prev) =>
        prev.map((item) => (item.id === assistantId ? { ...item, status: 'error' } : item)),
      )
      setError(err?.message || '回答失败了，请重试')
    } finally {
      sendingRef.current = false
      if (abortRef.current === controller) abortRef.current = null
      if (!controller.signal.aborted && mountedRef.current) setSending(false)
    }
  }

  const send = () => {
    const text = input.trim()
    if (!text || sendingRef.current || historyLoading) return
    setInput('')
    run(text)
  }

  const retry = () => {
    if (sendingRef.current) return
    const lastUser = [...messages].reverse().find((item) => item.role === 'user')
    if (!lastUser) return
    setMessages((prev) => {
      const index = prev.findIndex((item) => item.id === lastUser.id)
      return index === -1 ? prev : prev.slice(0, index + 1)
    })
    setError('')
    run(lastUser.content, { appendUser: false, retry: true })
  }

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  const primaryIsRetry =
    !input.trim() && Boolean(error) && messages.some((item) => item.role === 'user')
  const needsClass = isTeacher && classes.length > 1
  const sendDisabled =
    sending ||
    historyLoading ||
    (needsClass && classId == null) ||
    (!input.trim() && !primaryIsRetry)

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      {user?.role === 'student' ? <StudentHeader title="对话" /> : <TeacherHeader />}

      {needsClass && (
        <Flex gap={8} align="center" style={{ marginBottom: 12 }}>
          <Typography.Text type="secondary">当前班级</Typography.Text>
          <Select
            value={classId ?? undefined}
            placeholder="请选择班级"
            style={{ minWidth: 180 }}
            onChange={setClassId}
            options={classes.map((item) => ({ value: item.id, label: item.name }))}
          />
          <Typography.Text type="secondary">
            切换班级会加载该班自己的对话
          </Typography.Text>
        </Flex>
      )}

      <div
        ref={listRef}
        style={{
          height: 480,
          overflowY: 'auto',
          padding: 16,
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
        }}
      >
        {historyLoading ? (
          <Flex align="center" justify="center" style={{ height: '100%' }}>
            <Spin />
          </Flex>
        ) : messages.length === 0 ? (
          <Flex
            vertical
            align="center"
            justify="center"
            gap={8}
            style={{ height: '100%', textAlign: 'center' }}
          >
            <Typography.Text type="secondary">
              可以问我化学概念、反应原理或解题思路。
            </Typography.Text>
            <Typography.Text type="secondary">
              比如：氧化还原反应怎么判断？
            </Typography.Text>
          </Flex>
        ) : (
          messages.map((item) => {
            if (item.role === 'tool') {
              return (
                <Flex key={item.id} justify="flex-start" style={{ marginBottom: 8 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {item.content}
                  </Typography.Text>
                </Flex>
              )
            }
            const mine = item.role === 'user'
            return (
              <Flex
                key={item.id}
                justify={mine ? 'flex-end' : 'flex-start'}
                style={{ marginBottom: 12 }}
              >
                <div
                  style={{
                    maxWidth: '78%',
                    padding: '10px 14px',
                    borderRadius: 10,
                    background: mine ? '#1677ff' : '#fff',
                    border: mine ? '1px solid #1677ff' : '1px solid #f0f0f0',
                    color: mine ? '#fff' : 'rgba(0, 0, 0, 0.88)',
                  }}
                >
                  {item.role === 'assistant' && item.status === 'streaming' && !item.content ? (
                    <Spin size="small" />
                  ) : item.role === 'assistant' && item.status === 'error' && !item.content ? (
                    <Typography.Text type="secondary">这次没有收到回答。</Typography.Text>
                  ) : (
                    <Typography.Text
                      style={{ color: 'inherit', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                    >
                      {item.content}
                    </Typography.Text>
                  )}
                </div>
              </Flex>
            )
          })
        )}
      </div>

      {error && (
        <Alert
          style={{ marginTop: 12 }}
          type="error"
          showIcon
          title="回答中断了"
          description={error}
          action={
            <Button size="small" onClick={retry} disabled={sending}>
              重试
            </Button>
          }
        />
      )}

      <Flex gap={8} style={{ marginTop: 12 }} align="flex-end">
        <Input.TextArea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="问一句化学问题，Enter 发送，Shift+Enter 换行"
          autoSize={{ minRows: 2, maxRows: 5 }}
          disabled={sending}
        />
        <Button
          type="primary"
          onClick={primaryIsRetry ? retry : send}
          disabled={sendDisabled}
          loading={sending}
        >
          {primaryIsRetry ? '重试' : '发送'}
        </Button>
      </Flex>
      {practicePlan.length > 0 && (
        <Flex justify="flex-end" style={{ marginTop: 8 }}>
          <Button
            type="primary"
            onClick={() => navigate(`/student/practice?plan=${practicePlan.join(',')}`)}
          >
            {practicePlan.length === 1 ? '去练这道题' : `去练这 ${practicePlan.length} 道题`}
          </Button>
        </Flex>
      )}
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        对话会按当前身份保存；刷新或重新打开后可以继续。
      </Typography.Text>
    </div>
  )
}
