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
  Select,
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

export default function StudentReview() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [tab, setTab] = useState('due')
  const [due, setDue] = useState([])
  const [wrong, setWrong] = useState([])
  const [loading, setLoading] = useState(true)
  const [dueError, setDueError] = useState('')
  const [wrongError, setWrongError] = useState('')
  const [queueOnly, setQueueOnly] = useState(false)
  const [sourceFilter, setSourceFilter] = useState('all')
  const [duePage, setDuePage] = useState(1)
  const [duePageSize, setDuePageSize] = useState(20)
  const [dueTotal, setDueTotal] = useState(0)
  const [wrongPage, setWrongPage] = useState(1)
  const [wrongPageSize, setWrongPageSize] = useState(20)
  const [wrongTotal, setWrongTotal] = useState(0)
  const [activeTask, setActiveTask] = useState(null)
  const [answer, setAnswer] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)

  const loadDue = useCallback(
    async (page = duePage) => {
      try {
        const data = await listReviewTasks('due', {
          page,
          pageSize: duePageSize,
        })
        setDue(data.items)
        setDueTotal(data.total)
        setDuePageSize(data.page_size)
        setDuePage(page)
        setDueError('')
      } catch (err) {
        setDueError(err.message)
      } finally {
        setLoading(false)
      }
    },
    [duePage, duePageSize],
  )

  const loadWrong = useCallback(
    async (page = wrongPage) => {
      try {
        const data = await listWrongQuestions({
          source: sourceFilter === 'all' ? undefined : sourceFilter,
          inQueue: queueOnly || undefined,
          page,
          pageSize: wrongPageSize,
        })
        setWrong(data.items)
        setWrongTotal(data.total)
        setWrongPageSize(data.page_size)
        setWrongPage(page)
        setWrongError('')
      } catch (err) {
        setWrongError(err.message)
      } finally {
        setLoading(false)
      }
    },
    [sourceFilter, queueOnly, wrongPage, wrongPageSize],
  )

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (tab === 'due') {
        try {
          const data = await listReviewTasks('due', {
            page: duePage,
            pageSize: duePageSize,
          })
          if (!cancelled) {
            setDue(data.items)
            setDueTotal(data.total)
            setDuePageSize(data.page_size)
            setDueError('')
          }
        } catch (err) {
          if (!cancelled) setDueError(err.message)
        }
      } else {
        try {
          const data = await listWrongQuestions({
            source: sourceFilter === 'all' ? undefined : sourceFilter,
            inQueue: queueOnly || undefined,
            page: wrongPage,
            pageSize: wrongPageSize,
          })
          if (!cancelled) {
            setWrong(data.items)
            setWrongTotal(data.total)
            setWrongPageSize(data.page_size)
            setWrongError('')
          }
        } catch (err) {
          if (!cancelled) setWrongError(err.message)
        }
      }
      if (!cancelled) setLoading(false)
    }
    load()
    return () => {
      cancelled = true
    }
  }, [tab, sourceFilter, queueOnly, duePage, duePageSize, wrongPage, wrongPageSize])

  useEffect(() => {
    if (!loading && tab === 'due' && due.length === 0 && dueTotal > 0 && duePage > 1) {
      setDuePage(duePage - 1)
    }
  }, [loading, tab, due.length, dueTotal, duePage])

  useEffect(() => {
    if (
      !loading &&
      tab === 'wrong' &&
      wrong.length === 0 &&
      wrongTotal > 0 &&
      wrongPage > 1
    ) {
      setWrongPage(wrongPage - 1)
    }
  }, [loading, tab, wrong.length, wrongTotal, wrongPage])

  const switchTab = (next) => {
    setLoading(true)
    setDueError('')
    setWrongError('')
    setDuePage(1)
    setWrongPage(1)
    setTab(next)
  }

  const retry = () => {
    setLoading(true)
    setDueError('')
    setWrongError('')
    if (tab === 'due') loadDue()
    else loadWrong()
  }

  const openTask = (task) => {
    if (!task?.question) return
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
        pagination={{
          current: duePage,
          pageSize: duePageSize,
          total: dueTotal,
          showSizeChanger: false,
          onChange: (page) => {
            setLoading(true)
            setDuePage(page)
          },
        }}
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
    const visible = wrong
    return (
      <>
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            value={sourceFilter}
            onChange={(value) => {
              setLoading(true)
              setWrongPage(1)
              setSourceFilter(value)
            }}
            style={{ width: 140 }}
            options={[
              { value: 'all', label: '全部来源' },
              { value: 'exam', label: '考试' },
              { value: 'practice', label: '练习' },
              { value: 'review', label: '复习' },
            ]}
          />
          <Checkbox
            checked={queueOnly}
            onChange={(event) => {
              setLoading(true)
              setWrongPage(1)
              setQueueOnly(event.target.checked)
            }}
          >
            只看还在复习队列里的
          </Checkbox>
        </Space>
        {visible.length === 0 ? (
          <Empty
            description={
              queueOnly ? '复习队列里没有错题' : '还没有错题，继续保持'
            }
          />
        ) : (
          <List
            dataSource={visible}
            pagination={{
              current: wrongPage,
              pageSize: wrongPageSize,
              total: wrongTotal,
              showSizeChanger: false,
              onChange: (page) => {
                setLoading(true)
                setWrongPage(page)
              },
            }}
            renderItem={(item) => {
              const task = item.task
              return (
                <List.Item style={{ display: 'block' }}>
                  <Flex justify="space-between" align="flex-start" gap={12}>
                    <Typography.Paragraph strong style={{ marginBottom: 8 }}>
                      {item.stem}
                    </Typography.Paragraph>
                    <Space>
                      <Tag>{QUESTION_TYPES[item.type] ?? item.type}</Tag>
                      {task?.in_queue ? (
                        <Button
                          type="link"
                          size="small"
                          onClick={() =>
                            openTask({
                              ...task,
                              question: {
                                id: item.question_id,
                                stem: item.stem,
                                type: item.type,
                                options: item.options,
                              },
                            })
                          }
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
                    来源：{WRONG_SOURCE_LABELS[item.source] ?? item.source}
                    {item.paper_title ? ` · ${item.paper_title}` : ''} · 最近答错{' '}
                    {timeText(item.last_wrong_at)}
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
