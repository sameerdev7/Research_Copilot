import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, toErrorInfo } from "../api";
import ErrorNotice from "../components/ErrorNotice";
import { NewWorkspaceForm } from "../components/WorkspaceSwitcher";
import { lastWorkspaceId } from "../lastWorkspace";
import type { ErrorInfo, Workspace } from "../types";

// goes to the last workspace, or asks the user to create one
export default function Home() {
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [error, setError] = useState<ErrorInfo | null>(null);

  useEffect(() => {
    api.workspaces().then(setWorkspaces).catch((err) => setError(toErrorInfo(err)));
  }, []);

  if (error) return <div className="center-screen"><ErrorNotice error={error} /></div>;
  if (!workspaces) return <div className="center-screen"><span className="spinner" /></div>;

  if (workspaces.length > 0) {
    const target = workspaces.find((w) => w.id === lastWorkspaceId()) ?? workspaces[0];
    return <Navigate to={`/w/${target.id}`} replace />;
  }

  return (
    <div className="center-screen">
      <div className="card welcome">
        <h1>Welcome to Research Copilot</h1>
        <p className="muted">A workspace holds a set of papers and the conversations about them. Create your first one.</p>
        <NewWorkspaceForm autoFocus />
      </div>
    </div>
  );
}
