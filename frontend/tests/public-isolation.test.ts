// The public pages' boundaries in their own sources (src/public/** and the shell's sign-in form): they import only
// React, the user and onboarding contracts, the shared router and leave guard, the shared sign-in form, the Client's
// time formatting and each other, never an Admin module, an operator page or the TEST transport; they never touch
// browser storage or cookies (a password lives only in a live form); and no source, comments included, names a vendor
// or product, money, usage figures, a tariff or a fixed number of credits. Every number of credits on a public page
// comes from the server.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const publicDir = join(src, "public");
const files = (dir: string): string[] => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? files(path) : [path];
});
const pages = files(publicDir).filter((path) => /\.(ts|tsx|css)$/.test(path));
const shell = ["SignIn.tsx", "Shell.tsx", "shell.css"].map((name) => join(src, "shell", name));
const SHARED = new Set(["contracts/user.ts", "contracts/onboarding.ts", "router.tsx", "leave.ts", "shell/SignIn.tsx",
  "client/time.ts"].map((name) => join(src, name)));
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

test("public modules import only React, the contracts, the shared router, leave guard and sign-in form, and each other", () => {
  assert.ok(pages.length >= 10, `${pages.length} public sources`);
  for (const path of pages.filter((file) => !file.endsWith(".css"))) {
    for (const specifier of specifiers(readFileSync(path, "utf8"))) {
      if (!specifier.startsWith(".")) {
        assert.ok(specifier === "react", `${relative(src, path)} imports ${specifier}`);
        continue;
      }
      const target = resolved(path, specifier);
      assert.ok(target.startsWith(publicDir) || SHARED.has(target), `${relative(src, path)} imports ${relative(src, target)}`);
    }
  }
});

test("the shell's sign-in form imports nothing beyond React, the user contract and the public sign-in rules", () => {
  const allowed = new Set([join(src, "contracts/user.ts"), join(src, "public/signIn.ts")]);
  for (const specifier of specifiers(readFileSync(shell[0], "utf8"))) {
    assert.ok(specifier === "react" || allowed.has(resolved(shell[0], specifier)), `SignIn.tsx imports ${specifier}`);
  }
});

test("no public page or sign-in form touches browser storage or cookies", () => {
  for (const path of [...pages, shell[0]]) {
    const match = /localStorage|sessionStorage|indexedDB|document\.cookie|caches\./.exec(readFileSync(path, "utf8"));
    assert.equal(match, null, `${relative(src, path)} uses ${match?.[0]}`);
  }
});

test("no public source, comments included, carries the administrator's vocabulary, a tariff or a fixed credit number", () => {
  const banned = /claude|sonnet|opus|haiku|anthropic|openai|\$\s?\d|\busd\b|dollar|\btokens?\b|\bcosts?\b|\bproviders?\b|\bmodels?\b|\bprices?\b|planning|prompt|thinking|\btariffs?\b|usage-points-draft|Hypotheses|Market context|Case library/i;
  const fixed = /\b\d[\d,.]*\s*(credits?|points?)\b/i;
  for (const path of [...pages, ...shell]) {
    const text = readFileSync(path, "utf8");
    const match = banned.exec(text) ?? fixed.exec(text);
    assert.equal(match, null, `${relative(src, path)} says "${match?.[0]}"`);
  }
});
