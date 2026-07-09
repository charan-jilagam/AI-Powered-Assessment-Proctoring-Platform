import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { apiCall } from "../utils/api";

function AdminResults() {
    const { examId } = useParams();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        loadResults();
    }, [examId]);

    async function loadResults() {
        try {
            const res = await apiCall(`/exams/${examId}/results`, "GET");
            setData(res);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    function scoreColor(pct) {
        if (pct >= 80) return "#16a34a";
        if (pct >= 50) return "#ca8a04";
        return "#dc2626";
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
                {loading && <div style={styles.loadingBox}>Loading results...</div>}
                {error && <div style={styles.errorBox}>{error}</div>}

                {data && (
                    <>
                        <div style={styles.header}>
                            <div>
                                <h1 style={styles.title}>Candidate Results</h1>
                                <p style={styles.subtitle}>{data.exam_title}</p>
                            </div>
                            <div style={styles.summaryCard}>
                                <p style={styles.summaryVal}>{data.total_candidates}</p>
                                <p style={styles.summaryLabel}>Total Candidates</p>
                            </div>
                        </div>

                        {data.results.length === 0 && (
                            <div style={styles.emptyBox}>
                                <p style={{ fontSize: "40px" }}>📊</p>
                                <p style={{ fontWeight: "600", marginTop: "12px" }}>No submissions yet</p>
                                <p style={{ color: "#64748b", fontSize: "14px", marginTop: "6px" }}>
                                    Results will appear here once candidates complete the exam
                                </p>
                            </div>
                        )}

                        {data.results.length > 0 && (
                            <div style={styles.tableWrap}>
                                <table style={styles.table}>
                                    <thead>
                                        <tr style={styles.tableHead}>
                                            <th style={styles.th}>Rank</th>
                                            <th style={styles.th}>Candidate</th>
                                            <th style={styles.th}>Score</th>
                                            <th style={styles.th}>Result</th>
                                            <th style={styles.th}>Violations</th>
                                            <th style={styles.th}>Status</th>
                                            <th style={styles.th}>Submitted</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.results.map((r, index) => (
                                            <tr key={r.student_id}>
                                                <td style={styles.td}>
                                                    <span style={styles.rankBadge}>#{index + 1}</span>
                                                </td>
                                                <td style={styles.td}>
                                                    <div style={styles.candidateName}>{r.student_name}</div>
                                                    <div style={styles.candidateEmail}>{r.student_email}</div>
                                                </td>
                                                <td style={styles.td}>
                                                    <span style={{ fontWeight: "700", color: scoreColor(r.percentage) }}>
                                                        {r.score}/{r.total_questions}
                                                    </span>
                                                </td>
                                                <td style={styles.td}>
                                                    <div style={styles.progressTrack}>
                                                        <div style={{
                                                            ...styles.progressFill,
                                                            width: `${r.percentage}%`,
                                                            background: scoreColor(r.percentage),
                                                        }} />
                                                    </div>
                                                    <span style={styles.pctText}>{r.percentage}%</span>
                                                </td>
                                                <td style={styles.td}>
                                                    <span style={{
                                                        ...styles.violationBadge,
                                                        background: r.violation_count > 0 ? "#2A1215" : "#0C2E22",
                                                        color: r.violation_count > 0 ? "#FCA5A5" : "#6EE7B7",
                                                    }}>
                                                        {r.violation_count}
                                                    </span>
                                                </td>
                                                <td style={styles.td}>
                                                    {r.terminated ? (
                                                        <span style={styles.terminatedBadge}>Terminated</span>
                                                    ) : (
                                                        <span style={styles.completedBadge}>Completed</span>
                                                    )}
                                                </td>
                                                <td style={{ ...styles.td, color: "#64748b", fontSize: "13px" }}>
                                                    {new Date(r.submitted_at).toLocaleString()}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </>
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
    main: { maxWidth: "1100px", margin: "0 auto", padding: "40px 20px" },
    header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "32px" },
    title: { fontSize: "28px", fontWeight: "600", color: "#F8FAFC", marginBottom: "4px", fontFamily: "'Space Grotesk', sans-serif" },
    subtitle: { fontSize: "14px", color: "#64748B" },
    summaryCard: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "12px", padding: "16px 28px", textAlign: "center" },
    summaryVal: { fontSize: "28px", fontWeight: "600", color: "#22D3EE", margin: 0, fontFamily: "'Space Grotesk', sans-serif" },
    summaryLabel: { fontSize: "11px", color: "#64748B", margin: "4px 0 0" },
    loadingBox: { textAlign: "center", padding: "60px", color: "#64748B" },
    errorBox: { background: "#2A1215", color: "#FCA5A5", padding: "14px", borderRadius: "10px", fontSize: "13px", border: "1px solid #5B2121" },
    emptyBox: { textAlign: "center", padding: "80px 20px", background: "#0F1524", borderRadius: "16px", border: "1px solid #1C2438" },
    tableWrap: { background: "#0F1524", border: "1px solid #1C2438", borderRadius: "16px", overflow: "hidden" },
    table: { width: "100%", borderCollapse: "collapse" },
    tableHead: { background: "#0C1120" },
    th: { textAlign: "left", padding: "14px 20px", fontSize: "12px", fontWeight: "600", color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid #1C2438" },
    td: { padding: "16px 20px", fontSize: "14px", color: "#E2E8F0", borderBottom: "1px solid #1C2438" },
    rankBadge: { fontWeight: "700", color: "#64748B", fontFamily: "'Space Grotesk', sans-serif" },
    candidateName: { fontWeight: "600", color: "#F8FAFC" },
    candidateEmail: { fontSize: "12px", color: "#64748B", marginTop: "2px" },
    progressTrack: { height: "6px", background: "#0A0E1A", borderRadius: "3px", overflow: "hidden", marginBottom: "4px", width: "100px", border: "1px solid #1C2438" },
    progressFill: { height: "100%", borderRadius: "3px" },
    pctText: { fontSize: "12px", fontWeight: "600", color: "#64748B" },
    violationBadge: { display: "inline-block", padding: "4px 12px", borderRadius: "20px", fontSize: "13px", fontWeight: "700" },
    terminatedBadge: { background: "#2A1215", color: "#FCA5A5", padding: "4px 12px", borderRadius: "20px", fontSize: "12px", fontWeight: "600", border: "1px solid #5B2121" },
    completedBadge: { background: "#0C2E22", color: "#6EE7B7", padding: "4px 12px", borderRadius: "20px", fontSize: "12px", fontWeight: "600", border: "1px solid #1A5943" },
};

export default AdminResults;