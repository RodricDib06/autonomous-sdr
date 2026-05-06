import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus, UserX, Edit2, Check, X } from "lucide-react";
import { toast } from "sonner";
import { authApi } from "../lib/api";
import type { User } from "../types";
import { Header } from "../components/layout/Header";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "../components/ui/dialog";
import { formatDate } from "../lib/utils";
import { useAuthStore } from "../store/authStore";

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("rep");
  const [loading, setLoading] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await authApi.register(email, password, role);
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(`User ${email} created`);
      onOpenChange(false);
      setEmail(""); setPassword(""); setRole("rep");
    } catch (err: any) {
      toast.error(err.response?.data?.detail ?? "Failed to create user");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create New User</DialogTitle>
          <DialogDescription>Add a team member to AutonomousSDR</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleCreate} className="space-y-4 mt-2">
          <div className="space-y-2">
            <Label htmlFor="new-email">Email</Label>
            <Input id="new-email" type="email" placeholder="user@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">Password</Label>
            <Input id="new-password" type="password" placeholder="Min 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          </div>
          <div className="space-y-2">
            <Label>Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="rep">Rep — view & submit leads</SelectItem>
                <SelectItem value="manager">Manager — + import & export</SelectItem>
                <SelectItem value="admin">Admin — full access</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" variant="gradient" loading={loading}>Create User</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RoleInlineEdit({ user, onSave, onCancel }: { user: User; onSave: (role: string) => void; onCancel: () => void }) {
  const [role, setRole] = useState(user.role);
  return (
    <div className="flex items-center gap-2">
      <Select value={role} onValueChange={(v) => setRole(v as "admin" | "manager" | "rep")}>
        <SelectTrigger className="h-7 w-32 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="rep">rep</SelectItem>
          <SelectItem value="manager">manager</SelectItem>
          <SelectItem value="admin">admin</SelectItem>
        </SelectContent>
      </Select>
      <button onClick={() => onSave(role)} className="p-1 rounded hover:bg-emerald-500/10 text-emerald-400"><Check className="w-3.5 h-3.5" /></button>
      <button onClick={onCancel} className="p-1 rounded hover:bg-red-500/10 text-red-400"><X className="w-3.5 h-3.5" /></button>
    </div>
  );
}

export default function Users() {
  const qc = useQueryClient();
  const { user: me } = useAuthStore();
  const [createOpen, setCreateOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const { data: users = [], isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: authApi.listUsers,
  });

  const { mutate: changeRole } = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => authApi.changeRole(id, role),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(`Role updated to ${updated.role}`);
      setEditingId(null);
    },
    onError: () => toast.error("Failed to update role"),
  });

  const { mutate: deactivate } = useMutation({
    mutationFn: authApi.deactivateUser,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast.success("User deactivated"); },
    onError: (e: any) => toast.error(e.response?.data?.detail ?? "Failed"),
  });

  return (
    <div className="flex flex-col min-h-screen">
      <Header
        title="Users"
        subtitle={`${users.length} team member${users.length !== 1 ? "s" : ""}`}
        actions={
          <Button variant="gradient" size="sm" onClick={() => setCreateOpen(true)} className="gap-2">
            <UserPlus className="w-3.5 h-3.5" />
            Add User
          </Button>
        }
      />

      <div className="flex-1 p-8 animate-fade-in">
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/30">
                  {["User", "Role", "Status", "Last Login", "Joined", "Actions"].map((h) => (
                    <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  [...Array(4)].map((_, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td colSpan={6} className="p-4"><div className="skeleton h-10 rounded" /></td>
                    </tr>
                  ))
                ) : users.map((user) => (
                  <tr key={user.id} className="border-b border-border/50 hover:bg-secondary/20 transition-colors">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-indigo-600 flex items-center justify-center text-white text-xs font-semibold">
                          {user.email.slice(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <p className="font-medium">{user.email}</p>
                          {user.id === me?.id && <span className="text-xs text-muted-foreground">(you)</span>}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      {editingId === user.id ? (
                        <RoleInlineEdit
                          user={user}
                          onSave={(role) => changeRole({ id: user.id, role })}
                          onCancel={() => setEditingId(null)}
                        />
                      ) : (
                        <div className="flex items-center gap-2">
                          <Badge variant={user.role as "admin" | "manager" | "rep"}>{user.role}</Badge>
                          {me?.id !== user.id && (
                            <button onClick={() => setEditingId(user.id)} className="p-1 rounded hover:bg-secondary text-muted-foreground">
                              <Edit2 className="w-3 h-3" />
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <Badge variant={user.is_active ? "success" : "destructive"}>
                        {user.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 text-muted-foreground text-xs">{formatDate(user.last_login_at)}</td>
                    <td className="px-6 py-4 text-muted-foreground text-xs">{formatDate(user.created_at)}</td>
                    <td className="px-6 py-4">
                      {user.id !== me?.id && user.is_active && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-red-400 hover:bg-red-500/10 hover:text-red-400 gap-1.5"
                          onClick={() => { if (confirm(`Deactivate ${user.email}?`)) deactivate(user.id); }}
                        >
                          <UserX className="w-3.5 h-3.5" />
                          Deactivate
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Role reference */}
        <div className="mt-6 grid grid-cols-3 gap-4">
          {[
            { role: "rep", label: "Sales Rep", desc: "Submit and view leads", icon: "👤" },
            { role: "manager", label: "Manager", desc: "Import, export, and analytics", icon: "📊" },
            { role: "admin", label: "Admin", desc: "Full access, user management", icon: "🛡️" },
          ].map(({ role, label, desc, icon }) => (
            <Card key={role} className="p-4">
              <div className="flex items-start gap-3">
                <span className="text-2xl">{icon}</span>
                <div>
                  <div className="flex items-center gap-2 mb-0.5">
                    <p className="font-medium text-sm">{label}</p>
                    <Badge variant={role as any} className="text-[10px]">{role}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{desc}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </div>

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
