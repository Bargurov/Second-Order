// The user Client (user-api-0.5, docs/admin-user-contract.md with docs/onboarding-contract.md,
// docs/account-binding-contract.md, docs/news-usage-contract.md and docs/news-stories-contract.md). Mounted by the shared
// shell for a signed-in user; it talks to the server only through src/contracts/user.ts, src/contracts/news.ts and
// src/contracts/stories.ts (and reads the public credit terms through the public credits guide) and owns every page
// path of the Client build. News is the home: the wordmark and / open it (paths.ts). Page loads only read:
// preparing, quoting, running and saving a review each need the person's explicit action, and nothing retries.
// Work typed and not saved when the session ends is held in this tab's memory for the same user only (recovery.ts).
// A tab acts only for the account it was opened for: once another tab signs the browser in to another account, or a
// reply carries another account, it sends nothing more and keeps what was typed for its own account (identity.ts).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { newsApi } from "../contracts/news.ts";
import { storiesApi } from "../contracts/stories.ts";
import { userApi, type Account, type ClientAppProps, type Fetcher } from "../contracts/user.ts";
import { Link, useLocation } from "../router";
import { listen } from "../shell/sessionChannel.ts";
import { AnalysisPage } from "./components/AnalysisPage";
import { CreditsPage } from "./components/CreditsPage";
import { DeeperPage } from "./components/DeeperPage";
import { HomePage } from "./components/HomePage";
import { ImportPage } from "./components/ImportPage";
import { NewsHome } from "./components/NewsHome";
import { NewsPage } from "./components/NewsPage";
import { NewSourcePage } from "./components/NewSourcePage";
import { RecoveredWork } from "./components/RecoveredWork";
import { SourcePage, SourcesPage } from "./components/SourcePage";
import { StoryView } from "./components/StoryView";
import { TopicView } from "./components/TopicView";
import { ClientContext, type AccountState, type ClientContextValue } from "./context";
import { outcomeOf } from "./controller.ts";
import { focusTitleOnArrival } from "./focus.ts";
import { afterAnnouncement, BOUND, changedAccount, isOwn, maySend, type Identity } from "./identity.ts";
import { href, matchClientPath, type ClientRoute } from "./paths.ts";
import { admit, claim, discard, draftText, hold, toHold, type Recoverable } from "./recovery.ts";
import type { SessionReason } from "./refusals.ts";
import "./client.css";
import "./news.css";

const SECTION: Record<ClientRoute["view"], string> = {
  news: "News", story: "News", deeper: "Go deeper", topic: "News", reports: "Reports & search", analyses: "Analyses",
  import: "Import", sources: "Sources", "new-source": "New source", source: "Source", analysis: "Analysis",
  credits: "Credits", "signed-in": "Signed in", "not-found": "Not found",
};
const NEWS_VIEWS: ClientRoute["view"][] = ["news", "story", "deeper", "topic", "reports", "import"];

