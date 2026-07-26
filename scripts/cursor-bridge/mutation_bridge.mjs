#!/usr/bin/env node
/**
 * Doofus -> Cursor Composer mutation bridge.
 * Reads JSON context on stdin; prints JSON { ok, text, status, model } on stdout.
 */
import { Agent } from "@cursor/sdk";
import { readFileSync } from "node:fs";

const apiKey = process.env.CURSOR_API_KEY?.trim();
if (!apiKey) {
  console.log(JSON.stringify({ ok: false, error: "missing_cursor_api_key" }));
  process.exit(0);
}

const modelId = process.env.DOOFUS_CURSOR_MODEL?.trim() || "composer-2.5";
const cwd = process.env.DOOFUS_ROOT || process.cwd();
const rawIn = readFileSync(0, "utf8");
let context = {};
try {
  context = JSON.parse(rawIn || "{}");
} catch {
  context = { raw: rawIn };
}

const system = [
  "You are Doofus mutation advisor for a local autonomous evolution loop.",
  "Return ONLY valid JSON (no markdown fences):",
  '{"proposals":[{"traits":["replay_stability","proof_density","arena_agent_arcade"],"rationale":"..."}]}',
  "Use only safe traits: replay_stability, proof_density, generalization_pressure,",
  "arena_agent_arcade, compounding_focus, recursive_learning_bias.",
  "Never propose network egress, credentials, or forbidden execution traits.",
  "Prefer 3-8 proposals when pressure_level >= 2.",
].join("\n");

const user = `${system}\n\nContext:\n${JSON.stringify(context).slice(0, 6000)}`;

try {
  const result = await Agent.prompt(user, {
    apiKey,
    model: { id: modelId },
    local: { cwd },
  });
  const text = typeof result.result === "string" ? result.result : JSON.stringify(result.result ?? "");
  console.log(
    JSON.stringify({
      ok: true,
      text,
      status: result.status,
      model: modelId,
    }),
  );
} catch (err) {
  console.log(
    JSON.stringify({
      ok: false,
      error: err?.message || String(err),
      model: modelId,
    }),
  );
}
