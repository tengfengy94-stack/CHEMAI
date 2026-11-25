import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Radio,
  Result,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import {
  changeQuestionStatus,
  createQuestion,
  currentUser,
  deleteQuestion,
  getQuestionUsage,
  listQuestions,
  logout,
  updateQuestion,
} from '../../api.js'
import { DIFFICULTIES, QUESTION_TYPES, REVIEW_STATUS } from '../../constants.js'

const optionLetter = (index) => String.fromCharCode(65 + index)

const NEW_QUESTION_DEFAULTS = { type: 'single', difficulty: 2, options: ['', '', '', ''] }

const statusTag = (status) => {
  const s = REVIEW_STATUS[status]
  return s ? <Tag color={s.color}>{s.label}</Tag> : status
}

const columns = ({ onEdit, onReview, onDelete }) => [
  { title: '题干', dataIndex: 'stem', ellipsis: true },
  {
    title: '题型',
    dataIndex: 'type',
    width: 90,
    render: (type) => QUESTION_TYPES[type] ?? type,
  },
  { title: '难度', dataIndex: 'difficulty', width: 80, align: 'center' },
  {
    title: '审核状态',
    dataIndex: 'status',
    width: 110,
    render: statusTag,
  },
  {
    title: '操作',
    key: 'action',
    width: 260,
    render: (_, record) => (
      <Flex gap={4} wrap>
        {record.status !== 'approved' && (
          <Button type="link" size="small" onClick={() => onEdit(record)}>
            编辑
          </Button>
        )}
        {record.status === 'draft' && (
          <Button type="link" size="small" onClick={() => onReview(record, 'pending')}>
            标待复核
          </Button>
        )}
        {record.status !== 'approved' && (
          <Button type="link" size="small" onClick={() => onReview(record, 'approved')}>
            通过
          </Button>
        )}
        <Button type="link" size="small" danger onClick={() => onDelete(record)}>
          删除
        </Button>
      </Flex>
    ),
  },
]

function QuestionForm({ form, disabled }) {
  const type = Form.useWatch('type', form)
  const isChoice = type !== 'blank'

  return (
    <Form form={form} layout="vertical" initialValues={NEW_QUESTION_DEFAULTS} disabled={disabled}>
      <Form.Item
        label="题干"
        name="stem"
        rules={[{ required: true, whitespace: true, message: '请填写题干' }]}
      >
        <Input.TextArea rows={3} placeholder="纯文字，不带图" />
      </Form.Item>

      <Form.Item label="题型" name="type">
        <Radio.Group
          optionType="button"
          options={Object.entries(QUESTION_TYPES).map(([value, label]) => ({ value, label }))}
        />
      </Form.Item>

      {isChoice && (
        <Form.Item label="选项" required>
          <Form.List
            name="options"
            rules={[
              {
                validator: async (_, options) => {
                  if (!options || options.length < 2) throw new Error('选择题至少要有 2 个选项')
                },
              },
            ]}
          >
            {(fields, { add, remove }, { errors }) => (
              <>
                {fields.map((field, index) => (
                  <Flex key={field.key} gap={8} align="baseline">
                    <Typography.Text strong style={{ width: 20 }}>
                      {optionLetter(index)}
                    </Typography.Text>
                    <Form.Item
                      {...field}
                      style={{ flex: 1, marginBottom: 8 }}
                      rules={[{ required: true, whitespace: true, message: '选项不能为空' }]}
                    >
                      <Input placeholder={`选项 ${optionLetter(index)}`} />
                    </Form.Item>
                    {!disabled && fields.length > 2 && (
                      <MinusCircleOutlined onClick={() => remove(field.name)} />
                    )}
                  </Flex>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add('')} block>
                  添加选项
                </Button>
                <Form.ErrorList errors={errors} />
              </>
            )}
          </Form.List>
        </Form.Item>
      )}

      <Form.Item
        label="标准答案"
        name="answer"
        rules={[{ required: true, whitespace: true, message: '请填写标准答案' }]}
        extra={
          type === 'multiple'
            ? '多选写字母，如 AC（写成 C,A 或 ac 也行，保存时自动整理）'
            : type === 'blank'
              ? '填空写原文，如 NaCl'
              : '单选写一个字母，如 A'
        }
      >
        <Input />
      </Form.Item>

      <Form.Item label="解析" name="explanation">
        <Input.TextArea rows={3} placeholder="可不填，不填时学生看到“暂无解析”" />
      </Form.Item>

      <Form.Item label="难度" name="difficulty">
        <Radio.Group options={DIFFICULTIES.map((d) => ({ value: d, label: String(d) }))} />
      </Form.Item>
    </Form>
  )
}

function useQuestions(filters, page) {
  const [state, setState] = useState({
    loading: true,
    error: null,
    items: [],
    total: 0,
    pageSize: 20,
  })
  const [version, setVersion] = useState(0)

  // 重新加载：先标记 loading，再触发下面的 effect 重取
  const reload = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    listQuestions({ ...filters, page }).then(
      (data) =>
        !cancelled &&
        setState({
          loading: false,
          error: null,
          items: data.items,
          total: data.total,
          // 每页条数以服务端为准，前端不再另写一份
          pageSize: data.page_size,
        }),
      () => !cancelled && setState((s) => ({ ...s, loading: false, error: true })),
    )
    return () => {
      cancelled = true
    }
  }, [version, page, filters])

  return { ...state, reload }
}

