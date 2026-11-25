import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Row,
  Spin,
  Table,
  Typography,
} from 'antd'
import { useNavigate } from 'react-router'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getMyReport, getStudentReport } from '../../api.js'
import { formatPercent, timeText } from '../../format.js'

const weakColumns = [
  { title: '知识点', dataIndex: 'name', ellipsis: true },
  { title: '作答数', dataIndex: 'answered_count', align: 'center', width: 90 },
  { title: '错题数', dataIndex: 'wrong_count', align: 'center', width: 90 },
  {
    title: '错误率',
    dataIndex: 'error_rate',
    align: 'center',
    width: 100,
    render: (value) => formatPercent(value),
  },
]

function MasteryCard({ mastery }) {
  return (
    <Card size="small" title="掌握度">
      {mastery?.has_data ? (
        <Typography.Title level={2} style={{ margin: 0 }}>
          {formatPercent(mastery.value)}
        </Typography.Title>
      ) : (
        <Typography.Title level={4} type="secondary" style={{ margin: 0 }}>
          暂无可统计
        </Typography.Title>
      )}
      <Typography.Text type="secondary">
        相对指数，只用于比较同一学生的不同知识点
      </Typography.Text>
    </Card>
  )
}

function DueCard({ count, showAction, onReview }) {
  return (
    <Card size="small" title="待复习">
      <Typography.Title level={2} style={{ margin: 0 }}>
        {count} 题
      </Typography.Title>
      {showAction ? (
        <Button type="link" size="small" style={{ paddingLeft: 0 }} onClick={onReview}>
          去复习
        </Button>
      ) : (
        <Typography.Text type="secondary">今天及以前到期</Typography.Text>
      )}
    </Card>
  )
}

function ScoreChart({ scores }) {
  const data = scores.map((item) => ({
    name: item.paper_title,
    score: item.score === null || item.score === undefined ? null : Number(item.score),
  }))
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 64, bottom: 8, left: 56 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
        <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
        <Tooltip formatter={(value) => [`${Number(value).toFixed(1)} 分`, '分数']} />
        <Line
          type="monotone"
          dataKey="score"
          stroke="#1677ff"
          strokeWidth={2}
          dot={{ r: 3 }}
          connectNulls={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function ReportView({ studentId, teacherView = false }) {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const report = studentId ? await getStudentReport(studentId) : await getMyReport()
        if (!cancelled) setData(report)
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
  }, [studentId, reloadKey])

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
        message="报告加载失败"
        description="请稍后重试"
        action={
          <Button size="small" onClick={() => setReloadKey((key) => key + 1)}>
            重试
          </Button>
        }
      />
    )
  }

  if (!data?.has_data) {
    return (
      <Empty description={teacherView ? '这名学生还没有学习记录' : '还没有学习记录'}>
        {!teacherView && (
          <Button type="primary" onClick={() => navigate('/student/exams')}>
            去做几道题
          </Button>
        )}
      </Empty>
    )
  }

  const lastScore = data.recent_scores[data.recent_scores.length - 1]

  return (
    <Flex vertical gap={16}>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <MasteryCard mastery={data.mastery} />
        </Col>
        <Col xs={24} md={12}>
          <DueCard
            count={data.review_due_count}
            showAction={!teacherView}
            onReview={() => navigate('/student/review')}
          />
        </Col>
      </Row>

      <Card title="弱项前三">
        {data.items.length === 0 ? (
          <Empty description="暂无可统计的弱项">
            {!teacherView && (
              <Button type="primary" onClick={() => navigate('/student/practice')}>
                去练几道题
              </Button>
            )}
          </Empty>
        ) : (
          <Table
            rowKey="knowledge_point_id"
            size="small"
            pagination={false}
            columns={weakColumns}
            dataSource={data.items}
          />
        )}
      </Card>

      <Card title="最近五次分数">
        {data.recent_scores.length === 0 ? (
          <Empty
            description={teacherView ? '这名学生还没有已判分的考试' : '还没有已判分的考试'}
          >
            {!teacherView && (
              <Button type="primary" onClick={() => navigate('/student/exams')}>
                去考试
              </Button>
            )}
          </Empty>
        ) : (
          <>
            <ScoreChart scores={data.recent_scores} />
            <Typography.Text type="secondary">
              最近一次：{lastScore.paper_title}
              {' · '}
              {lastScore.score === null || lastScore.score === undefined
                ? '—'
                : Number(lastScore.score).toFixed(1)}{' '}
              分
              {' · '}
              {timeText(lastScore.graded_at)}
            </Typography.Text>
          </>
        )}
      </Card>
    </Flex>
  )
}
