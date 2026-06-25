"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGuard } from "@/components/auth-guard";
import { ThemeToggle } from "@/components/theme-toggle";
import { AuthUser, authHeaders } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

interface ManagedUser {
  email: string;
  role: "user" | "admin";
  name: string;
}

export default function UsersPage() {
  return (
    <AuthGuard requireAdmin>
      {(user) => <UsersContent currentUser={user} />}
    </AuthGuard>
  );
}

function UsersContent({ currentUser }: { currentUser: AuthUser }) {
  const router = useRouter();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [status, setStatus] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchUsers = async () => {
    const res = await fetch(`${API_BASE}/users`, { headers: authHeaders() });
    if (res.ok) {
      setUsers(await res.json());
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStatus(null);

    try {
      const res = await fetch(`${API_BASE}/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ email, password, name, role }),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Could not create user.");
      }

      setStatus({ type: "success", text: `Created account for ${data.email}` });
      setEmail("");
      setName("");
      setPassword("");
      setRole("user");
      fetchUsers();
    } catch (err) {
      setStatus({
        type: "error",
        text: err instanceof Error ? err.message : "Could not create user.",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (targetEmail: string) => {
    if (!confirm(`Delete user ${targetEmail}?`)) return;

    const res = await fetch(`${API_BASE}/users/${encodeURIComponent(targetEmail)}`, {
      method: "DELETE",
      headers: authHeaders(),
    });

    if (res.ok) {
      fetchUsers();
      setStatus({ type: "success", text: `Deleted ${targetEmail}` });
    } else {
      const data = await res.json();
      setStatus({ type: "error", text: data.detail || "Could not delete user." });
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-zinc-950 font-sans text-gray-900 dark:text-gray-100 p-6 md:p-12 overflow-hidden">
      <div className="max-w-4xl mx-auto w-full flex-1 flex flex-col bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-2xl shadow-xl overflow-hidden">
        <header className="p-6 border-b border-gray-200 dark:border-zinc-800 flex items-center justify-between bg-zinc-50 dark:bg-zinc-900/50">
          <div>
            <h1 className="text-xl font-extrabold uppercase tracking-wider text-pership-blue dark:text-zinc-200">
              User Management
            </h1>
            <p className="text-xs text-gray-500 mt-1">Signed in as {currentUser.email}</p>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button
              onClick={() => router.push("/dashboard")}
              className="px-4 py-2 text-xs font-bold text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 dark:hover:bg-zinc-700 border border-gray-200 dark:border-zinc-700 rounded-lg transition-colors uppercase shadow-sm"
            >
              Dashboard
            </button>
            <button
              onClick={() => router.push("/")}
              className="px-4 py-2 text-xs font-bold text-gray-600 dark:text-zinc-300 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 dark:hover:bg-zinc-700 border border-gray-200 dark:border-zinc-700 rounded-lg transition-colors uppercase shadow-sm"
            >
              Chat
            </button>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden flex-col md:flex-row">
          <div className="w-full md:w-1/2 p-6 border-b md:border-b-0 md:border-r border-gray-200 dark:border-zinc-800 overflow-y-auto">
            <form onSubmit={handleCreate} className="space-y-4">
              <h2 className="text-sm font-bold text-gray-500 uppercase">Create User</h2>

              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Display name"
                className="w-full p-3 border border-gray-300 dark:border-zinc-700 rounded-xl bg-gray-50 dark:bg-zinc-800 text-sm"
              />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                required
                className="w-full p-3 border border-gray-300 dark:border-zinc-700 rounded-xl bg-gray-50 dark:bg-zinc-800 text-sm"
              />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Temporary password"
                required
                minLength={6}
                className="w-full p-3 border border-gray-300 dark:border-zinc-700 rounded-xl bg-gray-50 dark:bg-zinc-800 text-sm"
              />
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as "user" | "admin")}
                className="w-full p-3 border border-gray-300 dark:border-zinc-700 rounded-xl bg-gray-50 dark:bg-zinc-800 text-sm"
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 bg-pership-red text-white text-sm font-bold rounded-xl uppercase tracking-wider disabled:opacity-50"
              >
                {loading ? "Creating..." : "Create User"}
              </button>
            </form>

            {status && (
              <div
                className={`mt-4 p-4 rounded-xl text-sm font-semibold border ${
                  status.type === "success"
                    ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/20 dark:text-green-400"
                    : "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/20 dark:text-red-400"
                }`}
              >
                {status.text}
              </div>
            )}
          </div>

          <div className="w-full md:w-1/2 p-6 overflow-y-auto bg-zinc-50 dark:bg-zinc-900/30">
            <h2 className="text-sm font-bold text-gray-500 uppercase mb-4">
              Existing Users ({users.length})
            </h2>
            <div className="space-y-3">
              {users.map((user) => (
                <div
                  key={user.email}
                  className="p-4 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl flex items-center justify-between gap-3"
                >
                  <div>
                    <p className="text-sm font-bold">{user.name}</p>
                    <p className="text-xs text-gray-500">{user.email}</p>
                    <p className="text-[10px] uppercase font-extrabold text-pership-blue mt-1">{user.role}</p>
                  </div>
                  {user.email !== currentUser.email && (
                    <button
                      onClick={() => handleDelete(user.email)}
                      className="text-xs font-bold text-red-500 hover:text-red-600 uppercase"
                    >
                      Delete
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
