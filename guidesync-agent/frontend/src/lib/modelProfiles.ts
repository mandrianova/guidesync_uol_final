import type { ModelSettings, ModelSettingsUpdate, ModelThinking, ProviderKind } from "../types";

export const builtInModelProfileId = "global-default";

export type ProviderPresetKey =
  | "openai"
  | "anthropic"
  | "google"
  | "mistral"
  | "cohere"
  | "litellm"
  | "lmstudio"
  | "local_http"
  | "pydantic_ai"
  | "mock";

export interface ProviderPreset {
  label: string;
  backendProvider: ProviderKind;
  defaultModel: string;
  defaultName: string;
  defaultBaseUrl?: string;
}

export const thinkingOptions = [
  { value: "", label: "Provider default" },
  { value: "true", label: "Enabled" },
  { value: "false", label: "Disabled" },
  { value: "minimal", label: "Minimal" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "XHigh" }
];

export const providerPresets: Record<ProviderPresetKey, ProviderPreset> = {
  openai: {
    label: "OpenAI",
    backendProvider: "pydantic_ai",
    defaultModel: "openai:gpt-4.1",
    defaultName: "OpenAI default"
  },
  anthropic: {
    label: "Anthropic",
    backendProvider: "pydantic_ai",
    defaultModel: "anthropic:claude-3-5-sonnet-latest",
    defaultName: "Anthropic Claude"
  },
  google: {
    label: "Google Gemini",
    backendProvider: "pydantic_ai",
    defaultModel: "google-gla:gemini-1.5-pro",
    defaultName: "Google Gemini"
  },
  mistral: {
    label: "Mistral",
    backendProvider: "pydantic_ai",
    defaultModel: "mistral:mistral-large-latest",
    defaultName: "Mistral"
  },
  cohere: {
    label: "Cohere",
    backendProvider: "pydantic_ai",
    defaultModel: "cohere:command-r-plus",
    defaultName: "Cohere"
  },
  litellm: {
    label: "LiteLLM / OpenAI-compatible",
    backendProvider: "pydantic_ai",
    defaultModel: "openai:gpt-4o-mini",
    defaultName: "LiteLLM proxy",
    defaultBaseUrl: "http://host.docker.internal:4000/v1"
  },
  lmstudio: {
    label: "LM Studio / OpenAI-compatible",
    backendProvider: "pydantic_ai",
    defaultModel: "openai:google/gemma-4-31b-qat",
    defaultName: "LM Studio agent",
    defaultBaseUrl: "http://host.docker.internal:1234/v1"
  },
  local_http: {
    label: "Local JSON HTTP",
    backendProvider: "local_http",
    defaultModel: "google/gemma-4-31b-qat",
    defaultName: "Local model",
    defaultBaseUrl: "http://host.docker.internal:1234/v1"
  },
  pydantic_ai: {
    label: "Custom pydantic-ai string",
    backendProvider: "pydantic_ai",
    defaultModel: "openai:gpt-4.1",
    defaultName: "Custom model"
  },
  mock: {
    label: "Mock / deterministic",
    backendProvider: "mock",
    defaultModel: "mock:deterministic",
    defaultName: "Mock provider"
  }
};

export function providerPresetForProfile(profile: Pick<ModelSettings, "provider" | "model" | "base_url">): ProviderPresetKey {
  if (profile.provider === "local_http") {
    return "local_http";
  }
  if (profile.provider === "mock") {
    return "mock";
  }
  const model = profile.model || "";
  if (model.startsWith("anthropic:")) {
    return "anthropic";
  }
  if (model.startsWith("google-") || model.startsWith("gemini:")) {
    return "google";
  }
  if (model.startsWith("mistral:")) {
    return "mistral";
  }
  if (model.startsWith("cohere:")) {
    return "cohere";
  }
  if (profile.base_url && model.startsWith("openai:")) {
    if (profile.base_url.includes("host.docker.internal:1234")) {
      return "lmstudio";
    }
    return "litellm";
  }
  if (model.startsWith("openai:")) {
    return "openai";
  }
  return "pydantic_ai";
}

export function readableProvider(profile: Pick<ModelSettings, "provider" | "model" | "base_url">): string {
  return providerPresets[providerPresetForProfile(profile)]?.label || profile.provider;
}

export function readableModelName(model: string | null | undefined): string {
  return String(model || "model").replace(/^[a-z-]+:/, "");
}

export function readableModelLabel(
  profile: Pick<ModelSettings, "provider" | "model" | "base_url"> | null | undefined
): string {
  if (!profile) {
    return "n/a";
  }
  return `${readableProvider(profile)} · ${readableModelName(profile.model)}`;
}

export function readableThinking(thinking: ModelThinking | null | undefined): string {
  if (thinking === null || thinking === undefined) {
    return "Thinking provider default";
  }
  if (thinking === true) {
    return "Thinking enabled";
  }
  if (thinking === false) {
    return "Thinking disabled";
  }
  return `Thinking ${thinking}`;
}

export function isBuiltInModelProfile(profile: ModelSettings | null): boolean {
  return profile?.id === builtInModelProfileId;
}

export function draftModelSettings(providerPreset: ProviderPresetKey = "openai"): ModelSettings {
  const preset = providerPresets[providerPreset];
  return {
    id: "",
    name: preset.defaultName,
    provider: preset.backendProvider,
    model: preset.defaultModel,
    base_url: preset.defaultBaseUrl || "",
    has_api_key: false,
    is_default: false,
    timeout_seconds: 60,
    thinking: null
  };
}

export function normalizeModelForProvider(providerPreset: ProviderPresetKey, model: string): string {
  if (!model || model.includes(":")) {
    return model;
  }
  if (providerPreset === "openai" || providerPreset === "litellm" || providerPreset === "lmstudio") {
    return `openai:${model}`;
  }
  if (providerPreset === "anthropic") {
    return `anthropic:${model}`;
  }
  if (providerPreset === "mistral") {
    return `mistral:${model}`;
  }
  if (providerPreset === "cohere") {
    return `cohere:${model}`;
  }
  return model;
}

export function toModelSettingsUpdate(values: {
  name: string;
  providerPreset: ProviderPresetKey;
  model: string;
  baseUrl: string;
  apiKey: string;
  clearApiKey: boolean;
  timeoutSeconds: number;
  thinking: string | null;
}): ModelSettingsUpdate {
  const preset = providerPresets[values.providerPreset] || providerPresets.pydantic_ai;
  const payload: ModelSettingsUpdate = {
    name: values.name.trim() || preset.defaultName,
    provider: preset.backendProvider,
    model: normalizeModelForProvider(values.providerPreset, values.model.trim() || preset.defaultModel),
    timeout_seconds: Number.isFinite(values.timeoutSeconds) && values.timeoutSeconds > 0 ? values.timeoutSeconds : 60,
    clear_api_key: values.clearApiKey,
    thinking: normalizeThinking(values.thinking)
  };
  if (values.baseUrl.trim()) {
    payload.base_url = values.baseUrl.trim();
  }
  if (values.apiKey.trim()) {
    payload.api_key = values.apiKey.trim();
  }
  return payload;
}

export function normalizeThinking(value: string | null | undefined): ModelThinking | null {
  if (!value) {
    return null;
  }
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return value as ModelThinking;
}

export function thinkingToFormValue(value: ModelThinking | null | undefined): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (value === true) {
    return "true";
  }
  if (value === false) {
    return "false";
  }
  return value;
}
