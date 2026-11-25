import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { ProtectedRoute } from '@/features/auth/ProtectedRoute'
import { RequirePermission } from '@/features/auth/RequirePermission'
import { AuditPage } from '@/features/audit/pages/AuditPage'
import { DecisionPage } from '@/features/decision/DecisionPage'
import { DashboardPage } from '@/features/dashboard/pages/DashboardPage'
import { MyWorkPage } from '@/features/my-work/MyWorkPage'
import { ReportsPage } from '@/features/reports/ReportsPage'
import { DocumentsPage } from '@/features/documents/DocumentsPage'
import { InvoicesPage } from '@/features/invoices/InvoicesPage'
import { DocumentStorePage } from '@/features/document-store/DocumentStorePage'
import { PurchaseOrdersPage } from '@/features/purchase-orders/PurchaseOrdersPage'
import { AgentFlowPage } from '@/features/agent-flow/AgentFlowPage'
import { ApprovalsPage } from '@/features/approvals/pages/ApprovalsPage'
import { CasesPage } from '@/features/cases/pages/CasesPage'
import { CaseDetailPage } from '@/features/cases/pages/CaseDetailPage'
import { HomeRedirect } from '@/features/auth/HomeRedirect'
import { MyRequestsPage } from '@/features/requests/pages/MyRequestsPage'
import { RequestDetailPage } from '@/features/requests/pages/RequestDetailPage'
import { SettingsPage } from '@/features/settings/pages/SettingsPage'
import { StockPage } from '@/features/stock/pages/StockPage'
import { StoreRoomPage } from '@/features/store-room/StoreRoomPage'
import { UsersPage } from '@/features/users/pages/UsersPage'
import { VendorsPage } from '@/features/vendors/pages/VendorsPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { RouteError } from '@/pages/RouteError'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage />, errorElement: <RouteError /> },
  { path: '/forgot-password', element: <ForgotPasswordPage />, errorElement: <RouteError /> },
  // Public: the link in an approval email. The link itself is the credential, so there is no sign-in.
  { path: '/decide/:token', element: <DecisionPage />, errorElement: <RouteError /> },
  {
    errorElement: <RouteError />, // anything that crashes outside the app shell
    // Everything below needs a signed-in user; each section also needs its permission.
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <AppShell />,
        children: [
         {
          // A crash in one page shows the message inside the app (menu and top bar stay), not a blank screen.
          errorElement: <RouteError />,
          children: [
          { index: true, element: <HomeRedirect /> },
          {
            element: <RequirePermission permission="dashboard:read" />,
            children: [
              { path: 'dashboard', element: <DashboardPage /> },
              { path: 'reports', element: <ReportsPage /> },
            ],
          },
          {
            element: <RequirePermission permission="cases:read_all" />,
            children: [
              { path: 'my-work', element: <MyWorkPage /> },
              { path: 'cases', element: <CasesPage /> },
              { path: 'cases/:caseId', element: <CaseDetailPage /> },
              { path: 'documents', element: <DocumentsPage /> },
              { path: 'purchase-orders', element: <PurchaseOrdersPage /> },
              { path: 'invoices', element: <InvoicesPage /> },
            ],
          },
          {
            element: <RequirePermission permission="cases:create" />,
            children: [
              { path: 'requests', element: <MyRequestsPage /> },
              { path: 'requests/:caseId', element: <RequestDetailPage /> },
            ],
          },
          { element: <RequirePermission permission="approvals:read" />, children: [{ path: 'approvals', element: <ApprovalsPage /> }] },
          { element: <RequirePermission permission="cases:read" />, children: [{ path: 'agent-flow', element: <AgentFlowPage /> }, { path: 'document-store', element: <DocumentStorePage /> }] },
          { element: <RequirePermission permission="storeroom:read" />, children: [{ path: 'store-room', element: <StoreRoomPage /> }] },
          { element: <RequirePermission permission="stock:read" />, children: [{ path: 'stock', element: <StockPage /> }] },
          { element: <RequirePermission permission="vendors:read" />, children: [{ path: 'vendors', element: <VendorsPage /> }] },
          { element: <RequirePermission permission="users:read" />, children: [{ path: 'users', element: <UsersPage /> }] },
          { element: <RequirePermission permission="audit:read" />, children: [{ path: 'audit', element: <AuditPage /> }] },
          { path: 'settings', element: <SettingsPage /> },
          { path: '*', element: <NotFoundPage /> },
          ],
         },
        ],
      },
    ],
  },
])
