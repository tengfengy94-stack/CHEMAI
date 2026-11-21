import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Checkbox,
  Empty,
  Flex,
  Input,
  List,
  Modal,
  Radio,
  Result,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  currentUser,
  getAttempt,
  listAttempts,
  logout,
  retryGrading,
  startAttempt,
  submitAttempt,
} from '../../api.js'
import { ATTEMPT_STATUS, QUESTION_TYPES } from '../../constants.js'

const optionLetter = (index) => String.fromCharCode(65 + index)

const statusTag = (attempt) => {
  if (attempt.status === 'submitted' && attempt.grading_in_progress) {
    return <Tag color="blue">判分中</Tag>
  }
  const info = ATTEMPT_STATUS[attempt.status]
  return info ? <Tag color={info.color}>{info.label}</Tag> : attempt.status
}

const scoreText = (score) =>
  score === null || score === undefined ? '—' : Number(score).toFixed(1)

export default function StudentExams() {
  const { message, modal } = AntApp.useApp()
  const user = currentUser()
  const [attempts, setAttempts] = useState([])
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState('list')
  const [attempt, setAttempt] = useState(null)
  const [answers, setAnswers] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [blankConfirm, setBlankConfirm] = useState(false)

  const fetchAttempts = useCallback(async () => {
    try {
      const data = await listAttempts()
      setAttempts(data.items)
    } catch (error) {
      message.error(error.message)
    } finally {
      setLoading(false)
    }
  }, [message])

  const reloadAttempts = useCallback(async () => {
    setLoading(true)
    await fetchAttempts()
  }, [fetchAttempts])

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await listAttempts()
        if (!cancelled) setAttempts(data.items)
      } catch (error) {
        if (!cancelled) message.error(error.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [message])

  const openAttempt = async (id) => {
    try {
      const data = await getAttempt(id)
      setAttempt(data)
      setAnswers({})
      setMode(data.status === 'in_progress' ? 'answer' : 'result')
    } catch (error) {
      message.error(error.message)
    }
  }

  const handleStart = async (record) => {
    try {
      const data = await startAttempt(record.id)
      setAttempt(data)
      setAnswers({})
      setMode('answer')
      await reloadAttempts()
    } catch (error) {
      message.error(error.message)
    }
  }

  const answeredCount = (attempt?.questions ?? []).filter((question) => {
    const value = answers[question.id]
    return Array.isArray(value) ? value.length > 0 : Boolean((value ?? '').trim())
  }).length

  const buildAnswers = () =>
    (attempt?.questions ?? [])
      .map((question) => {
        const value = answers[question.id]
        if (Array.isArray(value)) {
          return { question_id: question.id, answer: value.slice().sort().join('') }
        }
        return { question_id: question.id, answer: (value ?? '').trim() }
      })
      .filter((item) => item.answer !== '')

  const doSubmit = async () => {
    setSubmitting(true)
    try {
      const data = await submitAttempt(attempt.id, buildAnswers())
      setAttempt(data)
      setMode('result')
      message.success(
        data.status === 'graded' ? '交卷成功，已经出分' : '答案已收，判分没完成',
      )
      await reloadAttempts()
    } catch (error) {
      if (error.message.includes('已经交过了') || error.message.includes('不能再交卷')) {
        message.info('这份卷子已经交过了，正在刷新结果')
        await openAttempt(attempt.id)
      } else {
        message.error(error.message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleSubmit = () => {
    const total = attempt.questions.length
    const unanswered = total - answeredCount
    const blank = answeredCount === 0
    modal.confirm({
      title: '交卷确认',
      content: blank
        ? '你一道题都没答，交卷会按 0 分处理。'
        : unanswered > 0
          ? `还有 ${unanswered} 道题没答，未答的题按错算。`
          : '所有题都已作答，交卷后不能再修改。',
      okText: blank ? '继续' : '交卷',
      cancelText: '取消',
      onOk: () => {
        if (blank) setBlankConfirm(true)
        else doSubmit()
      },
    })
  }

  const handleRetry = async (id) => {
    setRetrying(true)
    try {
      const data = await retryGrading(id)
      setAttempt(data)
      setMode('result')
      message[data.status === 'graded' ? 'success' : 'warning'](
        data.status === 'graded' ? '判分完成' : '判分还没完成，请稍后再试',
      )
      await reloadAttempts()
    } catch (error) {
      if (error.message.includes('判分正在进行')) {
        message.info('判分正在进行，稍后刷新看看')
        await openAttempt(id)
      } else if (error.message.includes('分数已经定了')) {
        await openAttempt(id)
      } else {
        message.error(error.message)
      }
    } finally {
      setRetrying(false)
    }
  }

  const backToList = async () => {
    setMode('list')
    setAttempt(null)
    setAnswers({})
    await reloadAttempts()
  }

  const renderInput = (question) => {
    if (question.type === 'single') {
      return (
        <Radio.Group
          value={answers[question.id] ?? ''}
          onChange={(event) =>
            setAnswers((current) => ({ ...current, [question.id]: event.target.value }))
          }
          options={(question.options ?? []).map((text, index) => ({
            value: optionLetter(index),
            label: `${optionLetter(index)}. ${text}`,
          }))}
        />
      )
    }
    if (question.type === 'multiple') {
      return (
        <Checkbox.Group
          value={answers[question.id] ?? []}
          onChange={(values) =>
            setAnswers((current) => ({ ...current, [question.id]: values }))
          }
          options={(question.options ?? []).map((text, index) => ({
            value: optionLetter(index),
            label: `${optionLetter(index)}. ${text}`,
          }))}
        />
      )
    }
    return (
      <Input
        value={answers[question.id] ?? ''}
        maxLength={500}
        placeholder="填写答案"
        onChange={(event) =>
          setAnswers((current) => ({ ...current, [question.id]: event.target.value }))
        }
      />
    )
  }

  const renderAnswer = () => (
    <Card
      title={attempt.paper_title}
      extra={<Button onClick={backToList}>返回列表</Button>}
    >
      <Alert
        type="warning"
        showIcon
        message="答案在交卷时统一提交，请不要刷新页面；刷新后已填内容不会保留。"
        style={{ marginBottom: 16 }}
      />
      <Typography.Text strong style={{ display: 'block', marginBottom: 12 }}>
        已答 {answeredCount} / {attempt.questions.length}
      </Typography.Text>
      <List
        dataSource={attempt.questions}
        renderItem={(question, index) => (
          <List.Item style={{ display: 'block' }}>
            <Typography.Paragraph strong>
              第 {index + 1} 题（{QUESTION_TYPES[question.type] ?? question.type}）
            </Typography.Paragraph>
            <Typography.Paragraph>{question.stem}</Typography.Paragraph>
            {renderInput(question)}
          </List.Item>
        )}
      />
      <Button type="primary" loading={submitting} onClick={handleSubmit}>
        交卷
      </Button>
    </Card>
  )

  const renderResult = () => {
    const graded = attempt.status === 'graded'
    const grading = attempt.status === 'submitted' && attempt.grading_in_progress
    return (
      <Card
        title={attempt.paper_title}
        extra={<Button onClick={backToList}>返回列表</Button>}
      >
        {graded ? (
          <Result
            status="success"
            title={`${scoreText(attempt.score)} 分`}
            subTitle="分数按正确题数计算，满分 100.0"
          />
        ) : (
          <Result
            status="info"
            title={grading ? '判分中' : '答案已收，判分没完成'}
            subTitle={
              grading
                ? '系统正在判分，稍后刷新查看。'
                : '答案已经保存，可以重试判分；重试不会重新收答案。'
            }
            extra={
              grading ? (
                <Button onClick={() => openAttempt(attempt.id)}>刷新</Button>
              ) : (
                <Button
                  type="primary"
                  loading={retrying}
                  onClick={() => handleRetry(attempt.id)}
                >
                  重试判分
                </Button>
              )
            }
          />
        )}

        <List
          dataSource={attempt.questions}
          renderItem={(question, index) => (
            <List.Item style={{ display: 'block' }}>
              <Flex justify="space-between" align="center">
                <Typography.Text strong>
                  第 {index + 1} 题（{QUESTION_TYPES[question.type] ?? question.type}）
                </Typography.Text>
                {graded ? (
                  <Tag color={question.is_correct ? 'green' : 'red'}>
                    {question.is_correct ? '答对' : '答错'}
                  </Tag>
                ) : null}
              </Flex>
              <Typography.Paragraph>{question.stem}</Typography.Paragraph>
              <Typography.Paragraph>
                你的答案：{question.student_answer || '未作答'}
              </Typography.Paragraph>
              {graded ? (
                <>
                  <Typography.Paragraph>
                    标准答案：{question.answer}
                  </Typography.Paragraph>
                  <Typography.Paragraph type="secondary">
                    解析：{question.explanation || '暂无解析'}
                  </Typography.Paragraph>
                </>
              ) : (
                <Typography.Text type="secondary">
                  判分完成后显示标准答案与解析。
                </Typography.Text>
              )}
            </List.Item>
          )}
        />
      </Card>
    )
  }

  const columns = [
    { title: '卷子', dataIndex: 'paper_title', ellipsis: true },
    { title: '状态', key: 'status', width: 100, render: (_, record) => statusTag(record) },
    {
      title: '分数',
      dataIndex: 'score',
      width: 80,
      align: 'center',
      render: (score) => scoreText(score),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_, record) => {
        if (record.status === 'pending') {
          return (
            <Button type="link" size="small" onClick={() => handleStart(record)}>
              开始作答
            </Button>
          )
        }
        if (record.status === 'in_progress') {
          return (
            <Button type="link" size="small" onClick={() => handleStart(record)}>
              继续作答
            </Button>
          )
        }
        if (record.status === 'submitted' && record.grading_in_progress) {
          return (
            <Button type="link" size="small" disabled>
              判分中
            </Button>
          )
        }
        if (record.status === 'submitted') {
          return (
            <Space size={4}>
              <Typography.Text type="secondary">判分没完成</Typography.Text>
              <Button
                type="link"
                size="small"
                loading={retrying}
                onClick={() => handleRetry(record.id)}
              >
                重试
              </Button>
            </Space>
          )
        }
        return (
          <Button type="link" size="small" onClick={() => openAttempt(record.id)}>
            查看结果
          </Button>
        )
      },
    },
  ]

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          考试
        </Typography.Title>
        <Space>
          <Typography.Text type="secondary">
            {user ? `${user.name}（${user.username}）` : ''}
          </Typography.Text>
          <Button onClick={logout}>退出</Button>
        </Space>
      </Flex>

      {mode === 'list' ? (
        <Card
          title="我的考试"
          extra={
            <Button loading={loading} onClick={reloadAttempts}>
              刷新
            </Button>
          }
        >
          <Table
            rowKey="id"
            size="small"
            loading={loading}
            columns={columns}
            dataSource={attempts}
            pagination={false}
            locale={{
              emptyText: <Empty description="老师发布卷子后，这里会出现待作答记录" />,
            }}
          />
        </Card>
      ) : mode === 'answer' ? (
        renderAnswer()
      ) : (
        renderResult()
      )}

      <Modal
        title="确定交白卷吗？"
        open={blankConfirm}
        okText="交白卷"
        okButtonProps={{ danger: true }}
        cancelText="再检查一下"
        confirmLoading={submitting}
        onOk={async () => {
          await doSubmit()
          setBlankConfirm(false)
        }}
        onCancel={() => setBlankConfirm(false)}
      >
        交卷后不能修改，确定一道题都不答就交卷吗？
      </Modal>
    </div>
  )
}
