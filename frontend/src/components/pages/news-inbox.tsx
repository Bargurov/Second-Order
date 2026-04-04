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
import { RefreshCw } from "lucide-react";
import { api, type NewsCluster } from "@/lib/api";

export function NewsInbox() {
  const [clusters, setClusters] = useState<NewsCluster[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.news();
      setClusters(data.clusters);
      setTotal(data.total_headlines);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch news");
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
          <h2 className="text-lg font-semibold">Headline Clusters</h2>
          <p className="text-sm text-muted-foreground">
            {total} headlines ingested
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={load}
          disabled={loading}
        >
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
          {clusters.length === 0 && !loading && !error && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No clusters yet. Start the FastAPI backend and refresh.
            </p>
          )}
          {clusters.map((c, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm leading-snug">
                  {c.headline}
                </CardTitle>
                <CardDescription className="flex items-center gap-2">
                  <Badge variant="secondary" className="text-[10px]">
                    {c.source_count} source{c.source_count !== 1 && "s"}
                  </Badge>
                  {c.sources.map((s) => (
                    <span key={s.name} className="text-[11px]">
                      {s.name}
                    </span>
                  ))}
                </CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