export default function QuestionBank() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [filters, setFilters] = useState({ difficulty: undefined, status: undefined, q: '' })
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const questions = useQuestions(filters, page)
  const [drawer, setDrawer] = useState({ open: false, editing: null })
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const user = currentUser()

  // 当前页被删空（total 还在）时回退一页，避免停在越界页显示"题库里还没有题"
  useEffect(() => {
    if (!questions.loading && questions.items.length === 0 && questions.total > 0 && page > 1) {
      setPage(page - 1)
    }
  }, [questions.loading, questions.items.length, questions.total, page])

  const hasFilters = Boolean(filters.difficulty || filters.status || filters.q)

  const applyFilters = (patch) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }

  const clearFilters = () => {
    setKeyword('')
    applyFilters({ difficulty: undefined, status: undefined, q: '' })
  }

  const openCreate = () => {
    form.resetFields()
    setSubmitError(null)
    setDrawer({ open: true, editing: null })
  }

  const openEdit = (record) => {
    form.resetFields()
    form.setFieldsValue({
      stem: record.stem,
      type: record.type,
      options: record.options ?? [],
      answer: record.answer,
      explanation: record.explanation ?? '',
      difficulty: record.difficulty,
    })
    setSubmitError(null)
    setDrawer({ open: true, editing: record })
  }

  const close = () => setDrawer((d) => ({ ...d, open: false }))

  const handleSubmit = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const payload = { ...values, options: values.type === 'blank' ? null : values.options }
    setSubmitting(true)
    setSubmitError(null)
    try {
      if (drawer.editing) {
        await updateQuestion(drawer.editing.id, payload)
        message.success('已保存')
      } else {
        await createQuestion(payload)
        message.success('已保存为草稿，在列表第一行；确认无误后再标待复核或通过')
      }
      close()
      questions.reload()
    } catch (e) {
      // 失败保留老师填过的内容，不清空
      setSubmitError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleReview = async (record, status) => {
    try {
      await changeQuestionStatus(record.id, status)
      message.success(status === 'approved' ? '已通过，学生可见' : '已标为待复核')
      questions.reload()
    } catch (e) {
      message.error(e.message)
    }
  }

  const handleDelete = async (record) => {
    let papers
    try {
      papers = (await getQuestionUsage(record.id)).papers
    } catch (e) {
      message.error(e.message)
      return
    }
    // 被卷子用过就直接说，不弹确认——确认了也删不掉（设计/05 §4.2）
    if (papers > 0) {
      message.warning(`这道题已被 ${papers} 份卷子使用，不能删除`)
      return
    }
    Modal.confirm({
      title: '删除这道题？',
      content: '删除后不能恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteQuestion(record.id)
          message.success('已删除')
          // 删掉当前页最后一条时直接回退，不等下一轮请求发现越界
          if (questions.items.length === 1 && page > 1) {
            setPage(page - 1)
          } else {
            questions.reload()
          }
        } catch (e) {
          message.error(e.message)
        }
      },
    })
  }

  const editing = drawer.editing !== null

  // 出错只给固定文案加重试，不显示原始报错（设计/05 §4.3）
  let body
  if (questions.error && questions.items.length === 0) {
    body = (
      <Result
        status="warning"
        title="加载失败"
        subTitle="题库没有加载出来，请点重试"
        extra={
          <Button type="primary" onClick={questions.reload}>
            重试
          </Button>
        }
      />
    )
  } else {
    let emptyText
    if (hasFilters) {
      emptyText = (
        <Empty description="没有符合条件的题">
          <Button onClick={clearFilters}>清除筛选</Button>
        </Empty>
      )
    } else {
      emptyText = (
        <Empty description="题库里还没有题">
          <Button type="primary" onClick={openCreate}>
            新建第一道题
          </Button>
        </Empty>
      )
    }
    body = (
      <>
        {questions.error && (
          <Alert
            type="warning"
            showIcon
            message="列表刷新失败，下面显示的可能不是最新数据"
            action={
              <Button size="small" onClick={questions.reload}>
                重试
              </Button>
            }
            style={{ marginBottom: 16 }}
          />
        )}
        <Table
          rowKey="id"
          columns={columns({ onEdit: openEdit, onReview: handleReview, onDelete: handleDelete })}
          dataSource={questions.items}
          loading={questions.loading}
          pagination={{
            current: page,
            pageSize: questions.pageSize,
            total: questions.total,
            showSizeChanger: false,
            onChange: setPage,
          }}
          locale={{ emptyText: questions.loading ? ' ' : emptyText }}
        />
      </>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <Card>
        <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            题库
          </Typography.Title>
          <Flex gap={12} align="center">
            <Typography.Text type="secondary">
              {user ? `${user.name}（${user.username}）` : ''}
            </Typography.Text>
            <Button onClick={() => navigate('/teacher/exams')}>组卷</Button>
            <Button onClick={() => navigate('/teacher/knowledge')}>知识点</Button>
            <Button onClick={() => navigate('/teacher/class')}>班级报告</Button>
            <Button onClick={() => navigate('/student/chat')}>对话</Button>
            <Button onClick={logout}>退出</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建题目
            </Button>
          </Flex>
        </Flex>

        <Flex gap={12} wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            placeholder="难度"
            style={{ width: 120 }}
            value={filters.difficulty}
            onChange={(value) => applyFilters({ difficulty: value })}
            options={DIFFICULTIES.map((d) => ({ value: d, label: `难度 ${d}` }))}
          />
          <Select
            allowClear
            placeholder="审核状态"
            style={{ width: 140 }}
            value={filters.status}
            onChange={(value) => applyFilters({ status: value })}
            options={Object.entries(REVIEW_STATUS).map(([value, s]) => ({
              value,
              label: s.label,
            }))}
          />
          <Input.Search
            allowClear
            placeholder="按题干关键词搜索"
            style={{ width: 260 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={(value) => applyFilters({ q: value.trim() })}
          />
        </Flex>

        {body}
      </Card>

      <Drawer
        title={editing ? '编辑题目' : '新建题目'}
        open={drawer.open}
        onClose={close}
        size={520}
        forceRender
        extra={
          <Flex gap={8}>
            <Button onClick={close}>取消</Button>
            <Button type="primary" onClick={handleSubmit} loading={submitting}>
              提交
            </Button>
          </Flex>
        }
      >
        {submitError && (
          <Alert type="error" showIcon message={submitError} style={{ marginBottom: 16 }} />
        )}
        <QuestionForm form={form} disabled={submitting} />
      </Drawer>
    </div>
  )
}
