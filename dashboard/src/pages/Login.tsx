import { FormEvent, useState } from "react";
import { Session, api } from "../api";
import { Dict } from "../i18n";

export function Login({ t, onLogin }: { t: Dict; onLogin: (s: Session) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.login(email, password));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel login-card">
      <h1>{t.appName}</h1>
      <p className="muted">{t.tagline}</p>
      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}
      <form onSubmit={submit}>
        <label htmlFor="login-email">{t.email}</label>
        <input
          id="login-email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <label htmlFor="login-password">{t.password}</label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <div style={{ marginTop: 14 }}>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? t.signingIn : t.signIn}
          </button>
        </div>
      </form>
    </div>
  );
}