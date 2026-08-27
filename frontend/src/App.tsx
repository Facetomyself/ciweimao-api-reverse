import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { BooksPage } from "./pages/BooksPage";
import { DiscoveryPage } from "./pages/DiscoveryPage";
import { IdentityPage } from "./pages/IdentityPage";
import { OverviewPage } from "./pages/OverviewPage";
import { StoragePage } from "./pages/StoragePage";
import { TasksPage } from "./pages/TasksPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="books" element={<BooksPage />} />
        <Route path="discovery" element={<DiscoveryPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="identity" element={<IdentityPage />} />
        <Route path="storage" element={<StoragePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
