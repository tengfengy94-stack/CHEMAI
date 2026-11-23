import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  List,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useNavigate } from 'react-router'
import {
  currentUser,
  getClassExamReport,
  getClassReport,
  getMyClasses,
  logout,
} from '../../api.js'
import { ATTEMPT_STATUS, QUESTION_TYPES } from '../../constants.js'
import { formatPercent, timeText } from '../../format.js'

const statCard = (label, value) => (
  <Col xs={12} md={6} key={label}>
    <Card size="small">
      <Typography.Text type="secondary">{label}</Typography.Text>
      <Typography.Title level={3} style={{ margin: 0 }}>
        {value}
      </Typography.Title>
    </Card>
  </Col>
)

const questionColumns = [
  { title: '题号', dataIndex: 'position', width: 70, align: 'center' },
  { title: '题干', dataIndex: 'stem', ellipsis: true },
  {
    title: '题型',
    dataIndex: 'type',
    width: 80,
    align: 'center',
    render: (value) => QUESTION_TYPES[value] ?? value,
  },
  {
    title: '正确 / 已判分',
    key: 'counts',
    width: 130,
    align: 'center',
    render: (_, row) => `${row.correct_count} / ${row.graded_count}`,
  },
  {
    title: '正确率',
    dataIndex: 'correct_rate',
    width: 100,
    align: 'center',
    render: (value) => (value === null ? '—' : formatPercent(value)),
  },
]

const knowledgeColumns = [
  { title: '知识点', dataIndex: 'name', ellipsis: true },
  { title: '作答数', dataIndex: 'answered_count', width: 100, align: 'center' },
  { title: '错题数', dataIndex: 'wrong_count', width: 100, align: 'center' },
  {
    title: '错误率',
    dataIndex: 'error_rate',
    width: 100,
    align: 'center',
    render: (value) => formatPercent(value),
  },
]

const TABLE_PAGINATION = { pageSize: 20, showSizeChanger: false, hideOnSinglePage: true }

