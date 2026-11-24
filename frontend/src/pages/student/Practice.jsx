import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Checkbox,
  Empty,
  Flex,
  Input,
  Radio,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { answerPracticeQuestion, getNextPracticeQuestion, getPracticePlan } from '../../api.js'
import { DIFFICULTIES, QUESTION_TYPES } from '../../constants.js'
import { optionLetter } from '../../format.js'
import StudentHeader from './StudentHeader.jsx'

function DifficultyIndicator({ current }) {
  return (
    <Space size={8} align="center" style={{ marginBottom: 16 }}>
      <Typography.Text type="secondary">当前难度</Typography.Text>
      {DIFFICULTIES.map((level) => {
        const active = level === current
        return (
          <div
            key={level}
            style={{
              padding: '2px 14px',
              border: `1px solid ${active ? 'rgba(0, 0, 0, 0.85)' : '#d9d9d9'}`,
              borderRadius: 6,
              color: active ? 'rgba(0, 0, 0, 0.88)' : 'rgba(0, 0, 0, 0.45)',
              fontWeight: active ? 600 : 400,
              background: '#fff',
            }}
          >
            {level} 档
          </div>
        )
      })}
    </Space>
  )
}

export default function StudentPractice() {
  const navigate = useNavigate()
  const location = useLocation()
  const { message: toast } = AntApp.useApp()
  const planIds = useMemo(() => {
    const raw = new URLSearchParams(location.search).get('plan')
    if (!raw) return []
    return raw
      .split(',')
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value > 0)
      .slice(0, 20)
  }, [location.search])
  const [data, setData] = useState(null)
  const [answer, setAnswer] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [plan, setPlan] = useState(null)

  const applyNext = useCallback((next) => {
    setData(next)
    setAnswer(next.question?.type === 'multiple' ? [] : '')
  }, [])

  const applyPlanItem = useCallback(
    (items, index) => {
      const question = items[index]
      applyNext({
        status: 'question',
        reason: null,
        message: null,
        has_weak_data: false,
        current_difficulty: question.difficulty,
        served_difficulty: question.difficulty,
        question,
        knowledge_point: null,
      })
    },
    [applyNext],
  )

  const loadNext = useCallback(async () => {
    setError('')
    setFeedback(null)
    if (plan) {
      const nextIndex = plan.index + 1
      if (nextIndex < plan.items.length) {
        setPlan({ ...plan, index: nextIndex })
        applyPlanItem(plan.items, nextIndex)
        return
      }
      setPlan(null)
      setData({
        status: 'empty',
        reason: 'plan_done',
        message: '这组题做完了',
      })
      return
    }
    setLoading(true)
    try {
      const next = await getNextPracticeQuestion()
      applyNext(next)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [applyNext, applyPlanItem, plan])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        if (planIds.length) {
          const result = await getPracticePlan(planIds)
          if (cancelled) return
          if (!result.items?.length) {
            setData({
              status: 'empty',
              reason: 'plan_empty',
              message: '这组题暂时不可用',
            })
          } else {
            setPlan({ items: result.items, index: 0 })
            applyPlanItem(result.items, 0)
          }
        } else {
          const next = await getNextPracticeQuestion()
          if (!cancelled) applyNext(next)
        }
        if (!cancelled) setError('')
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [applyNext, applyPlanItem, planIds])

  const submit = async () => {
    if (!data?.question) return
    const submitted = Array.isArray(answer) ? answer.join('') : answer
    setSubmitting(true)
    try {
      const result = await answerPracticeQuestion(
        data.question.id,
        submitted,
        data.served_difficulty,
      )
      setFeedback(result)
    } catch {
      // 提交失败保留已填答案，不显示原始报错
      toast.error('提交失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  const renderInput = (question) => {
    if (question.type === 'single') {
      return (
        <Radio.Group
          value={answer}
          disabled={submitting}
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
          disabled={submitting}
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
        disabled={submitting}
        maxLength={500}
        placeholder="填写答案"
        onChange={(event) => setAnswer(event.target.value)}
        onPressEnter={submit}
      />
    )
  }

  const renderQuestion = () => {
    const question = data.question
    return (
      <>
        {data.has_weak_data === false && data.message && (
          <Alert
            type="info"
            showIcon
            title={data.message}
            style={{ marginBottom: 16 }}
          />
        )}
        <Card
          title="练习题"
          extra={<Tag>{QUESTION_TYPES[question.type]}</Tag>}
        >
          <Typography.Paragraph style={{ fontSize: 16, whiteSpace: 'pre-wrap' }}>
            {question.stem}
          </Typography.Paragraph>
          <div style={{ marginBottom: 20 }}>{renderInput(question)}</div>
          <Button
            type="primary"
            onClick={submit}
            loading={submitting}
            disabled={submitting}
          >
            提交答案
          </Button>
        </Card>
      </>
    )
  }

  const renderFeedback = () => (
    <Card
      title="练习结果"
      extra={
        <Button type="primary" onClick={loadNext}>
          下一题
        </Button>
      }
    >
      <Alert
        type={feedback.is_correct ? 'success' : 'error'}
        showIcon
        title={feedback.is_correct ? '答对了' : '答错了'}
        style={{ marginBottom: 16 }}
      />
      <Typography.Paragraph>
        你的答案：{feedback.student_answer || '未作答'}
      </Typography.Paragraph>
      <Typography.Paragraph>标准答案：{feedback.answer}</Typography.Paragraph>
      {feedback.explanation && (
        <Typography.Paragraph>解析：{feedback.explanation}</Typography.Paragraph>
      )}
      <Typography.Text type="secondary">
        本题难度：{feedback.served_difficulty} 档 · 下一题难度：
        {feedback.next_difficulty} 档
      </Typography.Text>
    </Card>
  )

  const renderContent = () => {
    if (loading) {
      return (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      )
    }
    if (error) {
      return (
        <Alert
          type="error"
          showIcon
          title="练习加载失败"
          description="请稍后重试"
          action={
            <Button size="small" onClick={loadNext}>
              重试
            </Button>
          }
        />
      )
    }
    if (!data) return null
    if (data.status === 'empty') {
      return (
        <Empty description={data.message || '暂时没有可练习的题'}>
          <Button onClick={loadNext}>重新加载</Button>
        </Empty>
      )
    }
    if (feedback) return renderFeedback()
    return renderQuestion()
  }

  const currentDifficulty = feedback
    ? feedback.next_difficulty
    : data?.current_difficulty

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <StudentHeader title="练习" />
      <Flex justify="flex-end" style={{ marginBottom: 8 }}>
        <Button onClick={() => navigate('/student/chat?scene=practice')}>
          问一句
        </Button>
      </Flex>
      {!loading && !error && data && (
        <DifficultyIndicator current={currentDifficulty} />
      )}
      {renderContent()}
    </div>
  )
}
