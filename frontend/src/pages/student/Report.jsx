import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, Flex, Spin, Table } from 'antd'
import { useNavigate } from 'react-router'
import { getWeakReport } from '../../api.js'
import { formatErrorRate } from '../../format.js'
import StudentHeader from './StudentHeader.jsx'

export default function StudentReport() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchReport = useCallback(async () => {
    try {
      setData(await getWeakReport())
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const report = await getWeakReport()
        if (!cancelled) {
          setData(report)
          setError('')
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const retry = () => {
    setLoading(true)
    setError('')
    fetchReport()
  }

  const columns = [
    { title: '知识点', dataIndex: 'name', ellipsis: true },
    {
      title: '作答数',
      dataIndex: 'answered_count',
      align: 'center',
      width: 100,
    },
    {
      title: '错题数',
      dataIndex: 'wrong_count',
      align: 'center',
      width: 100,
    },
    {
      title: '错误率',
      dataIndex: 'error_rate',
      align: 'center',
      width: 120,
      render: (value) => formatErrorRate(value),
    },
  ]

  const renderContent = () => {
    if (loading) {
      return (
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      )
    }
    if (error) {
      return (
        <Alert
          type="error"
          showIcon
          message="报告加载失败"
          description={error}
          action={
            <Button size="small" onClick={retry}>
              重试
            </Button>
          }
        />
      )
    }
    if (!data.has_data) {
      return (
        <Empty description="还没有学习记录">
          <Button type="primary" onClick={() => navigate('/student/exams')}>
            去做几道题
          </Button>
        </Empty>
      )
    }
    if (data.items.length === 0) {
      return <Empty description="暂无可统计的弱项" />
    }
    return (
      <Card title="弱项前三">
        <Table
          rowKey="knowledge_point_id"
          size="small"
          pagination={false}
          columns={columns}
          dataSource={data.items}
        />
      </Card>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <StudentHeader title="学习报告" />
      {renderContent()}
    </div>
  )
}
