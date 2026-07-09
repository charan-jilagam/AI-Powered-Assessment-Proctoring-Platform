import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Dashboard from "./pages/Dashboard";
import ExamPage from "./pages/ExamPage";
import AdminViolations from "./pages/AdminViolations";
import { getToken } from "./utils/api";
import AdminResults from "./pages/AdminResults";
import CreateExam from "./pages/CreateExam";
import ManageStudents from "./pages/ManageStudents";

// This component protects routes - only lets logged-in users through
function ProtectedRoute({ children }) {
  const token = getToken();
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/exam/:examId"
          element={
            <ProtectedRoute>
              <ExamPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/exam/:examId/violations"
          element={
            <ProtectedRoute>
              <AdminViolations />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/exam/:examId/violations"
          element={
            <ProtectedRoute>
              <AdminViolations />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/exam/:examId/results"
          element={
            <ProtectedRoute>
              <AdminResults />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/create-exam"
          element={
            <ProtectedRoute>
              <CreateExam />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/students"
          element={
            <ProtectedRoute>
              <ManageStudents />
            </ProtectedRoute>
          }
        />
        {/* Default route - redirect root to login */}
        <Route path="/" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;