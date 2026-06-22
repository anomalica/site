/**
 * The site contact-form edge function (Bunny Edge Scripting / Deno). One route:
 *
 *   POST /api/contact   { name, email, message, token, company? }
 *
 * Flow: validate input -> verify the Cloudflare Turnstile token (server-side)
 * -> send the message via Resend (Reply-To set to the visitor). The `company`
 * field is a honeypot: bots fill it, humans never see it.
 *
 * Env (set on the Bunny script by operations): TURNSTILE_SECRET_KEY,
 * RESEND_API_KEY, CONTACT_TO_EMAIL, CONTACT_FROM_EMAIL. If RESEND_API_KEY is
 * unset the handler degrades gracefully (503) so it can be deployed before the
 * Resend account exists. Kept import-safe (no serve) so it is unit-testable.
 */

export interface Env {
  turnstileSecret: string;
  resendKey: string;
  toEmail: string;
  fromEmail: string;
}

export function loadEnv(): Env {
  const get = (k: string): string => Deno.env.get(k) ?? "";
  return {
    turnstileSecret: get("TURNSTILE_SECRET_KEY"),
    resendKey: get("RESEND_API_KEY"),
    toEmail: get("CONTACT_TO_EMAIL"),
    fromEmail: get("CONTACT_FROM_EMAIL"),
  };
}

const MAX = { name: 200, email: 320, message: 5000 };
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function json(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

function clientIp(req: Request): string {
  return (
    req.headers.get("cf-connecting-ip") ??
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    ""
  );
}

async function verifyTurnstile(secret: string, token: string, ip: string): Promise<boolean> {
  const form = new URLSearchParams({ secret, response: token });
  if (ip) form.set("remoteip", ip);
  const res = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!res.ok) return false;
  const data = (await res.json()) as { success?: boolean };
  return data.success === true;
}

async function sendEmail(env: Env, name: string, email: string, message: string): Promise<boolean> {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.resendKey}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      from: env.fromEmail,
      to: [env.toEmail],
      reply_to: email,
      subject: `Contact form: ${name}`,
      text: `From: ${name} <${email}>\n\n${message}`,
    }),
  });
  return res.ok;
}

export async function handleRequest(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  if (url.pathname !== "/api/contact") return json(404, { error: "not_found" });
  if (req.method !== "POST") return json(405, { error: "method_not_allowed" });

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return json(400, { error: "invalid_json" });
  }

  // Honeypot: a filled "company" field means a bot. Pretend success, send nothing.
  if (typeof body.company === "string" && body.company.trim() !== "") {
    return json(200, { ok: true });
  }

  const name = typeof body.name === "string" ? body.name.trim() : "";
  const email = typeof body.email === "string" ? body.email.trim() : "";
  const message = typeof body.message === "string" ? body.message.trim() : "";
  const token = typeof body.token === "string" ? body.token : "";

  if (!name || name.length > MAX.name) return json(400, { error: "invalid_name" });
  if (!EMAIL_RE.test(email) || email.length > MAX.email)
    return json(400, { error: "invalid_email" });
  if (!message || message.length > MAX.message) return json(400, { error: "invalid_message" });
  if (!token) return json(400, { error: "missing_turnstile" });

  if (!env.turnstileSecret || !(await verifyTurnstile(env.turnstileSecret, token, clientIp(req)))) {
    return json(403, { error: "turnstile_failed" });
  }

  // Deployable before the Resend account exists - fail clearly, don't 500.
  if (!env.resendKey || !env.toEmail || !env.fromEmail) {
    return json(503, { error: "email_not_configured" });
  }

  if (!(await sendEmail(env, name, email, message))) {
    return json(502, { error: "send_failed" });
  }
  return json(200, { ok: true });
}
