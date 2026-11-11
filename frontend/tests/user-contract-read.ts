// Reads payloads the real server served (written by tests/test_user_research.py into a temporary file) with the user
// contract's own fail-closed readers, and prints what each reader made of them. Not a test file on its own: the
// backend test runs it with `node --experimental-strip-types` and checks that every payload reads.
import { readFileSync } from "node:fs";
import * as news from "../src/contracts/news.ts";
import * as onboarding from "../src/contracts/onboarding.ts";
import * as contract from "../src/contracts/user.ts";

const READERS: Record<string, (body: unknown) => contract.Read<unknown>> = {
  session: contract.readSession, account: contract.readAccount, sourceCreated: contract.readSourceCreated,
  sources: contract.readSources, sourceDetail: contract.readSourceDetail, prepared: contract.readPrepared,
  quote: contract.readQuoteIssued, analysis: contract.readAnalysis, run: contract.readRun,
  reviewSaved: contract.readReviewSaved, export: contract.readExport, analyses: contract.readAnalyses,
  error: contract.readError, creditTerms: onboarding.readCreditTerms, registration: onboarding.readRegistration,
  onboardingError: onboarding.readOnboardingError,
  news: news.readNews, interests: news.readInterests, interestsSaved: news.readInterestsSaved, search: news.readSearch,
  importCreated: news.readImportCreated, import: news.readImport, importConfirmed: news.readImportConfirmed,
  limits: news.readLimits, quality: news.readQuality,
};

const payloads: { name: string; reader: string; body: unknown }[] = JSON.parse(readFileSync(process.argv[2], "utf8"));
const results = payloads.map(({ name, reader, body }) => {
  const read = READERS[reader]?.(body);
  return { name, reader, problem: read === undefined ? `no reader ${reader}` : read.ok ? null : read.problem };
});
console.log(JSON.stringify(results));
