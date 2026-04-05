import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/queryKeys";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  RefreshCw,
  ChevronRight,
  ArrowLeft,
  Star,
  StickyNote,
  TrendingUp,
  TrendingDown,
  Minus,
  ShieldCheck,
  Shield,
  ShieldAlert,
  Calendar,
  Clock,
  Link2,
  Save,
  Loader2,
  Archive,
} from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { api, type SavedEvent, type Ticker } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Skeletons
// ---------------------------------------------------------------------------

function EventRowSkeleton() {
  return (
    <div className="rounded border border-transparent px-2.5 py-2">
      <div className="flex items-start gap-2.5">
        <Skeleton className="mt-0.5 hidden h-6 w-6 rounded sm:block" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <Skeleton className="h-3.5 w-4/5" />
          <div className="flex gap-1">
            <Skeleton className="h-3.5 w-14 rounded" />
            <Skeleton className="h-3.5 w-16 rounded" />
            <Skeleton className="h-3.5 w-12 rounded" />
          </div>
          <Skeleton className="h-3 w-28" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RATING_META: Record<string, { icon: React.ElementType; color: string; bg: string }> = {
  good:  { icon: TrendingUp,   color: "val-pos",        bg: "bg-emerald-500/10 border-emerald-500/20" },
  mixed: { icon: Minus,        color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
  poor:  { icon: TrendingDown, color: "val-neg",        bg: "bg-red-400/10 border-red-400/20" },
};

const CONFIDENCE_META: Record<string, { icon: React.ElementType; color: string }> = {
  high:   { icon: ShieldCheck, color: "val-pos" },
  medium: { icon: Shield,      color: "text-amber-400" },
  low:    { icon: ShieldAlert, color: "val-neg" },
};

function pct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function directionIcon(tag: string | null) {
  switch (tag) {
    case "supporting":
      return <TrendingUp className="h-3 w-3 val-pos" />;
    case "contradicting":
      return <TrendingDown className="h-3 w-3 val-neg" />;
    default:
      return <Minus className="h-3 w-3 val-flat" />;
  }
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-2xs font-medium uppercase tracking-widest text-muted-foreground">
      {children}
    </h3>
  );
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleDateString("en-GB", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Event row — compact
// ---------------------------------------------------------------------------

function EventRow({
  event,
  onClick,
}: {
  event: SavedEvent;
  onClick: () => void;
}) {
  const conf = CONFIDENCE_META[event.confidence] ?? { icon: ShieldAlert, color: "val-neg" };
  const ConfIcon = conf.icon;
  const rating = event.rating ? (RATING_META[event.rating] ?? null) : null;
  const RatingIcon = rating?.icon ?? Star;

  return (
    <button
      onClick={onClick}
      className="group w-full rounded-[18px] border border-border/60 bg-white/90 px-3 py-3 text-left shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition-all hover:-translate-y-px hover:border-border hover:bg-white hover:shadow-[0_12px_24px_rgba(15,23,42,0.05)] active:bg-secondary/60"
    >
      <div className="flex items-start gap-2.5">
        <div
          className={cn(
            "mt-0.5 hidden h-7 w-7 shrink-0 items-center justify-center rounded-xl border sm:flex",
            rating ? rating.bg : "bg-secondary border-border",
          )}
        >
          <RatingIcon className={cn("h-3 w-3", rating?.color ?? "text-muted-foreground")} />
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium leading-snug line-clamp-2">
            {event.headline}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <Badge variant="outline">{event.stage}</Badge>
            <Badge variant="outline">{event.persistence}</Badge>
            <span className={cn("inline-flex items-center gap-0.5 text-2xs", conf.color)}>
              <ConfIcon className="h-2.5 w-2.5" />
              {event.confidence}
            </span>
            {event.notes && (
              <StickyNote className="h-2.5 w-2.5 text-muted-foreground" />
            )}
            {rating && (
              <Badge variant="outline" className={cn("sm:hidden", rating.color)}>
                {event.rating}
              </Badge>
            )}
          </div>
          <p className="mt-0.5 font-num text-2xs text-muted-foreground">
            {formatTimestamp(event.timestamp)}
          </p>
        </div>

        <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Market table — compact (same pattern as analysis view)
// ---------------------------------------------------------------------------

function MarketTable({ tickers }: { tickers: Ticker[] }) {
  if (tickers.length === 0) return null;

  return (
    <div className="overflow-x-auto rounded border">
      <table className="w-full text-2xs">
        <thead>
          <tr className="border-b bg-secondary/50 text-muted-foreground">
            <th className="whitespace-nowrap px-2.5 py-1.5 text-left font-medium">Symbol</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-center font-medium">20d</th>
            <th className="hidden whitespace-nowrap px-2.5 py-1.5 text-left font-medium sm:table-cell">Role</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-center font-medium">Dir</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-right font-medium">1d</th>
            <th className="whitespace-nowrap px-2.5 py-1.5 text-right font-medium">5d</th>
            <th className="hidden whitespace-nowrap px-2.5 py-1.5 text-right font-medium md:table-cell">20d</th>
            <th className="hidden whitespace-nowrap px-2.5 py-1.5 text-right font-medium md:table-cell">Vol</th>
          </tr>
        </thead>
        <tbody>
          {tickers.map((t) => (
            <tr key={t.symbol} className="border-b last:border-0 hover:bg-secondary/30">
              <td className="whitespace-nowrap px-2.5 py-1.5 font-num font-semibold">{t.symbol}</td>
              <td className="px-2.5 py-1">
                <Sparkline
                  data={t.spark ?? []}
                  width={48}
                  height={16}
                  direction={t.return_20d}
                />
              </td>
              <td className="hidden whitespace-nowrap px-2.5 py-1.5 sm:table-cell">
                <Badge variant={t.role === "beneficiary" ? "secondary" : "outline"}>{t.role}</Badge>
              </td>
              <td className="px-2.5 py-1.5">
                <div className="flex items-center justify-center gap-1">
                  {directionIcon(t.direction_tag)}
                  <span>{t.label}</span>
                </div>
              </td>
              <td className={cn("whitespace-nowrap px-2.5 py-1.5 text-right font-num",
                t.return_1d > 0 && "val-pos", t.return_1d < 0 && "val-neg")}>{pct(t.return_1d)}</td>
              <td className={cn("whitespace-nowrap px-2.5 py-1.5 text-right font-num",
                t.return_5d > 0 && "val-pos", t.return_5d < 0 && "val-neg")}>{pct(t.return_5d)}</td>
              <td className={cn("hidden whitespace-nowrap px-2.5 py-1.5 text-right font-num md:table-cell",
                t.return_20d > 0 && "val-pos", t.return_20d < 0 && "val-neg")}>{pct(t.return_20d)}</td>
              <td className="hidden whitespace-nowrap px-2.5 py-1.5 text-right font-num md:table-cell">
                {t.volume_ratio != null ? `${t.volume_ratio.toFixed(1)}x` : "\u2014"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function EventDetail({
  event,
  onBack,
  onRatingChange,
  onNotesChange,
}: {
  event: SavedEvent;
  onBack: () => void;
  onRatingChange: (event: SavedEvent) => void;
  onNotesChange: (event: SavedEvent) => void;
}) {
  // related events loaded via useQuery below
  const [editingNotes, setEditingNotes] = useState(false);
  const [noteDraft, setNoteDraft] = useState(event.notes ?? "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [savingRating, setSavingRating] = useState<string | null>(null);

  const conf = CONFIDENCE_META[event.confidence] ?? { icon: ShieldAlert, color: "val-neg" };
  const ConfIcon = conf.icon;
  const rating = event.rating ? (RATING_META[event.rating] ?? null) : null;

  const { data: relatedData } = useQuery({
    queryKey: qk.related(event.id),
    queryFn: () => api.relatedEvents(event.id),
  });
  const related = relatedData ?? [];

  const setRating = async (r: string) => {
    const newRating = r === event.rating ? undefined : r;
    setSavingRating(r);
    try {
      await api.updateReview(event.id, { rating: newRating ?? "" });
      onRatingChange({ ...event, rating: newRating ?? null });
    } catch { /* ignore */ }
    setSavingRating(null);
  };

  const saveNotes = async () => {
    setSavingNotes(true);
    try {
      await api.updateReview(event.id, { notes: noteDraft });
      onNotesChange({ ...event, notes: noteDraft });
      setEditingNotes(false);
    } catch { /* ignore */ }
    setSavingNotes(false);
  };

  return (
    <div className="page-enter flex h-full flex-col">
      <div className="mb-2 shrink-0">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
          <ArrowLeft className="h-3 w-3" />
          Back
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="fade-in space-y-3 pb-4 pr-2">
          {/* Header */}
          <Card className="overflow-hidden border-border/80 bg-white/95">
            <CardHeader className="gap-3 border-b border-border/60 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(255,255,255,0.88))]">
              <p className="section-kicker">Saved research</p>
              <CardTitle className="text-sm leading-snug">{event.headline}</CardTitle>
              <CardDescription className="flex flex-wrap items-center gap-1.5 pt-1">
                <Badge variant="outline">{event.stage}</Badge>
                <Badge variant="outline">{event.persistence}</Badge>
                <Badge variant="secondary" className={cn("gap-1", conf.color)}>
                  <ConfIcon className="h-3 w-3" />
                  {event.confidence}
                </Badge>
                {event.event_date && (
                  <span className="inline-flex items-center gap-1 font-num text-2xs text-muted-foreground">
                    <Calendar className="h-3 w-3" />
                    {event.event_date}
                  </span>
                )}
                <span className="inline-flex items-center gap-1 font-num text-2xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {formatTimestamp(event.timestamp)}
                </span>
              </CardDescription>
            </CardHeader>
          </Card>

          {/* Rating */}
          <Card className="overflow-hidden">
            <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Review Rating</SectionLabel></CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1.5">
                {(["good", "mixed", "poor"] as const).map((r) => {
                  const meta = RATING_META[r]!;
                  const Icon = meta.icon;
                  const active = event.rating === r;
                  return (
                    <Button
                      key={r}
                      variant={active ? "secondary" : "outline"}
                      size="sm"
                      className={cn("capitalize", active && meta.bg)}
                      onClick={() => setRating(r)}
                      disabled={savingRating !== null}
                    >
                      {savingRating === r ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Icon className={cn("h-3 w-3", meta.color)} />
                      )}
                      {r}
                    </Button>
                  );
                })}
                {!rating && (
                  <span className="self-center text-2xs text-muted-foreground ml-1">
                    No review rating yet
                  </span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Mechanism grid */}
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="space-y-3 lg:col-span-2">
              {event.what_changed && (
                <Card className="overflow-hidden">
                  <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>What Changed</SectionLabel></CardHeader>
                  <CardContent>
                    <p className="text-[13px] leading-relaxed">{event.what_changed}</p>
                  </CardContent>
                </Card>
              )}
              {event.mechanism_summary && (
                <Card className="overflow-hidden">
                  <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Mechanism Summary</SectionLabel></CardHeader>
                  <CardContent>
                    <p className="text-[13px] leading-relaxed whitespace-pre-line">{event.mechanism_summary}</p>
                  </CardContent>
                </Card>
              )}
            </div>

            <div className="space-y-3">
              <Card className="overflow-hidden">
                <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Beneficiaries</SectionLabel></CardHeader>
                <CardContent>
                  {event.beneficiaries.length > 0 ? (
                    <ul className="space-y-0.5">
                      {event.beneficiaries.map((b) => (
                        <li key={b} className="flex items-center gap-1.5 text-[13px]">
                          <TrendingUp className="h-3 w-3 shrink-0 val-pos" />{b}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-2xs text-muted-foreground">No clear beneficiaries identified.</p>
                  )}
                </CardContent>
              </Card>
              <Card className="overflow-hidden">
                <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Losers</SectionLabel></CardHeader>
                <CardContent>
                  {event.losers.length > 0 ? (
                    <ul className="space-y-0.5">
                      {event.losers.map((l) => (
                        <li key={l} className="flex items-center gap-1.5 text-[13px]">
                          <TrendingDown className="h-3 w-3 shrink-0 val-neg" />{l}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-2xs text-muted-foreground">No clear losers identified.</p>
                  )}
                </CardContent>
              </Card>
              {event.assets_to_watch.length > 0 && (
                <Card className="overflow-hidden">
                  <CardHeader className="border-b border-border/60 bg-secondary/35"><SectionLabel>Assets to Watch</SectionLabel></CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-1">
                      {event.assets_to_watch.map((a) => (
                        <Badge key={a} variant="outline" className="font-num">{a}</Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>

          {/* Market */}
          {event.market_tickers.length > 0 && (
            <>
              <Separator />
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <SectionLabel>Market Check</SectionLabel>
                  <span className="font-num text-2xs text-muted-foreground">
                    {event.market_tickers.length} ticker{event.market_tickers.length !== 1 && "s"}
                  </span>
                </div>
                {event.market_note && (
                  <p className="text-2xs text-muted-foreground">{event.market_note}</p>
                )}
                <MarketTable tickers={event.market_tickers} />
              </div>
            </>
          )}

          {/* Notes */}
          <Separator />
          <Card className="overflow-hidden">
            <CardHeader>
              <div className="flex items-center justify-between">
                <SectionLabel>Research Notes</SectionLabel>
                {!editingNotes && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 text-2xs"
                    onClick={() => { setNoteDraft(event.notes ?? ""); setEditingNotes(true); }}
                  >
                    {event.notes ? "Edit notes" : "Add notes"}
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {editingNotes ? (
                <div className="space-y-2">
                  <textarea
                    value={noteDraft}
                    onChange={(e) => setNoteDraft(e.target.value)}
                    rows={3}
                    className="w-full rounded border bg-background px-2.5 py-1.5 text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-y"
                    placeholder="Add research notes, follow-ups, or observations..."
                    autoFocus
                  />
                  <div className="flex gap-1.5">
                    <Button size="sm" onClick={saveNotes} disabled={savingNotes}>
                      {savingNotes ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                      Save
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setEditingNotes(false)}>Cancel</Button>
                  </div>
                </div>
              ) : event.notes ? (
                <p className="text-[13px] leading-relaxed whitespace-pre-line">{event.notes}</p>
              ) : (
                <p className="text-2xs text-muted-foreground">No research notes yet.</p>
              )}
            </CardContent>
          </Card>

          {/* Related events */}
          {related.length > 0 && (
            <>
              <Separator />
              <div className="space-y-2">
                <SectionLabel>Related Events</SectionLabel>
                <div className="space-y-2">
                  {related.map((r) => (
                    <div key={r.id} className="flex items-start gap-2 rounded-[16px] border border-border/70 bg-white/90 px-3 py-2.5">
                      <Link2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] font-medium leading-snug">{r.headline}</p>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1">
                          <Badge variant="outline">{r.stage}</Badge>
                          <Badge variant="outline">{r.persistence}</Badge>
                          <span className="font-num text-2xs text-muted-foreground">{formatTimestamp(r.timestamp)}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

export function RecentEvents() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: events = [], isLoading: loading, error: queryError, refetch } = useQuery({
    queryKey: qk.events(50),
    queryFn: () => api.events(50),
  });
  const error = queryError instanceof Error ? queryError.message : queryError ? String(queryError) : null;

  const selectedEvent = events.find((e) => e.id === selectedId) ?? null;

  const updateEvent = useCallback((updated: SavedEvent) => {
    queryClient.setQueryData<SavedEvent[]>(qk.events(50), (old) =>
      old?.map((e) => (e.id === updated.id ? updated : e)) ?? [],
    );
  }, [queryClient]);

  if (selectedEvent) {
    return (
      <EventDetail
        event={selectedEvent}
        onBack={() => setSelectedId(null)}
        onRatingChange={updateEvent}
        onNotesChange={updateEvent}
      />
    );
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="soft-panel flex shrink-0 flex-col gap-3 rounded-[22px] px-4 py-4 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-border bg-white">
            <Archive className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="min-w-0 space-y-1">
            <p className="section-kicker">Archive</p>
            <h2 className="truncate text-lg font-semibold tracking-[-0.02em] text-foreground">Research Archive</h2>
            <p className="text-[12px] leading-5 text-muted-foreground">
              {loading ? "Loading archive..." : <><span className="font-num">{events.length}</span> saved event{events.length !== 1 ? "s" : ""} with notes, ratings, and linked follow-ups.</>}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={loading} className="shrink-0">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          <span className="hidden sm:inline">Refresh archive</span>
        </Button>
      </div>

      {error && (
        <Card className="shrink-0 border-destructive/30 bg-destructive/5">
          <CardContent className="py-4 text-2xs leading-5 text-destructive">{error}</CardContent>
        </Card>
      )}

      {loading && events.length === 0 && (
        <div className="min-h-0 flex-1 space-y-0.5">
          {Array.from({ length: 6 }).map((_, i) => <EventRowSkeleton key={i} />)}
        </div>
      )}

      {!loading && !error && events.length === 0 && (
        <Card className="empty-surface flex flex-1 items-center justify-center bg-transparent">
          <CardContent className="flex max-w-md flex-col items-center gap-3 py-12 text-center text-muted-foreground">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border border-border bg-white">
              <Archive className="h-6 w-6 opacity-70" />
            </div>
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-foreground">No saved events yet</p>
              <p className="text-[12px] leading-5">Run an analysis and save the result to start building the archive.</p>
            </div>
          </CardContent>
        </Card>
      )}

      {events.length > 0 && (
        <ScrollArea className="min-h-0 flex-1">
          <div className="fade-in space-y-2 pr-2">
            {events.map((ev) => (
              <EventRow key={ev.id} event={ev} onClick={() => setSelectedId(ev.id)} />
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
