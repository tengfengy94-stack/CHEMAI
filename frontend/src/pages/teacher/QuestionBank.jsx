import { useState } from 'react'
import {
  Button,
  Card,
  Drawer,
  Flex,
  Form,
  Input,
  Radio,
  Table,
  Tag,
  Typography,
} from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { DIFFICULTIES, QUESTION_TYPES, REVIEW_STATUS } from '../../constants.js'
import { MOCK_QUESTIONS } from './mockQuestions.js'

const optionLetter = (index) => String.fromCharCode(65 + index)

const columns = (onEdit) => [
  { title: '题干', dataIndex: 'stem', ellipsis: true },
  {
    title: '题型',
    dataIndex: 'type',
    width: 90,
    render: (type) => QUESTION_TYPES[type],
  },
  { title: '难度', dataIndex: 'difficulty', width: 80, align: 'center' },
  {
    title: '审核状态',
    dataIndex: 'status',
    width: 110,
    render: (status) => (
      <Tag color={REVIEW_STATUS[status].color}>{REVIEW_STATUS[status].label}</Tag>
    ),
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

function QuestionForm({ form }) {
  const type = Form.useWatch('type', form)
  const isChoice = type !== 'blank'

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{ type: 'single', difficulty: 2, options: ['', '', '', ''] }}
    >
      <Form.Item label="题干" name="stem" rules={[{ required: true, message: '请填写题干' }]}>
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
          <Form.List name="options">
            {(fields, { add, remove }) => (
              <>
                {fields.map((field, index) => (
                  <Flex key={field.key} gap={8} align="baseline">
                    <Typography.Text strong style={{ width: 20 }}>
                      {optionLetter(index)}
                    </Typography.Text>
                    <Form.Item
                      {...field}
                      style={{ flex: 1, marginBottom: 8 }}
                      rules={[{ required: true, message: '请填写选项内容' }]}
                    >
                      <Input placeholder={`选项 ${optionLetter(index)}`} />
                    </Form.Item>
                    {fields.length > 2 && (
                      <MinusCircleOutlined onClick={() => remove(field.name)} />
                    )}
                  </Flex>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add('')} block>
                  添加选项
                </Button>
              </>
            )}
          </Form.List>
        </Form.Item>
      )}

      <Form.Item
        label="标准答案"
        name="answer"
        rules={[{ required: true, message: '请填写标准答案' }]}
        extra={
          type === 'multiple'
            ? '多选写字母，如 AC'
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

export default function QuestionBank() {
  const [form] = Form.useForm()
  const [drawer, setDrawer] = useState({ open: false, editing: null })

  const openCreate = () => {
    form.resetFields()
    setDrawer({ open: true, editing: null })
  }

  const openEdit = (record) => {
    form.resetFields()
    form.setFieldsValue({
      stem: record.stem,
      type: record.type,
      difficulty: record.difficulty,
    })
    setDrawer({ open: true, editing: record })
  }

  const close = () => setDrawer((d) => ({ ...d, open: false }))

  // 第 01 章只做界面：提交即关闭，不保存（保存在第 02 章接后端）
  const handleSubmit = () => close()

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

        <Table
          rowKey="id"
          columns={columns(openEdit)}
          dataSource={MOCK_QUESTIONS}
          pagination={false}
        />
      </Card>

      <Drawer
        title={drawer.editing ? '编辑题目' : '新建题目'}
        open={drawer.open}
        onClose={close}
        size={520}
        forceRender
        extra={
          <Flex gap={8}>
            <Button onClick={close}>取消</Button>
            <Button type="primary" onClick={handleSubmit}>
              提交
            </Button>
          </Flex>
        }
      >
        <QuestionForm form={form} />
      </Drawer>
    </div>
  )
}
