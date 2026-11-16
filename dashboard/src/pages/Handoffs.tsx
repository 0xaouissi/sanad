import { useEffect, useState } from "react";
import { HandoffItem, api } from "../api";
import { Dict, Lang } from "../i18n";

const STATUS_CLASS: Record<HandoffItem["email_status"], string> = {
  sent: "ready",
  failed: "failed",
  skipped: "pending",
};

export function Handoffs({
  t,
  lang,
  onError,
}: {
  t: Dict;
  lang: Lang;
  onError: (e: unknown) => void;
}) {
  const [items, setItems] = useState<HandoffItem[] | null>(null);

  useEffect(() => {
    api
      .handoffs()
      .then(setItems)
      .catch(onError);
  }, [onError]);

  function statusLabel(status: HandoffItem["email_status"]): string {
    if (status === "sent") return t.statusSent;
    if (status === "failed") return t.statusFailed;
    return t.statusSkipped;
  }

  return (
    <section className="panel">
      <h2>{t.handoffs}</h2>
      {items === null ? (
        <p className="muted">{t.loading}</p>
      ) : items.length === 0 ? (
        <p className="muted">{t.noHandoffs}</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>{t.email}</th>
              <th>{t.message}</th>
              <th>{t.language}</th>
              <th>{t.channelEmail}</th>
              <th>{t.channelTelegram}</th>
              <th>{t.date}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td dir="ltr">{item.email}</td>
                <td>{item.message}</td>
                <td>{item.language ?? "—"}</td>
                <td>
                  <span className={`badge ${STATUS_CLASS[item.email_status]}`}>
                    {statusLabel(item.email_status)}
                  </span>
                </td>
                <td>
                  <span className={`badge ${STATUS_CLASS[item.telegram_status]}`}>
                    {statusLabel(item.telegram_status)}
                  </span>
                </td>
                <td>{new Date(item.created_at).toLocaleString(lang)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}