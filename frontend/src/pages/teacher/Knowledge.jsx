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
  listKnowledgePoints,
  logout,
  mergeKnowledgePoint,
  updateKnowledgePoint,
} from '../../api.js'

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
    </div>
  )
}
