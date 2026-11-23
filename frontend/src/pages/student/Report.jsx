import ReportView from '../report/ReportView.jsx'
import StudentHeader from './StudentHeader.jsx'

export default function StudentReport() {
  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <StudentHeader title="学习报告" />
      <ReportView />
    </div>
  )
}
