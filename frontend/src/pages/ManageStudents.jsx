import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { apiCall, getToken } from "../utils/api";

const API_URL = "http://localhost:8000";

function ManageStudents() {
    const [students, setStudents] = useState([]);
    const [exams, setExams] = useState([]);
    const [selectedExam, setSelectedExam] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [message, setMessage] = useState("");

    useEffect(() => {
        loadData();
    }, []);

    async function loadData() {
        try {
            const studentData = await apiCall("/admin/students", "GET");
            setStudents(studentData);
            const examData = await apiCall("/exams/available", "GET");
            setExams(examData);
            if (examData.length > 0) setSelectedExam(examData[0].id);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    function showMessage(text) {
        setMessage(text);
        setTimeout(() => setMessage(""), 4000);
    }

    // These per-exam actions need exam_id as a query parameter
    async function resetAttempt(studentId, studentName) {
        if (!selectedExam) {
            showMessage("Please select an exam first.");
            return;
        }
        if (!window.confirm(`Reset ${studentName}'s attempt for this exam? They will be able to retake it.`)) return;
        try {
            const res = await fetch(`${API_URL}/admin/students/${studentId}/reset-attempt?exam_id=${selectedExam}`, {
                method: "POST",
                headers: { "Authorization": `Bearer ${getToken()}` },
            });
            if (!res.ok) throw new Error("Reset failed");
            showMessage(`${studentName}'s attempt was reset.`);
            loadData();
        } catch (err) {
            showMessage("Error: " + err.message);
        }
    }

    async function deleteResult(studentId, studentName) {
        if (!selectedExam) {
            showMessage("Please select an exam first.");
            return;
        }
        if (!window.confirm(`Delete ${studentName}'s result for this exam?`)) return;
        try {
            const res = await fetch(`${API_URL}/admin/students/${studentId}/result?exam_id=${selectedExam}`, {
                method: "DELETE",
                headers: { "Authorization": `Bearer ${getToken()}` },
            });
            if (!res.ok) throw new Error("Delete failed");
            showMessage(`${studentName}'s result was deleted.`);
            loadData();
        } catch (err) {
            showMessage("Error: " + err.message);
        }
    }

    async function deleteAccount(studentId, studentName) {
        if (!window.confirm(`Permanently delete ${studentName}'s account and ALL their data everywhere? This cannot be undone.`)) return;
        try {
            await apiCall(`/admin/students/${studentId}`, "DELETE");
            showMessage(`${studentName}'s account was deleted.`);
            loadData();
        } catch (err) {
            showMessage("Error: " + err.message);
        }
    }

    return (
        <div style={styles.page}>
            <nav style={styles.navbar}>
                <div style={styles.navBrand}>
                    <span style={styles.navLogo}>🎓</span>
                    <span style={styles.navName}>ProctorAI</span>
                </div>
                <Link to="/dashboard" style={styles.backBtn}>← Back to Dashboard</Link>
            </nav>

            <div style={styles.main}>
                <h1 style={styles.title}>Manage Students</h1>
                <p style={styles.subtitle}>Reset attempts, delete results, or remove student accounts</p>

                {message && <div style={styles.messageBox}>{message}</div>}
                {error && <div style={styles.errorBox}>{error}</div>}

                {/* Exam selector for per-exam actions */}
                <div style={styles.selectorCard}>
                    <label style={styles.label}>Exam for "Reset Attempt" and "Delete Result" actions:</label>
                    <select value={selectedExam} onChange={(e) => setSelectedExam(e.target.value)} style={styles.select}>
                        {exams.map((ex) => (
                            <option key={ex.id} value={ex.id}>{ex.title}</option>
                        ))}
                    </select>
                </div>

                {loading && <div style={styles.loadingBox}>Loading students...</div>}

                {!loading && students.length === 0 && (
                    <div style={styles.emptyBox}>No student accounts found.</div>
                )}

                {students.length > 0 && (
                    <div style={styles.tableWrap}>
                        <table style={styles.table}>
                            <thead>
                                <tr style={styles.tableHead}>
                                    <th style={styles.th}>Student</th>
                                    <th style={styles.th}>Submissions</th>
                                    <th style={styles.th}>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {students.map((s) => (
                                    <tr key={s.id}>
                                        <td style={styles.td}>
                                            <div style={styles.studentName}>{s.full_name}</div>
                                            <div style={styles.studentEmail}>{s.email}</div>
                                        </td>
                                        <td style={styles.td}>
                                            <span style={styles.countBadge}>{s.submission_count}</span>
                                        </td>
                                        <td style={styles.td}>
                                            <div style={styles.actionRow}>
                                                <button onClick={() => resetAttempt(s.id, s.full_name)} style={styles.resetBtn}>
                                                    Reset Attempt
                                                </button>
                                                <button onClick={() => deleteResult(s.id, s.full_name)} style={styles.resultBtn}>
                                                    Delete Result
                                                </button>
                                                <button onClick={() => deleteAccount(s.id, s.full_name)} style={styles.accountBtn}>
                                                    Delete Account
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
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
    main: { maxWidth: "900px", margin: "0 auto", padding: "40px 20px" },
    title: { fontSize: "28px", fontWeight: "600", color: "#F8FAFC", marginBottom: "4px", fontFamily: "'Space Grotesk', sans-serif" },
    subtitle: { fontSize: "14px", color: "#64748B", marginBottom: "24px" },
    messageBox: { background: "#0C2E22", color: "#6EE7B7", padding: "12px", borderRadius: "10px", marginBottom: "16px", fontSize: "14px", border: "1px solid #1A5943" },
    errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "12px", borderRadius: "10px", marginBottom: "16px", fontSize: "14px", border: "1px solid #5B2121" },
    selectorCard: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "12px", padding: "16px 20px", marginBottom: "20px" },
    label: { display: "block", fontSize: "13px", fontWeight: "600", color: "#94A3B8", marginBottom: "8px" },
    select: { width: "100%", padding: "10px 12px", borderRadius: "8px", border: "1px solid #1E293B", background: "#0A0E1A", color: "#E2E8F0", fontSize: "14px", fontFamily: "Inter, sans-serif", outline: "none" },
    loadingBox: { textAlign: "center", padding: "40px", color: "#64748B" },
    emptyBox: { textAlign: "center", padding: "40px", background: "#0F1524", borderRadius: "12px", border: "1px solid #1C2438", color: "#64748B" },
    tableWrap: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "16px", overflow: "hidden" },
    table: { width: "100%", borderCollapse: "collapse" },
    tableHead: { background: "#0C1120" },
    th: { textAlign: "left", padding: "14px 20px", fontSize: "12px", fontWeight: "600", color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid #1C2438" },
    td: { padding: "16px 20px", fontSize: "14px", color: "#E2E8F0", borderBottom: "1px solid #1C2438" },
    studentName: { fontWeight: "600", color: "#F8FAFC" },
    studentEmail: { fontSize: "12px", color: "#64748B", marginTop: "2px" },
    countBadge: { display: "inline-block", background: "#0D2540", color: "#22D3EE", padding: "4px 12px", borderRadius: "20px", fontSize: "13px", fontWeight: "700", border: "1px solid #1E4E7A" },
    actionRow: { display: "flex", gap: "8px", flexWrap: "wrap" },
    resetBtn: { padding: "8px 12px", background: "#0D2540", color: "#22D3EE", border: "1px solid #1E4E7A", borderRadius: "8px", fontSize: "12px", fontWeight: "600", cursor: "pointer" },
    resultBtn: { padding: "8px 12px", background: "#2E2410", color: "#FCD34D", border: "1px solid #5B4718", borderRadius: "8px", fontSize: "12px", fontWeight: "600", cursor: "pointer" },
    accountBtn: { padding: "8px 12px", background: "#2A1215", color: "#FCA5A5", border: "1px solid #5B2121", borderRadius: "8px", fontSize: "12px", fontWeight: "600", cursor: "pointer" },
};

export default ManageStudents;