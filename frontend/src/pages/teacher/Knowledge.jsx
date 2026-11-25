import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Divider,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  List,
  Modal,
  Result,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  createKnowledgePoint,
  currentUser,
  getKnowledgePointQuestions,
  getQuestionKnowledgePoints,
  listKnowledgePoints,
  listQuestions,
  logout,
  mergeKnowledgePoint,
  setQuestionKnowledgePoints,
  updateKnowledgePoint,
} from '../../api.js'
import { QUESTION_TYPES, REVIEW_STATUS } from '../../constants.js'

const flatten = (nodes, depth = 0) =>
  nodes.flatMap((node) => [
    { ...node, depth },
    ...flatten(node.children ?? [], depth + 1),
  ])

// 与后端 merge_points 的校验保持一致：非法目标在弹窗里直接禁用。
const invalidTargetReason = (source, target) => {
  if (target.id === source.id) return '不能合并到自己'
  if (target.parent_id === source.id) return '不能合并到自己的下级'
  if ((source.children?.length ?? 0) > 0 && target.parent_id !== null) {
    return '源有子节点，目标必须是根节点'
  }
  return ''
}

const toTableData = (nodes) =>
  nodes.map(({ children, ...node }) =>
    children?.length ? { ...node, children: toTableData(children) } : node,
  )

const cleanAliases = (aliases) =>
  (aliases ?? []).map((alias) => alias.trim()).filter(Boolean)

