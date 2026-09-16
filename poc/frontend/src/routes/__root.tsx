import { createRootRoute, Outlet } from '@tanstack/react-router'

/* 根路由只挂一个 Outlet。壳子（导航栏 / 顶栏 / 命令面板 / 历史抽屉）在 `_app`
   布局路由上 —— 登录页在壳外，它和壳内页面唯一的共同祖先就是这里。 */
export const Route = createRootRoute({
  component: Outlet,
})
