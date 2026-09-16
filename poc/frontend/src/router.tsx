import { createRouter } from '@tanstack/react-router'

import { routeTree } from './routeTree.gen'

/*
 * 路由器。`basepath` 就是原来 BrowserRouter 的 `basename="/v2"` —— 新界面挂在
 * /v2 下，老的 /static/index.html 还在跑，URL 一个都不能变。
 *
 * `defaultPreload: 'intent'`：鼠标停在链接上就开始拉那条路由的 chunk。原来这些
 * chunk 是点下去才开始下载的，顶部进度条报的正是那段等待。
 */
export const router = createRouter({
  routeTree,
  basepath: '/v2',
  defaultPreload: 'intent',
  /* 顶部进度条已经在报等待了，路由自己再渲染一个 pending 组件是第二个加载指示。 */
  defaultPendingComponent: () => null,
  scrollRestoration: true,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
