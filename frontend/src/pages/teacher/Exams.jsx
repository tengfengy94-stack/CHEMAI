import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Empty,
  Flex,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  addPaperQuestion,
  createPaper,
  currentUser,
  getPaper,
  listClasses,
  listPapers,
  listQuestionPool,
  logout,
  publishPaper,
  removePaperQuestion,
} from '../../api.js'
import { DIFFICULTIES, PAPER_STATUS, QUESTION_TYPES } from '../../constants.js'

const statusTag = (status) => {
  const info = PAPER_STATUS[status]
  return info ? <Tag color={info.color}>{info.label}</Tag> : status
}

const questionMeta = (question, withPosition = false) => (
  <Space size={4} wrap>
    {withPosition && question.position ? (
      <Typography.Text type="secondary">第 {question.position} 题</Typography.Text>
    ) : null}
    <Tag>{QUESTION_TYPES[question.type] ?? question.type}</Tag>
    <Tag>难度 {question.difficulty}</Tag>
  </Space>
)

export default function TeacherExams() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const user = currentUser()
  const [papers, setPapers] = useState([])
  const [classes, setClasses] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [pool, setPool] = useState([])
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [poolLoading, setPoolLoading] = useState(false)
  const [filters, setFilters] = useState({ difficulty: undefined, q: '' })
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [publishTarget, setPublishTarget] = useState(null)
  const [publishClassId, setPublishClassId] = useState(undefined)
  const [publishing, setPublishing] = useState(false)
  const [form] = Form.useForm()

  const fetchPapers = useCallback(async () => {
    try {
      const data = await listPapers()
      setPapers(data.items)
    } catch (error) {
      message.error(error.message)
    } finally {
      setLoading(false)
    }
  }, [message])

  const reloadPapers = useCallback(async () => {
    setLoading(true)
    await fetchPapers()
  }, [fetchPapers])

  const reloadDetail = useCallback(
    async (paperId, quiet = false) => {
      if (!paperId) return
      if (!quiet) setDetailLoading(true)
      try {
        setDetail(await getPaper(paperId))
      } catch (error) {
        message.error(error.message)
      } finally {
        if (!quiet) setDetailLoading(false)
      }
    },
    [message],
  )

  const activeId = selectedId ?? papers[0]?.id ?? null

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await listPapers()
        if (!cancelled) setPapers(data.items)
      } catch (error) {
        if (!cancelled) message.error(error.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    listClasses()
      .then((data) => {
        if (!cancelled) setClasses(data.items)
      })
      .catch((error) => {
        if (!cancelled) message.error(error.message)
      })
    return () => {
      cancelled = true
    }
  }, [message])

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!activeId) return
      try {
        const data = await getPaper(activeId)
        if (!cancelled) setDetail(data)
      } catch (error) {
        if (!cancelled) message.error(error.message)
      } finally {
        if (!cancelled) setDetailLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [activeId, message])

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await listQuestionPool(filters)
        if (!cancelled) setPool(data.items)
      } catch (error) {
        if (!cancelled) message.error(error.message)
      } finally {
        if (!cancelled) setPoolLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [filters, message])

  const selectPaper = (paperId) => {
    if (paperId === activeId) return
    setDetail(null)
    setDetailLoading(true)
    setSelectedId(paperId)
  }

  const applyFilters = (patch) => {
    setPoolLoading(true)
    setFilters((current) => ({ ...current, ...patch }))
  }

  const handleCreate = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setCreating(true)
    try {
      const paper = await createPaper(values.title.trim())
      message.success('卷子已建好')
      setCreateOpen(false)
      form.resetFields()
      await reloadPapers()
      selectPaper(paper.id)
    } catch (error) {
      message.error(error.message)
    } finally {
      setCreating(false)
    }
  }

  const handleAdd = async (question) => {
    if (!detail || detail.status !== 'draft') return
    try {
      const data = await addPaperQuestion(detail.id, question.id)
      message[data.added ? 'success' : 'info'](
        data.added ? '已加入卷子' : '这道题已经在卷子里了',
      )
      await reloadDetail(detail.id, true)
      await reloadPapers()
    } catch (error) {
      message.error(error.message)
    }
  }

  const handleRemove = async (question) => {
    if (!detail || detail.status !== 'draft') return
    try {
      await removePaperQuestion(detail.id, question.id)
      message.success('已从卷子移除')
      await reloadDetail(detail.id, true)
      await reloadPapers()
    } catch (error) {
      message.error(error.message)
    }
  }

  const openPublish = (paper) => {
    setPublishTarget(paper)
    setPublishClassId(undefined)
  }

  const handlePublish = async () => {
    if (!publishClassId) {
      message.warning('请选择要发给的班级')
      return
    }
    setPublishing(true)
    try {
      const data = await publishPaper(publishTarget.id, publishClassId)
      message.success(`已发布：新增 ${data.created} 条，跳过 ${data.skipped} 条`)
      const targetId = publishTarget.id
      setPublishTarget(null)
      await reloadPapers()
      if (selectedId === targetId) await reloadDetail(targetId, true)
      else selectPaper(targetId)
    } catch (error) {
      message.error(error.message)
    } finally {
      setPublishing(false)
    }
  }

  const selectedIds = new Set((detail?.questions ?? []).map((question) => question.id))

  const columns = [
    { title: '卷子', dataIndex: 'title', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: statusTag,
    },
    {
      title: '题数',
      dataIndex: 'question_count',
      width: 80,
      align: 'center',
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_, record) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => selectPaper(record.id)}>
            打开
          </Button>
          {record.status === 'published' && (
            <Button type="link" size="small" onClick={() => openPublish(record)}>
              再发布
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          组卷
        </Typography.Title>
        <Space>
          <Typography.Text type="secondary">{user?.name}</Typography.Text>
          <Button onClick={() => navigate('/teacher/questions')}>题库</Button>
          <Button onClick={() => navigate('/teacher/knowledge')}>知识点</Button>
          <Button onClick={logout}>退出</Button>
        </Space>
      </Flex>

      <Card
        title="我的卷子"
        extra={
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            新建卷子
          </Button>
        }
        style={{ marginBottom: 16 }}
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={papers}
          pagination={false}
          locale={{ emptyText: <Empty description="还没有卷子，先新建一份" /> }}
        />
      </Card>

      {detailLoading ? (
        <Card>
          <Spin />
        </Card>
      ) : detail ? (
        <Card
          title={
            <Space>
              <Typography.Text strong>{detail.title}</Typography.Text>
              {statusTag(detail.status)}
            </Space>
          }
          extra={
            detail.status === 'draft' ? (
              <Button
                type="primary"
                disabled={detail.question_count === 0}
                onClick={() => openPublish(detail)}
              >
                发布
              </Button>
            ) : null
          }
        >
          {detail.status === 'draft' ? (
            <Flex gap={16} wrap align="flex-start">
              <Card
                type="inner"
                title="题目池"
                style={{ flex: 1, minWidth: 320 }}
                extra={
                  <Space wrap>
                    <Input.Search
                      allowClear
                      placeholder="搜索题干"
                      style={{ width: 180 }}
                      onSearch={(value) => applyFilters({ q: value.trim() })}
                    />
                    <Select
                      allowClear
                      placeholder="难度"
                      style={{ width: 100 }}
                      value={filters.difficulty}
                      options={DIFFICULTIES.map((difficulty) => ({
                        value: difficulty,
                        label: `难度 ${difficulty}`,
                      }))}
                      onChange={(value) => applyFilters({ difficulty: value })}
                    />
                    <Button onClick={() => applyFilters({ difficulty: undefined, q: '' })}>
                      清空
                    </Button>
                  </Space>
                }
              >
                {poolLoading ? (
                  <Spin />
                ) : (
                  <List
                    dataSource={pool}
                    locale={{
                      emptyText: <Empty description="没有可加的题（只显示已通过的题）" />,
                    }}
                    renderItem={(question) => {
                      const already = selectedIds.has(question.id)
                      return (
                        <List.Item
                          actions={[
                            <Button
                              key="add"
                              size="small"
                              type="link"
                              disabled={already}
                              onClick={() => handleAdd(question)}
                            >
                              {already ? '已加入' : '加入'}
                            </Button>,
                          ]}
                        >
                          <List.Item.Meta
                            title={
                              <Typography.Text ellipsis={{ tooltip: question.stem }}>
                                {question.stem}
                              </Typography.Text>
                            }
                            description={questionMeta(question)}
                          />
                        </List.Item>
                      )
                    }}
                  />
                )}
              </Card>

              <Card
                type="inner"
                title={`已选 ${detail.question_count} 道`}
                style={{ flex: 1, minWidth: 320 }}
              >
                <List
                  dataSource={detail.questions}
                  locale={{
                    emptyText: <Empty description="卷子里还没有题，从左边加入" />,
                  }}
                  renderItem={(question) => (
                    <List.Item
                      actions={[
                        <Button
                          key="remove"
                          size="small"
                          type="link"
                          danger
                          onClick={() => handleRemove(question)}
                        >
                          移除
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Typography.Text ellipsis={{ tooltip: question.stem }}>
                            {question.stem}
                          </Typography.Text>
                        }
                        description={questionMeta(question, true)}
                      />
                    </List.Item>
                  )}
                />
              </Card>
            </Flex>
          ) : (
            <List
              dataSource={detail.questions}
              renderItem={(question) => (
                <List.Item>
                  <List.Item.Meta
                    title={
                      <Typography.Text ellipsis={{ tooltip: question.stem }}>
                        {question.stem}
                      </Typography.Text>
                    }
                    description={questionMeta(question, true)}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      ) : (
        <Card>
          <Empty description="从上面选一份卷子" />
        </Card>
      )}

      <Modal
        title="新建卷子"
        open={createOpen}
        okText="建好"
        cancelText="取消"
        confirmLoading={creating}
        onOk={handleCreate}
        onCancel={() => {
          setCreateOpen(false)
          form.resetFields()
        }}
      >
        <Form form={form} layout="vertical" initialValues={{ title: '' }}>
          <Form.Item
            label="卷子名称"
            name="title"
            rules={[{ required: true, whitespace: true, message: '请填写卷子名称' }]}
            extra="名称建好后不能改"
          >
            <Input placeholder="例如：周五周测" maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`发布「${publishTarget?.title ?? ''}」`}
        open={Boolean(publishTarget)}
        okText="确认发布"
        cancelText="取消"
        confirmLoading={publishing}
        onOk={handlePublish}
        onCancel={() => setPublishTarget(null)}
      >
        {classes.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="还没有班级"
            description="先在班级里加学生，再回来发布。"
          />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Typography.Text>选择要发给的班级：</Typography.Text>
            <Select
              style={{ width: '100%' }}
              placeholder="选择班级"
              value={publishClassId}
              onChange={setPublishClassId}
              options={classes.map((klass) => ({
                value: klass.id,
                label: `${klass.name}（${klass.student_count} 人）`,
              }))}
            />
            <Typography.Text type="secondary">
              确认后会立刻给班内学生建作答记录；重复发布只补没有记录的学生。
            </Typography.Text>
          </Space>
        )}
      </Modal>
    </div>
  )
}
