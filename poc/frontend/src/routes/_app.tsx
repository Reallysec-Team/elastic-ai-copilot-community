import { createFileRoute, redirect } from '@tanstack/react-router'

import { AppShell } from '@/components/AppShell'
import { fetchMe } from '@/lib/auth'

/*
 * 壳内每一页的登录闸。原来是 `App.tsx` 里的 `RequireAuth` 组件，现在是路由的
 * `beforeLoad` —— 判定在渲染之前跑完，不会先闪一帧空页面再跳走。
 *
 * 三个分支，第三个是关键：部署没开密码登录时（SSO / Basic Auth / demo）必须
 * 完全让路 —— 把这些部署重定向到一个后端根本不认的登录页，等于把客户锁在自己
 * 的产品外面。
 *
 * `/api/me` 按设计是免鉴权可达的，所以这里请求失败意味着网关没起来，不是被拒。
 * 拿「服务器连不上」换一个误导性的登录框，只会让人去查密码。
 */
export const Route = createFileRoute('/_app')({
  beforeLoad: async ({ location }) => {
    const me = await fetchMe().catch(() => null)
    if (me && me.login_enabled && !me.authenticated) {
      /* 把原本要去的地方带上，分享出去的深链在触发登录之后还能回到原处。
         放在 router state 而不是 `?next=` 参数里：路径不进 URL、不进访问日志，
         也没法从外面构造。 */
      throw redirect({ to: '/login', state: { from: location.href } as never })
    }
  },
  component: AppShell,
})
