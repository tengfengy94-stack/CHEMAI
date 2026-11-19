import { useCallback, useEffect, useState } from 'react'
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
  Radio,
  Result,
  Table,
  Tag,
  Typography,
} from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { createQuestion, listQuestions } from '../../api.js'
import { DIFFICULTIES, QUESTION_TYPES, REVIEW_STATUS } from '../../constants.js'

const optionLetter = (index) => String.fromCharCode(65 + index)

const NEW_QUESTION_DEFAULTS = { type: 'single', difficulty: 2, options: ['', '', '', ''] }

const columns = (onEdit) => [
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
    render: (status) => {
      const s = REVIEW_STATUS[status]
      return s ? <Tag color={s.color}>{s.label}</Tag> : status
    },
  },
  {
    title: '操作',
    key: 'action',
    width: 90,
    render: (_, record) => (
      <Button type="link" size="small" onClick={() => onEdit(record)}>
        编辑
      </Button>
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

function useQuestions() {
  const [state, setState] = useState({ loading: true, error: null, data: [] })
  const [version, setVersion] = useState(0)

  // 重新加载：先标记 loading，再触发下面的 effect 重取
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }))
    setVersion((v) => v + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    listQuestions().then(
      (data) => !cancelled && setState({ loading: false, error: null, data }),
      () => !cancelled && setState((s) => ({ ...s, loading: false, error: true })),
    )
    return () => {
      cancelled = true
    }
  }, [version])

  return { ...state, reload }
}

export default function QuestionBank() {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const questions = useQuestions()
  const [drawer, setDrawer] = useState({ open: false, editing: null })
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

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
    setSubmitting(true)
    setSubmitError(null)
    try {
      await createQuestion({
        ...values,
        options: values.type === 'blank' ? null : values.options,
      })
      message.success('已保存为草稿，在列表第一行；确认无误后再标待复核或通过')
      close()
      questions.reload()
    } catch (e) {
      // 失败保留老师填过的内容，不清空
      setSubmitError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const editing = drawer.editing !== null

  // 出错只给固定文案加重试，不显示原始报错（设计/05 §4.3）
  let body
  if (questions.error && questions.data.length === 0) {
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
          columns={columns(openEdit)}
          dataSource={questions.data}
          loading={questions.loading}
          pagination={false}
          locale={{
            emptyText: questions.loading ? ' ' : (
              <Empty description="题库里还没有题">
                <Button type="primary" onClick={openCreate}>
                  新建第一道题
                </Button>
              </Empty>
            ),
          }}
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
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建题目
          </Button>
        </Flex>
        {body}
      </Card>

      <Drawer
        title={editing ? '编辑题目（第 04 章开放保存）' : '新建题目'}
        open={drawer.open}
        onClose={close}
        size={520}
        forceRender
        extra={
          <Flex gap={8}>
            <Button onClick={close}>取消</Button>
            <Button
              type="primary"
              onClick={handleSubmit}
              loading={submitting}
              disabled={editing}
            >
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
