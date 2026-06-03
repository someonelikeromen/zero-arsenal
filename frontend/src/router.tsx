/**
 * TanStack Router 路由配置（12-frontend-architecture.md §2.3）
 *
 * 路由结构：
 *   /                  → 首页（会话选择）
 *   /sessions/$id      → 会话主界面
 *   /settings          → 设置页面
 */
import {
  createRouter,
  createRoute,
  createRootRoute,
  Outlet,
  redirect,
} from '@tanstack/react-router'
import { HomePage } from './pages/HomePage'
import { SessionPage } from './pages/SessionPage'

// ── 根布局 ──────────────────────────────────────────────────────────────────
const rootRoute = createRootRoute({
  component: () => <Outlet />,
})

// ── 首页 ─────────────────────────────────────────────────────────────────────
const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePageWrapper,
})

function HomePageWrapper() {
  const navigate = homeRoute.useNavigate()
  return (
    <HomePage
      onSelectSession={(id) => {
        navigate({ to: '/sessions/$id', params: { id } })
      }}
    />
  )
}

// ── 设置页（兼容路由：跳转到首页 Settings Tab）───────────────────────────────
const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  beforeLoad: () => {
    throw redirect({ to: '/' })
  },
})

// ── 会话列表页（兼容路由：跳转到首页）────────────────────────────────────────
const sessionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/sessions',
  beforeLoad: () => {
    throw redirect({ to: '/' })
  },
})

const sessionDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/sessions/$id',
  component: SessionPageWrapper,
})

function SessionPageWrapper() {
  const { id } = sessionDetailRoute.useParams()
  const navigate = sessionDetailRoute.useNavigate()

  return (
    <div>
      <SessionPage
        sessionId={id}
        onNavigateSession={(newId) => {
          navigate({ to: '/sessions/$id', params: { id: newId } })
        }}
      />
      <button
        onClick={() => navigate({ to: '/' })}
        className="fixed top-2 left-2 text-xs text-zinc-600 hover:text-zinc-400 z-50 xl:hidden"
        title="返回首页"
      >
        ← 首页
      </button>
    </div>
  )
}

// ── 路由树 & 路由器 ──────────────────────────────────────────────────────────
const routeTree = rootRoute.addChildren([
  homeRoute,
  settingsRoute,
  sessionsRoute,
  sessionDetailRoute,
])

export const router = createRouter({ routeTree })

// TanStack Router 类型声明
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
