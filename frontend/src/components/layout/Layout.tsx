import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Toaster } from "sonner";

export function Layout() {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="flex-1 ml-60 flex flex-col min-h-screen">
        <Outlet />
      </main>
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: "hsl(222 47% 9%)",
            border: "1px solid hsl(217 33% 16%)",
            color: "hsl(210 40% 98%)",
          },
        }}
      />
    </div>
  );
}
