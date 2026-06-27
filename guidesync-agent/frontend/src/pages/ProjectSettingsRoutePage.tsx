import { useGuideSync } from "../app/GuideSyncProvider";
import { ProjectSettings } from "../features/projects/ProjectSettings";

export function ProjectSettingsRoutePage() {
  const { projectDraft, projectStatus, saveProject, savingProject, setProjectDraft } =
    useGuideSync();

  return (
    <ProjectSettings
      onChange={setProjectDraft}
      onSave={() => void saveProject()}
      project={projectDraft}
      projectStatus={projectStatus}
      saving={savingProject}
    />
  );
}
