import { useCallback, useEffect, useState } from "react";
import { ApiError, Session, api, setCsrf } from "./api";
import { DICTS, LANGS, Lang, initialLang } from "./i18n";
import { Documents } from "./pages/Documents";
import { Crawl } from "./pages/Crawl";
import { Evaluation } from "./pages/Evaluation";
import { Handoffs } from "./pages/Handoffs";
import { Login } from "./pages/Login";
import { Questions } from "./pages/Questions";
import { Ratings } from "./pages/Ratings";
import { SettingsPage } from "./pages/Settings";

type Page =
  | "documents"
  | "website"
  | "questions"
  | "ratings"
  | "handoffs"
  | "evaluation"
  | "settings";

export function App() {
  const [lang, setLang] = useState<Lang>(initialLang);
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [page, setPage] = useState<Page>("documents");
  const [error, setError] = useState("");
  const t = DICTS[lang];

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    localStorage.setItem("sanad-lang", lang);
  }, [lang]);

  useEffect(() => {
    api
      .me()
      .then((s) => {
        setCsrf(s.csrf_token);
        setSession(s);
      })
      .catch(() => undefined)
      .finally(() => setReady(true));
  }, []);

  const onError = useCallback((e: unknown) => {
    setError(e instanceof ApiError ? e.message : String(e));
  }, []);

  const onLogin = useCallback((s: Session) => {
    setCsrf(s.csrf_token);
    setSession(s);
    setError("");
  }, []);

  const onLogout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Session may already be expired; clearing locally is enough.
    }
    setCsrf("");
    setSession(null);
    setPage("documents");
  }, []);

  if (!ready) return <div className="app">{t.loading}</div>;

  if (!session) {
    return (
      <div className="app">
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <LangPicker lang={lang} setLang={setLang} />
        </div>
        <Login t={t} onLogin={onLogin} />
      </div>
    );
  }

  const isOwner = session.user.role === "owner";
  const tabs: { id: Page; label: string }[] = [
    { id: "documents", label: t.documents },
    { id: "website", label: t.website },
    { id: "questions", label: t.questions },
    { id: "ratings", label: t.ratings },
    { id: "handoffs", label: t.handoffs },
    { id: "evaluation", label: t.evaluation },
    { id: "settings", label: t.settings },
  ];

  return (
    <div className="app">
      <header className="top">
        <h1>{t.appName}</h1>
        <span className="company">
          {session.company.name} · {session.user.email}{" "}
          {!isOwner && <span className="badge">{t.readOnly}</span>}
        </span>
        <span className="spacer" />
        <LangPicker lang={lang} setLang={setLang} />
        <button className="ghost" onClick={onLogout}>
          {t.signOut}
        </button>
      </header>
      {error && (
        <div className="banner error" role="alert">
          <button className="ghost" onClick={() => setError("")}>
            {t.dismiss}
          </button>
          {error}
        </div>
      )}
      <nav className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={page === tab.id ? "active" : ""}
            onClick={() => setPage(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      {page === "documents" && <Documents t={t} isOwner={isOwner} onError={onError} />}
      {page === "website" && <Crawl t={t} lang={lang} isOwner={isOwner} onError={onError} />}
      {page === "questions" && <Questions t={t} lang={lang} onError={onError} />}
      {page === "ratings" && <Ratings t={t} lang={lang} onError={onError} />}
      {page === "handoffs" && <Handoffs t={t} lang={lang} onError={onError} />}
      {page === "evaluation" && <Evaluation t={t} isOwner={isOwner} onError={onError} />}
      {page === "settings" && <SettingsPage t={t} isOwner={isOwner} onError={onError} />}
    </div>
  );
}

function LangPicker({ lang, setLang }: { lang: Lang; setLang: (l: Lang) => void }) {
  return (
    <select
      aria-label="Language"
      value={lang}
      onChange={(e) => setLang(e.target.value as Lang)}
      style={{ width: "auto" }}
    >
      {LANGS.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  );
}