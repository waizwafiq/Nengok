import { createBrowserRouter, Navigate } from "react-router-dom";
import { DashboardLayout } from "./layouts/DashboardLayout";
import { ClustersPage } from "./pages/ClustersPage";
import { ClusterDetailPage } from "./pages/ClusterDetailPage";
import { LoginPage } from "./pages/LoginPage";
import { OverviewPage } from "./pages/OverviewPage";

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/",
    element: <DashboardLayout />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "clusters", element: <ClustersPage /> },
      { path: "clusters/:clusterId", element: <ClusterDetailPage /> },
    ],
  },
]);
