import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  MessageSquare, Key, Lock, Eye, EyeOff, Plus, Trash2, Copy, CheckCircle2, Send, WifiOff,
  Shield, ShieldBan, Gauge, AtSign, Flame, Mail, MailCheck, XCircle, HelpCircle, AlertTriangle,
  Link2, ArrowUpRight, ArrowDownLeft,
} from "lucide-react";
import { toast } from "sonner";
import {
  authApi, configApi, complianceApi, mailboxesApi, verificationApi, crmApi2,
  type MailboxCreatePayload, type OAuthProvider, type EmailVerification,
} from "../lib/api";
import type { APIKeyCreated } from "../types";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "../components/ui/dialog";
import { formatDate, apiErrorMessage } from "../lib/utils";
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
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Failed to save")),
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
    } catch (err) {
      toast.error(apiErrorMessage(err, "Failed"));
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
    } catch (err) {
      toast.error(apiErrorMessage(err, "Failed to change password"));
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

function MailboxSection() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<MailboxCreatePayload>({
    email: "", display_name: "", smtp_host: "", smtp_username: "", smtp_password: "",
    imap_host: "", imap_enabled: true, daily_limit: 50, start_warmup: true,
  });

  const { data } = useQuery({ queryKey: ["mailboxes"], queryFn: mailboxesApi.list });

  const { mutate: create, isPending: creating } = useMutation({
    mutationFn: () => mailboxesApi.create({ ...form, imap_host: form.imap_host || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mailboxes"] });
      setShowForm(false);
      setForm({ email: "", display_name: "", smtp_host: "", smtp_username: "", smtp_password: "", imap_host: "", imap_enabled: true, daily_limit: 50, start_warmup: true });
      toast.success("Mailbox added — warm-up ramp starts at 10 sends/day");
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Failed to add mailbox")),
  });

  const { mutate: testBox } = useMutation({
    mutationFn: mailboxesApi.test,
    onSuccess: (res) => (res.ok ? toast.success(res.message) : toast.error(res.message)),
  });

  const { mutate: remove } = useMutation({
    mutationFn: mailboxesApi.deactivate,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mailboxes"] }); toast.success("Mailbox deactivated"); },
  });

  const { mutate: connectOAuth, isPending: oauthPending } = useMutation({
    mutationFn: (provider: OAuthProvider) => mailboxesApi.oauthStart(provider),
    onSuccess: (res) => {
      // Hand the browser to the provider's consent screen; the callback
      // creates the mailbox and this page shows it on return.
      window.location.assign(res.authorize_url);
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "OAuth is not configured on the server")),
  });

  const valid = form.email.includes("@") && form.smtp_host && form.smtp_username && form.smtp_password;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-sky-500/10">
              <AtSign className="w-5 h-5 text-sky-400" />
            </div>
            <div>
              <CardTitle className="text-sm">Sending Mailboxes</CardTitle>
              <CardDescription>Rotate sends across warmed identities; replies are polled automatically</CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline" size="sm" disabled={oauthPending}
              onClick={() => connectOAuth("gmail")} className="gap-1.5"
            >
              <Mail className="w-3.5 h-3.5" />
              Connect Gmail
            </Button>
            <Button
              variant="outline" size="sm" disabled={oauthPending}
              onClick={() => connectOAuth("microsoft")} className="gap-1.5"
            >
              <Mail className="w-3.5 h-3.5" />
              Connect Microsoft 365
            </Button>
            <Button variant="outline" size="sm" onClick={() => setShowForm(!showForm)} className="gap-1.5">
              <Plus className="w-3.5 h-3.5" />
              SMTP
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {showForm && (
          <div className="p-3 rounded-lg border border-border grid grid-cols-2 gap-2">
            <Input placeholder="Email (from address)" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <Input placeholder="Display name" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
            <Input placeholder="SMTP host" value={form.smtp_host} onChange={(e) => setForm({ ...form, smtp_host: e.target.value })} />
            <Input placeholder="SMTP username" value={form.smtp_username} onChange={(e) => setForm({ ...form, smtp_username: e.target.value })} />
            <Input type="password" placeholder="SMTP password / app password" value={form.smtp_password} onChange={(e) => setForm({ ...form, smtp_password: e.target.value })} />
            <Input placeholder="IMAP host (optional, for replies)" value={form.imap_host} onChange={(e) => setForm({ ...form, imap_host: e.target.value, imap_enabled: !!e.target.value })} />
            <div className="col-span-2 flex items-center justify-between">
              <p className="text-[11px] text-muted-foreground">
                Credentials are encrypted at rest. New mailboxes warm up from 10 sends/day.
              </p>
              <Button size="sm" variant="gradient" disabled={!valid} loading={creating} onClick={() => create()}>
                Save mailbox
              </Button>
            </div>
          </div>
        )}

        {(data?.mailboxes.length ?? 0) === 0 && !showForm ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No mailboxes yet — connect Gmail / Microsoft 365 with one click (works even when your
            admin has disabled app passwords), or add any SMTP mailbox. Without one, outreach falls
            back to the global SMTP settings (or demo mode).
          </p>
        ) : (
          <div className="space-y-2">
            {data?.mailboxes.map((m) => (
              <div key={m.id} className="flex items-center gap-3 p-3 rounded-lg border border-border">
                <AtSign className="w-4 h-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium truncate">{m.email}</p>
                    {m.warming_up && (
                      <Badge variant="warning" className="text-[10px] gap-1"><Flame className="w-2.5 h-2.5" />warming up</Badge>
                    )}
                    {m.provider === "gmail_oauth" && <Badge variant="admin" className="text-[10px]">Gmail API</Badge>}
                    {m.provider === "microsoft_oauth" && <Badge variant="manager" className="text-[10px]">Microsoft 365</Badge>}
                    {m.provider === "smtp" && m.imap_enabled && <Badge variant="secondary" className="text-[10px]">IMAP</Badge>}
                    {!m.is_active && <Badge variant="destructive" className="text-[10px]">inactive</Badge>}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {m.sent_last_24h}/{m.effective_daily_limit} today · cap {m.daily_limit}/day
                  </p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => testBox(m.id)} className="text-xs">Test login</Button>
                {m.is_active && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-red-400 hover:bg-red-500/10 hover:text-red-400 shrink-0 h-7 w-7"
                    onClick={() => { if (confirm(`Deactivate ${m.email}?`)) remove(m.id); }}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CrmSection() {
  const qc = useQueryClient();

  const { data: status } = useQuery({ queryKey: ["crm-status"], queryFn: crmApi2.status });
  const hubspot = status?.hubspot;
  const { data: logData } = useQuery({
    queryKey: ["crm-log"],
    queryFn: () => crmApi2.log(8),
    enabled: !!hubspot?.connected,
  });

  const { mutate: connect, isPending: connecting } = useMutation({
    mutationFn: crmApi2.hubspotStart,
    onSuccess: (res) => window.location.assign(res.authorize_url),
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "HubSpot OAuth is not configured on the server")),
  });

  const { mutate: disconnect } = useMutation({
    mutationFn: crmApi2.disconnectHubspot,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["crm-status"] });
      toast.success("HubSpot disconnected");
    },
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-orange-500/10">
            <Link2 className="w-5 h-5 text-orange-400" />
          </div>
          <div className="flex-1">
            <CardTitle className="text-sm">CRM Sync — HubSpot</CardTitle>
            <CardDescription>
              Bidirectional: verdicts push out as contacts; lifecycle and deal changes flow
              back into conversion status — which is what trains the scoring models
            </CardDescription>
          </div>
          {hubspot?.connected ? (
            <Badge variant="success">Portal {hubspot.portal_id}</Badge>
          ) : hubspot?.legacy_api_key ? (
            <Badge variant="warning">API key (outbound only)</Badge>
          ) : (
            <Badge variant="secondary">Not connected</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          {hubspot?.connected ? (
            <>
              <p className="text-xs text-muted-foreground flex-1">
                Last push {hubspot.last_outbound_at ? formatDate(hubspot.last_outbound_at) : "never"} ·
                last inbound event {hubspot.last_inbound_at ? formatDate(hubspot.last_inbound_at) : "never"}
              </p>
              <Button variant="ghost" size="sm" onClick={() => { if (confirm("Disconnect HubSpot?")) disconnect(); }}
                      className="text-red-400 hover:text-red-400 hover:bg-red-500/10 gap-1.5">
                <WifiOff className="w-3.5 h-3.5" />
                Disconnect HubSpot
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" disabled={connecting} onClick={() => connect()} className="gap-1.5">
              <Link2 className="w-3.5 h-3.5" />
              Connect HubSpot
            </Button>
          )}
        </div>

        {(logData?.entries.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <Label>Recent sync activity</Label>
            {logData!.entries.map((entry, i) => (
              <div key={i} className="flex items-center gap-2 text-xs py-1 border-b border-border/40 last:border-0">
                {entry.direction === "outbound"
                  ? <ArrowUpRight className="w-3 h-3 text-violet-400 shrink-0" aria-label="Outbound" />
                  : <ArrowDownLeft className="w-3 h-3 text-emerald-400 shrink-0" aria-label="Inbound" />}
                <span className="font-mono">{entry.event_type}</span>
                {!entry.success && <Badge variant="destructive" className="text-[10px]">failed</Badge>}
                <span className="text-muted-foreground truncate flex-1">
                  {entry.error_message ?? (entry.payload ? JSON.stringify(entry.payload) : "")}
                </span>
                <span className="text-muted-foreground shrink-0">{formatDate(entry.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const VERIFICATION_META: Record<EmailVerification["status"], { variant: "success" | "warning" | "destructive" | "secondary"; label: string }> = {
  valid: { variant: "success", label: "Deliverable" },
  risky: { variant: "warning", label: "Risky" },
  undeliverable: { variant: "destructive", label: "Undeliverable" },
  unknown: { variant: "secondary", label: "Unknown" },
};

const CHECK_LABELS: Record<string, string> = {
  syntax: "Address syntax",
  disposable: "Not a disposable domain",
  role_account: "Personal (not a role account)",
  mx: "Domain accepts mail (MX)",
  smtp_probe: "Mailbox exists (SMTP probe)",
  bounce: "No hard bounce on record",
};

function CheckIcon({ ok }: { ok: boolean | null }) {
  if (ok === true) return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" aria-label="Passed" />;
  if (ok === false) return <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" aria-label="Failed" />;
  return <HelpCircle className="w-3.5 h-3.5 text-muted-foreground shrink-0" aria-label="Inconclusive" />;
}

function VerificationSection() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<EmailVerification | null>(null);

  const { mutate: check, isPending } = useMutation({
    mutationFn: () => verificationApi.verify({ email: email.trim() }),
    onSuccess: setResult,
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Verification failed")),
  });

  const meta = result ? VERIFICATION_META[result.status] : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-teal-500/10">
            <MailCheck className="w-5 h-5 text-teal-400" />
          </div>
          <div>
            <CardTitle className="text-sm">Email Verification</CardTitle>
            <CardDescription>
              The same pre-send gate the agent runs before any outreach — syntax, disposable domains, role accounts, and MX records
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="flex gap-2"
          onSubmit={(e) => { e.preventDefault(); if (email.includes("@")) check(); }}
        >
          <Input
            type="email"
            placeholder="jane@acme.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-label="Email address to verify"
            className="flex-1"
          />
          <Button type="submit" variant="outline" size="sm" loading={isPending} disabled={!email.includes("@")} className="gap-1.5 shrink-0">
            <MailCheck className="w-3.5 h-3.5" />
            Verify
          </Button>
        </form>

        {result && meta && (
          <div className="rounded-lg border border-border p-3 space-y-3 animate-fade-in">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs">{result.email}</span>
              <Badge variant={meta.variant} className="text-[10px]">{meta.label}</Badge>
              <span className="text-xs text-muted-foreground truncate">{result.reason}</span>
            </div>
            <ul className="space-y-1.5">
              {Object.entries(result.checks).map(([name, check_]) => (
                <li key={name} className="flex items-center gap-2 text-xs">
                  <CheckIcon ok={check_.ok} />
                  <span>{CHECK_LABELS[name] ?? name.replace(/_/g, " ")}</span>
                  {check_.detail && <span className="text-muted-foreground truncate">· {check_.detail}</span>}
                </li>
              ))}
            </ul>
            {result.status === "undeliverable" && (
              <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
                <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5 text-yellow-400" />
                The agent skips undeliverable addresses automatically — bounces are what burn a sending domain.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ComplianceSection() {
  const qc = useQueryClient();
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");

  const { data: guardrails } = useQuery({
    queryKey: ["guardrails"],
    queryFn: complianceApi.guardrails,
    refetchInterval: 60_000,
  });

  const { data: suppressions } = useQuery({
    queryKey: ["suppressions"],
    queryFn: () => complianceApi.listSuppressions(),
  });

  const { mutate: add, isPending: adding } = useMutation({
    mutationFn: () => complianceApi.addSuppression(value.trim(), reason.trim() || undefined),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["suppressions"] });
      qc.invalidateQueries({ queryKey: ["guardrails"] });
      setValue(""); setReason("");
      toast.success(
        res.cancelled_emails > 0
          ? `${res.value} suppressed — ${res.cancelled_emails} pending email(s) cancelled`
          : `${res.value} added to do-not-contact list`
      );
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, "Failed to add suppression")),
  });

  const { mutate: remove } = useMutation({
    mutationFn: complianceApi.removeSuppression,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["suppressions"] });
      qc.invalidateQueries({ queryKey: ["guardrails"] });
      toast.success("Suppression removed");
    },
  });

  const capPct = guardrails
    ? Math.min(100, Math.round((guardrails.sent_last_24h / Math.max(1, guardrails.daily_limit)) * 100))
    : 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/10">
            <ShieldBan className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <CardTitle className="text-sm">Compliance &amp; Send Safety</CardTitle>
            <CardDescription>Do-not-contact list, unsubscribe handling, and send guardrails</CardDescription>
          </div>
          {guardrails && (
            <Badge variant={guardrails.can_send ? "success" : "warning"} className="ml-auto">
              {guardrails.can_send ? "Sending allowed" : "Sends held"}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {guardrails && (
          <div className="p-3 rounded-lg border border-border space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <Gauge className="w-4 h-4 text-muted-foreground" />
              <span className="font-medium">Daily send cap</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {guardrails.sent_last_24h} / {guardrails.daily_limit} in last 24h
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
              <div
                className={`h-full rounded-full ${capPct >= 90 ? "bg-red-500" : capPct >= 70 ? "bg-yellow-500" : "bg-emerald-500"}`}
                style={{ width: `${capPct}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {guardrails.reason} · Window {String(guardrails.window_start_hour_utc).padStart(2, "0")}:00–{String(guardrails.window_end_hour_utc).padStart(2, "0")}:00 UTC
              {guardrails.weekdays_only ? " · weekdays only" : ""}
            </p>
          </div>
        )}

        <div className="space-y-2">
          <Label>Add to do-not-contact list</Label>
          <div className="flex gap-2">
            <Input
              placeholder="jane@acme.com or acme.com"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="flex-1"
            />
            <Input
              placeholder="Reason (optional)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="flex-1"
            />
            <Button
              variant="outline"
              size="sm"
              disabled={!value.includes(".") || adding}
              onClick={() => add()}
              className="gap-1.5 shrink-0"
            >
              <Plus className="w-3.5 h-3.5" />
              Suppress
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            A bare domain (e.g. <code className="bg-secondary px-1 rounded">acme.com</code>) blocks every address at that company. Pending sequence emails are cancelled immediately.
          </p>
        </div>

        {suppressions && suppressions.entries.length > 0 && (
          <div className="space-y-2">
            <Label>Suppressed ({suppressions.total})</Label>
            <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
              {suppressions.entries.map((entry) => (
                <div key={entry.id} className="flex items-center gap-3 p-2.5 rounded-lg border border-border text-sm">
                  <span className="font-mono text-xs">{entry.value}</span>
                  <Badge variant="secondary" className="text-[10px]">{entry.kind}</Badge>
                  <span className="text-xs text-muted-foreground truncate flex-1">
                    {entry.source.replace(/_/g, " ")}{entry.reason ? ` — ${entry.reason}` : ""}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-red-400 hover:bg-red-500/10 hover:text-red-400 shrink-0 h-7 w-7"
                    onClick={() => { if (confirm(`Allow contacting ${entry.value} again?`)) remove(entry.id); }}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
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
                <Badge variant={(user?.role ?? "rep") as "admin" | "manager" | "rep"}>{user?.role}</Badge>
                <span className="text-xs text-muted-foreground">Member since {user ? formatDate(user.created_at) : "—"}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <MailboxSection />
        <CrmSection />
        <VerificationSection />
        <ComplianceSection />
        <SlackSection />
        <APIKeysSection />
        <PasswordSection />
      </div>
    </div>
  );
}
