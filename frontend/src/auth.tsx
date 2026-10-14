import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, setApiToken, User } from "@/src/api";
import { queryClient } from "@/src/query-client";
import { storage } from "@/src/utils/storage";

const TOKEN_KEY = "mba_auth_token";

type AuthCtx = {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (u: User) => void;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const t = await storage.secureGet<string | null>(TOKEN_KEY, null);
      if (t) {
        setApiToken(t);
        try {
          setUser(await api<User>("/auth/me"));
        } catch {
          setApiToken(null);
          await storage.secureRemove(TOKEN_KEY);
        }
      }
      setLoading(false);
    })();
  }, []);

  const handle = async (res: { access_token: string; user: User }) => {
    setApiToken(res.access_token);
    await storage.secureSet(TOKEN_KEY, res.access_token);
    queryClient.clear();
    setUser(res.user);
  };

  const signIn = useCallback(async (email: string, password: string) => {
    await handle(await api("/auth/login", { body: { email: email.trim(), password } }));
  }, []);

  const signUp = useCallback(async (name: string, email: string, password: string) => {
    await handle(await api("/auth/register", { body: { name, email: email.trim(), password } }));
  }, []);

  const signOut = useCallback(async () => {
    setApiToken(null);
    await storage.secureRemove(TOKEN_KEY);
    queryClient.clear();
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    setUser(await api<User>("/auth/me"));
  }, []);

  return <Ctx.Provider value={{ user, loading, signIn, signUp, signOut, refresh, setUser }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
