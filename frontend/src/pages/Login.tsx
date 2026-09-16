import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { Zap, Mail, Lock, ArrowRight, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { authApi, healthApi } from "../lib/api";
import { useAuthStore } from "../store/authStore";
import { apiErrorMessage } from "../lib/utils";

export default function Login() {
  const navigate = useNavigate();
  const { setAuth } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  // Free hosting tiers idle the API out; the first sign-in of the day pays a
  // cold start of up to a minute. Without a word from the UI that reads as a
  // dead button, so say what is happening once it is clearly slow.
  const [waking, setWaking] = useState(false);

  // Pre-warm the API. The static site is always up, so the moment someone
  // lands on the login page we can start the backend's cold start in the
  // background — by the time they've typed credentials it is usually awake.
  // Fire-and-forget: a failure here means nothing on its own.
  useEffect(() => {
    const ac = new AbortController();
    healthApi.check(ac.signal).catch(() => {});
    return () => ac.abort();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    const wakeHint = setTimeout(() => setWaking(true), 4000);
    try {
      const data = await authApi.login(email, password);
      setAuth(data.user, data.access_token, data.refresh_token);
      toast.success(`Welcome back, ${data.user.email}`);
      navigate("/");
    } catch (err) {
      // A cold start that never completes is a network error, not a bad
      // password — don't accuse the user of the wrong thing.
      const offline =
        axios.isAxiosError(err) && !err.response;
      toast.error(
        offline
          ? "Couldn't reach the server. On free hosting it may still be waking up — try again in a moment."
          : apiErrorMessage(err, "Invalid credentials")
      );
    } finally {
      clearTimeout(wakeHint);
      setWaking(false);
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background relative overflow-hidden">
      {/* Background glow effects */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-violet-600/10 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] rounded-full bg-indigo-600/8 blur-[100px] pointer-events-none" />

      <div className="relative w-full max-w-sm mx-4 animate-fade-in">
        {/* Card */}
        <div className="rounded-2xl border border-border bg-card/80 backdrop-blur-xl p-8 shadow-2xl">
          {/* Logo */}
          <div className="flex flex-col items-center mb-8">
            <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-600 to-indigo-600 shadow-lg shadow-violet-500/30 mb-4">
              <Zap className="w-7 h-7 text-white" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight gradient-text">AutonomousSDR</h1>
            <p className="text-sm text-muted-foreground mt-1">AI-powered lead intelligence</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="pl-9"
                  required
                  autoFocus
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pl-9 pr-9"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <Button type="submit" variant="gradient" size="lg" className="w-full gap-2" loading={loading}>
              Sign in
              <ArrowRight className="w-4 h-4" />
            </Button>

            {waking && (
              <p className="text-center text-xs text-muted-foreground animate-pulse">
                Waking the server — free hosting sleeps when idle, this can take up to a minute.
              </p>
            )}
          </form>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Don't have an account?{" "}
            <a href="#" className="text-primary hover:underline" onClick={(e) => { e.preventDefault(); toast.info("Contact your administrator to create an account."); }}>
              Contact admin
            </a>
          </p>
        </div>

        {/* Tagline */}
        <p className="text-center text-xs text-muted-foreground/50 mt-6">
          Powered by multi-agent AI · Mistral · FastAPI
        </p>
      </div>
    </div>
  );
}
