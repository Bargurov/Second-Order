import { useEffect, useState } from "react";
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
import { RefreshCw } from "lucide-react";
import { api, type SavedEvent } from "@/lib/api";

const CONFIDENCE_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  high: "default",
  medium: "secondary",
  low: "outline",
};

export function RecentEvents() {
  const [events, setEvents] = useState<SavedEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setEvents(await api.events(50));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load events");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Saved Events</h2>
          <p className="text-sm text-muted-foreground">
            {events.length} event{events.length !== 1 && "s"} in archive
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {error && (
        <Card className="border-destructive">
          <CardContent className="py-3 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      )}

      <ScrollArea className="h-[calc(100vh-12rem)]">
        <div className="space-y-3 pr-3">
          {events.length === 0 && !loading && !error && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No saved events yet. Analyze a headline to create one.
            </p>
          )}
          {events.map((ev) => (
            <Card key={ev.id}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-sm leading-snug">
                    {ev.headline}
                  </CardTitle>
                  {ev.rating && (
                    <Badge
                      variant={
                        ev.rating === "good"
                          ? "default"
                          : ev.rating === "poor"
                            ? "destructive"
                            : "secondary"
                      }
                      className="shrink-0"
                    >
                      {ev.rating}
                    </Badge>
                  )}
                </div>
                <CardDescription className="flex flex-wrap items-center gap-2 pt-1">
                  <Badge variant="outline">{ev.stage}</Badge>
                  <Badge variant="outline">{ev.persistence}</Badge>
                  <Badge variant={CONFIDENCE_VARIANT[ev.confidence] ?? "outline"}>
                    {ev.confidence}
                  </Badge>
                  {ev.event_date && (
                    <span className="text-[11px]">{ev.event_date}</span>
                  )}
                  <span className="text-[11px] text-muted-foreground">
                    {ev.timestamp}
                  </span>
                </CardDescription>
              </CardHeader>
              {(ev.mechanism_summary || ev.notes) && (
                <>
                  <Separator className="mx-6" />
                  <CardContent className="pt-3 text-sm text-muted-foreground">
                    {ev.mechanism_summary && <p>{ev.mechanism_summary}</p>}
                    {ev.notes && (
                      <p className="mt-1 italic">{ev.notes}</p>
                    )}
                  </CardContent>
                </>
              )}
            </Card>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
