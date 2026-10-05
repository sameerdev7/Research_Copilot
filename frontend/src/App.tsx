import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Shell from "./components/Shell";
import ChatPage from "./pages/ChatPage";
import LoginPage from "./pages/LoginPage";
import PapersPage from "./pages/PapersPage";
import Home from "./pages/Home";

export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <div className="center-screen"><span className="spinner" /></div>;
  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/" element={<Home />} />
      <Route path="/w/:workspaceId" element={<Shell />}>
        <Route index element={<Navigate to="chat" replace />} />
        <Route path="chat/:conversationId?" element={<ChatPage />} />
        <Route path="papers" element={<PapersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
