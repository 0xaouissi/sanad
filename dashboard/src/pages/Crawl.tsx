import { useCallback, useEffect, useState } from "react";
import { CrawlSource, api } from "../api";
import { Dict, Lang } from "../i18n";

const STATUS_LABEL: Record<CrawlSource["status"], keyof Dict> = {
  pending: "statusPending",
  crawling: "statusCrawling",
  ready: "statusReady",
  failed: "statusFailed",
};

const STATUS_CLASS: Record<CrawlSource["status"], string> = {
  pending: "pending",
  crawling: "processing",
  ready: "ready",
  failed: "failed",
};

export function Crawl({
  t,
  lang,
  isOwner,
  onError,
}: {
  t: Dict;
  lang: Lang;
  isOwner: boolean;
  onError: (e: unknown) => void;
}) {
  const [sources, setSources] = useState<CrawlSource[] | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .crawlSources()
      .then(setSources)
      .catch(onError);
  }, [onError]);

  useEffect(() => {
    load();
  }, [load]);

  const active = sources?.some((s) => s.status === "pending" || s.status === "crawling");

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [active, load]);

  const add = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try {
      await api.addCrawlSource(url.trim());
      setUrl("");
      load();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  const sync = async (source: CrawlSource) => {
    try {
      await api.syncCrawlSource(source.id);
      load();
    } catch (e) {
      onError(e);
    }
  };

  const remove = async (source: CrawlSource) => {
    if (!window.confirm(t.confirmDeleteSource)) return;
    try {
      await api.deleteCrawlSource(source.id);
      load();
    } catch (e) {
      onError(e);
    }
  };

  return (
    <section className="panel">
      <h2>{t.website}</h2>
      <p className="muted">{t.crawlHint}</p>
      {isOwner && (
        <div className="row" style={{ marginBottom: 12 }}>
          <input
            id="crawl-url"
            type="url"
            value={url}
            placeholder={t.crawlUrlPlaceholder}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button
            className="primary"
            id="crawl-add"
            disabled={busy || !url.trim()}
            onClick={add}
          >
            {t.addSource}
          </button>
        </div>
      )}
      {sources === null ? (
        <p className="muted">{t.loading}</p>
      ) : sources.length === 0 ? (
        <p className="muted">{t.noSources}</p>
      ) : (
        <table id="crawl-sources">
          <thead>
            <tr>
              <th>{t.url}</th>
              <th>{t.status}</th>
              <th>{t.pagesCrawled}</th>
              <th>{t.lastSynced}</th>
              {isOwner && <th>{t.actions}</th>}
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.id}>
                <td>
                  {source.url}
                  {source.error && <div className="muted">{source.error}</div>}
                </td>
                <td>
                  <span className={`badge ${STATUS_CLASS[source.status]}`}>
                    {t[STATUS_LABEL[source.status]]}
                  </span>
                </td>
                <td>{source.pages_crawled}</td>
                <td>
                  {source.last_synced_at
                    ? new Date(source.last_synced_at).toLocaleString(lang)
                    : t.neverSynced}
                </td>
                {isOwner && (
                  <td>
                    <div className="row">
                      <button
                        className="ghost"
                        onClick={() => sync(source)}
                        disabled={source.status === "pending" || source.status === "crawling"}
                      >
                        {t.syncNow}
                      </button>
                      <button className="danger" onClick={() => remove(source)}>
                        {t.delete}
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}