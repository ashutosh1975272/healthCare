"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  ErrorState,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/auth-client";
import { useSearchParams, useRouter } from "next/navigation";

type ProviderModel = {
  provider: "nvidia" | "openai" | "gemini" | "groq" | "ollama" | "mock";
  model: string;
  name: string;
};

type ApiKeyFormState = {
  isSubmitting: boolean;
  error: string | null;
};

export default function ProfileApiKeysPage() {
  const [keys, setKeys] = useState<{
    id: string;
    provider: string;
    is_active: boolean;
  }[] | null>(null);
  const [provider, setProvider] = useState<"nvidia" | "openai" | "gemini" | "groq" | "ollama" | "mock">(
    "nvidia"
  );
  const [model, setModel] = useState<string>("nvidia/nemotron-3.5-lightning-30b-a3b");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Available models per provider
  const availableModels: Record<string, { model: string; name: string }> = {
    nvidia: {
      model: "nvidia/nemotron-3.5-lightning-30b-a3b",
      name: "Nemotron 3.5 Lightning",
    },
    openai: {
      model: "gpt-4o-mini",
      name: "GPT-4o Mini",
    },
    gemini: {
      model: "gemini-1.5-flash",
      name: "Gemini 1.5 Flash",
    },
    groq: {
      model: "openai/gpt-oss-120b",
      name: "GPT-OSS 120B (Groq)",
    },
    ollama: {
      model: "llama3",
      name: "Llama 3 (local)",
    },
    mock: {
      model: "mock-model",
      name: "Mock (demo mode)",
    },
  };

  const [telegramToken, setTelegramToken] = useState("");
  const [telegramUsername, setTelegramUsername] = useState("");
  const [telegramStatus, setTelegramStatus] = useState<string | null>(null);
  const [telegramLoading, setTelegramLoading] = useState(false);
  const [telegramBotUsername, setTelegramBotUsername] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const [me, acc] = await Promise.all([
        apiClient<any>("/api/v1/auth/me"),
        apiClient<{ id: string; provider: string; is_active: boolean }[]>("/api/v1/profile/api-keys"),
      ]);

      if (me.error) {
        setError(me.error.detail || "Failed to load profile. Please sign in again.");
        setKeys(null);
        return;
      }

      setKeys(acc.data || []);
      const telegramKey = (acc.data || []).find((k: { provider: string }) => k.provider === "telegram");
      setTelegramStatus(telegramKey?.is_active ? "connected" : null);
      setTelegramBotUsername(telegramKey?.provider === "telegram" ? telegramKey.provider : null);
    } catch (e) {
      setError("Failed to load API keys. Please try again.");
      setKeys(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAddKey = useCallback(
    async (providerName: string, apiKey: string) => {
      setError(null);
      setLoading(true);
      try {
        await apiClient("/api/v1/profile/api-keys", {
          method: "POST",
          body: JSON.stringify({
            provider: providerName,
            api_key: apiKey,
          }),
        });
        setSuccess(`API key for ${providerName} added successfully!`);
        void load();
      } catch (e: any) {
        setError(e.response?.detail || "Failed to add API key. Please try again.");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const handleRemoveKey = useCallback(
    async (providerName: string) => {
      setError(null);
      setLoading(true);
      try {
        await apiClient("/api/v1/profile/api-keys/" + providerName, {
          method: "DELETE",
        });
        setSuccess(`API key for ${providerName} removed successfully!`);
        void load();
      } catch (e: any) {
        setError(e.response?.detail || "Failed to remove API key. Please try again.");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const handleConnectTelegram = useCallback(async () => {
    setError(null);
    setTelegramLoading(true);
    try {
      const res = await apiClient<{ connected: boolean; bot_username?: string; webhook_registered?: boolean }>(
        "/api/v1/integrations/telegram/connect",
        {
          method: "POST",
          body: JSON.stringify({
            bot_token: telegramToken.trim(),
            telegram_username: telegramUsername.trim() || undefined,
          }),
        }
      );
      if (res.error) {
        setError(res.error.detail || "Failed to connect Telegram.");
        setTelegramStatus(null);
        return;
      }
      setSuccess(`Telegram connected as @${res.data?.bot_username ?? "unknown"}`);
      setTelegramStatus("connected");
      setTelegramBotUsername(res.data?.bot_username ?? null);
      setTelegramToken("");
      setTelegramUsername("");
      void load();
    } catch (e: any) {
      setError(e.response?.detail || "Failed to connect Telegram. Please try again.");
      setTelegramStatus(null);
    } finally {
      setTelegramLoading(false);
    }
  }, [telegramToken, telegramUsername, load]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h2 className="font-display text-3xl font-semibold tracking-tight text-ink">
          API Keys
        </h2>
        <p className="text-sm text-muted">Loading...</p>
        <Skeleton className="h-6 w-64" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h2 className="font-display text-3xl font-semibold tracking-tight text-ink">
          API Keys
        </h2>
        <ErrorState description={error} onRetry={() => void load()} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <h1 className="font-display text-3xl font-semibold tracking-tight text-ink">
          API Keys
        </h1>
        <p className="text-sm text-muted">
          Manage your LLM provider API keys to enable AI features
        </p>
      </div>

      {error ? (
        <ErrorState description={error} onRetry={() => void load()} />
      ) : null}

      {success && (
        <div className="rounded-[1.75rem] bg-success/5 px-4 py-2 text-sm text-success">
          {success}
        </div>
      )}

      {/* Add New Provider Form */}
      <Card>
        <CardHeader>
          <p className="text-sm font-semibold text-ink">Add LLM Provider API Key</p>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs font-semibold text-muted">Provider</p>
            <Input
              type="hidden"
              value={provider}
              onChange={(e) => setProvider(e.target.value as any)}
            />
            <div className="mt-2 space-y-1">
              {Object.keys(availableModels).map((prov) => (
                <label
                  key={prov}
                  className={`flex items-center gap-2 rounded border ${
                    prov === provider
                      ? "border-primary bg-primary/10"
                      : "border-muted/20 hover:bg-primary/5"
                  }`}
                >
                  <input
                    type="radio"
                    name="provider"
                    value={prov}
                    checked={prov === provider}
                    onChange={(e) =>
                      setProvider(e.target.value as "nvidia" | "openai" | "gemini" | "groq" | "ollama" | "mock")
                    }
                  />
                  <span className="text-sm font-medium text-ink">
                    {prov === "nvidia"
                      ? "NVIDIA NIM"
                      : prov === "openai"
                      ? "OpenAI"
                      : prov === "gemini"
                      ? "Google Gemini"
                      : prov === "groq"
                      ? "Groq"
                      : prov === "ollama"
                      ? "Ollama (local)"
                      : "Mock"}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold text-muted">API Key</p>
            <Input
              type="password"
              placeholder="Enter your API key"
              required
              className="w-full"
              disabled={loading}
            />
          </div>

          <div className="flex gap-2 mt-4">
            <Button
              disabled={loading}
              type="submit"
              onClick={() => {}}
            >
              Add Key
            </Button>
            <Button
              type="button"
              onClick={() => {}}
              variant="outline"
              disabled={loading}
            >
              Cancel
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Existing Keys List */}
      {keys && keys.length > 0 && (
        <Card>
          <CardHeader>
            <p className="text-sm font-semibold text-ink">Your Active Provider Keys</p>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {keys.map((key) => (
                <div
                  key={key.id}
                  className="rounded-2xl bg-mist/60 px-4 py-2 flex items-center justify-between text-sm"
                >
                  <span className="font-medium text-ink capitalize">
                    {key.provider === "nvidia"
                      ? "NVIDIA NIM"
                      : key.provider === "openai"
                      ? "OpenAI"
                      : key.provider === "gemini"
                      ? "Google Gemini"
                      : key.provider === "groq"
                      ? "Groq"
                      : key.provider === "ollama"
                      ? "Ollama (local)"
                      : key.provider === "telegram"
                      ? "Telegram"
                      : "Mock"}
                  </span>
                  <span className="text-muted">
                    {key.is_active ? "Active" : "Inactive"}
                  </span>
                  {key.is_active && key.provider !== "telegram" && (
                    <Button
                      size="icon"
                        variant="ghost"
                        onClick={() => {}}
                        aria-label="Configure"
                    >
                      ⚙️
                    </Button>
                  )}
                  {!key.is_active && key.provider !== "telegram" && (
                    <Button
                      size="icon"
                        variant="ghost"
                        onClick={() => {}}
                        aria-label="Reactivate"
                      >
                        ⏳
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Telegram Connection */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-ink">Telegram Bot</p>
              <p className="text-xs text-muted mt-1">
                {telegramStatus === "connected"
                  ? `Connected as @${telegramBotUsername ?? "bot"}`
                  : "Connect your Telegram bot to chat with Aarogya via Xomni"}
              </p>
            </div>
            {telegramStatus === "connected" ? (
              <span className="inline-flex items-center rounded-full border border-success/40 bg-success/10 px-2.5 py-0.5 text-xs font-medium text-success">Connected</span>
            ) : (
              <span className="inline-flex items-center rounded-full border border-muted/40 bg-mist/60 px-2.5 py-0.5 text-xs font-medium text-muted">Not connected</span>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <p className="text-xs text-muted">
              Paste the bot token from @BotFather. Your messages will be routed through Xomni AI.
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold text-muted">Bot Token</p>
            <Input
              type="password"
              placeholder="123456:ABC-DEF..."
              value={telegramToken}
              onChange={(e) => setTelegramToken(e.target.value)}
              disabled={telegramLoading || telegramStatus === "connected"}
              className="w-full"
            />
          </div>
          <div>
            <p className="text-xs font-semibold text-muted">Allowed Username <span className="text-muted">(optional)</span></p>
            <Input
              type="text"
              placeholder="@yourusername"
              value={telegramUsername}
              onChange={(e) => setTelegramUsername(e.target.value)}
              disabled={telegramLoading || telegramStatus === "connected"}
              className="w-full"
            />
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <Button
              disabled={telegramLoading || !telegramToken.trim() || telegramStatus === "connected"}
              onClick={handleConnectTelegram}
            >
              {telegramStatus === "connected" ? "Connected" : telegramLoading ? "Connecting..." : "Connect Telegram"}
            </Button>
            {telegramStatus === "connected" && (
              <span className="text-xs text-success self-center">Bot is live and routed through Xomni.</span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Model Selection Info */}
      {keys && keys.length > 0 && (
        <Card>
          <CardHeader>
            <p className="text-sm font-semibold text-ink">Selected Model</p>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-ink">
              Currently selected: <strong className="font-semibold">
                {provider === "nvidia"
                  ? "Nemotron 3.5 Lightning (NVIDIA NIM)"
                  : provider === "openai"
                  ? "GPT-4o Mini (OpenAI)"
                  : provider === "gemini"
                  ? "Gemini 1.5 Flash (Google)"
                  : provider === "groq"
                  ? "Llama 3.1 8B Instant (Groq)"
                  : provider === "ollama"
                  ? "Llama 3 (Ollama local)"
                  : "Mock (demo)"}
                </strong>
            </p>
            <p className="text-xs text-muted mt-1">
              Change your provider key in the profile to switch models.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/*Skeleton component placeholder - will be imported from UI library*/
const Skeleton = (props: any) => <div {...props} />;