export function ClientApp({ session, signOut, sessionEnded }: ClientAppProps) {
  const userId = session.user.user_id;
  // Which account this tab acts for (identity.ts). The ref is what requests consult; the state renders it.
  const [identity, setIdentity] = useState<Identity>(BOUND);
  const identityNow = useRef<Identity>(BOUND);
  const becomes = useCallback((next: Identity) => {
    identityNow.current = next;
    setIdentity(next);
  }, []);
  const [stopped, setStopped] = useState<string[] | null>(null);
  const stopNow = useRef<() => void>(() => undefined);
  // Every request names this tab's account (account binding). A tab whose account changed sends nothing, and a
  // request the server refused as bound to another account (nothing read or written) stops it. No reply is invented
  // either way: the request never settles, and the page that asked is replaced by the stopped view, with what was typed
  // kept for this account.
  const [api, news, stories] = useMemo(() => {
    const never = () => new Promise<Response>(() => undefined);
    const guarded: Fetcher = async (input, init) => {
      if (!maySend(identityNow.current)) {
        stopNow.current();
        return never();
      }
      const response = await fetch(input, init);
      if (await changedAccount(response)) {
        stopNow.current();
        return never();
      }
      return response;
    };
    const binding = { account: userId };
    return [userApi(guarded, binding), newsApi(guarded, binding), storiesApi(guarded, binding)] as const;
  }, [userId]);
  const { pathname } = useLocation();
  const route = matchClientPath(pathname);
  const [account, setAccount] = useState<AccountState>({ state: "loading" });
  const [ended, setEnded] = useState<{ reason: SessionReason; texts: string[] } | null>(null);
  const unsaved = useRef(new Map<string, Recoverable>());
  const [recovered, setRecovered] = useState<Record<string, Recoverable>>({});
  const recoveredNow = useRef(recovered);
  recoveredNow.current = recovered;

  useEffect(() => { admit(userId); }, [userId]);  // Anyone else's held drafts are discarded unseen.

  // Another tab signed this browser in to another account (or back to this one): sessionChannel.ts.
  useEffect(() => listen((heard) => {
    const next = afterAnnouncement(identityNow.current, userId, heard.signedIn);
    if (next !== identityNow.current) becomes(next);
  }), [becomes, userId]);

  const setUnsaved = useCallback((key: string, draft: Recoverable | null) => {
    if (draft === null) unsaved.current.delete(key);
    else unsaved.current.set(key, draft);
  }, []);

  const releaseRecovered = useCallback((key: string) => {
    setRecovered((current) => {
      const { [key]: _released, ...rest } = current;
      return rest;
    });
  }, []);

  /** What is open now and what was given back but not yet reopened, held for this user only, in memory; its text. */
  const holdDrafts = useCallback((): string[] => {
    const drafts = toHold(unsaved.current, recoveredNow.current);
    hold(userId, drafts);
    return Object.values(drafts).map(draftText).filter((text) => text.trim() !== "");
  }, [userId]);

  const endSession = useCallback((reason: SessionReason) => {
    const texts = holdDrafts();
    if (texts.length === 0) sessionEnded(reason);
    else setEnded({ reason, texts });  // Shown first, so typed text can also be copied before signing in again.
  }, [holdDrafts, sessionEnded]);

  /** The browser now acts for another account: send nothing more, keep what was typed for this one, and say so. */
  const stop = useCallback(() => {
    if (identityNow.current.state === "stopped") return;
    becomes({ state: "stopped" });
    setStopped(holdDrafts());
  }, [becomes, holdDrafts]);
  stopNow.current = stop;

  /** Before an action that bypasses the request helpers (a download link): true when this tab may act. */
  const mayAct = useCallback(() => {
    if (maySend(identityNow.current)) return true;
    stop();
    return false;
  }, [stop]);

  const readAccount = useCallback(async () => {
    const outcome = outcomeOf(await api.account());
    if (outcome.kind === "ok") {
      if (!isOwn(outcome.data, userId)) return stop();  // Never shown or adopted under this account's name.
      setAccount({ state: "ready", account: outcome.data, readAt: new Date().toISOString() });
      // The server has confirmed who is signed in: only now are drafts held for this same user given back.
      if (outcome.data.user.user_id === userId) {
        const claimed = claim(userId);
        if (Object.keys(claimed).length > 0) setRecovered((current) => ({ ...claimed, ...current }));
      }
    } else if (outcome.kind === "session") endSession(outcome.reason);
    else setAccount({ state: "error", notice: outcome.notice });
  }, [api, endSession, stop, userId]);

  const adoptAccount = useCallback((next: Account) => {
    if (!isOwn(next, userId)) return stop();
    setAccount({ state: "ready", account: next, readAt: new Date().toISOString() });
  }, [stop, userId]);

  useEffect(() => { void readAccount(); }, [readAccount, route.view]);  // A read on each page: never a write.

  const main = useRef<HTMLElement>(null);
  const landed = useRef(true);
  useEffect(() => {  // Arriving on another page: its title takes focus once shown. The first page is where the browser landed.
    if (landed.current) {
      landed.current = false;
      return;
    }
    return focusTitleOnArrival(main.current);
  }, [pathname]);

  useEffect(() => {  // Given back but not reopened yet: reloading or closing the tab would lose it.
    if (Object.keys(recovered).length === 0) return;
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [recovered]);

  const value: ClientContextValue = useMemo(() => ({
    api, news, stories, session, account, readAccount, adoptAccount, endSession, mayAct, setUnsaved, recovered,
    releaseRecovered,
  }), [api, news, stories, session, account, readAccount, adoptAccount, endSession, mayAct, setUnsaved, recovered,
       releaseRecovered]);

  const leave = () => {
    // The browser's session is now another account's: signing out from here would end theirs, not this tab's.
    if (!mayAct()) return;
    const pending = unsaved.current.size > 0 || Object.keys(recovered).length > 0;
    if (pending && !window.confirm("Text you have not saved will be lost. Sign out anyway?")) return;
    discard();  // An explicit sign-out keeps nothing.
    setRecovered({});
    void signOut();
  };

  if (stopped) {
    const name = session.user.display_name;
    return (
      <main className="shell-panel client-ended" role="alert" data-account="stopped">
        <p className="kicker">Session</p>
        <h1>This tab has stopped</h1>
        <p>It was opened for {name}, but this browser has since been signed in to another account in another tab or
          window, and every tab shares that sign-in. So that nothing is read, saved or shown for the wrong account, this
          tab sends nothing more.</p>
        {stopped.length > 0 && (
          <>
            <p>What you typed here and had not saved is kept in this tab for {name} only, not on the server. Sign in
              again as {name} and it is given back where you left it, for you to check and save. Signing in as someone
              else, or closing or reloading this tab, discards it.</p>
            <p>You can also copy it now:</p>
            {stopped.map((text, index) => (
              <textarea key={index} className="client-ended-text" readOnly value={text} aria-label="Unsaved text" />
            ))}
          </>
        )}
        <p className="client-actions">
          <button type="button" className="button" onClick={() => sessionEnded("session_expired")}>Sign in again</button>
          <button type="button" className="button button-quiet" onClick={() => window.location.reload()}>Reload this
            tab</button>
        </p>
        <p className="muted">Reloading opens the account this browser is signed in to now{stopped.length > 0
          ? ", and discards the unsaved text above" : ""}.</p>
      </main>
    );
  }

  if (ended) {
    return (
      <main className="shell-panel client-ended" role="alert">
        <p className="kicker">Session</p>
        <h1>Your session has ended</h1>
        <p>What you typed and had not saved is kept in this tab, not on the server. Sign in again as{" "}
          {session.user.display_name} and it is given back where you left it, for you to check and save. Signing in as
          someone else, signing out, or closing or reloading this tab discards it.</p>
        <p>You can also copy it now:</p>
        {ended.texts.map((text, index) => (
          <textarea key={index} className="client-ended-text" readOnly value={text} aria-label="Unsaved text" />
        ))}
        <button type="button" className="button" onClick={() => sessionEnded(ended.reason)}>Sign in again</button>
      </main>
    );
  }

  return (
    <ClientContext.Provider value={value}>
      <div className="topbar client-topbar">
        <div className="topbar-primary">
          <Link to={href.news} className="wordmark">
            <span className="wordmark-name">Second Order</span>
            <span className="wordmark-section">{SECTION[route.view]}</span>
          </Link>
          <nav className="site-nav" aria-label="Sections">
            <Link to={href.news} className="site-link"
                  aria-current={NEWS_VIEWS.includes(route.view) ? "page" : undefined}>News</Link>
            <Link to={href.analyses} className="site-link"
                  aria-current={route.view === "analyses" || route.view === "analysis" ? "page" : undefined}>
              Analyses</Link>
            <Link to={href.sources} className="site-link"
                  aria-current={route.view === "sources" || route.view === "source" ? "page" : undefined}>Sources</Link>
            <Link to={href.newSource} className="site-link"
                  aria-current={route.view === "new-source" ? "page" : undefined}>New source</Link>
            <Link to={href.credits} className="site-link"
                  aria-current={route.view === "credits" ? "page" : undefined}>Credits</Link>
          </nav>
        </div>
      </div>
      <div className="account-strip">
        <span className="account-strip-name"><span className="account-strip-label">
          {identity.state === "bound" ? "Signed in as" : "This tab was opened for"}</span>{" "}
          {session.user.display_name}</span>
        <button type="button" onClick={leave}>Sign out</button>
      </div>
      <main className="page client" data-view={route.view} ref={main}>
        {identity.state === "elsewhere" && (
          <div className="client-notice is-unconfirmed" role="status" data-account="elsewhere">
            <p>In another tab or window, this browser has been signed in to another account. This tab still shows what
              was read for {session.user.display_name}, and nothing more is read or saved from it.</p>
            <p className="client-actions"><button type="button" className="button button-quiet" onClick={stop}>See how
              to continue</button></p>
          </div>
        )}
        <RecoveredWork route={route} />
        {route.view === "news" && <NewsHome tab={route.tab} />}
        {route.view === "story" && <StoryView key={route.storyId} storyId={route.storyId} />}
        {route.view === "deeper" && <DeeperPage key={route.storyId} storyId={route.storyId} />}
        {route.view === "topic" && <TopicView key={route.topicId} topicId={route.topicId} />}
        {route.view === "reports" && <NewsPage />}
        {route.view === "analyses" && <HomePage />}
        {route.view === "import" && <ImportPage key={route.importId} importId={route.importId} />}
        {route.view === "sources" && <SourcesPage />}
        {route.view === "new-source" && <NewSourcePage />}
        {route.view === "source" && <SourcePage key={route.sourceId} sourceId={route.sourceId} />}
        {route.view === "analysis" && <AnalysisPage key={route.analysisId} analysisId={route.analysisId} />}
        {route.view === "credits" && <CreditsPage />}
        {route.view === "signed-in" && (
          <section className="card client-card" data-view-note="signed-in">
            <h1 className="client-title">You are already signed in</h1>
            <p>You are signed in as {session.user.display_name}. To register another account or sign in as someone
              else, sign out first.</p>
            <p className="client-actions"><Link className="button" to={href.news}>The news</Link>
              <Link to={href.analyses}>Your analyses</Link> <Link to={href.credits}>Your credits</Link></p>
          </section>
        )}
        {route.view === "not-found" && (
          <section className="card client-card" role="alert">
            <h1 className="client-title">Not found</h1>
            <p>This address is not a page of your research workspace.</p>
            <p><Link to={href.news}>The news</Link> · <Link to={href.analyses}>Your analyses</Link></p>
          </section>
        )}
      </main>
    </ClientContext.Provider>
  );
}
