import { createFileRoute } from '@tanstack/react-router'

import { UsersPage } from '@/pages/UsersPage'

export const Route = createFileRoute('/_app/users')({
  component: UsersPage,
})
