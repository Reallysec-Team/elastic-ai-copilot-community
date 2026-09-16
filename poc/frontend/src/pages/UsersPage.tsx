import { useCallback, useEffect, useMemo, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  AlertCircleIcon, Delete02Icon, Key01Icon, Loading03Icon, MoreHorizontalCircle01Icon,
  Search01Icon, ToggleOffIcon, ToggleOnIcon, UserAdd01Icon, UserGroupIcon,
} from '@hugeicons/core-free-icons'
import { toast } from 'sonner'
import { useTable, type ColumnDef, type SortingState } from '@tanstack/react-table'

import { api, type ApiError, type UserAccount, type UserRole, type UsersPayload } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { useT, type Translate } from '@/lib/i18n'
import { commonCopy } from '@/locales/common'
import { ROLE_HINT_KEY, ROLE_KEY, shellCopy, type ShellKey } from '@/locales/shell'
import { usersCopy } from '@/locales/users'
import { Alert, AlertDescription } from '@/components/reui/alert'
import { Badge } from '@/components/reui/badge'
import { DataGrid, dataGridFeatures, type DataGridFeatures } from '@/components/reui/data-grid/data-grid'
import { DataGridColumnHeader } from '@/components/reui/data-grid/data-grid-column-header'
import { DataGridScrollArea } from '@/components/reui/data-grid/data-grid-scroll-area'
import { DataGridTable } from '@/components/reui/data-grid/data-grid-table'
import {
  Frame, FrameHeader, FramePanel, FrameTitle,
} from '@/components/reui/frame'
import { PageHeader } from '@/components/shell/page-header'
import { AdminOnlyView, useIsAdmin } from '@/components/gated-button'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { HintTip } from '@/components/hint-tip'

/*
 * 用户与角色。
 *
 * 后端在 Phase 03 就把这四个接口做全了（GET / POST / PATCH / DELETE `/api/users`），
 * 界面一直没有入口 —— 管理员登录进来找不到「在哪加人」，不是权限不够，是页面没做。
 *
 * 三个后端已经在守的规矩，这里同样拦一道（拦是礼貌，不是控制 —— 每一条后端都会
 * 再拒一次）：不能停用自己、不能删自己、密码至少 8 位。
 *
 * `multi_user=false` 表示没配独立用户表（没有 Postgres），这时整个部署只有 .env
 * 里那一个 admin，加人是加不进去的 —— 与其让人填完表单吃一个 400，不如把话说在
 * 前面。
 *
 * 版式照 `@reui/solution-users-1`（members-grid）：Frame 卡头 + 工具条（搜索）+
 * DataGrid + 行尾「…」菜单。没照搬的：多选 / 批量改角色（三五个账号用不上）、
 * SSO / 2FA 列（产品没有）、成员详情 Sheet（账号只有名字和角色，没有第二层）。
 */

const MIN_PASSWORD = 8

/* 角色名和角色说明走 shell.ts —— 账号菜单和个人资料抽屉读的是同一份。这里原来
   自己又抄了一遍，是全站第三份。 */
function roleName(t: Translate<ShellKey>, role: string): string {
  return ROLE_KEY[role] ? t(ROLE_KEY[role]) : role
}
function roleHint(t: Translate<ShellKey>, role: string): string | undefined {
  return ROLE_HINT_KEY[role] ? t(ROLE_HINT_KEY[role]) : undefined
}

/*
 * GET /api/users 要管理员。这一页原本就"整页就是管理员页"，只是非管理员进来
 * 看到的是加载失败，而不是一句"你看不到"。
 */
export function UsersPage() {
  const t = useT(usersCopy)
  const isAdmin = useIsAdmin()
  if (!isAdmin) return <AdminOnlyView title={t('title')} />
  return <UsersView />
}

