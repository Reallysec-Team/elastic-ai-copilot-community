import { createFileRoute } from '@tanstack/react-router'

import { AssetIdentityPage } from '@/pages/AssetIdentityPage'

export const Route = createFileRoute('/_app/asset-identity')({
  component: AssetIdentityPage,
})
