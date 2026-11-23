import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Flex, Input, Space, Spin, Typography } from 'antd'
import { useNavigate } from 'react-router'
import { currentUser, logout, streamChat } from '../../api.js'
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

export default function Chat() {
  const user = currentUser()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const listRef = useRef(null)
  const abortRef = useRef(null)
  const idRef = useRef(0)
  const mountedRef = useRef(true)
  const sendingRef = useRef(false)

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

  const run = async (text, { appendUser = true } = {}) => {
    if (sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    setError('')

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
        onEvent: ({ event, data }) => {
          if (event === 'text') {
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
    if (!text || sendingRef.current) return
    setInput('')
    run(text)
  }

  const retry = () => {
    if (sendingRef.current) return
    const lastUser = [...messages].reverse().find((item) => item.role === 'user')
    if (!lastUser) return
    // 保留提问，清掉失败的回答，重新生成
    setMessages((prev) => {
      const index = prev.findIndex((item) => item.id === lastUser.id)
      return index === -1 ? prev : prev.slice(0, index + 1)
    })
    setError('')
    run(lastUser.content, { appendUser: false })
  }

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  // 出错且输入框为空时，主按钮从“发送”变成“重试”；开始输入新问题就回到“发送”。
  const primaryIsRetry =
    !input.trim() && Boolean(error) && messages.some((item) => item.role === 'user')

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      {user?.role === 'student' ? <StudentHeader title="对话" /> : <TeacherHeader />}

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
        {messages.length === 0 ? (
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
          disabled={sending || (!input.trim() && !primaryIsRetry)}
          loading={sending}
        >
          {primaryIsRetry ? '重试' : '发送'}
        </Button>
      </Flex>
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        本轮对话不会保存，刷新页面后清空。
      </Typography.Text>
    </div>
  )
}