export default function Knowledge() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const user = currentUser()

  const [tree, setTree] = useState([])
  const [expandedKeys, setExpandedKeys] = useState([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [createParent, setCreateParent] = useState(null)
  const [creating, setCreating] = useState(false)
  const [createForm] = Form.useForm()

  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)
  const [editForm] = Form.useForm()

  const [mergeSource, setMergeSource] = useState(null)
  const [mergeTargetId, setMergeTargetId] = useState(undefined)
  const [merging, setMerging] = useState(false)

  const [questionsOpen, setQuestionsOpen] = useState(false)
  const [questionsPoint, setQuestionsPoint] = useState(null)
  const [questions, setQuestions] = useState([])
  const [questionsLoading, setQuestionsLoading] = useState(false)
  const [questionsError, setQuestionsError] = useState('')
  const [questionsPage, setQuestionsPage] = useState(1)
  const [questionsPageSize, setQuestionsPageSize] = useState(20)
  const [questionsTotal, setQuestionsTotal] = useState(0)
  const [questionCandidates, setQuestionCandidates] = useState([])
  const [candidateLoading, setCandidateLoading] = useState(false)
  const [linking, setLinking] = useState(false)

  const applyTree = useCallback((items) => {
    setTree(items)
    setExpandedKeys(flatten(items).map((node) => node.id))
    setFailed(false)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listKnowledgePoints()
      applyTree(data.items)
    } catch {
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }, [applyTree])

  const loadPointQuestions = useCallback(
    async (node, page = questionsPage) => {
      if (!node) return
      setQuestionsLoading(true)
      setQuestionsError('')
      try {
        const data = await getKnowledgePointQuestions(node.id, {
          page,
          pageSize: questionsPageSize,
        })
        setQuestions(data.items)
        setQuestionsTotal(data.total)
        setQuestionsPageSize(data.page_size)
        setQuestionsPage(page)
      } catch (error) {
        setQuestionsError(error.message)
      } finally {
        setQuestionsLoading(false)
      }
    },
    [questionsPage, questionsPageSize],
  )

  const openQuestions = (node) => {
    setQuestionsPoint(node)
    setQuestions([])
    setQuestionsError('')
    setQuestionCandidates([])
    setQuestionsOpen(true)
    setQuestionsPage(1)
    loadPointQuestions(node, 1)
  }

  const searchCandidates = async (value) => {
    setCandidateLoading(true)
    try {
      const data = await listQuestions({ q: value.trim() || undefined, page: 1 })
      const linked = new Set(questions.map((item) => item.id))
      setQuestionCandidates(data.items.filter((item) => !linked.has(item.id)))
    } catch (error) {
      message.error(error.message)
    } finally {
      setCandidateLoading(false)
    }
  }

  const saveQuestionLinks = async (question, attach) => {
    if (!questionsPoint) return
    setLinking(true)
    try {
      const existing = await getQuestionKnowledgePoints(question.id)
      const currentIds = existing.knowledge_points.map((item) => item.id)
      const nextIds = attach
        ? [...new Set([...currentIds, questionsPoint.id])]
        : currentIds.filter((id) => id !== questionsPoint.id)
      const primary = existing.knowledge_points.find((item) => item.is_primary)?.id
      const nextPrimary = primary && nextIds.includes(primary) ? primary : null
      await setQuestionKnowledgePoints(question.id, nextIds, nextPrimary)
      message.success(attach ? '题目已关联' : '已取消关联')
      const nextPage =
        !attach && questions.length === 1 && questionsPage > 1
          ? questionsPage - 1
          : questionsPage
      await loadPointQuestions(questionsPoint, nextPage)
      await load()
      if (attach) {
        setQuestionCandidates((current) => current.filter((item) => item.id !== question.id))
      }
    } catch (error) {
      message.error(error.message)
    } finally {
      setLinking(false)
    }
  }

  const setPrimary = async (question) => {
    if (!questionsPoint) return
    setLinking(true)
    try {
      const existing = await getQuestionKnowledgePoints(question.id)
      const ids = existing.knowledge_points.map((item) => item.id)
      await setQuestionKnowledgePoints(question.id, ids, questionsPoint.id)
      message.success('已设为主知识点')
      await loadPointQuestions(questionsPoint, questionsPage)
      await load()
    } catch (error) {
      message.error(error.message)
    } finally {
      setLinking(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    async function run() {
      try {
        const data = await listKnowledgePoints()
        if (!cancelled) applyTree(data.items)
      } catch {
        if (!cancelled) setFailed(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [applyTree])

  const openCreate = (parent) => {
    setCreateParent(parent)
    createForm.resetFields()
    setCreateOpen(true)
  }

  const handleCreate = async () => {
    let values
    try {
      values = await createForm.validateFields()
    } catch {
      return
    }
    setCreating(true)
    try {
      await createKnowledgePoint({
        name: values.name.trim(),
        parentId: createParent?.id ?? null,
        aliases: cleanAliases(values.aliases),
      })
      message.success('知识点已创建')
      setCreateOpen(false)
      await load()
    } catch (error) {
      message.error(error.message)
    } finally {
      setCreating(false)
    }
  }

  const openEdit = (node) => {
    setEditing(node)
    editForm.setFieldsValue({ name: node.name, aliases: node.aliases })
  }

  const handleEdit = async () => {
    let values
    try {
      values = await editForm.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      await updateKnowledgePoint(editing.id, {
        name: values.name.trim(),
        aliases: cleanAliases(values.aliases),
      })
      message.success('知识点已保存')
      setEditing(null)
      await load()
    } catch (error) {
      message.error(error.message)
    } finally {
      setSaving(false)
    }
  }

  const openMerge = (node) => {
    setMergeSource(node)
    setMergeTargetId(undefined)
  }

  const handleMerge = async () => {
    if (!mergeTargetId) {
      message.warning('请选择合并目标')
      return
    }
    const target = flatten(tree).find((node) => node.id === mergeTargetId)
    setMerging(true)
    try {
      await mergeKnowledgePoint(mergeSource.id, mergeTargetId)
      message.success(`已把「${mergeSource.name}」并入「${target?.name ?? '目标'}」`)
      setMergeSource(null)
      await load()
    } catch (error) {
      message.error(error.message)
    } finally {
      setMerging(false)
    }
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name, record) => (
        <Space size={6}>
          <span>{name}</span>
          {record.parent_id === null && <Tag>根</Tag>}
        </Space>
      ),
    },
    {
      title: '别名',
      dataIndex: 'aliases',
      render: (aliases) =>
        aliases?.length ? (
          <Space size={[0, 4]} wrap>
            {aliases.map((alias) => (
              <Tag key={alias}>{alias}</Tag>
            ))}
          </Space>
        ) : (
          '—'
        ),
    },
    { title: '题目数', dataIndex: 'question_count', width: 90, align: 'center' },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_, record) => (
        <Space size="small">
          {record.parent_id === null && (
            <Button size="small" onClick={() => openCreate(record)}>
              建子节点
            </Button>
          )}
          <Button size="small" onClick={() => openQuestions(record)}>
            题目
          </Button>
          <Button size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button size="small" onClick={() => openMerge(record)}>
            合并
          </Button>
        </Space>
      ),
    },
  ]

  const candidates = mergeSource
    ? flatten(tree).map((node) => ({ ...node, reason: invalidTargetReason(mergeSource, node) }))
    : []

  let body
  if (loading && tree.length === 0) {
    body = (
      <Flex justify="center" style={{ padding: 48 }}>
        <Spin />
      </Flex>
    )
  } else if (failed && tree.length === 0) {
    body = (
      <Result
        status="warning"
        title="知识点加载失败"
        subTitle="知识点没有加载出来，请点重试"
        extra={
          <Button type="primary" onClick={load}>
            重试
          </Button>
        }
      />
    )
  } else if (tree.length === 0) {
    body = (
      <Empty description="还没有知识点">
        <Button type="primary" onClick={() => openCreate(null)}>
          新建第一个知识点
        </Button>
      </Empty>
    )
  } else {
    body = (
      <>
        {failed && (
          <Alert
            type="warning"
            showIcon
            message="知识点刷新失败"
            action={
              <Button size="small" onClick={load}>
                重试
              </Button>
            }
            style={{ marginBottom: 16 }}
          />
        )}
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          pagination={false}
          columns={columns}
          dataSource={toTableData(tree)}
          expandable={{
            expandedRowKeys: expandedKeys,
            onExpandedRowsChange: setExpandedKeys,
          }}
        />
      </>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          知识点
        </Typography.Title>
        <Space>
          <Typography.Text type="secondary">{user?.name}</Typography.Text>
          <Button onClick={() => navigate('/teacher/questions')}>题库</Button>
          <Button onClick={() => navigate('/teacher/exams')}>组卷</Button>
          <Button onClick={() => navigate('/teacher/class')}>班级报告</Button>
          <Button onClick={() => navigate('/student/chat')}>对话</Button>
          <Button onClick={logout}>退出</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate(null)}>
            新建知识点
          </Button>
        </Space>
      </Flex>

      <Card>{body}</Card>

      <Modal
        title={createParent ? `在「${createParent.name}」下新建子节点` : '新建根知识点'}
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        confirmLoading={creating}
        okText="创建"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入知识点名称' }]}
          >
            <Input maxLength={100} placeholder="例如：氧化还原" />
          </Form.Item>
          <Form.Item
            name="aliases"
            label="别名"
            extra="同一个点的不同写法，可留空；保存时整体替换。"
          >
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[',', '，']}
              placeholder="输入后回车添加"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑知识点"
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={handleEdit}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        forceRender
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入知识点名称' }]}
          >
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            name="aliases"
            label="别名"
            extra="保存时整体替换；改名会把旧名称自动保留为别名。"
          >
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[',', '，']}
              placeholder="输入后回车添加"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="合并知识点"
        open={mergeSource !== null}
        onCancel={() => setMergeSource(null)}
        onOk={handleMerge}
        confirmLoading={merging}
        okText="确认合并"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        destroyOnHidden
      >
        {mergeSource && (
          <>
            <Alert
              type="warning"
              showIcon
              message="合并后源节点会消失"
              description={`「${mergeSource.name}」的别名、题目关联和子节点会移到目标节点；这个操作不能撤销。`}
              style={{ marginBottom: 16 }}
            />
            <Form layout="vertical">
              <Form.Item label="合并目标">
                <Select
                  value={mergeTargetId}
                  onChange={setMergeTargetId}
                  placeholder="选择要并入的知识点"
                  options={candidates.map((node) => ({
                    value: node.id,
                    disabled: Boolean(node.reason),
                    label: `${node.depth > 0 ? '　└ ' : ''}${node.name}${
                      node.reason ? `（${node.reason}）` : ''
                    }`,
                  }))}
                />
              </Form.Item>
            </Form>
          </>
        )}
      </Modal>

      <Drawer
        title={questionsPoint ? `「${questionsPoint.name}」的题目` : '知识点题目'}
        open={questionsOpen}
        onClose={() => setQuestionsOpen(false)}
        width={640}
      >
        {questionsError ? (
          <Alert
            type="error"
            showIcon
            message="题目加载失败"
            description={questionsError}
            action={
              <Button
                size="small"
                onClick={() => loadPointQuestions(questionsPoint, questionsPage)}
              >
                重试
              </Button>
            }
          />
        ) : questionsLoading ? (
          <Flex justify="center" style={{ padding: 32 }}>
            <Spin />
          </Flex>
        ) : questions.length === 0 ? (
          <Empty description="这个知识点还没有关联题目" />
        ) : (
          <List
            dataSource={questions}
            pagination={{
              current: questionsPage,
              pageSize: questionsPageSize,
              total: questionsTotal,
              showSizeChanger: false,
              onChange: (page) => loadPointQuestions(questionsPoint, page),
            }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  !item.is_primary ? (
                    <Button
                      key="primary"
                      size="small"
                      type="link"
                      loading={linking}
                      onClick={() => setPrimary(item)}
                    >
                      设为主
                    </Button>
                  ) : null,
                  <Button
                    key="remove"
                    size="small"
                    danger
                    loading={linking}
                    onClick={() => saveQuestionLinks(item, false)}
                  >
                    移除
                  </Button>,
                ].filter(Boolean)}
              >
                <List.Item.Meta
                  title={
                    <Typography.Text ellipsis={{ tooltip: item.stem }}>
                      {item.stem}
                    </Typography.Text>
                  }
                  description={
                    <Space size={4} wrap>
                      <Tag>{QUESTION_TYPES[item.type] ?? item.type}</Tag>
                      <Tag>难度 {item.difficulty}</Tag>
                      <Tag color={REVIEW_STATUS[item.status]?.color}>
                        {REVIEW_STATUS[item.status]?.label ?? item.status}
                      </Tag>
                      {item.is_primary ? <Tag color="blue">主知识点</Tag> : null}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}

        <Divider />
        <Typography.Text strong>关联题目</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginTop: 4 }}>
          搜索你建的题目，关联后进入弱项统计和练习选题。
        </Typography.Paragraph>
        <Input.Search
          allowClear
          placeholder="按题干关键词搜索"
          enterButton="搜索"
          loading={candidateLoading}
          onSearch={searchCandidates}
          style={{ marginBottom: 12 }}
        />
        {candidateLoading ? (
          <Flex justify="center" style={{ padding: 16 }}>
            <Spin />
          </Flex>
        ) : (
          <List
            dataSource={questionCandidates}
            locale={{
              emptyText: <Empty description="搜索后从结果里选择要关联的题目" />,
            }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="attach"
                    size="small"
                    type="link"
                    loading={linking}
                    onClick={() => saveQuestionLinks(item, true)}
                  >
                    关联
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Typography.Text ellipsis={{ tooltip: item.stem }}>
                      {item.stem}
                    </Typography.Text>
                  }
                  description={
                    <Space size={4} wrap>
                      <Tag>{QUESTION_TYPES[item.type] ?? item.type}</Tag>
                      <Tag>难度 {item.difficulty}</Tag>
                      <Tag color={REVIEW_STATUS[item.status]?.color}>
                        {REVIEW_STATUS[item.status]?.label ?? item.status}
                      </Tag>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Drawer>
    </div>
  )
}
