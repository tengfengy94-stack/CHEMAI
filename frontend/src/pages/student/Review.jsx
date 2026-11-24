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
  Radio,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useNavigate } from 'react-router'
import { answerReviewTask, listReviewTasks, listWrongQuestions } from '../../api.js'
import { QUESTION_TYPES, WRONG_SOURCE_LABELS } from '../../constants.js'
import { dueLabel, optionLetter, timeText } from '../../format.js'
import StudentHeader from './StudentHeader.jsx'

const tasksByQuestion = (items) => new Map(items.map((task) => [task.question_id, task]))

export default function StudentReview() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [tab, setTab] = useState('due')
  const [due, setDue] = useState([])
  const [wrong, setWrong] = useState([])
  const [taskMap, setTaskMap] = useState(new Map())
  const [loading, setLoading] = useState(true)
  const [dueError, setDueError] = useState('')
  const [wrongError, setWrongError] = useState('')
  const [taskError, setTaskError] = useState('')
  const [queueOnly, setQueueOnly] = useState(false)
  const [activeTask, setActiveTask] = useState(null)
  const [answer, setAnswer] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)

  const loadDue = useCallback(async () => {
    try {
      const data = await listReviewTasks('due')
      setDue(data.items)
      setDueError('')
    } catch (err) {
      setDueError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadWrong = useCallback(async () => {
    const [wrongResult, taskResult] = await Promise.allSettled([
      listWrongQuestions(),
      listReviewTasks('all'),
    ])
    if (wrongResult.status === 'fulfilled') {
      setWrong(wrongResult.value.items)
      setWrongError('')
    } else {
      setWrongError(wrongResult.reason.message)
    }
    if (taskResult.status === 'fulfilled') {
      setTaskMap(tasksByQuestion(taskResult.value.items))
      setTaskError('')
    } else {
      setTaskError(taskResult.reason.message)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (tab === 'due') {
        try {
          const data = await listReviewTasks('due')
          if (!cancelled) {
            setDue(data.items)
            setDueError('')
          }
        } catch (err) {
          if (!cancelled) setDueError(err.message)
        }
      } else {
        const [wrongResult, taskResult] = await Promise.allSettled([
          listWrongQuestions(),
          listReviewTasks('all'),
        ])
        if (!cancelled) {
          if (wrongResult.status === 'fulfilled') {
            setWrong(wrongResult.value.items)
            setWrongError('')
          } else {
            setWrongError(wrongResult.reason.message)
          }
          if (taskResult.status === 'fulfilled') {
            setTaskMap(tasksByQuestion(taskResult.value.items))
            setTaskError('')
          } else {
            setTaskError(taskResult.reason.message)
          }
        }
      }
      if (!cancelled) setLoading(false)
    }
    load()
    return () => {
      cancelled = true
    }
  }, [tab])

  const switchTab = (next) => {
    setLoading(true)
    setDueError('')
    setWrongError('')
    setTaskError('')
    setTab(next)
  }

  const retry = () => {
    setLoading(true)
    setDueError('')
    setWrongError('')
    setTaskError('')
    if (tab === 'due') loadDue()
    else loadWrong()
  }

  const retryTasks = async () => {
    setTaskError('')
    try {
      const data = await listReviewTasks('all')
      setTaskMap(tasksByQuestion(data.items))
    } catch (err) {
      setTaskError(err.message)
    }
  }

  const openTask = (task) => {
    setActiveTask(task)
    setResult(null)
    setAnswer(task.question.type === 'multiple' ? [] : '')
  }

  const backToList = async () => {
    setActiveTask(null)
    setResult(null)
    setAnswer('')
    setLoading(true)
    if (tab === 'due') await loadDue()
    else await loadWrong()
  }

  const submit = async () => {
    const submitted = Array.isArray(answer) ? answer.join('') : answer
    setSubmitting(true)
    try {
      const data = await answerReviewTask(activeTask.id, submitted)
      setResult(data)
      if (tab === 'due') await loadDue()
      else await loadWrong()
    } catch (err) {
      message.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const renderInput = (question) => {
    if (question.type === 'single') {
      return (
        <Radio.Group
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
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
          value={answer}
          onChange={setAnswer}
          options={(question.options ?? []).map((text, index) => ({
            value: optionLetter(index),
            label: `${optionLetter(index)}. ${text}`,
          }))}
        />
      )
    }
    return (
      <Input
        value={answer}
        maxLength={500}
        placeholder="填写答案"
        onChange={(event) => setAnswer(event.target.value)}
        onPressEnter={submit}
      />
    )
  }

  const renderResult = () => (
    <Card title="复习结果" extra={<Button onClick={backToList}>返回列表</Button>}>
      <Alert
        type={result.is_correct ? 'success' : 'error'}
        showIcon
        message={result.is_correct ? '答对了' : '答错了，回到第 0 级'}
        style={{ marginBottom: 16 }}
      />
      <Typography.Paragraph>
        你的答案：{result.student_answer || '未作答'}
      </Typography.Paragraph>
      <Typography.Paragraph>标准答案：{result.answer}</Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        解析：{result.explanation || '暂无解析'}
      </Typography.Paragraph>
      <Typography.Paragraph>
        上次答案：{result.previous_answer ?? '第一次复习，没有上次答案'}
      </Typography.Paragraph>
      <Typography.Text type="secondary">
        当前级别：第 {result.level} 级 ·{' '}
        {result.in_queue ? `下次到期 ${dueLabel(result.due_on)}` : '已出队'}
      </Typography.Text>
    </Card>
  )

  const renderAnswer = () => {
    if (result) return renderResult()
    const question = activeTask.question
    return (
      <Card title="复习一题" extra={<Button onClick={backToList}>返回列表</Button>}>
        <Typography.Paragraph strong>
          {QUESTION_TYPES[question.type] ?? question.type}
        </Typography.Paragraph>
        <Typography.Paragraph>{question.stem}</Typography.Paragraph>
        {renderInput(question)}
        <div style={{ marginTop: 16 }}>
          <Button type="primary" loading={submitting} onClick={submit}>
            提交答案
          </Button>
        </div>
      </Card>
    )
  }

  const renderOptions = (options) => {
    if ((options ?? []).length === 0) return null
    return (
      <div style={{ marginBottom: 8 }}>
        {options.map((text, index) => (
          <Typography.Paragraph key={index} style={{ marginBottom: 2 }}>
            {optionLetter(index)}. {text}
          </Typography.Paragraph>
        ))}
      </div>
    )
  }

  const renderDue = () => {
    if (loading) {
      return (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      )
    }
    if (dueError) {
      return (
        <Alert
          type="error"
          showIcon
          message="复习列表加载失败"
          description={dueError}
          action={
            <Button size="small" onClick={retry}>
              重试
            </Button>
          }
        />
      )
    }
    if (due.length === 0) {
      return (
        <Empty description="今天没有要复习的">
          <Button type="primary" onClick={() => navigate('/student/exams')}>
            去做几道题
          </Button>
        </Empty>
      )
    }
    return (
      <List
        dataSource={due}
        renderItem={(item) => (
          <List.Item
            style={{ display: 'block' }}
            actions={[
              <Button type="link" key="start" onClick={() => openTask(item)}>
                开始复习
              </Button>,
            ]}
          >
            <Flex justify="space-between" align="flex-start" gap={12}>
              <Typography.Paragraph strong style={{ marginBottom: 8 }}>
                {item.question.stem}
              </Typography.Paragraph>
              <Tag>{QUESTION_TYPES[item.question.type] ?? item.question.type}</Tag>
            </Flex>
            {renderOptions(item.question.options)}
            <Typography.Text type="secondary">
              第 {item.level} 级 · 到期 {dueLabel(item.due_on)} · 已复习{' '}
              {item.review_count} 次
            </Typography.Text>
          </List.Item>
        )}
      />
    )
  }

  const renderWrong = () => {
    if (loading) {
      return (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      )
    }
    if (wrongError) {
      return (
        <Alert
          type="error"
          showIcon
          message="错题加载失败"
          description={wrongError}
          action={
            <Button size="small" onClick={retry}>
              重试
            </Button>
          }
        />
      )
    }
    const visible =
      queueOnly && !taskError ? wrong.filter((item) => item.task?.in_queue) : wrong
    return (
      <>
        {taskError ? (
          <Alert
            type="warning"
            showIcon
            message="队列状态加载失败，错题列表仍可查看"
            description={taskError}
            style={{ marginBottom: 12 }}
            action={
              <Button size="small" onClick={retryTasks}>
                重试
              </Button>
            }
          />
        ) : null}
        <Checkbox
          checked={queueOnly && !taskError}
          disabled={Boolean(taskError)}
          onChange={(event) => setQueueOnly(event.target.checked)}
          style={{ marginBottom: 12 }}
        >
          只看还在复习队列里的
        </Checkbox>
        {visible.length === 0 ? (
          <Empty
            description={
              queueOnly && !taskError ? '复习队列里没有错题' : '还没有错题，继续保持'
            }
          />
        ) : (
          <List
            dataSource={visible}
            renderItem={(item) => {
              const task = taskMap.get(item.question_id)
              return (
                <List.Item style={{ display: 'block' }}>
                  <Flex justify="space-between" align="flex-start" gap={12}>
                    <Typography.Paragraph strong style={{ marginBottom: 8 }}>
                      {item.stem}
                    </Typography.Paragraph>
                    <Space>
                      <Tag>{QUESTION_TYPES[item.type] ?? item.type}</Tag>
                      {taskError ? (
                        <Tag>队列状态未知</Tag>
                      ) : task?.in_queue ? (
                        <Button
                          type="link"
                          size="small"
                          onClick={() => openTask(task)}
                        >
                          去复习
                        </Button>
                      ) : task ? (
                        <Tag>已出队</Tag>
                      ) : (
                        <Tag>未在复习队列</Tag>
                      )}
                    </Space>
                  </Flex>
                  {renderOptions(item.options)}
                  <Typography.Paragraph style={{ marginBottom: 4 }}>
                    你的答案：{item.student_answer || '未作答'}
                  </Typography.Paragraph>
                  <Typography.Paragraph style={{ marginBottom: 4 }}>
                    标准答案：{item.answer}
                  </Typography.Paragraph>
                  <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>
                    解析：{item.explanation || '暂无解析'}
                  </Typography.Paragraph>
                  <Typography.Text type="secondary">
                    来源：{WRONG_SOURCE_LABELS[item.source] ?? item.source} ·{' '}
                    {item.paper_title} · 最近答错 {timeText(item.last_wrong_at)}
                  </Typography.Text>
                </List.Item>
              )
            }}
          />
        )}
      </>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <StudentHeader title="复习" />
      <Flex justify="flex-end" style={{ marginBottom: 8 }}>
        <Button onClick={() => navigate('/student/chat?scene=wrong')}>
          问一句
        </Button>
      </Flex>

      {activeTask ? (
        renderAnswer()
      ) : (
        <Tabs
          activeKey={tab}
          onChange={switchTab}
          items={[
            { key: 'due', label: '今日到期', children: renderDue() },
            { key: 'wrong', label: '全部错题', children: renderWrong() },
          ]}
        />
      )}
    </div>
  )
}
