const KEY = "lastWorkspaceId";

export function rememberWorkspace(id: number) {
  try {
    localStorage.setItem(KEY, String(id));
  } catch {
    // storage unavailable: skip remembering
  }
}

export function lastWorkspaceId(): number {
  try {
    return Number(localStorage.getItem(KEY));
  } catch {
    return 0;
  }
}
