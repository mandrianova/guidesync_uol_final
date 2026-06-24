import { useGuideSync } from "../app/GuideSyncProvider";
import { ModelSettingsPage } from "../features/models/ModelSettingsPage";

export function ModelSettingsRoutePage() {
  const {
    modelProfiles,
    reloadModelProfiles,
    selectedModelProfile,
    setSelectedModelProfile
  } = useGuideSync();

  return (
    <ModelSettingsPage
      onProfilesReload={reloadModelProfiles}
      onSelectedProfileChange={setSelectedModelProfile}
      profiles={modelProfiles}
      selectedProfile={selectedModelProfile}
    />
  );
}
