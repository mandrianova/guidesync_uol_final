import { useNavigate } from "react-router-dom";

import { useGuideSync } from "../app/GuideSyncProvider";
import { pathForPage } from "../app/routePaths";
import { ProjectSettings } from "../features/projects/ProjectSettings";

export function ProjectSettingsRoutePage() {
  const navigate = useNavigate();
  const { projectDraft, projectStatus, saveProject, savingProject, setProjectDraft } =
    useGuideSync();

  const saveAndOpenRun = async () => {
    const saved = await saveProject();
    if (saved) {
      navigate(pathForPage("run"));
    }
  };

  return (
    <ProjectSettings
      onChange={setProjectDraft}
      onSave={() => void saveAndOpenRun()}
      project={projectDraft}
      projectStatus={projectStatus}
      saving={savingProject}
    />
  );
}
