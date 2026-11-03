// The website's settings, read once from frontend/.env.local.
//
// Vite copies any setting that starts with VITE_ into the website the browser downloads, which is why only public
// values belong here: the Supabase address, its publishable key, and where the Navi API runs. If a required
// setting is missing, `missingSettings` lists it, and the app shows a clear setup message instead of a broken page.

export const config = {
  supabaseUrl: import.meta.env.VITE_SUPABASE_URL ?? "",
  supabaseKey: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "",
  // Remove any trailing slash, so we can always write `${apiUrl}/chat`.
  apiUrl: (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
};

export const missingSettings: string[] = [
  !config.supabaseUrl && "VITE_SUPABASE_URL",
  !config.supabaseKey && "VITE_SUPABASE_PUBLISHABLE_KEY",
].filter((name): name is string => Boolean(name));
