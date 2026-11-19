import { Button, Card, Flex, Result, Typography } from 'antd'
import { currentUser, logout } from '../../api.js'

// 第 03 章的占位页：让学生有地方落地，作答列表第 05 章接上
export default function Exams() {
  const user = currentUser()
  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <Card>
        <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            考试
          </Typography.Title>
          <Flex gap={12} align="center">
            <Typography.Text type="secondary">
              {user ? `${user.name}（${user.username}）` : ''}
            </Typography.Text>
            <Button onClick={logout}>退出</Button>
          </Flex>
        </Flex>
        <Result
          status="info"
          title="考试列表将在后续章节开放"
          subTitle="老师发布试卷之后，这里会列出你要作答的卷子。"
        />
      </Card>
    </div>
  )
}
