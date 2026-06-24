import {
  Button,
  Checkbox,
  Group,
  NumberInput,
  Paper,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { IconDeviceFloppy, IconPlus, IconStar, IconTrash } from "@tabler/icons-react";
import { useEffect } from "react";

import { api } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { SectionPanel } from "../../components/SectionPanel";
import { StatusBadge } from "../../components/StatusBadge";
import {
  draftModelSettings,
  isBuiltInModelProfile,
  providerPresetForProfile,
  providerPresets,
  readableModelName,
  readableProvider,
  readableThinking,
  thinkingOptions,
  thinkingToFormValue,
  toModelSettingsUpdate,
  type ProviderPresetKey
} from "../../lib/modelProfiles";
import type { ModelSettings } from "../../types";

interface ModelSettingsPageProps {
  profiles: ModelSettings[];
  selectedProfile: ModelSettings;
  onProfilesReload: (selectedId?: string) => Promise<void>;
  onSelectedProfileChange: (profile: ModelSettings) => void;
}

interface ModelFormValues {
  name: string;
  providerPreset: ProviderPresetKey;
  model: string;
  baseUrl: string;
  apiKey: string;
  clearApiKey: boolean;
  timeoutSeconds: number;
  thinking: string;
}

export function ModelSettingsPage({
  profiles,
  selectedProfile,
  onProfilesReload,
  onSelectedProfileChange
}: ModelSettingsPageProps) {
  const builtIn = isBuiltInModelProfile(selectedProfile);
  const form = useForm<ModelFormValues>({
    initialValues: {
      name: "",
      providerPreset: "openai",
      model: "",
      baseUrl: "",
      apiKey: "",
      clearApiKey: false,
      timeoutSeconds: 60,
      thinking: ""
    }
  });

  useEffect(() => {
    const providerPreset = providerPresetForProfile(selectedProfile);
    const preset = providerPresets[providerPreset];
    form.setValues({
      name: selectedProfile.name || preset.defaultName,
      providerPreset,
      model: selectedProfile.model || preset.defaultModel,
      baseUrl: selectedProfile.base_url || "",
      apiKey: "",
      clearApiKey: false,
      timeoutSeconds: selectedProfile.timeout_seconds || 60,
      thinking: thinkingToFormValue(selectedProfile.thinking)
    });
    form.resetDirty();
    // Mantine form object is intentionally stable enough for this field reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProfile.id]);

  const status = builtIn
    ? "Built-in default"
    : selectedProfile.is_default
      ? "Default model"
      : selectedProfile.id
        ? "Saved profile"
        : "New model";

  const selectPreset = (value: string | null) => {
    const providerPreset = (value || "pydantic_ai") as ProviderPresetKey;
    const preset = providerPresets[providerPreset] || providerPresets.pydantic_ai;
    form.setFieldValue("providerPreset", providerPreset);
    form.setFieldValue("model", preset.defaultModel);
    form.setFieldValue("baseUrl", preset.defaultBaseUrl || "");
    if (!form.values.name.trim()) {
      form.setFieldValue("name", preset.defaultName);
    }
  };

  const saveProfile = async (values: ModelFormValues) => {
    if (builtIn) {
      notifications.show({
        color: "yellow",
        message: "Built-in default model profile is read-only.",
        title: "Model settings"
      });
      return;
    }
    try {
      const payload = toModelSettingsUpdate(values);
      const saved = selectedProfile.id
        ? await api.updateModelProfile(selectedProfile.id, payload)
        : await api.createModelProfile(payload);
      await onProfilesReload(saved.id);
      notifications.show({
        color: "teal",
        message: "Model profile saved",
        title: "Model settings"
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not save model profile",
        title: "Save failed"
      });
    }
  };

  const setDefault = async () => {
    if (!selectedProfile.id) {
      notifications.show({
        color: "yellow",
        message: "Save the profile before using it as default.",
        title: "Model settings"
      });
      return;
    }
    try {
      const saved = await api.setDefaultModelProfile(selectedProfile.id);
      await onProfilesReload(saved.id);
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not set default model",
        title: "Default switch failed"
      });
    }
  };

  const deleteProfile = async () => {
    if (!selectedProfile.id) {
      onSelectedProfileChange(draftModelSettings());
      return;
    }
    try {
      const saved = await api.deleteModelProfile(selectedProfile.id);
      await onProfilesReload(saved.id);
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Could not delete model profile",
        title: "Delete failed"
      });
    }
  };

  return (
    <Stack gap="lg">
      <PageHeader title="Model settings" />
      <SectionPanel
        actions={<StatusBadge status={status} />}
        description="Choose the default model used by project analysis runs."
        title="Model settings"
      >
        <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
          <Stack gap="md">
            <Group justify="space-between">
              <div>
                <Title order={3}>Saved models</Title>
                <Text c="dimmed" size="sm">
                  Keep the current default and switch back to it later.
                </Text>
              </div>
              <Button
                leftSection={<IconPlus size={17} />}
                onClick={() => onSelectedProfileChange(draftModelSettings("openai"))}
                variant="light"
              >
                Add model
              </Button>
            </Group>

            {!profiles.length ? (
              <EmptyState>No saved model profiles yet.</EmptyState>
            ) : (
              <Stack gap="xs">
                {profiles.map((profile) => (
                  <Paper
                    className={selectedProfile.id === profile.id ? "row-card active" : "row-card"}
                    component="button"
                    key={profile.id}
                    onClick={() => onSelectedProfileChange(profile)}
                    p="md"
                    type="button"
                    withBorder
                  >
                    <Group justify="space-between" wrap="nowrap">
                      <div>
                        <Text fw={800}>{profile.name || "Model profile"}</Text>
                        <Text c="dimmed" size="sm">
                          {readableProvider(profile)} · {readableModelName(profile.model)}
                        </Text>
                        <Text c="dimmed" size="xs">
                          {readableThinking(profile.thinking)}
                        </Text>
                      </div>
                      <Group gap="xs" justify="flex-end">
                        {profile.id === "global-default" ? <StatusBadge status="Built-in" /> : null}
                        {profile.is_default ? <StatusBadge status="Default" /> : null}
                      </Group>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            )}
          </Stack>

          <Paper className={builtIn ? "model-editor readonly" : "model-editor"} p="md" withBorder>
            <form onSubmit={form.onSubmit(saveProfile)}>
              <Stack gap="md">
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <TextInput
                    disabled={builtIn}
                    label="Profile name"
                    placeholder="Production OpenAI"
                    {...form.getInputProps("name")}
                  />
                  <Select
                    allowDeselect={false}
                    data={Object.entries(providerPresets).map(([value, preset]) => ({
                      value,
                      label: preset.label
                    }))}
                    disabled={builtIn}
                    label="Provider"
                    onChange={selectPreset}
                    value={form.values.providerPreset}
                  />
                </SimpleGrid>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <TextInput
                    disabled={builtIn}
                    label="Model"
                    placeholder="openai:gpt-4.1"
                    {...form.getInputProps("model")}
                  />
                  <TextInput
                    disabled={builtIn}
                    label="Base URL"
                    placeholder="Optional, e.g. LiteLLM or local proxy URL"
                    {...form.getInputProps("baseUrl")}
                  />
                </SimpleGrid>
                {!builtIn ? (
                  <>
                    <SimpleGrid cols={{ base: 1, sm: 2 }}>
                      <PasswordInput
                        label="Token"
                        placeholder={
                          selectedProfile.has_api_key
                            ? "Saved token is configured"
                            : "Optional; saved server-side"
                        }
                        {...form.getInputProps("apiKey")}
                      />
                      <NumberInput
                        allowDecimal={false}
                        label="Timeout seconds"
                        min={1}
                        {...form.getInputProps("timeoutSeconds")}
                      />
                      <Select
                        allowDeselect={false}
                        data={thinkingOptions}
                        label="Thinking"
                        {...form.getInputProps("thinking")}
                      />
                    </SimpleGrid>
                    <Checkbox
                      label="Clear saved token"
                      {...form.getInputProps("clearApiKey", { type: "checkbox" })}
                    />
                  </>
                ) : null}

                <Group justify="flex-end">
                  <Button
                    color="red"
                    disabled={!selectedProfile.id || selectedProfile.is_default || builtIn}
                    leftSection={<IconTrash size={17} />}
                    onClick={deleteProfile}
                    type="button"
                    variant="subtle"
                  >
                    Delete model
                  </Button>
                  <Button
                    disabled={!selectedProfile.id || selectedProfile.is_default}
                    leftSection={<IconStar size={17} />}
                    onClick={setDefault}
                    type="button"
                    variant="light"
                  >
                    Use as default
                  </Button>
                  <Button disabled={builtIn} leftSection={<IconDeviceFloppy size={17} />} type="submit">
                    Save model profile
                  </Button>
                </Group>
              </Stack>
            </form>
          </Paper>
        </SimpleGrid>
      </SectionPanel>
    </Stack>
  );
}