function UsersView() {
  const t = useT(usersCopy)
  const c = useT(commonCopy)
  const sh = useT(shellCopy)
  const me = useMe()
  // 用户管理是管理员的事，后端也这么判。me 还没回来时不抢先禁用（按 !== false），
  // 免得页面一闪一个全灰的表。
  const canManage = me?.is_admin !== false
  const [data, setData] = useState<UsersPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [resetFor, setResetFor] = useState<string | null>(null)
  const [deleteFor, setDeleteFor] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [sorting, setSorting] = useState<SortingState>([{ id: 'username', desc: false }])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await api.usersList())
    } catch (e) {
      setError((e as ApiError).message || t('errLoad'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    load()
  }, [load])

  /* 四个接口回的都是全量快照，所以每次写完直接换掉整份，不用再拉一次。 */
  const run = useCallback(async (key: string, op: () => Promise<UsersPayload>, ok: string) => {
    setBusy(key)
    try {
      setData(await op())
      toast.success(ok)
    } catch (e) {
      toast.error((e as ApiError).message || t('errAction'))
    } finally {
      setBusy(null)
    }
  }, [t])

  const myName = me?.user?.username ?? ''
  const users = data?.users ?? []
  const roles = data?.roles ?? (['admin', 'analyst', 'viewer'] as UserRole[])
  const singleUser = data != null && !data.multi_user

  /* 客户端搜索：账号总共就几个到几十个，全量在手里，不值得为它开一个后端参数。 */
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return users
    return users.filter((u) => u.username.toLowerCase().includes(q) || roleName(sh, u.role).toLowerCase().includes(q))
  }, [users, query, sh])

  const columns = useMemo<ColumnDef<DataGridFeatures, UserAccount>[]>(() => [
    {
      accessorKey: 'username',
      id: 'username',
      header: ({ column }) => <DataGridColumnHeader title={t('colAccount')} column={column} />,
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-2 font-medium">
          {row.original.username}
          {row.original.username === myName && (
            <Badge variant="secondary" size="sm">{t('currentSession')}</Badge>
          )}
        </span>
      ),
      enableSorting: true,
      minSize: 200,
      meta: { headerTitle: t('colAccount'), autoSize: true },
    },
    {
      accessorKey: 'role',
      id: 'role',
      header: ({ column }) => <DataGridColumnHeader title={t('colRole')} column={column} />,
      cell: ({ row }) => {
        const u = row.original
        return (
          <Select
            value={u.role}
            onValueChange={(v) => run(u.username, () => api.userUpdate(u.username, { role: v as UserRole }), t('okRole'))}
            disabled={busy === u.username || !canManage}
          >
            <SelectTrigger size="sm" className="w-[150px]" aria-label={t('roleOf', { name: u.username })}>
              <SelectValue>{roleName(sh, u.role)}</SelectValue>
            </SelectTrigger>
            {/* 弹层默认和触发器同宽（150px），第二行的角色说明被截成「可以改配置、管…」。
                说明才是选角色时真正要读的东西：弹层放宽，说明允许换行。 */}
            <SelectContent align="start" className="w-auto min-w-72 max-w-96">
              {roles.map((r) => (
                <SelectItem key={r} value={r}>
                  <span className="flex flex-col gap-0.5">
                    <span>{roleName(sh, r)}</span>
                    <span className="text-xs whitespace-normal text-muted-foreground">{roleHint(sh, r)}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )
      },
      size: 180,
      enableSorting: true,
      meta: { headerTitle: t('colRole') },
    },
    {
      accessorKey: 'disabled',
      id: 'status',
      header: ({ column }) => <DataGridColumnHeader title={t('colStatus')} column={column} />,
      cell: ({ row }) => row.original.disabled
        ? <Badge variant="destructive-light">{t('statusDisabled')}</Badge>
        : <Badge variant="success-light">{t('statusOk')}</Badge>,
      size: 110,
      enableSorting: true,
      meta: { headerTitle: t('colStatus') },
    },
    {
      id: 'actions',
      header: () => <span className="sr-only">{t('colActions')}</span>,
      cell: ({ row }) => {
        const u = row.original
        const isMe = u.username === myName
        const rowBusy = busy === u.username
        return (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-7"
                  aria-label={t('actionsOf', { name: u.username })}
                  disabled={rowBusy || !canManage}
                />
              }
            >
              <HugeiconsIcon
                icon={rowBusy ? Loading03Icon : MoreHorizontalCircle01Icon}
                strokeWidth={2}
                className={rowBusy ? 'size-4 animate-spin' : 'size-4'}
                aria-hidden="true"
              />
            </DropdownMenuTrigger>
            <DropdownMenuContent side="bottom" align="end" className="w-44">
              <DropdownMenuGroup>
                <DropdownMenuItem onClick={() => setResetFor(u.username)}>
                  <HugeiconsIcon icon={Key01Icon} strokeWidth={2} className="size-4" aria-hidden="true" />
                  {t('resetPassword')}
                </DropdownMenuItem>
                {/* 停用自己会把自己锁在门外，删自己更是；后端两条都会拒，这里先不给点。 */}
                <DropdownMenuItem
                  disabled={isMe}
                  onClick={() => run(
                    u.username,
                    () => api.userUpdate(u.username, { disabled: !u.disabled }),
                    u.disabled ? t('okEnabled') : t('okDisabled'),
                  )}
                >
                  <HugeiconsIcon icon={u.disabled ? ToggleOnIcon : ToggleOffIcon} strokeWidth={2} className="size-4" aria-hidden="true" />
                  {u.disabled ? t('enable') : t('disable')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" disabled={isMe} onClick={() => setDeleteFor(u.username)}>
                  <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} className="size-4" aria-hidden="true" />
                  {t('delete')}
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )
      },
      size: 56,
      enableSorting: false,
      enableResizing: false,
      meta: { headerTitle: t('colActions') },
    },
  ], [t, sh, roles, busy, canManage, myName, run])

  const table = useTable({
    features: dataGridFeatures,
    columns,
    data: filtered,
    getRowId: (row) => row.username,
    state: { sorting },
    onSortingChange: setSorting,
  })

  return (
    <div className="@container flex w-full flex-col gap-5">
      <PageHeader
        title={t('title')}
        actions={
          <Button size="sm" disabled={singleUser || !canManage} onClick={() => setAddOpen(true)}>
            <HugeiconsIcon icon={UserAdd01Icon} strokeWidth={2} className="size-4" />
            {t('newUser')}
          </Button>
        }
      />

      {error && (
        <Alert variant="destructive">
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {singleUser && (
        <Alert>
          <HugeiconsIcon icon={AlertCircleIcon} strokeWidth={2} className="size-4" />
          <AlertDescription>
            {t('singleUserNotice')}
          </AlertDescription>
        </Alert>
      )}

      <section aria-label={t('secList')}>
        <DataGrid
          table={table}
          recordCount={filtered.length}
          isLoading={loading && users.length === 0}
          loadingMode="skeleton"
          emptyMessage={users.length > 0 && filtered.length === 0 ? t('noMatch') : undefined}
          tableLayout={{ dense: true, rowBorder: true, headerSticky: true, columnsResizable: false, columnsMovable: false }}
          tableClassNames={{
            bodyRow: '[&>td]:h-12',
            edgeCell: 'first:ps-(--frame-panel-header-px) last:pe-(--frame-panel-header-px)',
          }}
        >
          <Frame dense spacing="sm" className="w-full min-w-0">
            <FrameHeader className="flex-row items-center justify-between gap-3">
              <FrameTitle className="flex items-center gap-1.5 text-balance">
                {t('cardTitle')}
                <HintTip text={t('cardDesc')} />
              </FrameTitle>
            </FrameHeader>
            <FramePanel className="p-0! shadow-none!">
              <div className="flex flex-wrap items-center justify-between gap-2 px-(--frame-panel-header-px) py-2.5">
                <InputGroup className="w-full max-w-xs">
                  <InputGroupAddon align="inline-start">
                    <HugeiconsIcon icon={Search01Icon} strokeWidth={2} className="size-4" aria-hidden="true" />
                  </InputGroupAddon>
                  <InputGroupInput
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={t('searchPlaceholder')}
                    aria-label={t('searchPlaceholder')}
                  />
                </InputGroup>
                <span className="text-xs text-muted-foreground">{t('countLine', { n: users.length })}</span>
              </div>
              <Separator />
              {!loading && users.length === 0 ? (
                <Empty>
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <HugeiconsIcon icon={UserGroupIcon} strokeWidth={2} />
                    </EmptyMedia>
                    <EmptyTitle>{t('emptyTitle')}</EmptyTitle>
                    <EmptyDescription>{t('emptyDesc')}</EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <DataGridScrollArea>
                  <DataGridTable />
                </DataGridScrollArea>
              )}
            </FramePanel>
          </Frame>
        </DataGrid>
      </section>

      <AddUserDialog
        open={addOpen}
        roles={roles}
        onOpenChange={setAddOpen}
        onCreate={async (body) => {
          setData(await api.userCreate(body))
          toast.success(t('okCreated'))
        }}
      />

      <ResetPasswordDialog
        username={resetFor}
        onOpenChange={(v) => !v && setResetFor(null)}
        onReset={async (password) => {
          if (!resetFor) return
          setData(await api.userUpdate(resetFor, { password }))
          toast.success(t('okReset'))
        }}
      />

      {/* 删除不可逆，照 solution-users-1 走一道 AlertDialog；原来是行尾一个图标按钮
          直接删。 */}
      <AlertDialog open={deleteFor !== null} onOpenChange={(v) => !v && setDeleteFor(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('deleteUser', { name: deleteFor ?? '' })}</AlertDialogTitle>
            <AlertDialogDescription>{t('deleteConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{c('cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                const name = deleteFor
                setDeleteFor(null)
                if (name) void run(name, () => api.userDelete(name), t('okDeleted'))
              }}
            >
              {t('delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function AddUserDialog({
  open, roles, onOpenChange, onCreate,
}: {
  open: boolean
  roles: UserRole[]
  onOpenChange: (v: boolean) => void
  onCreate: (body: { username: string; password: string; role: UserRole }) => Promise<void>
}) {
  const t = useT(usersCopy)
  const c = useT(commonCopy)
  const sh = useT(shellCopy)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRole>('viewer')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim()) return setError(t('errUsernameRequired'))
    if (password.length < MIN_PASSWORD) return setError(t('errPasswordShort', { n: MIN_PASSWORD }))
    setSaving(true)
    setError(null)
    try {
      await onCreate({ username: username.trim(), password, role })
      setUsername(''); setPassword(''); setRole('viewer')
      onOpenChange(false)
    } catch (err) {
      setError((err as ApiError).message || t('errCreate'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('dlgAddTitle')}</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-5 px-6 pb-6" onSubmit={submit}>
          <FieldGroup className="gap-4">
            <Field className="gap-2">
              <FieldLabel htmlFor="new-username">{t('fieldAccount')}</FieldLabel>
              <Input
                id="new-username"
                autoComplete="off"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </Field>
            <Field className="gap-2">
              <FieldLabel htmlFor="new-password">{t('fieldInitialPassword')}</FieldLabel>
              {/* 明文框而不是 password 框：这是管理员替别人设的初始密码，要能核对着
                  念给对方；对方登录后自己改。 */}
              <Input
                id="new-password"
                autoComplete="off"
                placeholder={t('minChars', { n: MIN_PASSWORD })}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <Field className="gap-2">
              <FieldLabel htmlFor="new-role">{t('fieldRole')}</FieldLabel>
              <Select value={role} onValueChange={(v) => setRole(v as UserRole)}>
                <SelectTrigger id="new-role" className="w-full">
                  <SelectValue>{roleName(sh, role)}</SelectValue>
                </SelectTrigger>
                <SelectContent align="start" className="w-auto min-w-72 max-w-96">
                  {roles.map((r) => (
                    <SelectItem key={r} value={r}>
                      <span className="flex flex-col gap-0.5">
                        <span>{roleName(sh, r)}</span>
                        <span className="text-xs whitespace-normal text-muted-foreground">{roleHint(sh, r)}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {c('cancel')}
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && (
                <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
              )}
              {t('create')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ResetPasswordDialog({
  username, onOpenChange, onReset,
}: {
  username: string | null
  onOpenChange: (v: boolean) => void
  onReset: (password: string) => Promise<void>
}) {
  const t = useT(usersCopy)
  const c = useT(commonCopy)
  const [password, setPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (password.length < MIN_PASSWORD) return setError(t('errPasswordShort', { n: MIN_PASSWORD }))
    setSaving(true)
    setError(null)
    try {
      await onReset(password)
      setPassword('')
      onOpenChange(false)
    } catch (err) {
      setError((err as ApiError).message || t('errReset'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={username !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('dlgResetTitle', { name: username ?? '' })}</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-5 px-6 pb-6" onSubmit={submit}>
          <Field className="gap-2">
            <FieldLabel htmlFor="reset-password">{t('fieldNewPassword')}</FieldLabel>
            <Input
              id="reset-password"
              autoComplete="off"
              placeholder={t('minChars', { n: MIN_PASSWORD })}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <p className="text-xs text-muted-foreground">
            {t('resetNotice')}
          </p>

          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {c('cancel')}
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && (
                <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-4 animate-spin" />
              )}
              {t('reset')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default UsersPage
