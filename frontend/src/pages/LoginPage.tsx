import { useState, type FormEvent } from "react";
import { api, toErrorInfo } from "../api";
import { useAuth } from "../auth";
import ErrorNotice from "../components/ErrorNotice";
import Logo from "../components/Logo";
import type { ErrorInfo } from "../types";

export default function LoginPage() {
  const { setUser } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { user } = await (mode === "login" ? api.login : api.register)(username, password);
      setUser(user);
    } catch (err) {
      setError(toErrorInfo(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-screen">
      <form className="card auth-card" onSubmit={submit}>
        <Logo />
        <h1>{mode === "login" ? "Sign in" : "Create your account"}</h1>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" required />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
          />
        </label>
        {error && <ErrorNotice error={error} />}
        <button className="primary" disabled={busy || !username || !password}>
          {busy ? <span className="spinner small" /> : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          className="link"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "No account? Create one" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
