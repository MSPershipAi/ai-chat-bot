"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchCurrentUser, login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    fetchCurrentUser().then((user) => {
      if (user) router.replace("/");
      else setCheckingSession(false);
    });
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setLoading(false);
    }
  };

  if (checkingSession) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50 dark:bg-zinc-950 text-gray-500">
        Loading...
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-zinc-950 font-sans text-gray-900 dark:text-gray-100 px-4 py-8">
      <form
        onSubmit={handleSubmit}
        className="p-6 sm:p-8 bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl shadow-lg max-w-sm w-full"
      >
        <div className="flex justify-center mb-4">
          <div className="w-10 h-10 rounded-full bg-pership-red flex items-center justify-center text-white font-black text-lg shadow">
            P
          </div>
        </div>
        <h2 className="text-2xl font-black mb-2 text-center text-pership-blue dark:text-zinc-200">
          Sign In
        </h2>
        <p className="text-xs text-gray-500 text-center mb-6">
          Use the email and password provided by your admin.
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-gray-500 uppercase mb-2">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full p-2.5 border border-gray-300 dark:border-zinc-700 rounded bg-gray-50 dark:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-pership-red"
              placeholder="you@company.com"
            />
          </div>
          <div>
            <label className="block text-xs font-bold text-gray-500 uppercase mb-2">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full p-2.5 border border-gray-300 dark:border-zinc-700 rounded bg-gray-50 dark:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-pership-red"
              placeholder="Enter password"
            />
          </div>
          {error && <p className="text-red-500 text-xs font-bold">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-pership-red text-white font-bold rounded uppercase tracking-wider hover:bg-opacity-90 transition disabled:opacity-50"
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </div>
      </form>
    </div>
  );
}
