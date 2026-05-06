import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Key, Lock, Eye, EyeOff, Plus, Trash2, Copy, CheckCircle2, Send, WifiOff, Shield } from "lucide-react";
import { toast } from "sonner";
import { authApi, configApi } from "../lib/api";
import type { APIKeyCreated } from "../types";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "../components/ui/dialog";
import { formatDate } from "../lib/utils";
import { useAuthStore } from "../store/authStore";

function SlackSection() {
  const [webhook, setWebhook] = useState("");

  const { data: slackConfig } = useQuery({
    queryKey: ["slack-config"],
    queryFn: configApi.getSlack,
  });

  const { mutate: save } = useMutation({
    mutationFn: (url: string) => configApi.setSlack(url),
    onSuccess: () => { toast.success("Slack webhook saved"); setWebhook(""); },
    onError: (e: any) => toast.error(e.response?.data?.detail ?? "Failed to save"),
  });

  const { mutate: testHook, isPending: testPending } = useMutation({
    mutationFn: configApi.testSlack,
    onSuccess: () => toast.success("Test message sent! Check your Slack channel."),
    onError: () => toast.error("Webhook test failed — verify the URL"),
  });

  const { mutate: disable } = useMutation({
    mutationFn: configApi.disableSlack,
    onSuccess: () => { toast.success("Slack notifications disabled"); },
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-violet-500/10">
            <MessageSquare className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <CardTitle className="text-sm">Slack Notifications</CardTitle>
            <CardDescription>Get alerted when hot leads are found</CardDescription>
          </div>
          {slackConfig?.configured ? (
            <Badge variant="success" className="ml-auto">Connected</Badge>
          ) : (
            <Badge variant="secondary" className="ml-auto">Not connected</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {slackConfig?.configured ? (
          <div className="flex items-center gap-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <p className="text-sm text-emerald-400">Slack webhook is configured and active</p>
          </div>
        ) : null}

        <div className="space-y-2">
          <Label>Webhook URL</Label>
          <Input
            type="url"
            placeholder="https://hooks.slack.com/services/..."
            value={webhook}
            onChange={(e) => setWebhook(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Create a webhook at api.slack.com/apps → Incoming Webhooks
          </p>
        </div>

        <div className="flex gap-2">
          <Button
            variant="gradient"
            size="sm"
            disabled={!webhook.startsWith("https://hooks.slack.com/")}
            onClick={() => save(webhook)}
            className="gap-1.5"
          >
            Save Webhook
          </Button>
          {slackConfig?.configured && (
            <>
              <Button variant="outline" size="sm" onClick={() => testHook()} loading={testPending} className="gap-1.5">
                <Send className="w-3.5 h-3.5" />
                Test
              </Button>
              <Button variant="ghost" size="sm" onClick={() => disable()} className="text-red-400 hover:text-red-400 hover:bg-red-500/10 gap-1.5">
                <WifiOff className="w-3.5 h-3.5" />
                Disconnect
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function NewKeyDialog({ open, onOpenChange, onCreate }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreate: (key: APIKeyCreated) => void;
}) {
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const key = await authApi.createApiKey(name);
      onCreate(key);
      onOpenChange(false);
      setName("");
    } catch (err: any) {
      toast.error(err.response?.data?.detail ?? "Failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create API Key</DialogTitle>
          <DialogDescription>Name this key for identification. The raw key is shown only once.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleCreate} className="space-y-4 mt-2">
          <div className="space-y-2">
            <Label>Key Name</Label>
            <Input placeholder="e.g. Production, CRM Integration" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" variant="gradient" loading={loading}>Create Key</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RevealedKeyDialog({ apiKey, onClose }: { apiKey: APIKeyCreated; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(apiKey.key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            API Key Created
          </DialogTitle>
          <DialogDescription>Copy this key now — it will never be shown again.</DialogDescription>
        </DialogHeader>
        <div className="mt-2 space-y-3">
          <div className="flex items-center gap-2 p-3 rounded-lg bg-secondary font-mono text-xs break-all">
            <span className="flex-1">{apiKey.key}</span>
            <button onClick={copy} className="shrink-0 p-1.5 rounded hover:bg-border transition-colors">
              {copied ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4 text-muted-foreground" />}
            </button>
          </div>
          <p className="text-xs text-yellow-400/80 flex items-start gap-1.5">
            <Shield className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            Store this key securely. Use it in the <code className="bg-secondary px-1 rounded">X-API-Key</code> header.
          </p>
        </div>
        <DialogFooter>
          <Button variant="gradient" onClick={onClose}>Done — I've saved my key</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function APIKeysSection() {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [revealedKey, setRevealedKey] = useState<APIKeyCreated | null>(null);

  const { data: keys = [] } = useQuery({ queryKey: ["api-keys"], queryFn: authApi.listApiKeys });

  const { mutate: revoke } = useMutation({
    mutationFn: authApi.revokeApiKey,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["api-keys"] }); toast.success("API key revoked"); },
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-indigo-500/10">
              <Key className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <CardTitle className="text-sm">API Keys</CardTitle>
              <CardDescription>Use keys instead of passwords for programmatic access</CardDescription>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)} className="gap-1.5">
            <Plus className="w-3.5 h-3.5" />
            New Key
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {keys.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            No API keys yet — create one to access the API programmatically
          </div>
        ) : (
          <div className="space-y-2">
            {keys.map((key) => (
              <div key={key.id} className="flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-secondary/30 transition-colors">
                <Key className="w-4 h-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{key.name}</p>
                  <p className="text-xs font-mono text-muted-foreground">{key.key_prefix}•••••••••••••</p>
                </div>
                {key.last_used_at ? (
                  <span className="text-xs text-muted-foreground">Used {formatDate(key.last_used_at)}</span>
                ) : (
                  <span className="text-xs text-muted-foreground">Never used</span>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-red-400 hover:bg-red-500/10 hover:text-red-400 shrink-0"
                  onClick={() => { if (confirm("Revoke this key?")) revoke(key.id); }}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>

      <NewKeyDialog open={createOpen} onOpenChange={setCreateOpen} onCreate={setRevealedKey} />
      {revealedKey && <RevealedKeyDialog apiKey={revealedKey} onClose={() => setRevealedKey(null)} />}
    </Card>
  );
}

function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleChange = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next.length < 8) { toast.error("Password must be at least 8 characters"); return; }
    setLoading(true);
    try {
      await authApi.changePassword(current, next);
      toast.success("Password changed successfully");
      setCurrent(""); setNext("");
    } catch (err: any) {
      toast.error(err.response?.data?.detail ?? "Failed to change password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-orange-500/10">
            <Lock className="w-5 h-5 text-orange-400" />
          </div>
          <div>
            <CardTitle className="text-sm">Change Password</CardTitle>
            <CardDescription>Update your account password</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleChange} className="space-y-4 max-w-sm">
          <div className="space-y-2">
            <Label>Current Password</Label>
            <Input type={show ? "text" : "password"} value={current} onChange={(e) => setCurrent(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label>New Password</Label>
            <div className="relative">
              <Input type={show ? "text" : "password"} value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} />
              <button type="button" onClick={() => setShow(!show)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <Button type="submit" variant="gradient" size="sm" loading={loading}>Update Password</Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function Settings() {
  const { user } = useAuthStore();

  return (
    <div className="flex flex-col min-h-screen">
      <Header title="Settings" subtitle="Configure integrations and manage your account" />

      <div className="flex-1 p-8 space-y-6 max-w-3xl animate-fade-in">
        {/* Profile card */}
        <Card className="bg-gradient-to-br from-violet-500/10 to-indigo-500/5 border-violet-500/20">
          <CardContent className="p-5 flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center text-white font-semibold text-lg">
              {user?.email.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <p className="font-semibold">{user?.email}</p>
              <div className="flex items-center gap-2 mt-0.5">
                <Badge variant={user?.role as any}>{user?.role}</Badge>
                <span className="text-xs text-muted-foreground">Member since {user ? formatDate(user.created_at) : "—"}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <SlackSection />
        <APIKeysSection />
        <PasswordSection />
      </div>
    </div>
  );
}
