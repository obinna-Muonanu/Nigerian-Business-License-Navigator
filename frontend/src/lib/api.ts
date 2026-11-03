// Everything the website needs to talk to the Navi API.
//
// Every request carries the user's sign-in pass in an "Authorization" header. The API checks that pass and works
// out who the user is from it, so the website never sends a user ID of its own.
//
// The chat request is special: Navi's reply streams back a few words at a time as "Server-Sent Events" (lines that
// start with "data: "). streamChat reads them as they arrive and hands each one to the screen straight away.

import { config } from "./config";
import { supabase } from "./supabase";
import type { ChatEvent } from "./types";

// An error from the API, with its status code, so the screen can react differently to "please sign in" (401),
// "too many messages" (429) and other problems.
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Get the current sign-in pass from Supabase. Supabase renews it automatically, so it's always fresh.
async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, "Please sign in.");
  return { Authorization: `Bearer ${token}` };
}

// Turn a failed response into an ApiError with the API's own message ("detail") when it gave one.
async function toError(response: Response): Promise<ApiError> {
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") message = body.detail;
  } catch {
    // The body wasn't JSON; keep the general message.
  }
  return new ApiError(response.status, message);
}

// One small function for the usual requests that send and receive JSON.
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...(await authHeader()) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(`${config.apiUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Can't reach the Navi server at ${config.apiUrl}. Is it running?`);
  }
  if (!response.ok) throw await toError(response);
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

// Send one chat message and call `onEvent` for every piece of the reply as it arrives.
export async function streamChat(
  body: { session_id: string | null; message: string; mode: string },
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${config.apiUrl}/chat`, {
      method: "POST",
      headers: { ...(await authHeader()), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Can't reach the Navi server at ${config.apiUrl}. Is it running?`);
  }
  if (!response.ok || !response.body) throw await toError(response);

  // Read the stream piece by piece. A piece of network data can end halfway through an event, so we keep any
  // unfinished part in `buffer` until the rest arrives. Each complete event ends with a blank line ("\n\n").
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      const chunk = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as ChatEvent);
      }
      end = buffer.indexOf("\n\n");
    }
  }
}
