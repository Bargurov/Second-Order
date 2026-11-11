// The Client's boundaries in its own sources (src/client/**): it imports only React, the user, onboarding, news and
// stories contracts and the shared router, leave guard and session channel, never an operator page, the Admin app or the
// operator API module; the TEST transport is not
// reachable from any production Client module; and no Client source, comments included, names a vendor or product,
// money, usage figures or internal transport terms. The Client's SYNTHETIC fixtures read under the contract.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { readAccount, readAnalysis, readSession } from "../src/contracts/user.ts";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const clientDir = join(src, "client");
const files = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? files(path) : [path];
});
const sources = files(clientDir).filter((path) => /\.(ts|tsx|css)$/.test(path));
// The public credits guide (src/public/CreditsGuide.tsx) is shared with the signed-in /credits page; nothing else of
// the public pages is. The shell's session channel (src/shell/sessionChannel.ts) is how a tab hears that another tab
// signed the browser in to another account; nothing else of the shell is imported.
const SHARED = new Set(["contracts/user.ts", "contracts/onboarding.ts", "router.tsx", "leave.ts", "public/CreditsGuide.tsx",
                        "contracts/news.ts", "contracts/stories.ts", "contracts/economics.ts", "shell/sessionChannel.ts"].map((name) => join(src, name)));
const specifiers = (text: string) => [...text.matchAll(/^\s*import\s+(?:[^"']*?\s+from\s+)?["']([^"']+)["']/gm)]
  .map((match) => match[1]);

function resolved(from: string, specifier: string): string {
  const base = resolve(dirname(from), specifier);
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`]) {
    try {
      if (statSync(candidate).isFile()) return candidate;
    } catch { /* try the next */ }
  }
  return base;
}

test("Client modules import only React, the user, onboarding, news and stories contracts, the shared router, leave guard and session channel, and each other", () => {
  assert.ok(sources.length >= 15);
  for (const path of sources.filter((file) => !file.endsWith(".css"))) {
    for (const specifier of specifiers(readFileSync(path, "utf8"))) {
      if (!specifier.startsWith(".")) {
        assert.ok(specifier === "react", `${relative(src, path)} imports ${specifier}`);
        continue;
      }
      const target = resolved(path, specifier);
      assert.ok(target.startsWith(clientDir) || SHARED.has(target), `${relative(src, path)} imports ${relative(src, target)}`);
    }
  }
});

test("the TEST transport is reachable only from tests, never from a production Client module", () => {
  const testing = join(clientDir, "testing");
  for (const path of sources.filter((file) => !file.startsWith(testing) && !file.endsWith(".css"))) {
    for (const specifier of specifiers(readFileSync(path, "utf8")).filter((item) => item.startsWith("."))) {
      assert.ok(!resolved(path, specifier).startsWith(testing), `${relative(src, path)} imports the test transport`);
    }
  }
});

test("no Client source, comments included, carries the administrator's vocabulary", () => {
  const banned = /claude|sonnet|opus|haiku|anthropic|openai|\$\s?\d|\busd\b|dollar|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|\bprices?\b|planning estimate/i;
  for (const path of sources) {
    // React's context API member (`SomeContext.Provider`) is a framework name, not vocabulary; nothing else is exempt.
    const text = readFileSync(path, "utf8").replace(/\b[A-Z]\w*Context\.Provider\b/g, "");
    const match = banned.exec(text);
    assert.ok(match === null, `${relative(src, path)} says "${match?.[0]}"`);
  }
});

test("the account strip is styled by the Client's own stylesheet and keeps Sign out as its only button", () => {
  const css = readFileSync(join(clientDir, "client.css"), "utf8");
  for (const rule of [/\.account-strip\s*\{[^}]*max-width[^}]*border-bottom/, /\.account-strip button\s*\{/,
                      /\.account-strip button:focus-visible\s*\{[^}]*outline/]) {
    assert.match(css, rule);
  }
  const app = readFileSync(join(clientDir, "ClientApp.tsx"), "utf8");
  const strip = /<div className="account-strip"[\s\S]*?\n {6}<\/div>/.exec(app)?.[0] ?? "";
  assert.match(strip, /session\.user\.display_name/);
  assert.equal(strip.match(/<button\b/g)?.length, 1);
  assert.match(strip, /Sign out/);
});

test("the Client's own SYNTHETIC fixtures read under the contract", () => {
  const fixtures = resolve(here, "fixtures");
  const names = readdirSync(fixtures).filter((name) => name.startsWith("client-"));
  const reconciled = ["failed", "unresolved"].flatMap((kind) => ["charged", "partial", "returned", "zero"]
    .map((variant) => `client-analysis-${kind}-${variant}.json`));
  assert.deepEqual(names.sort(), ["client-account-reader-b.json", ...reconciled, "client-session-reader-b.json"].sort());
  // Reconciled analyses: readable under the unchanged contract, and the published analysis with only its charge and
  // the server's detail changed (same identity, state, source and absence of a result).
  for (const name of reconciled) {
    const body = JSON.parse(readFileSync(join(fixtures, name), "utf8"));
    const read = readAnalysis(body);
    assert.ok(read.ok, `${name}: ${read.ok ? "" : read.problem}`);
    const kind = name.includes("-failed-") ? "failed" : "unresolved";
    const published = JSON.parse(readFileSync(join(fixtures, `user-contract-analysis-${kind}.json`), "utf8"));
    const strip = (value: { analysis: Record<string, unknown> }) => {
      const { charge, state_detail, ...rest } = value.analysis;
      return rest;
    };
    assert.deepEqual(strip(body), strip(published), name);
    assert.notEqual(body.analysis.charge.state, "under_review", name);
  }
  const session = readSession(JSON.parse(readFileSync(join(fixtures, "client-session-reader-b.json"), "utf8")));
  const account = readAccount(JSON.parse(readFileSync(join(fixtures, "client-account-reader-b.json"), "utf8")));
  assert.ok(session.ok && account.ok);
  assert.ok(session.ok && account.ok && session.value.state === "signed_in" &&
    session.value.user.user_id === account.value.user.user_id && session.value.user.role === "user");
  for (const name of names) assert.match(readFileSync(join(fixtures, name), "utf8"), /SYNTHETIC|synthetic/);
});
