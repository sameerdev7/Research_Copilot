import { Component, type ReactNode } from "react";
import ErrorNotice from "./ErrorNotice";

interface State {
  error: Error | null;
}

// catches render crashes so the page shows a message instead of going blank
export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("render crash", error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="center-screen">
        <div className="card welcome">
          <ErrorNotice
            error={{
              code: "ui_crash",
              message: "Something broke while drawing this page.",
              hint: "Reload to try again. If it keeps happening, check the browser console.",
              detail: import.meta.env.DEV ? this.state.error.message : undefined,
            }}
          />
          <button className="primary" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </div>
    );
  }
}
