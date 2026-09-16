import { createFileRoute } from '@tanstack/react-router'

import { FieldDictPage } from '@/pages/FieldDictPage'

export const Route = createFileRoute('/_app/field-dictionary')({
  component: FieldDictPage,
})
