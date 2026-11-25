import { Navigate, Route, Routes, useLocation } from 'react-router'
import { loadAuth } from './api.js'
import { homeFor } from './constants.js'
import LoginPage from './pages/LoginPage.jsx'
import QuestionBank from './pages/teacher/QuestionBank.jsx'
import TeacherExams from './pages/teacher/Exams.jsx'
import Knowledge from './pages/teacher/Knowledge.jsx'
import TeacherClassReport from './pages/teacher/TeacherClassReport.jsx'
import TeacherStudentReport from './pages/teacher/StudentReport.jsx'
import StudentExams from './pages/student/Exams.jsx'
import StudentPractice from './pages/student/Practice.jsx'
import StudentReport from './pages/student/Report.jsx'
import StudentReview from './pages/student/Review.jsx'
import Chat from './pages/student/Chat.jsx'

// 路由守卫只管体验，真正的权限在服务端按身份再过滤一次
function RequireAuth({ roles, children, wrongRoleTo }) {
  const location = useLocation()
  const auth = loadAuth()
  if (!auth) {
    return <Navigate to={`/login?from=${encodeURIComponent(location.pathname)}`} replace />
  }
  if (roles && !roles.includes(auth.user?.role)) {
    // 学生误入老师页回自己的落地页；老师误入学生页按路由回到班级报告等落点。
    return <Navigate to={wrongRoleTo ?? homeFor(auth.user?.role)} replace />
  }
  return children
}

function Entry() {
  const auth = loadAuth()
  if (!auth) return <Navigate to="/login" replace />
  return <Navigate to={homeFor(auth.user?.role)} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<Entry />} />
      <Route
        path="/teacher/questions"
        element={
          <RequireAuth roles={['teacher', 'admin']}>
            <QuestionBank />
          </RequireAuth>
        }
      />
      <Route
        path="/teacher/exams"
        element={
          <RequireAuth roles={['teacher', 'admin']}>
            <TeacherExams />
          </RequireAuth>
        }
      />
      <Route
        path="/teacher/knowledge"
        element={
          <RequireAuth roles={['teacher', 'admin']}>
            <Knowledge />
          </RequireAuth>
        }
      />
      <Route
        path="/teacher/class"
        element={
          <RequireAuth roles={['teacher', 'admin']}>
            <TeacherClassReport />
          </RequireAuth>
        }
      />
      <Route
        path="/teacher/students/:studentId/report"
        element={
          <RequireAuth roles={['teacher', 'admin']}>
            <TeacherStudentReport />
          </RequireAuth>
        }
      />
      <Route
        path="/student/exams"
        element={
          <RequireAuth roles={['student']} wrongRoleTo="/teacher/class">
            <StudentExams />
          </RequireAuth>
        }
      />
      <Route
        path="/student/review"
        element={
          <RequireAuth roles={['student']} wrongRoleTo="/teacher/class">
            <StudentReview />
          </RequireAuth>
        }
      />
      <Route
        path="/student/practice"
        element={
          <RequireAuth roles={['student']} wrongRoleTo="/teacher/class">
            <StudentPractice />
          </RequireAuth>
        }
      />
      <Route
        path="/student/report"
        element={
          <RequireAuth roles={['student']} wrongRoleTo="/teacher/class">
            <StudentReport />
          </RequireAuth>
        }
      />
      <Route
        path="/student/chat"
        element={
          <RequireAuth roles={['student', 'teacher', 'admin']}>
            <Chat />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Entry />} />
    </Routes>
  )
}
