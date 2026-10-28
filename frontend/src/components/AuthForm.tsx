"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useApp } from "@/lib/app-context";

import { Disclaimer } from "./Disclaimer";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { t, onAuth, locale } = useApp();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res =
        mode === "login" ? await api.login(email, password) : await api.register(email, password, name || null, locale);
      onAuth(res);
      router.push(mode === "register" ? "/trade" : "/portfolio");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const input =
    "mt-1 w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";
  return (
    <div className="mx-auto max-w-sm space-y-4 pt-4">
      <h1 className="text-2xl font-bold">{mode === "login" ? t("login_title") : t("register_title")}</h1>
      {mode === "register" && <p className="text-sm text-neutral-600 dark:text-neutral-400">{t("starting_balance")}</p>}
      <form
        onSubmit={submit}
        className="space-y-3 rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900"
      >
        <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-400">
          {t("email")}
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={input}
          />
        </label>
        {mode === "register" && (
          <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-400">
            {t("display_name")}
            <input
              type="text"
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={input}
            />
          </label>
        )}
        <label className="block text-xs font-medium text-neutral-600 dark:text-neutral-400">
          {t("password")}
          <input
            type="password"
            required
            minLength={mode === "register" ? 8 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={input}
          />
          {mode === "register" && <span className="mt-1 block text-[11px] text-neutral-500">{t("password_hint")}</span>}
        </label>
        {error && (
          <p role="alert" className="text-sm text-rose-600">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-sky-600 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
        >
          {busy ? t("loading") : t("submit")}
        </button>
      </form>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        {mode === "login" ? t("no_account") : t("have_account")}{" "}
        <Link href={mode === "login" ? "/register" : "/login"} className="font-semibold text-sky-600 hover:underline">
          {mode === "login" ? t("nav_register") : t("nav_login")}
        </Link>
      </p>
      <Disclaimer compact />
    </div>
  );
}
