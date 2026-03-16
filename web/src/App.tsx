import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Submit from './pages/Submit'
import TaskDetail from './pages/TaskDetail'
import Approvals from './pages/Approvals'
import History from './pages/History'
import Health from './pages/Health'

export default function App() {
  return (
    <>
      <nav>
        <span className="brand">AI Dev Crew</span>
        <NavLink to="/">Dashboard</NavLink>
        <NavLink to="/submit">Submit</NavLink>
        <NavLink to="/approvals">Approvals</NavLink>
        <NavLink to="/history">History</NavLink>
        <NavLink to="/health">Health</NavLink>
      </nav>
      <div className="container">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/submit" element={<Submit />} />
          <Route path="/tasks/:taskId" element={<TaskDetail />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/history" element={<History />} />
          <Route path="/health" element={<Health />} />
        </Routes>
      </div>
    </>
  )
}
