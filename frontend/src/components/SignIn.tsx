// The sign-in page: the first thing a visitor sees.
//
// People can sign in with an email and password, or create an account. Supabase checks the password and creates
// the account; this page only collects the details and shows what happened. Once Supabase signs someone in, the
// App notices and shows the chat instead.

import { useState, type FormEvent } from "react";
import { supabase } from "../lib/supabase";
import { Logo } from "./Logo";

type Mode = "sign-in" | "sign-up";

export function SignIn() {
  const [mode, setMode] = useState<Mode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Switch between "Sign in" and "Create account", clearing any old message.
  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setNotice(null);
  }

  async function submit(event: FormEvent) {
    // Stop the browser from reloading the page, which is what a form normally does when submitted.
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "sign-in") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        // If Supabase is set to confirm email addresses, there's no session yet: the person must click the link
        // in the email first. Otherwise they're signed in straight away and the App moves on by itself.
        if (!data.session) {
          setNotice("Account created. Check your email for a confirmation link, then sign in here.");
          setMode("sign-in");
        }
      }
    } catch (err) {
      setError(friendlyError(err, mode));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-b from-brand-soft to-white px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo size={64} />
          <h1 className="mt-4 text-2xl font-semibold text-slate-900">Business Licensing Navigator</h1>
          <p className="mt-2 text-sm text-slate-600">
            Meet <span className="font-semibold text-brand">Navi</span>, your guide to the registrations, licences and
            permits a Nigerian business needs.
          </p>
        </div>

        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          {/* Two clear tabs, so nobody tries to sign in before they've created an account. */}
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1 text-sm font-medium">
            {(["sign-in", "sign-up"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => switchMode(m)}
                className={`rounded-md py-1.5 transition ${mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
              >
                {m === "sign-in" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <label className="block">
            <span className="text-sm font-medium text-slate-700">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium text-slate-700">Password</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
            />
            {mode === "sign-up" && <span className="mt-1 block text-xs text-slate-500">At least 8 characters.</span>}
          </label>

          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          {notice && <p className="rounded-lg bg-brand-soft px-3 py-2 text-sm text-brand-dark">{notice}</p>}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-dark disabled:opacity-60"
          >
            {busy ? "Please wait…" : mode === "sign-in" ? "Sign in" : "Create account"}
          </button>

          <p className="text-center text-sm text-slate-600">
            {mode === "sign-in" ? "New here?" : "Already have an account?"}{" "}
            <button
              type="button"
                onClick={() => switchMode(mode === "sign-in" ? "sign-up" : "sign-in")}
              className="font-semibold text-brand hover:text-brand-dark"
            >
              {mode === "sign-in" ? "Create an account" : "Sign in"}
            </button>
          </p>
        </form>

        <p className="mt-6 text-center text-xs text-slate-500">
          Navi gives guidance, not legal advice. Always confirm fees and rules with the regulator.
        </p>
      </div>
    </div>
  );
}

// Turn Supabase's short technical messages into plain advice about what to do next.
function friendlyError(err: unknown, mode: Mode): string {
  const message = err instanceof Error ? err.message : "";
  if (/invalid login credentials/i.test(message)) {
    return "Wrong email or password. New here? Choose \"Create account\" above first.";
  }
  if (/email not confirmed/i.test(message)) {
    return "Please confirm your email first, using the link Supabase sent you, then sign in.";
  }
  if (/already registered|already exists/i.test(message)) {
    return "There's already an account with this email. Choose \"Sign in\" above.";
  }
  if (/rate limit|too many/i.test(message)) {
    return "Too many attempts. Please wait a minute and try again.";
  }
  return message || (mode === "sign-in" ? "Couldn't sign in. Please try again." : "Couldn't create the account. Please try again.");
}
