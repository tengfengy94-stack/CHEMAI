import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { login } from '../api.js'
import { homeFor } from '../constants.js'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  // 未登录访问受保护页会被守卫送过来，登录后回原页
  const from = new URLSearchParams(location.search).get('from')

  const handleSubmit = async (values) => {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const user = await login(values.username, values.password)
      navigate(from && from !== '/login' ? from : homeFor(user.role), { replace: true })
    } catch (e) {
      setSubmitError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f5f5f5',
      }}
    >
      <Card style={{ width: 360 }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginTop: 8 }}>
          ChemAI 教学助手
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          老师、学生和管理员都从这里登录
        </Typography.Paragraph>
        {submitError && <Alert type="error" showIcon message={submitError} style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={handleSubmit} disabled={submitting}>
          <Form.Item
            label="用户名"
            name="username"
            rules={[{ required: true, whitespace: true, message: '请输入用户名' }]}
          >
            <Input placeholder="如 teacher01、s0101、admin" autoFocus />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password placeholder="请输入密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
