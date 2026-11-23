import { Button, Flex, Space, Typography } from 'antd'
import { useNavigate } from 'react-router'
import { currentUser, logout } from '../../api.js'

export default function StudentHeader({ title }) {
  const navigate = useNavigate()
  const user = currentUser()
  return (
    <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        {title}
      </Typography.Title>
      <Space>
        <Button onClick={() => navigate('/student/exams')}>考试</Button>
        <Button onClick={() => navigate('/student/review')}>复习</Button>
        <Button onClick={() => navigate('/student/report')}>学习报告</Button>
        <Typography.Text type="secondary">
          {user ? `${user.name}（${user.username}）` : ''}
        </Typography.Text>
        <Button onClick={logout}>退出</Button>
      </Space>
    </Flex>
  )
}
