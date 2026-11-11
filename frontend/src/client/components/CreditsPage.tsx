// A signed-in user's credits at /credits (docs/onboarding-contract.md section 7): their own allowance and any missing
// step as the server last reported them (GET /api/user/account), today's counted searches, imports, new sources and
// prepared analyses (GET /api/user/limits), then the server's public credit terms. Reads only.
import { useEffect } from "react";
import { CreditsGuide } from "../../public/CreditsGuide";
import { Entitlements } from "./Entitlements";
import { FirstUse } from "./FirstUse";
import { LimitsPanel } from "./LimitsPanel";

export function CreditsPage() {
  useEffect(() => { document.title = "Your credits · Second Order"; }, []);
  return (
    <>
      <header className="client-header">
        <p className="kicker">Credits</p>
        <h1 className="client-title">Your credits</h1>
        <p className="client-lede">Credits are points of usage on this server, with no money value. Every analysis is
          quoted before it runs, and nothing runs until you approve the quote.</p>
      </header>
      <FirstUse />
      <Entitlements />
      <LimitsPanel />
      <CreditsGuide />
    </>
  );
}
