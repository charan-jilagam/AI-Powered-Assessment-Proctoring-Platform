import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiCall, setToken } from "../utils/api";

function Signup() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await apiCall("/auth/signup", "POST", {
    full_name: fullName,
    email,
    password,
});
      const loginData = await apiCall("/auth/login", "POST", { email, password });
      setToken(loginData.access_token);
      navigate("/dashboard");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.left}>
        <div style={styles.brand}>
          <div style={styles.logo}>🎓</div>
          <h1 style={styles.brandName}>PlaceMux</h1>
          <p style={styles.brandTagline}>Secure. Smart. Reliable.</p>
        </div>
        <div style={styles.infoBox}>
          <h3 style={styles.infoTitle}>Why PlaceMux?</h3>
          <ul style={styles.infoList}>
            <li>✅ AI-powered face detection</li>
            <li>✅ Real-time gaze tracking</li>
            <li>✅ Browser security enforcement</li>
            <li>✅ Detailed violation reports</li>
            <li>✅ Secure exam environment</li>
          </ul>
        </div>
      </div>

      <div style={styles.right}>
        <div style={styles.card}>
          <h2 style={styles.title}>Create your account</h2>
          <p style={styles.subtitle}>Join ProctorAI today</p>

          {error && <div style={styles.error}>{error}</div>}

          <form onSubmit={handleSubmit}>
            <div style={styles.field}>
              <label style={styles.label}>Full Name</label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                style={styles.input}
                placeholder="John Doe"
                required
              />
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Email address</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={styles.input}
                placeholder="you@example.com"
                required
              />
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={styles.input}
                placeholder="••••••••"
                required
              />
            </div>

            
            <button type="submit" style={styles.button} disabled={loading}>
              {loading ? "Creating account..." : "Create Account →"}
            </button>
          </form>

          <p style={styles.linkText}>
            Already have an account?{" "}
            <Link to="/login" style={styles.link}>Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: {
    display: "flex",
    minHeight: "100vh",
  },
  left: {
    flex: 1,
    background: "linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%)",
    display: "flex",
    flexDirection: "column",
    justifyContent: "center",
    padding: "60px",
    color: "white",
  },
  brand: { marginBottom: "48px" },
  logo: { fontSize: "48px", marginBottom: "12px" },
  brandName: { fontSize: "36px", fontWeight: "700", marginBottom: "8px" },
  brandTagline: { fontSize: "16px", opacity: 0.8 },
  infoBox: {
    background: "rgba(255,255,255,0.1)",
    borderRadius: "12px",
    padding: "24px",
    backdropFilter: "blur(10px)",
  },
  infoTitle: {
    fontSize: "16px",
    fontWeight: "600",
    marginBottom: "16px",
  },
  infoList: {
    listStyle: "none",
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    fontSize: "14px",
    opacity: 0.9,
  },
  right: {
    width: "480px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "40px",
    background: "#f8fafc",
  },
  card: {
    width: "100%",
    background: "white",
    borderRadius: "16px",
    padding: "40px",
    boxShadow: "0 4px 24px rgba(0,0,0,0.08)",
  },
  title: {
    fontSize: "24px",
    fontWeight: "700",
    marginBottom: "6px",
    color: "#1e293b",
  },
  subtitle: {
    fontSize: "14px",
    color: "#64748b",
    marginBottom: "28px",
  },
  field: { marginBottom: "20px" },
  label: {
    display: "block",
    fontSize: "13px",
    fontWeight: "600",
    color: "#374151",
    marginBottom: "6px",
  },
  input: {
    width: "100%",
    padding: "11px 14px",
    borderRadius: "8px",
    border: "1.5px solid #e2e8f0",
    fontSize: "14px",
    color: "#1e293b",
    outline: "none",
  },
  roleSelector: {
    display: "flex",
    gap: "10px",
  },
  roleBtn: {
    flex: 1,
    padding: "10px",
    border: "1.5px solid #e2e8f0",
    borderRadius: "8px",
    background: "white",
    fontSize: "14px",
    cursor: "pointer",
    fontWeight: "500",
    color: "#64748b",
  },
  roleBtnActive: {
    border: "1.5px solid #2563eb",
    background: "#eff6ff",
    color: "#2563eb",
  },
  button: {
    width: "100%",
    padding: "12px",
    background: "linear-gradient(135deg, #2563eb, #1d4ed8)",
    color: "white",
    border: "none",
    borderRadius: "8px",
    fontSize: "15px",
    fontWeight: "600",
    cursor: "pointer",
    marginTop: "8px",
    letterSpacing: "0.3px",
  },
  error: {
    background: "#fef2f2",
    color: "#dc2626",
    padding: "12px",
    borderRadius: "8px",
    marginBottom: "20px",
    fontSize: "13px",
    border: "1px solid #fecaca",
  },
  linkText: {
    textAlign: "center",
    marginTop: "20px",
    fontSize: "13px",
    color: "#64748b",
  },
  link: {
    color: "#2563eb",
    fontWeight: "600",
    textDecoration: "none",
  },
};

export default Signup;