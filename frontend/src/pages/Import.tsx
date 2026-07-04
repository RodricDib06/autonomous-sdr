import { useState, useRef, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, FileText, CheckCircle2, XCircle, Clock, ArrowUpFromLine } from "lucide-react";
import { toast } from "sonner";
import { leadsApi } from "../lib/api";
import type { ImportResult } from "../types";
import { Header } from "../components/layout/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { formatDate, cn, apiErrorMessage } from "../lib/utils";

function DropZone({ onFile }: { onFile: (f: File) => void }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".csv")) onFile(file);
    else toast.error("Only CSV files are supported");
  }, [onFile]);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={cn(
        "relative border-2 border-dashed rounded-2xl p-16 text-center cursor-pointer transition-all",
        dragging
          ? "border-primary bg-primary/10 scale-[1.02]"
          : "border-border hover:border-primary/50 hover:bg-secondary/30"
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }}
      />
      <div className="flex flex-col items-center gap-4">
        <div className={cn(
          "w-16 h-16 rounded-2xl flex items-center justify-center transition-colors",
          dragging ? "bg-primary/20" : "bg-secondary"
        )}>
          <ArrowUpFromLine className={cn("w-8 h-8 transition-colors", dragging ? "text-primary" : "text-muted-foreground")} />
        </div>
        <div>
          <p className="font-semibold text-lg">{dragging ? "Drop it!" : "Drop CSV here"}</p>
          <p className="text-sm text-muted-foreground mt-1">or click to browse · CSV format required</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2 text-xs text-muted-foreground">
          {["name", "email", "company", "source (optional)"].map((field) => (
            <Badge key={field} variant="secondary" className="font-mono">{field}</Badge>
          ))}
        </div>
      </div>
    </div>
  );
}

function ImportResultCard({ result }: { result: ImportResult }) {
  const total = result.total;
  const successRate = total > 0 ? (result.successful / total) * 100 : 0;

  return (
    <Card className="border-border bg-card animate-fade-in">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <CardTitle className="text-sm">Import Complete</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Total", value: result.total, color: "text-foreground" },
            { label: "Imported", value: result.successful, color: "text-emerald-400" },
            { label: "Duplicates", value: result.duplicates, color: "text-yellow-400" },
            { label: "Failed", value: result.failed, color: "text-red-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="text-center p-3 rounded-lg bg-secondary/50">
              <p className={cn("text-2xl font-bold", color)}>{value}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
            </div>
          ))}
        </div>

        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Success rate</span>
            <span>{Math.round(successRate)}%</span>
          </div>
          <div className="w-full bg-secondary rounded-full h-2 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-violet-500 to-emerald-500 transition-all"
              style={{ width: `${successRate}%` }}
            />
          </div>
        </div>

        {result.errors.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Errors</p>
            <div className="max-h-32 overflow-y-auto space-y-1">
              {result.errors.map((e, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 rounded-md px-2.5 py-1.5">
                  <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  {e}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function Import() {
  const qc = useQueryClient();
  const [lastResult, setLastResult] = useState<ImportResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ["import-history"],
    queryFn: () => leadsApi.importHistory(20),
  });

  const handleFile = async (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    setLastResult(null);

    // Fake progress animation while uploading
    const interval = setInterval(() => {
      setUploadProgress((p) => Math.min(p + 15, 85));
    }, 200);

    try {
      const result = await leadsApi.importCsv(file);
      clearInterval(interval);
      setUploadProgress(100);
      setLastResult(result);
      qc.invalidateQueries({ queryKey: ["import-history"] });
      qc.invalidateQueries({ queryKey: ["leads"] });
      toast.success(`Imported ${result.successful} leads from ${file.name}`);
    } catch (err) {
      clearInterval(interval);
      toast.error(apiErrorMessage(err, "Import failed"));
    } finally {
      setTimeout(() => { setUploading(false); setUploadProgress(0); }, 500);
    }
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header title="Import" subtitle="Upload leads from CSV files" />

      <div className="flex-1 p-8 space-y-8 animate-fade-in">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Upload area */}
          <div className="space-y-4">
            <DropZone onFile={handleFile} />

            {uploading && (
              <Card className="animate-fade-in">
                <CardContent className="p-4 space-y-2">
                  <div className="flex items-center gap-2 text-sm">
                    <Upload className="w-4 h-4 text-primary animate-bounce" />
                    <span>Uploading & processing…</span>
                  </div>
                  <div className="w-full bg-secondary rounded-full h-2 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-violet-500 to-indigo-500 transition-all duration-300"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                </CardContent>
              </Card>
            )}

            {lastResult && <ImportResultCard result={lastResult} />}

            {/* CSV format guide */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <FileText className="w-4 h-4 text-muted-foreground" />
                  CSV Format Guide
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="rounded-lg bg-secondary/70 p-3 font-mono text-xs text-muted-foreground overflow-x-auto">
                  <div className="text-primary/80 font-semibold">name,email,company,source</div>
                  <div>John Smith,john@acme.com,Acme Inc,linkedin</div>
                  <div>Jane Doe,jane@techcorp.com,TechCorp,referral</div>
                </div>
                <ul className="mt-3 text-xs text-muted-foreground space-y-1">
                  <li className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> name, email, company are required</li>
                  <li className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> source is optional (linkedin, referral, etc.)</li>
                  <li className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Duplicates are detected automatically</li>
                </ul>
              </CardContent>
            </Card>
          </div>

          {/* Import history */}
          <div>
            <Card className="h-full">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Clock className="w-4 h-4 text-muted-foreground" />
                      Import History
                    </CardTitle>
                    <CardDescription>Recent file uploads</CardDescription>
                  </div>
                  <Badge variant="secondary">{historyData?.count ?? 0} imports</Badge>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {historyLoading ? (
                  <div className="p-4 space-y-3">
                    {[...Array(4)].map((_, i) => <div key={i} className="skeleton h-14 rounded-lg" />)}
                  </div>
                ) : historyData?.imports.length ? (
                  <div className="divide-y divide-border">
                    {historyData.imports.map((imp) => (
                      <div key={imp.id} className="px-6 py-4 hover:bg-secondary/20 transition-colors">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-2.5 min-w-0">
                            <FileText className="w-4 h-4 text-muted-foreground shrink-0 mt-0.5" />
                            <div className="min-w-0">
                              <p className="text-sm font-medium truncate">{imp.filename}</p>
                              <p className="text-xs text-muted-foreground">{formatDate(imp.started_at)}</p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-xs text-emerald-400 font-medium">{imp.successful}✓</span>
                            {imp.failed > 0 && <span className="text-xs text-red-400">{imp.failed}✗</span>}
                            {imp.duplicates > 0 && <span className="text-xs text-yellow-400">{imp.duplicates}⊘</span>}
                          </div>
                        </div>
                        <div className="mt-2 w-full bg-secondary rounded-full h-1 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-violet-500 to-emerald-500"
                            style={{ width: imp.total > 0 ? `${(imp.successful / imp.total) * 100}%` : "0%" }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-12 text-center text-muted-foreground text-sm">
                    No imports yet — upload your first CSV file
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
