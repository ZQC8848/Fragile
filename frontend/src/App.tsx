import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ConsoleRoute } from './routes/ConsoleRoute'
import { PlayRoute } from './routes/PlayRoute'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/play" replace />} />
        <Route path="/play" element={<PlayRoute />} />
        <Route path="/console" element={<ConsoleRoute />} />
        <Route path="*" element={<Navigate to="/play" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
