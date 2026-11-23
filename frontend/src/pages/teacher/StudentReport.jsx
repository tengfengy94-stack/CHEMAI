import { Button, Flex, Space, Typography } from 'antd'
import { useLocation, useNavigate, useParams } from 'react-router'
import { currentUser, logout } from '../../api.js'
import ReportView from '../report/ReportView.jsx'

export default function TeacherStudentReport() {
  const { studentId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const user = currentUser()
  const studentName = location.state?.studentName

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Space>
          <Button onClick={() => navigate('/teacher/class')}>返回班级报告</Button>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {studentName ? `${studentName}的学习报告` : '学生报告'}
          </Typography.Title>
        </Space>
        <Space>
          <Typography.Text type="secondary">{user?.name}</Typography.Text>
          <Button onClick={logout}>退出</Button>
        </Space>
      </Flex>
      <ReportView studentId={studentId} teacherView />
    </div>
  )
}
