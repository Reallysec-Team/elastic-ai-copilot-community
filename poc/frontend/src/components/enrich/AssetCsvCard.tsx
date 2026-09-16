import { useEffect, useRef, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { CheckIcon, Download01Icon, Loading03Icon, Upload01Icon } from '@hugeicons/core-free-icons'
import { GatedButton } from '@/components/gated-button'
import { api, type ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Frame, FrameHeader, FramePanel, FrameTitle } from '@/components/reui/frame'
import { Separator } from '@/components/ui/separator'
import { Pill } from '@/components/ui/Pill'
import { useT, translate } from '@/lib/i18n'
import { assetIdentityCopy } from '@/locales/assetIdentity'
import { HintTip } from '@/components/hint-tip'

type Kind = 'assets' | 'identities'

const COLUMNS: Record<Kind, string> = {
  assets: 'name, host, ip, criticality, category, owner, department',
  identities: 'name, user, criticality, category, owner, department',
}

// Downloadable templates — headers match the backend column whitelist exactly,
// with example rows the customer overwrites. Leading BOM so Excel reads the
// Chinese as UTF-8 instead of mojibake.
function sampleFor(kind: Kind): string {
  return kind === 'assets'
    ? 'name,host,ip,criticality,category,owner,department\n' +
        translate(assetIdentityCopy, 'csvSampleAssets')
    : 'name,user,criticality,category,owner,department\n' +
        translate(assetIdentityCopy, 'csvSampleIdentities')
}

function downloadSample(kind: Kind) {
  const blob = new Blob(['﻿' + sampleFor(kind)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = kind === 'assets' ? 'rst-assets-sample.csv' : 'rst-identities-sample.csv'
  a.click()
  URL.revokeObjectURL(url)
}

function UploadRow({
  kind, label, onImported,
}: { kind: Kind; label: string; onImported?: () => void }) {
  const t = useT(assetIdentityCopy)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function onFile(file: File) {
    setBusy(true)
    setErr(null)
    setResult(null)
    try {
      const text = await file.text()
      const fn = kind === 'assets' ? api.enrichmentUploadAssets : api.enrichmentUploadIdentities
      const r = await fn(text)
      setResult(t('csvImported', { n: r.indexed, index: r.index }))
      onImported?.()
    } catch (e) {
      setErr((e as ApiError).message || t('csvErrImport'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-foreground">{label}</p>
          <p className="font-mono text-xs text-muted-foreground">
            {t('csvColumns', { cols: COLUMNS[kind] })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => downloadSample(kind)}>
            <HugeiconsIcon icon={Download01Icon} strokeWidth={2} className="size-3.5" />
            {t('csvDownloadSample')}
          </Button>
          {/* A <button> inside a <label> swallows the label's activation, so the
              picker is opened from a ref — same pattern as LicensePage. */}
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void onFile(f)
              e.target.value = '' // allow re-upload of the same file
            }}
          />
          <GatedButton gate="admin" variant="outline" size="sm" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? <HugeiconsIcon icon={Loading03Icon} strokeWidth={2} className="size-3.5 animate-spin" /> : <HugeiconsIcon icon={Upload01Icon} strokeWidth={2} className="size-3.5" />}
            {t('csvUpload')}
          </GatedButton>
        </div>
      </div>
      {result && (
        <p className="inline-flex items-center gap-1 text-xs text-success">
          <HugeiconsIcon icon={CheckIcon} strokeWidth={2} className="size-3.5" /> {result}
        </p>
      )}
      {err && <p className="text-xs text-destructive">{err}</p>}
    </div>
  )
}

export function AssetCsvCard({ onImported }: { onImported?: () => void } = {}) {
  const t = useT(assetIdentityCopy)
  const [sources, setSources] = useState<Record<string, boolean> | null>(null)

  useEffect(() => {
    api.enrichmentStatus().then((r) => setSources(r.sources)).catch(() => {})
  }, [])

  return (
    <Frame dense className="flex w-full min-w-0 flex-col">
      <FrameHeader>
        <FrameTitle className="flex items-center gap-1.5 text-balance">
          {t('csvTitle')}
          <HintTip text={t('csvDesc')} />
        </FrameTitle>
      </FrameHeader>
      <FramePanel className="flex flex-col gap-2.5">
        {sources && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">{t('csvSources')}</span>
            {Object.entries(sources).map(([k, v]) => (
              <Pill key={k} tone={v ? 'blue' : 'gray'}>
                {k} {v ? t('csvAvailable') : t('csvUnavailable')}
              </Pill>
            ))}
          </div>
        )}
        <UploadRow kind="assets" label={t('csvAssetsLabel')} onImported={onImported} />
        <Separator />
        <UploadRow kind="identities" label={t('csvIdentitiesLabel')} onImported={onImported} />
      </FramePanel>
    </Frame>
  )
}
