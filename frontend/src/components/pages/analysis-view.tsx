import { useState } from "react";
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
import { Send } from "lucide-react";
import { api, type AnalyzeResponse } from "@/lib/api";

export function AnalysisView() {
  const [headline, setHeadline] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!headline.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.analyze({
        headline: headline.trim(),
        event_date: eventDate || undefined,
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Analyze a Headline</CardTitle>
          <CardDescription>
            Enter a geopolitical or policy headline to classify and analyze.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="e.g. US imposes new tariffs on steel"
              value={headline}
              onChange={(e) => setHeadline(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              className="flex-1 rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <input
              type="date"
              value={eventDate}
              onChange={(e) => setEventDate(e.target.value)}
              className="w-36 rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <Button onClick={submit} disabled={loading || !headline.trim()}>
              <Send className="mr-2 h-3.5 w-3.5" />
              {loading ? "Analyzing..." : "Analyze"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive">
          <CardContent className="py-3 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      )}

      {result && (
        <ScrollArea className="h-[calc(100vh-18rem)]">
          <div className="space-y-4 pr-3">
            {/* Classification */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{result.headline}</CardTitle>
                <CardDescription className="flex gap-2 pt-1">
                  <Badge variant="outline">{result.stage}</Badge>
                  <Badge variant="outline">{result.persistence}</Badge>
                  <Badge variant={result.is_mock ? "destructive" : "secondary"}>
                    {result.is_mock ? "mock" : result.analysis.confidence}
                  </Badge>
                </CardDescription>
              </CardHeader>
            </Card>

            {/* Mechanism */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-xs text-muted-foreground uppercase tracking-wider">
                  Mechanism
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  <span className="font-medium">What changed: </span>
                  {result.analysis.what_changed}
                </p>
                <Separator />
                <p>{result.analysis.mechanism_summary}</p>
              </CardContent>
            </Card>

            {/* Tickers */}
            <div className="grid grid-cols-2 gap-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs text-muted-foreground uppercase tracking-wider">
                    Beneficiaries
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {result.analysis.beneficiaries.map((b) => (
                      <Badge key={b} variant="secondary">{b}</Badge>
                    ))}
                    {result.analysis.beneficiaries.length === 0 && (
                      <span className="text-xs text-muted-foreground">None identified</span>
                    )}
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs text-muted-foreground uppercase tracking-wider">
                    Losers
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {result.analysis.losers.map((l) => (
                      <Badge key={l} variant="secondary">{l}</Badge>
                    ))}
                    {result.analysis.losers.length === 0 && (
                      <span className="text-xs text-muted-foreground">None identified</span>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Market note */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-xs text-muted-foreground uppercase tracking-wider">
                  Market Check
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                {result.market.note}
              </CardContent>
            </Card>
          </div>
        </ScrollArea>
      )}

      {!result && !error && (
        <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
          Enter a headline above to begin analysis.
        </div>
      )}
    </div>
  );
}
