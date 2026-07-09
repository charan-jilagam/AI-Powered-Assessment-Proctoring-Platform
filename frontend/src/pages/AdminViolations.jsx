import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { apiCall } from "../utils/api";

function AdminViolations() {
  const { examId } = useParams();
  const [violations, setViolations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    loadViolations();
  }, [examId]);

  async function loadViolations() {
    try {
      const data = await apiCall(`/exams/${examId}/violations`, "GET");
      setViolations(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // Group violations by student
  const byStudent = violations.reduce((acc, v) => {
    if (!acc[v.student_id]) acc[v.student_id] = [];
    acc[v.student_id].push(v);
    return acc;
  }, {});

  const level1Types = ["Attempted copy/paste/cut", "Attempted right-click", "Keyboard shortcut attempted"];
  const aiSevereKeywords = ["No face", "Multiple faces", "phone", "book", "laptop", "tv", "remote", "keyboard", "mouse", "Mobile"];

  function getViolationLevel(type) {
    // Browser Level 1 violations
    if (level1Types.includes(type)) return 1;

    // AI violations: severe keywords = level 2, soft signals = level 1
    if (type.startsWith("AI:")) {
      const isSevere = aiSevereKeywords.some(kw => type.toLowerCase().includes(kw.toLowerCase()));
      return isSevere ? 2 : 1;
    }

    // Browser Level 2 (tab switch, fullscreen exit)
    return 2;
  }

  return (
    <div style={styles.page}>
      {/* Navbar */}
      <nav style={styles.navbar}>
        <div style={styles.navBrand}>
          <span style={styles.navLogo}>🎓</span>
          <span style={styles.navName}>ProctorAI</span>
        </div>
        <Link to="/dashboard" style={styles.backBtn}>← Back to Dashboard</Link>
      </nav>

      <div style={styles.main}>
        {/* Header */}
        <div style={styles.header}>
          <div>
            <h1 style={styles.title}>Violation Report</h1>
            <p style={styles.subtitle}>Exam #{examId} — Security audit trail</p>
          </div>
          <div style={styles.summaryCards}>
            <div style={styles.summaryCard}>
              <p style={styles.summaryVal}>{violations.length}</p>
              <p style={styles.summaryLabel}>Total Violations</p>
            </div>
            <div style={styles.summaryCard}>
              <p style={styles.summaryVal}>{Object.keys(byStudent).length}</p>
              <p style={styles.summaryLabel}>Students Flagged</p>
            </div>
            <div style={{ ...styles.summaryCard, borderColor: "#5B2121" }}>
              <p style={{ ...styles.summaryVal, color: "#EF4444" }}>
                {violations.filter((v) => getViolationLevel(v.violation_type) === 2).length}
              </p>
              <p style={styles.summaryLabel}>Level 2 (Severe)</p>
            </div>
          </div>
        </div>
        <div style={styles.advisoryNote}>
          <span style={{ fontSize: "18px", marginRight: "8px" }}>ℹ️</span>
          <span>
            <strong>Advisory:</strong> AI-detected flags (gaze, lip movement, voice) are automated
            signals intended to assist human review — not definitive proof of misconduct. AI detection
            is not 100% accurate and can produce false positives. Please review flagged sessions
            in context before making decisions.
          </span>
        </div>

        {loading && <div style={styles.loadingBox}>Loading violations...</div>}
        {error && <div style={styles.errorBox}>{error}</div>}

        {!loading && violations.length === 0 && (
          <div style={styles.cleanBox}>
            <p style={{ fontSize: "48px" }}>✅</p>
            <p style={styles.cleanTitle}>No violations recorded</p>
            <p style={styles.cleanDesc}>All students had clean exam sessions</p>
          </div>
        )}

        {/* Violations by student */}
        {Object.entries(byStudent).map(([studentId, studentViolations]) => (
          <div key={studentId} style={styles.studentBlock}>
            <div style={styles.studentHeader}>
              <div style={styles.studentAvatar}>S{studentId}</div>
              <div>
                <p style={styles.studentTitle}>Student ID: {studentId}</p>
                <p style={styles.studentMeta}>
                  {studentViolations.length} violation{studentViolations.length !== 1 ? "s" : ""} recorded
                </p>
              </div>
              <div style={styles.riskBadge(studentViolations)}>
                {studentViolations.filter(v => getViolationLevel(v.violation_type) === 2).length >= 3
                  ? "🚫 Exam Terminated"
                  : studentViolations.length >= 3
                    ? "⚠️ High Risk"
                    : "🟡 Low Risk"}
              </div>
            </div>

            <table style={styles.table}>
              <thead>
                <tr style={styles.tableHead}>
                  <th style={styles.th}>Level</th>
                  <th style={styles.th}>Violation Type</th>
                  <th style={styles.th}>Time</th>
                </tr>
              </thead>
              <tbody>
                {studentViolations.map((v) => {
                  const level = getViolationLevel(v.violation_type);
                  return (
                    <tr key={v.id}>
                      <td style={styles.td}>
                        <span style={level === 1 ? styles.level1Badge : styles.level2Badge}>
                          Level {level}
                        </span>
                      </td>
                      <td style={styles.td}>{v.violation_type}</td>
                      <td style={{ ...styles.td, color: "#64748b", fontSize: "13px" }}>
                        {new Date(v.created_at).toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}

const styles = {
  page: { minHeight: "100vh", background: "#0A0E1A", fontFamily: "Inter, sans-serif" },
  navbar: { background: "#0C1120", borderBottom: "1px solid #1C2438", padding: "0 40px", height: "64px", display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, zIndex: 100 },
  navBrand: { display: "flex", alignItems: "center", gap: "10px" },
  navLogo: { fontSize: "24px" },
  navName: { fontSize: "18px", fontWeight: "600", color: "#F8FAFC", fontFamily: "'Space Grotesk', sans-serif" },
  backBtn: { color: "#22D3EE", textDecoration: "none", fontSize: "14px", fontWeight: "500" },
  main: { maxWidth: "1000px", margin: "0 auto", padding: "40px 20px" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "24px", flexWrap: "wrap", gap: "20px" },
  title: { fontSize: "28px", fontWeight: "600", color: "#F8FAFC", marginBottom: "4px", fontFamily: "'Space Grotesk', sans-serif" },
  subtitle: { fontSize: "14px", color: "#64748B" },
  summaryCards: { display: "flex", gap: "12px" },
  summaryCard: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "12px", padding: "16px 24px", textAlign: "center", minWidth: "110px" },
  summaryVal: { fontSize: "28px", fontWeight: "600", color: "#F8FAFC", margin: 0, fontFamily: "'Space Grotesk', sans-serif" },
  summaryLabel: { fontSize: "11px", color: "#64748B", margin: "4px 0 0" },
  advisoryNote: { display: "flex", alignItems: "flex-start", gap: "4px", background: "#0D2540", border: "1px solid #1E4E7A", borderRadius: "12px", padding: "14px 18px", marginBottom: "24px", fontSize: "13px", color: "#7DD3FC", lineHeight: "1.6" },
  loadingBox: { textAlign: "center", padding: "60px", color: "#64748B" },
  errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "14px", borderRadius: "10px", marginBottom: "20px", fontSize: "13px", border: "1px solid #5B2121" },
  cleanBox: { textAlign: "center", padding: "80px 20px", background: "#0F1524", borderRadius: "16px", border: "1px solid #1C2438" },
  cleanTitle: { fontSize: "20px", fontWeight: "700", color: "#F8FAFC", marginTop: "12px" },
  cleanDesc: { fontSize: "14px", color: "#64748B", marginTop: "6px" },
  studentBlock: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "16px", marginBottom: "20px", overflow: "hidden" },
  studentHeader: { display: "flex", alignItems: "center", gap: "14px", padding: "20px 24px", borderBottom: "1px solid #1C2438", background: "#0C1120" },
  studentAvatar: { width: "40px", height: "40px", borderRadius: "50%", background: "#0D2540", border: "1px solid #1E4E7A", color: "#22D3EE", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: "700", fontSize: "13px", flexShrink: 0 },
  studentTitle: { fontWeight: "600", fontSize: "14px", color: "#F8FAFC", margin: 0 },
  studentMeta: { fontSize: "12px", color: "#64748B", margin: "2px 0 0" },
  riskBadge: (violations) => ({
    marginLeft: "auto", padding: "6px 14px", borderRadius: "20px", fontSize: "12px", fontWeight: "600",
    background: violations.length >= 3 ? "#2A1215" : "#2E2410",
    color: violations.length >= 3 ? "#FCA5A5" : "#FCD34D",
    border: violations.length >= 3 ? "1px solid #5B2121" : "1px solid #5B4718",
  }),
  table: { width: "100%", borderCollapse: "collapse" },
  tableHead: { background: "#0C1120" },
  th: { textAlign: "left", padding: "12px 24px", fontSize: "12px", fontWeight: "600", color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid #1C2438" },
  td: { padding: "14px 24px", fontSize: "14px", color: "#E2E8F0", borderBottom: "1px solid #1C2438" },
  level1Badge: { background: "#0C2E22", color: "#6EE7B7", padding: "3px 10px", borderRadius: "20px", fontSize: "12px", fontWeight: "600", border: "1px solid #1A5943" },
  level2Badge: { background: "#2A1215", color: "#FCA5A5", padding: "3px 10px", borderRadius: "20px", fontSize: "12px", fontWeight: "600", border: "1px solid #5B2121" },
};

export default AdminViolations;