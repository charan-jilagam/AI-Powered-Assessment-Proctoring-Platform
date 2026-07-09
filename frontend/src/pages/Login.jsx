import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiCall, setToken } from "../utils/api";

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState("");
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await apiCall("/auth/login", "POST", { email, password });
      setToken(data.access_token);
      navigate("/dashboard");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={styles.page}>
      {/* Left: brand + live monitoring showcase */}
      <div style={styles.left}>
        <div style={styles.brandRow}>
          <div style={styles.logoBox}>🛡️</div>
          <span style={styles.brandName}>ProctorAI</span>
        </div>

        <div style={styles.leftContent}>
          <div style={styles.eyebrow}>SECURE ASSESSMENT PLATFORM</div>
          <h1 style={styles.headline}>
            Assessments you<br />can actually trust
          </h1>
          <p style={styles.subhead}>
            Real-time AI monitoring, browser lockdown, and full candidate
            analytics — in one secure console.
          </p>

          <div style={styles.features}>
            <div style={styles.featureRow}>
              <div style={{ ...styles.featureIcon, color: "#22D3EE", background: "#0D2540", borderColor: "#1E4E7A" }}>👁️</div>
              <div>
                <div style={styles.featureTitle}>Face &amp; gaze tracking</div>
                <div style={styles.featureDesc}>MediaPipe vision engine</div>
              </div>
            </div>
            <div style={styles.featureRow}>
              <div style={{ ...styles.featureIcon, color: "#A78BFA", background: "#1E1B3A", borderColor: "#4C3F91" }}>📵</div>
              <div>
                <div style={styles.featureTitle}>Object detection</div>
                <div style={styles.featureDesc}>YOLOv8 real-time scan</div>
              </div>
            </div>
            <div style={styles.featureRow}>
              <div style={{ ...styles.featureIcon, color: "#10B981", background: "#0C2E22", borderColor: "#1A5943" }}>🔒</div>
              <div>
                <div style={styles.featureTitle}>Browser lockdown</div>
                <div style={styles.featureDesc}>Tab, copy &amp; fullscreen guard</div>
              </div>
            </div>
          </div>
        </div>

        <div style={styles.statusRow}>
          <span style={styles.statusDot}></span>
          <span style={styles.statusText}>System active · All detectors online</span>
        </div>
      </div>

      {/* Right: login form */}
      <div style={styles.right}>
        <div style={styles.card}>
          <div style={styles.eyebrowSmall}>SECURE ACCESS</div>
          <h2 style={styles.cardTitle}>Welcome back</h2>
          <p style={styles.cardSub}>Sign in to your assessment console</p>

          {error && (
            <div style={styles.error}>
              <span>⚠</span> {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div style={styles.field}>
              <label style={styles.label}>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={() => setFocused("email")}
                onBlur={() => setFocused("")}
                style={{ ...styles.input, ...(focused === "email" ? styles.inputFocus : {}) }}
                placeholder="candidate@company.com"
                required
              />
            </div>

            <div style={styles.field}>
              <label style={styles.label}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setFocused("password")}
                onBlur={() => setFocused("")}
                style={{ ...styles.input, ...(focused === "password" ? styles.inputFocus : {}) }}
                placeholder="••••••••••"
                required
              />
            </div>

            <button type="submit" style={styles.button} disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>

          <p style={styles.linkText}>
            Don't have an account?{" "}
            <Link to="/signup" style={styles.link}>Create one</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: { display: "flex", minHeight: "100vh", background: "#0A0E1A" },
  left: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    padding: "40px 48px",
    borderRight: "1px solid #1C2438",
    background: "#0C1120",
  },
  brandRow: { display: "flex", alignItems: "center", gap: "11px" },
  logoBox: {
    width: "34px", height: "34px", borderRadius: "9px",
    background: "#0D2540", border: "1px solid #1E4E7A",
    display: "flex", alignItems: "center", justifyContent: "center", fontSize: "17px",
  },
  brandName: { color: "#F8FAFC", fontSize: "18px", fontWeight: "600", fontFamily: "'Space Grotesk', sans-serif", letterSpacing: "0.3px" },
  leftContent: { maxWidth: "440px" },
  eyebrow: { fontFamily: "'Space Grotesk', sans-serif", color: "#334155", fontSize: "12px", letterSpacing: "2px", marginBottom: "18px" },
  headline: { fontSize: "38px", fontWeight: "600", color: "#F8FAFC", lineHeight: "1.15", letterSpacing: "-0.5px", marginBottom: "16px" },
  subhead: { color: "#64748B", fontSize: "15px", lineHeight: "1.6", marginBottom: "40px" },
  features: { display: "flex", flexDirection: "column", gap: "14px" },
  featureRow: { display: "flex", alignItems: "center", gap: "14px" },
  featureIcon: {
    width: "42px", height: "42px", borderRadius: "11px", border: "1px solid",
    display: "flex", alignItems: "center", justifyContent: "center", fontSize: "18px", flexShrink: 0,
  },
  featureTitle: { color: "#E2E8F0", fontSize: "14px", fontWeight: "600" },
  featureDesc: { color: "#64748B", fontSize: "12px", marginTop: "2px" },
  statusRow: { display: "flex", alignItems: "center", gap: "9px" },
  statusDot: { width: "8px", height: "8px", borderRadius: "50%", background: "#10B981", boxShadow: "0 0 8px #10B981" },
  statusText: { color: "#475569", fontSize: "12px" },
  right: { width: "480px", display: "flex", alignItems: "center", justifyContent: "center", padding: "40px" },
  card: {
    width: "100%", maxWidth: "380px",
    background: "#0F1524", border: "1px solid #1C2438",
    borderRadius: "16px", padding: "36px",
  },
  eyebrowSmall: { fontFamily: "'Space Grotesk', sans-serif", color: "#334155", fontSize: "11px", letterSpacing: "2px", marginBottom: "14px" },
  cardTitle: { fontSize: "24px", fontWeight: "600", color: "#F8FAFC", marginBottom: "6px" },
  cardSub: { color: "#64748B", fontSize: "13px", marginBottom: "28px" },
  field: { marginBottom: "18px" },
  label: { display: "block", color: "#94A3B8", fontSize: "12px", fontWeight: "500", marginBottom: "7px" },
  input: {
    width: "100%", padding: "12px 14px", borderRadius: "9px",
    border: "1px solid #1E293B", background: "#0A0E1A", color: "#E2E8F0",
    fontSize: "14px", outline: "none", boxSizing: "border-box", transition: "all 0.15s",
  },
  inputFocus: { border: "1px solid #22D3EE", boxShadow: "0 0 0 3px rgba(34,211,238,0.1)" },
  button: {
    width: "100%", padding: "13px", marginTop: "8px",
    background: "#22D3EE", color: "#04141C", border: "none",
    borderRadius: "9px", fontSize: "14px", fontWeight: "600", cursor: "pointer",
    boxShadow: "0 0 20px rgba(34,211,238,0.3)", transition: "all 0.15s",
  },
  error: {
    display: "flex", alignItems: "center", gap: "8px",
    background: "#2A1215", color: "#FCA5A5", padding: "11px 14px",
    borderRadius: "9px", marginBottom: "18px", fontSize: "13px", border: "1px solid #5B2121",
  },
  linkText: { textAlign: "center", marginTop: "22px", fontSize: "13px", color: "#64748B" },
  link: { color: "#22D3EE", fontWeight: "500", textDecoration: "none" },
};

export default Login;