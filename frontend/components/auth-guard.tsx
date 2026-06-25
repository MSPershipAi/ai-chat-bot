"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthUser, fetchCurrentUser } from "@/lib/auth";

interface AuthGuardProps {
  children: (user: AuthUser) => React.ReactNode;
  requireAdmin?: boolean;
}

export function AuthGuard({ children, requireAdmin = false }: AuthGuardProps) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCurrentUser()
      .then((currentUser) => {
        if (!currentUser) {
          router.replace("/login");
          return;
        }
        if (requireAdmin && currentUser.role !== "admin") {
          router.replace("/");
          return;
        }
        setUser(currentUser);
      })
      .finally(() => setLoading(false));
  }, [router, requireAdmin]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50 dark:bg-zinc-950 text-gray-500">
        Loading...
      </div>
    );
  }

  if (!user) return null;

  return <>{children(user)}</>;
}
