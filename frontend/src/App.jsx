import { Navigate, Route, Routes } from 'react-router'
import QuestionBank from './pages/teacher/QuestionBank.jsx'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/teacher/questions" replace />} />
      <Route path="/teacher/questions" element={<QuestionBank />} />
      <Route path="*" element={<Navigate to="/teacher/questions" replace />} />
    </Routes>
  )
}
