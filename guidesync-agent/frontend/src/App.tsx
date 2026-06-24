import { HashRouter } from "react-router-dom";

import { GuideSyncProvider } from "./app/GuideSyncProvider";
import { GuideSyncRoutes } from "./app/GuideSyncRoutes";

export function App() {
  return (
    <HashRouter>
      <GuideSyncProvider>
        <GuideSyncRoutes />
      </GuideSyncProvider>
    </HashRouter>
  );
}
