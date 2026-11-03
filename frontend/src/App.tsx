// The top of the website. It decides which screen to show:
//
//   a setup message, if the website's settings (frontend/.env.local) haven't been filled in yet;
//   the sign-in page, if nobody is signed in;
//   the chat, once someone is signed in.
//
// Supabase tells us whenever someone signs in or out, so the screen switches by itself. The chat is given the user's
// ID as its "key": if a different person signs in on the same browser, React throws away everything on screen and
// starts fresh, so one person can never see what the previous person was looking at.

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { missingSettings } from "./lib/config";
import { supabase } from "./lib/supabase";
import { Logo } from "./components/Logo";
import { SignIn } from "./components/SignIn";
import { Workspace } from "./components/Workspace";

export default function App() {
  // undefined = still checking whether someone is signed in; null = nobody is.
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  useEffect(() => {
    if (missingSettings.length) return;
    // Check once when the page opens, then listen for any sign-in or sign-out afterwards.
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  if (missingSettings.length) return <SetupNeeded missing={missingSettings} />;
  if (session === undefined) {
    return <div className="flex h-full items-center justify-center"><Logo size={48} /></div>;
  }
  if (!session) return <SignIn />;
  return <Workspace key={session.user.id} email={session.user.email ?? null} />;
}

// Shown only while setting up, so a missing setting gives clear instructions instead of a blank page.
function SetupNeeded({ missing }: { missing: string[] }) {
  return (
    <div className="mx-auto max-w-lg px-6 py-16">
      <Logo size={48} />
      <h1 className="mt-4 text-xl font-semibold">One more step to finish setting up</h1>
      <p className="mt-2 text-slate-600">
        The website needs these settings in <code className="rounded bg-slate-100 px-1">frontend/.env.local</code>:
      </p>
      <ul className="mt-3 list-disc pl-6 font-mono text-sm">
        {missing.map((name) => <li key={name}>{name}</li>)}
      </ul>
      <p className="mt-4 text-sm text-slate-600">
        Copy <code className="rounded bg-slate-100 px-1">frontend/.env.example</code> to{" "}
        <code className="rounded bg-slate-100 px-1">.env.local</code>, fill in the values, and restart{" "}
        <code className="rounded bg-slate-100 px-1">npm run dev</code>.
      </p>
    </div>
  );
}
