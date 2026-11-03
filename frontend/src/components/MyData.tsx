// The "My data" page: everything Navi remembers about the signed-in user, and their data rights.
//
// It shows each business with its remembered facts (and where Navi learned each one), the steps marked as done, and
// the notes from recent chats. The user can download all of it as a file, delete one business, or delete everything.
// This is what Nigeria's data protection law (the NDPA) asks for: people can see their data, take it with them, and
// have it erased.

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { FACT_NAMES, SOURCE_NAMES, factValue, shortDate } from "../lib/labels";
import type { MemoryView } from "../lib/types";

// Say a number of days in months, the way people talk about it: 180 days is "6 months", 540 is "18 months".
function months(days: number): string {
  const m = Math.round(days / 30);
  return m >= 1 ? `${m} month${m === 1 ? "" : "s"}` : `${days} days`;
}

interface Props {
  // Called after something is deleted, so the sidebar and chat can refresh.
  onChanged: () => void;
  // Called after everything is deleted.
  onDeletedAll: () => void;
}

export function MyData({ onChanged, onDeletedAll }: Props) {
  const [memory, setMemory] = useState<MemoryView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  async function load() {
    try {
      setMemory(await api.get<MemoryView>("/me/memory"));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your data.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  // Download everything as a JSON file. The browser saves it like any other download.
  async function download() {
    setWorking(true);
    try {
      const data = await api.get<unknown>("/me/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "navi-my-data.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not download your data.");
    } finally {
      setWorking(false);
    }
  }

  async function deleteBusiness(businessId: string, label: string) {
    if (!window.confirm(`Delete "${label}" and everything Navi recorded about it? This can't be undone.`)) return;
    setWorking(true);
    try {
      await api.delete(`/me/businesses/${encodeURIComponent(businessId)}`);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete that business.");
    } finally {
      setWorking(false);
    }
  }

  async function deleteEverything() {
    setWorking(true);
    try {
      await api.delete("/me");
      setConfirmText("");
      await load();
      onDeletedAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete your data.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-8 px-4 py-8">
        <header>
          <h1 className="text-2xl font-semibold text-slate-900">My data</h1>
          <p className="mt-2 text-sm text-slate-600">
            This is everything Navi remembers about you. Navi only saves facts you've told it about your businesses,
            never ID or card numbers.
          </p>
        </header>

        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        {!memory && !error && <p className="text-sm text-slate-500">Loading…</p>}

        {memory && (
          <>
            <section className="space-y-4">
              <h2 className="text-lg font-semibold text-slate-900">Your businesses</h2>
              {/* The retention rule in plain words, so nobody is surprised when an old business disappears. */}
              {memory.retention.business_inactive_days > 0 && memory.retention.business_delete_days > 0 && (
                <p className="text-xs text-slate-500">
                  A business you haven't used for {months(memory.retention.business_inactive_days)} is marked
                  inactive: it's kept, and comes back as soon as you mention it to Navi. One unused for{" "}
                  {months(memory.retention.business_delete_days)} is deleted automatically.
                </p>
              )}
              {memory.businesses.length === 0 && (
                <p className="text-sm text-slate-500">No businesses yet. Tell Navi about your business to get started.</p>
              )}
              {memory.businesses.map((b) => (
                <div
                  key={b.business_id}
                  className={`rounded-xl border p-4 ${b.status === "inactive" ? "border-dashed border-slate-300 bg-slate-50" : "border-slate-200"}`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="flex flex-wrap items-center gap-2 font-semibold text-slate-900">
                        {b.label}
                        {b.status === "inactive" && (
                          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600">
                            Inactive
                          </span>
                        )}
                      </h3>
                      {b.last_used_at && (
                        <p className="mt-0.5 text-xs text-slate-400">Last used {shortDate(b.last_used_at)}</p>
                      )}
                    </div>
                    <button
                      onClick={() => deleteBusiness(b.business_id, b.label)}
                      disabled={working}
                      className="shrink-0 text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                    >
                      Delete this business
                    </button>
                  </div>

                  {Object.keys(b.profile).length === 0 ? (
                    <p className="mt-2 text-sm text-slate-500">No details saved yet.</p>
                  ) : (
                    <dl className="mt-3 divide-y divide-slate-100 text-sm">
                      {Object.entries(b.profile).map(([field, value]) => (
                        <div key={field} className="grid grid-cols-1 gap-1 py-2 sm:grid-cols-3">
                          <dt className="text-slate-500">{FACT_NAMES[field] ?? field}</dt>
                          <dd className="font-medium text-slate-900">{factValue(field, value)}</dd>
                          <dd className="text-xs text-slate-400 sm:text-right">
                            {SOURCE_NAMES[b.fact_sources[field]?.source] ?? ""}
                            {b.fact_sources[field] ? ` · ${shortDate(b.fact_sources[field].updated_at)}` : ""}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}

                  <p className="mt-3 text-sm text-slate-600">
                    <span className="font-medium">Steps done:</span>{" "}
                    {b.completed_steps.length ? b.completed_steps.map((s) => s.name).join(", ") : "none yet"}
                  </p>
                </div>
              ))}
            </section>

            <section>
              <h2 className="text-lg font-semibold text-slate-900">Notes from your recent chats</h2>
              <p className="mt-1 text-xs text-slate-500">
                Written automatically at the end of each chat to help Navi pick up where you left off.
              </p>
              {memory.recent_sessions.length === 0 ? (
                <p className="mt-3 text-sm text-slate-500">No notes yet.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {memory.recent_sessions.map((e) => (
                    <li key={e.session_id} className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">
                      <span className="mr-2 text-xs text-slate-400">{shortDate(e.updated_at)}</span>
                      {e.summary}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}

        <section className="rounded-xl border border-slate-200 p-4">
          <h2 className="font-semibold text-slate-900">Download your data</h2>
          <p className="mt-1 text-sm text-slate-600">Get a copy of everything Navi holds about you, as a file.</p>
          <button
            onClick={download}
            disabled={working}
            className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Download (JSON)
          </button>
        </section>

        <section className="rounded-xl border border-red-200 bg-red-50/40 p-4">
          <h2 className="font-semibold text-red-700">Delete everything</h2>
          <p className="mt-1 text-sm text-slate-600">
            Deletes all your businesses, chats, notes and reminders. Your sign-in stays, so you can start fresh. This
            can't be undone. Type <span className="font-mono font-semibold">DELETE</span> to confirm.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="w-32 rounded-lg border border-slate-300 px-2 py-1.5 text-sm outline-none focus:border-red-400"
              aria-label="Type DELETE to confirm"
            />
            <button
              onClick={deleteEverything}
              disabled={working || confirmText !== "DELETE"}
              className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-40"
            >
              Delete my data
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