export default function TeacherClassReport() {
  const navigate = useNavigate()
  const user = currentUser()
  const [classes, setClasses] = useState([])
  const [classesLoading, setClassesLoading] = useState(true)
  const [classId, setClassId] = useState(null)
  const [overview, setOverview] = useState(null)
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [overviewError, setOverviewError] = useState('')
  const [paperId, setPaperId] = useState(null)
  const [exam, setExam] = useState(null)
  const [examLoading, setExamLoading] = useState(false)
  const [examError, setExamError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  const [examReloadKey, setExamReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await getMyClasses()
        if (cancelled) return
        setClasses(data.items)
        setClassId((current) => current ?? data.items[0]?.id ?? null)
        if (data.items.length === 0) setOverviewLoading(false)
      } catch (err) {
        if (!cancelled) {
          setOverviewError(err.message)
          setOverviewLoading(false)
        }
      } finally {
        if (!cancelled) setClassesLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  useEffect(() => {
    if (!classId) return
    let cancelled = false
    async function load() {
      setOverviewLoading(true)
      setOverviewError('')
      setOverview(null)
      setExam(null)
      setPaperId(null)
      try {
        const data = await getClassReport(classId)
        if (cancelled) return
        setOverview(data)
        setPaperId((current) =>
          data.exams.some((item) => item.paper_id === current)
            ? current
            : data.exams[0]?.paper_id ?? null,
        )
        if (data.exams.length === 0) setExamLoading(false)
      } catch (err) {
        if (!cancelled) setOverviewError(err.message)
      } finally {
        if (!cancelled) setOverviewLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [classId, reloadKey])

  useEffect(() => {
    if (!classId || !paperId) return
    let cancelled = false
    async function load() {
      setExamLoading(true)
      setExamError('')
      setExam(null)
      try {
        const data = await getClassExamReport(classId, paperId)
        if (!cancelled) setExam(data)
      } catch (err) {
        if (!cancelled) setExamError(err.message)
      } finally {
        if (!cancelled) setExamLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [classId, paperId, reloadKey, examReloadKey])

  const retry = () => setReloadKey((key) => key + 1)
  const retryExam = () => setExamReloadKey((key) => key + 1)

  const renderExam = () => {
    if (examLoading) {
      return (
        <Flex justify="center" style={{ padding: 32 }}>
          <Spin />
        </Flex>
      )
    }
    if (examError) {
      return (
        <Alert
          type="error"
          showIcon
          message="这次考试加载失败"
          description="请稍后重试"
          action={
            <Button size="small" onClick={retryExam}>
              重试
            </Button>
          }
        />
      )
    }
    if (!exam) return null
    return (
      <>
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          {statCard('名单人数', exam.submission.total)}
          {statCard('已交卷', exam.submission.submitted)}
          {statCard('作答中', exam.submission.in_progress)}
          {statCard('还没开始', exam.submission.pending)}
        </Row>
        <Table
          rowKey="question_id"
          size="small"
          pagination={TABLE_PAGINATION}
          columns={questionColumns}
          dataSource={exam.questions}
          locale={{ emptyText: <Empty description="这份卷子里还没有题" /> }}
        />
        <Card size="small" title="未交名单" style={{ marginTop: 16 }}>
          {exam.unsubmitted.length === 0 ? (
            <Empty description="都交了" />
          ) : (
            <List
              size="small"
              pagination={{ pageSize: 20, hideOnSinglePage: true }}
              dataSource={exam.unsubmitted}
              renderItem={(item) => (
                <List.Item>
                  <Space>
                    <Typography.Text>{item.student_name}</Typography.Text>
                    <Tag color={ATTEMPT_STATUS[item.status]?.color}>
                      {ATTEMPT_STATUS[item.status]?.label ?? item.status}
                    </Tag>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Card>
      </>
    )
  }

  const renderContent = () => {
    if (classesLoading) {
      return (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      )
    }
    if (classes.length === 0 && !overviewError) {
      return <Empty description="还没有带班（班级由管理员分配）" />
    }
    if (overviewLoading) {
      return (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      )
    }
    if (overviewError) {
      return (
        <Alert
          type="error"
          showIcon
          message="班级报告加载失败"
          description="请稍后重试"
          action={
            <Button size="small" onClick={retry}>
              重试
            </Button>
          }
        />
      )
    }
    if (overview && overview.exams.length === 0) {
      return (
        <Empty description="还没有考试记录">
          <Button type="primary" onClick={() => navigate('/teacher/exams')}>
            去组卷发布
          </Button>
        </Empty>
      )
    }
    return (
      <>
        <Card
          title="按考试"
          extra={
            <Select
              style={{ minWidth: 360 }}
              value={paperId ?? undefined}
              onChange={setPaperId}
              options={overview.exams.map((item) => ({
                value: item.paper_id,
                label: `${item.paper_title}（${timeText(item.published_at)} · ${item.question_count} 题 · ${item.student_count} 人）`,
              }))}
            />
          }
          style={{ marginBottom: 16 }}
        >
          {renderExam()}
        </Card>

        <Card
          title="按知识点"
          extra={<Typography.Text type="secondary">考试数据，不含练习</Typography.Text>}
          style={{ marginBottom: 16 }}
        >
          {overview.knowledge_points.length === 0 ? (
            <Empty description="暂无可统计的知识点">
              <Button type="primary" onClick={() => navigate('/teacher/exams')}>
                去组卷发布
              </Button>
            </Empty>
          ) : (
            <Table
              rowKey="knowledge_point_id"
              size="small"
              pagination={TABLE_PAGINATION}
              columns={knowledgeColumns}
              dataSource={overview.knowledge_points}
            />
          )}
        </Card>

        <Card title="学生">
          {overview.students.length === 0 ? (
            <Empty description="班里还没有学生（学生名单由管理员导入）" />
          ) : (
            <Table
              rowKey="student_id"
              size="small"
              pagination={TABLE_PAGINATION}
              columns={[
                { title: '姓名', dataIndex: 'student_name', ellipsis: true },
                {
                  title: '最近一次分数',
                  dataIndex: 'latest_score',
                  width: 140,
                  align: 'center',
                  render: (value, row) => {
                    if (value === null || value === undefined) {
                      return row.grading_pending ? '判分中' : '未作答'
                    }
                    return Number(value).toFixed(1)
                  },
                },
                { title: '错题数', dataIndex: 'wrong_count', width: 100, align: 'center' },
                {
                  title: '状态',
                  key: 'status',
                  width: 100,
                  align: 'center',
                  render: (_, row) =>
                    row.is_current_member ? null : <Tag>已转出</Tag>,
                },
                {
                  title: '操作',
                  key: 'action',
                  width: 110,
                  render: (_, row) =>
                    row.can_view_report ? (
                      <Button
                        type="link"
                        size="small"
                        onClick={() =>
                          navigate(`/teacher/students/${row.student_id}/report`, {
                            state: { studentName: row.student_name },
                          })
                        }
                      >
                        查看报告
                      </Button>
                    ) : (
                      <Typography.Text type="secondary">—</Typography.Text>
                    ),
                },
              ]}
              dataSource={overview.students}
            />
          )}
        </Card>
      </>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          班级报告
        </Typography.Title>
        <Space>
          <Typography.Text type="secondary">{user?.name}</Typography.Text>
          <Button onClick={() => navigate('/teacher/questions')}>题库</Button>
          <Button onClick={() => navigate('/teacher/exams')}>组卷</Button>
          <Button onClick={() => navigate('/teacher/knowledge')}>知识点</Button>
          <Button onClick={logout}>退出</Button>
        </Space>
      </Flex>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Typography.Text>班级</Typography.Text>
          <Select
            style={{ minWidth: 240 }}
            value={classId ?? undefined}
            onChange={setClassId}
            placeholder="选择班级"
            options={classes.map((item) => ({
              value: item.id,
              label: `${item.name}（${item.student_count} 人）`,
            }))}
          />
          {overview ? (
            <Typography.Text type="secondary">
              共考过 {overview.exam_count} 次
            </Typography.Text>
          ) : null}
        </Space>
      </Card>

      {renderContent()}
    </div>
  )
}
