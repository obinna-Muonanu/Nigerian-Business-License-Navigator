// The connection to Supabase, which handles signing in.
//
// Supabase looks after accounts and passwords for us. When someone signs in, it gives the browser a sign-in pass
// (a token), keeps it safe in the browser, and renews it automatically before it expires. The rest of the app just
// asks this client for the current pass whenever it calls the Navi API.

import { createClient } from "@supabase/supabase-js";
import { config, missingSettings } from "./config";

// If the settings are missing we still create a client with placeholder values, so the app can load far enough
// to show the "please finish setup" screen instead of crashing.
export const supabase = createClient(
  missingSettings.length ? "https://placeholder.supabase.co" : config.supabaseUrl,
  missingSettings.length ? "placeholder" : config.supabaseKey,
  { auth: { persistSession: true, autoRefreshToken: true } },
);
