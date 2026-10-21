import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiCall, removeToken } from "../utils/api";

function Dashboard() {
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [userRole, setUserRole] = useState("");
  const [userName, setUserName] = useState("");
  const [myResults, setMyResults] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    loadExams();
  }, []);

  async function loadExams() {
    try {
      const userData = await apiCall("/auth/me", "GET");
      setUserRole(userData.role);
      setUserName(userData.full_name);
      const data = await apiCall("/exams/available", "GET");
      setExams(data);
      if (userData.role === "student") {
        const results = await apiCall("/my-results", "GET");
        setMyResults(results);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function handleLogout() {
    removeToken();
    navigate("/login");
  }

  async function handleDeleteExam(examId, examTitle) {
    const confirmed = window.confirm(
      `Delete "${examTitle}"?\n\nThis permanently removes the exam and all its questions, submissions, and violation records. This cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await apiCall(`/exams/${examId}`, "DELETE");
      loadExams();
    } catch (err) {
      alert("Failed to delete exam: " + err.message);
    }
  }

  return (
    <div style={styles.page}>
      {/* Navbar */}
      <nav style={styles.navbar}>
        <div style={styles.navBrand}>
          <div style={styles.navLogo}>🛡️</div>
          <span style={styles.navName}>ProctorAI</span>
        </div>
        <div style={styles.navRight}>
          <div style={styles.statusPill}>
            <span style={styles.statusDot}></span>
            System active
          </div>
          <div style={styles.userInfo}>
            <div style={styles.avatar}>{userName.charAt(0).toUpperCase()}</div>
            <div>
              <p style={styles.userName}>{userName}</p>
              <p style={styles.userRole}>{userRole}</p>
            </div>
          </div>
          <button onClick={handleLogout} style={styles.logoutBtn}>Sign out</button>
        </div>
      </nav>

      <div style={styles.main}>
        <div style={styles.header}>
          <div>
            <div style={styles.eyebrow}>{userRole === "admin" ? "ADMIN CONSOLE" : "CANDIDATE CONSOLE"}</div>
            <h1 style={styles.title}>
              {userRole === "admin" ? "Exam Management" : "Available Assessments"}
            </h1>
            <p style={styles.subtitle}>
              {userRole === "admin"
                ? "Create exams, review candidate results, and monitor violations."
                : "Select an assessment to begin. Ensure you're in a quiet, well-lit room."}
            </p>
          </div>
          {userRole === "admin" && (
            <div style={styles.adminActions}>
              <Link to="/admin/create-exam" style={styles.createExamBtn}>+ Create Exam</Link>
              <Link to="/admin/students" style={styles.manageBtn}>Manage Students</Link>
            </div>
          )}
        </div>

        {userRole === "admin" && (
          <div style={styles.statsBar}>
            <div style={styles.statCard}>
              <p style={{ ...styles.statValue, color: "#22D3EE" }}>{exams.length}</p>
              <p style={styles.statLabel}>Total Exams</p>
            </div>
            <div style={styles.statCard}>
              <p style={{ ...styles.statValue, color: "#A78BFA" }}>
                {exams.reduce((sum, e) => sum + e.questions.length, 0)}
              </p>
              <p style={styles.statLabel}>Total Questions</p>
            </div>
          </div>
        )}

        {loading && <div style={styles.loadingBox}>Loading...</div>}
        {error && <div style={styles.errorBox}>{error}</div>}

        {!loading && exams.length === 0 && (
          <div style={styles.emptyBox}>
            <p style={{ fontSize: "40px" }}>📋</p>
            <p style={{ fontWeight: "600", marginTop: "12px", color: "#E2E8F0" }}>No assessments available</p>
            <p style={{ color: "#64748B", fontSize: "14px", marginTop: "6px" }}>Check back later for upcoming assessments</p>
          </div>
        )}

        <div style={styles.examGrid}>
          {exams.map((exam) => (
            <div key={exam.id} style={styles.examCard}>
              <div style={styles.scanLine}></div>
              <div style={styles.examCardTop}>
                <div style={styles.examIcon}>📝</div>
                <div style={styles.examMeta}>
                  <span style={styles.metaTag}>⏱ {exam.duration_minutes} min</span>
                  <span style={styles.metaTag}>❓ {exam.questions.length} questions</span>
                  {exam.coding_problem_count > 0 && (
                    <span style={styles.metaTag}>💻 {exam.coding_problem_count} coding</span>
                  )}
                </div>
              </div>
              <h3 style={styles.examTitle}>{exam.title}</h3>
              <p style={styles.examDesc}>{exam.description}</p>
              <div style={styles.examFooter}>
                {userRole === "student" && (
                  <Link to={`/exam/${exam.id}`} style={styles.startBtn}>Start assessment →</Link>
                )}
                {userRole === "admin" && (
                  <div style={styles.adminBtnRow}>
                    <Link to={`/admin/exam/${exam.id}/results`} style={styles.resultsBtn}>Results</Link>
                    <Link to={`/admin/exam/${exam.id}/coding`} style={styles.codingBtn}>Coding</Link>
                    <Link to={`/admin/exam/${exam.id}/violations`} style={styles.violationsBtn}>Violations</Link>
                    <button onClick={() => handleDeleteExam(exam.id, exam.title)} style={styles.deleteBtn}>Delete</button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Student results */}
        {userRole === "student" && myResults.length > 0 && (
          <div style={styles.resultsSection}>
            <div style={styles.eyebrow}>YOUR RESULTS</div>
            <div style={styles.resultsList}>
              {myResults.map((r) => {
                const percent = Math.round((r.score / r.total_questions) * 100);
                const perf = percent >= 80
                  ? { label: "Excellent", color: "#10B981", bg: "#0C2E22", border: "#1A5943" }
                  : percent >= 50
                    ? { label: "Good", color: "#F59E0B", bg: "#2E2410", border: "#5B4718" }
                    : { label: "Needs work", color: "#EF4444", bg: "#2A1215", border: "#5B2121" };
                return (
                  <div key={r.id} style={styles.resultRow}>
                    <div style={{ flex: 1 }}>
                      <p style={styles.resultExam}>{r.exam_title}</p>
                      <p style={styles.resultDate}>
                        {new Date(r.submitted_at).toLocaleString()}
                      </p>
                    </div>
                    <div style={styles.resultScoreArea}>
                      <div style={styles.progressTrack}>
                        <div style={{ ...styles.progressFill, width: `${percent}%`, background: perf.color }} />
                      </div>
                      <span style={styles.resultScoreText}>{r.score}/{r.total_questions} · {percent}%</span>
                    </div>
                    <span style={{ ...styles.perfBadge, color: perf.color, background: perf.bg, border: `1px solid ${perf.border}` }}>
                      {perf.label}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  page: { minHeight: "100vh", background: "#0A0E1A" },
  navbar: {
    background: "#0C1120", borderBottom: "1px solid #1C2438",
    padding: "0 40px", height: "64px", display: "flex", alignItems: "center",
    justifyContent: "space-between", position: "sticky", top: 0, zIndex: 100,
  },
  navBrand: { display: "flex", alignItems: "center", gap: "10px" },
  navLogo: {
    width: "30px", height: "30px", borderRadius: "8px", background: "#0D2540",
    border: "1px solid #1E4E7A", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "15px",
  },
  navName: { fontSize: "18px", fontWeight: "600", color: "#F8FAFC", fontFamily: "'Space Grotesk', sans-serif" },
  navRight: { display: "flex", alignItems: "center", gap: "18px" },
  statusPill: {
    display: "flex", alignItems: "center", gap: "7px", fontSize: "12px", color: "#64748B",
    padding: "5px 12px", background: "#0F1524", border: "1px solid #1C2438", borderRadius: "20px",
  },
  statusDot: { width: "7px", height: "7px", borderRadius: "50%", background: "#10B981", boxShadow: "0 0 6px #10B981" },
  userInfo: { display: "flex", alignItems: "center", gap: "10px" },
  avatar: {
    width: "36px", height: "36px", borderRadius: "50%", background: "#0D2540",
    border: "1px solid #1E4E7A", color: "#22D3EE", display: "flex", alignItems: "center",
    justifyContent: "center", fontWeight: "600", fontSize: "14px",
  },
  userName: { fontSize: "13px", fontWeight: "600", color: "#E2E8F0", margin: 0 },
  userRole: { fontSize: "11px", color: "#64748B", margin: 0, textTransform: "capitalize" },
  logoutBtn: {
    padding: "8px 16px", background: "transparent", border: "1px solid #1E293B",
    borderRadius: "8px", fontSize: "13px", fontWeight: "500", color: "#94A3B8", cursor: "pointer",
  },
  main: { maxWidth: "1100px", margin: "0 auto", padding: "40px 20px" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "32px", flexWrap: "wrap", gap: "16px" },
  eyebrow: { fontFamily: "'Space Grotesk', sans-serif", color: "#334155", fontSize: "11px", letterSpacing: "2px", marginBottom: "10px" },
  title: { fontSize: "30px", fontWeight: "600", color: "#F8FAFC", marginBottom: "8px", letterSpacing: "-0.5px" },
  subtitle: { fontSize: "14px", color: "#64748B", maxWidth: "480px", lineHeight: "1.5" },
  adminActions: { display: "flex", gap: "10px", alignItems: "center" },
  createExamBtn: {
    padding: "10px 18px", background: "#22D3EE", color: "#04141C", borderRadius: "8px",
    textDecoration: "none", fontSize: "14px", fontWeight: "600", boxShadow: "0 0 16px rgba(34,211,238,0.25)",
  },
  manageBtn: {
    padding: "10px 18px", background: "#0F1524", color: "#94A3B8", border: "1px solid #1C2438",
    borderRadius: "8px", textDecoration: "none", fontSize: "14px", fontWeight: "500",
  },
  statsBar: { display: "flex", gap: "16px", marginBottom: "32px" },
  statCard: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "12px", padding: "20px 28px", minWidth: "150px" },
  statValue: { fontSize: "32px", fontWeight: "600", margin: 0, fontFamily: "'Space Grotesk', sans-serif" },
  statLabel: { fontSize: "12px", color: "#64748B", margin: "4px 0 0" },
  loadingBox: { textAlign: "center", padding: "60px", color: "#64748B" },
  errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "14px", borderRadius: "10px", marginBottom: "20px", fontSize: "13px", border: "1px solid #5B2121" },
  emptyBox: { textAlign: "center", padding: "80px 20px", background: "#0F1524", borderRadius: "16px", border: "1px solid #1C2438" },
  examGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "20px" },
  examCard: {
    background: "#0F1524", border: "1px solid #1C2438", borderRadius: "16px",
    padding: "24px", position: "relative", overflow: "hidden",
  },
  scanLine: { position: "absolute", top: 0, left: 0, right: 0, height: "1px", background: "linear-gradient(90deg, transparent, #22D3EE, transparent)" },
  examCardTop: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" },
  examIcon: { fontSize: "30px" },
  examMeta: { display: "flex", gap: "8px", flexWrap: "wrap", justifyContent: "flex-end" },
  metaTag: { background: "#0A0E1A", color: "#64748B", padding: "4px 10px", borderRadius: "20px", fontSize: "12px", fontWeight: "500", border: "1px solid #1C2438" },
  examTitle: { fontSize: "17px", fontWeight: "600", color: "#F8FAFC", marginBottom: "8px" },
  examDesc: { fontSize: "13px", color: "#64748B", marginBottom: "20px", lineHeight: "1.5" },
  examFooter: { borderTop: "1px solid #1C2438", paddingTop: "16px" },
  startBtn: {
    display: "inline-block", padding: "10px 20px", background: "#22D3EE", color: "#04141C",
    borderRadius: "8px", textDecoration: "none", fontSize: "14px", fontWeight: "600", boxShadow: "0 0 16px rgba(34,211,238,0.25)",
  },
  adminBtnRow: { display: "flex", gap: "8px", flexWrap: "wrap" },
  resultsBtn: { padding: "8px 14px", background: "#0D2540", color: "#22D3EE", border: "1px solid #1E4E7A", borderRadius: "8px", textDecoration: "none", fontSize: "13px", fontWeight: "600" },
  codingBtn: { padding: "8px 14px", background: "#1E1B3A", color: "#C4B5FD", border: "1px solid #4C3F91", borderRadius: "8px", textDecoration: "none", fontSize: "13px", fontWeight: "600" },
  violationsBtn: { padding: "8px 14px", background: "#2A1215", color: "#FCA5A5", border: "1px solid #5B2121", borderRadius: "8px", textDecoration: "none", fontSize: "13px", fontWeight: "600" },
  deleteBtn: { padding: "8px 14px", background: "transparent", color: "#64748B", border: "1px solid #1E293B", borderRadius: "8px", fontSize: "13px", fontWeight: "600", cursor: "pointer" },
  resultsSection: { marginTop: "48px" },
  resultsList: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "16px", overflow: "hidden" },
  resultRow: { display: "flex", alignItems: "center", gap: "24px", padding: "18px 24px", borderBottom: "1px solid #1C2438" },
  resultExam: { fontSize: "15px", fontWeight: "600", color: "#E2E8F0", margin: "0 0 4px" },
  resultDate: { fontSize: "12px", color: "#64748B", margin: 0 },
  resultScoreArea: { width: "200px" },
  progressTrack: { height: "8px", background: "#0A0E1A", borderRadius: "4px", overflow: "hidden", marginBottom: "6px", border: "1px solid #1C2438" },
  progressFill: { height: "100%", borderRadius: "4px" },
  resultScoreText: { fontSize: "13px", fontWeight: "600", color: "#94A3B8", margin: 0 },
  perfBadge: { padding: "6px 14px", borderRadius: "20px", fontSize: "12px", fontWeight: "600", whiteSpace: "nowrap" },
};

export default Dashboard;