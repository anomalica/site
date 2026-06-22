/**
 * Deployed entry for Bunny Edge Scripting. Bunny routes requests to the handler
 * registered via BunnySDK.net.http.serve (not a raw Deno.serve). Env is read
 * lazily on the first request - Deno.env access is a per-request capability on
 * the edge, so reading it at import time can take the script down. Bundle THIS
 * file (`deno task bundle`) for deployment.
 */

import * as BunnySDK from "@bunny.net/edgescript-sdk";
import { type Env, handleRequest, loadEnv } from "./main.ts";

let env: Env | null = null;

BunnySDK.net.http.serve(async (req: Request): Promise<Response> => {
  if (!env) env = loadEnv();
  return await handleRequest(req, env);
});
