// The Admin entry point: every existing operator page, unchanged, and in accounts mode the Admin screens (users,
// credits and holds, actions, policy and settings, usage and limits, the News desk) under an administrator bar. Mounted by src/main.tsx through the
// shell, only for an admin session (the server serves this build to admins only). In local-operator mode (a server
// without accounts) the app is exactly the operator app it was before accounts existed.
import { App } from "../App";
import { Link, useLocation } from "../router";
import type { ShellProps } from "../shell/Shell";
import { AdminActions } from "./AdminActions";
import { bindAdminAccount } from "./adminApi.ts";
import { ADMIN_SCREENS, SCREEN_LABEL, adminScreen, type AdminScreen } from "./adminFormat.ts";
import { AdminLedger } from "./AdminLedger";
import { AdminNews } from "./AdminNews";
import { AdminPolicy } from "./AdminPolicy";
import { AdminRegistrations } from "./AdminRegistrations";
import { AdminUsage } from "./AdminUsage";
import { AdminUsers } from "./AdminUsers";
import "./admin.css";

export type AdminAppProps = Pick<ShellProps, "session" | "signOut">;

const SCREENS: Record<AdminScreen, () => JSX.Element> = {
  users: AdminUsers, registrations: AdminRegistrations, credits: AdminLedger, actions: AdminActions,
  policy: AdminPolicy, usage: AdminUsage, news: AdminNews,
};

export function AdminApp({ session, signOut }: AdminAppProps) {
  const { pathname } = useLocation();
  if (session.mode !== "accounts") return <App />;
  bindAdminAccount(session.user.user_id);  // Before any screen's first read: every Admin request names this account.
  const screen = adminScreen(pathname);
  const Screen = screen ? SCREENS[screen] : null;
  return (
    <>
      <div className="admin-bar">
        <nav aria-label="Administration">
          <Link to="/" aria-current={screen === null ? "page" : undefined}>Operator pages</Link>
          {ADMIN_SCREENS.map((name) => (
            <Link key={name} to={name === "users" ? "/admin" : `/admin/${name}`}
                  aria-current={screen === name ? "page" : undefined}>{SCREEN_LABEL[name]}</Link>
          ))}
        </nav>
        <span className="admin-account" aria-label="Account">
          <span>{session.user.display_name}</span>
          <span className="admin-role">Administrator</span>
          <button type="button" onClick={() => void signOut()}>Sign out</button>
        </span>
      </div>
      {Screen ? <main className="page"><Screen /></main> : <App />}
    </>
  );
}
