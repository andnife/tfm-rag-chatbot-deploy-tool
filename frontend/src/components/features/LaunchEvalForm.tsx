'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  useDatasetList,
  useChatbots,
  useCalibrate,
  useCreateEntityRun,
} from '@/lib/queries'
import { ApiError } from '@/lib/api'
import { JudgeModelSelect, type JudgeSelection } from './JudgeModelSelect'

// ---- Component ------------------------------------------------------------------

interface LaunchEvalFormProps {
  /** Called with the new run's ID when a run is successfully created. */
  onLaunched: (runId: string) => void
}

export function LaunchEvalForm({ onLaunched }: LaunchEvalFormProps) {
  const { t } = useTranslation()

  // Form state
  const [datasetId, setDatasetId] = useState<string>('')
  const [chatbotId, setChatbotId] = useState<string>('')
  const [judge, setJudge] = useState<JudgeSelection>({
    credential_id: '',
    judge_model: '',
  })

  // Data
  const { data: datasets, isLoading: loadingDatasets } = useDatasetList()
  const { data: chatbots, isLoading: loadingChatbots } = useChatbots()

  // Mutations — both need datasetId to know the endpoint, but we only enable if set
  const calibrate = useCalibrate(datasetId)
  const createRun = useCreateEntityRun(datasetId)

  // Validation
  const isValid = !!datasetId && !!chatbotId && !!judge.credential_id && !!judge.judge_model
  const canCalibrateOrLaunch = isValid

  // Build shared body
  function buildBody() {
    return {
      chatbot_id: chatbotId,
      judge_credential_id: judge.credential_id,
      judge_model: judge.judge_model,
    }
  }

  function handleCalibrate() {
    if (!canCalibrateOrLaunch) return
    calibrate.mutate(buildBody(), {
      onError: (err) =>
        toast.error(err instanceof ApiError ? err.message : t('eval.launch.errorCalibrate')),
    })
  }

  function handleLaunch() {
    if (!canCalibrateOrLaunch) return
    createRun.mutate(buildBody(), {
      onSuccess: (run) => {
        toast.success(t('eval.launch.launched'))
        onLaunched(run.id)
      },
      onError: (err) =>
        toast.error(err instanceof ApiError ? err.message : t('eval.launch.errorLaunch')),
    })
  }

  const calibrateResult = calibrate.data

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold">{t('eval.launch.title')}</h2>
        <p className="text-sm text-muted-foreground">{t('eval.launch.subtitle')}</p>
      </div>

      <div className="max-w-md">
        {/* Dataset + chatbot + judge */}
        <div className="space-y-5">
          {/* Dataset */}
          <div className="flex flex-col gap-1">
            <Label>{t('eval.selectDataset')}</Label>
            <Select
              value={datasetId}
              onValueChange={setDatasetId}
              disabled={loadingDatasets}
            >
              <SelectTrigger>
                <SelectValue placeholder={t('eval.launch.selectDatasetPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {(datasets ?? []).map((ds) => (
                  <SelectItem
                    key={ds.id}
                    value={ds.id}
                    disabled={ds.status !== 'ready'}
                  >
                    <span className="flex items-center gap-2">
                      {ds.name}
                      {ds.status !== 'ready' && (
                        <Badge variant={ds.status === 'processing' ? 'info' : ds.status === 'failed' ? 'danger' : 'default'}>
                          {t(`eval.datasets.status.${ds.status}`)}
                        </Badge>
                      )}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Chatbot */}
          <div className="flex flex-col gap-1">
            <Label>{t('eval.selectChatbot')}</Label>
            <Select
              value={chatbotId}
              onValueChange={setChatbotId}
              disabled={loadingChatbots}
            >
              <SelectTrigger>
                <SelectValue placeholder={t('eval.launch.selectChatbotPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {(chatbots ?? []).map((cb) => (
                  <SelectItem key={cb.id} value={cb.id}>
                    {cb.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Judge */}
          <JudgeModelSelect value={judge} onChange={setJudge} />
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          disabled={!canCalibrateOrLaunch || calibrate.isPending}
          onClick={handleCalibrate}
        >
          {calibrate.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {t('eval.launch.calibrate')}
        </Button>
        <Button
          disabled={!canCalibrateOrLaunch || createRun.isPending}
          onClick={handleLaunch}
        >
          {createRun.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {t('eval.launch.launch')}
        </Button>
        {!isValid && (
          <span className="text-xs text-muted-foreground">
            {t('eval.launch.validationHint')}
          </span>
        )}
      </div>

      {/* Calibration result */}
      {calibrateResult && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t('eval.launch.calibrateResultTitle')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              <div>
                <span className="text-xs text-muted-foreground">
                  {t('eval.launch.sampleSize')}
                </span>
                <p className="font-medium">{calibrateResult.sample_size}</p>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">
                  {t('eval.launch.projectedTokens')}
                </span>
                <p className="font-medium">
                  {calibrateResult.projected_total.tokens.toLocaleString()}
                </p>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">
                  {t('eval.launch.projectedSeconds')}
                </span>
                <p className="font-medium">
                  {Math.round(calibrateResult.projected_total.seconds)}s
                </p>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">
                  {t('eval.launch.avgGenTokens')}
                </span>
                <p className="font-medium">
                  {calibrateResult.avg_gen_tokens.toLocaleString()}
                </p>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">
                  {t('eval.launch.avgJudgeTokens')}
                </span>
                <p className="font-medium">
                  {calibrateResult.avg_judge_tokens.toLocaleString()}
                </p>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">
                  {t('eval.launch.avgSeconds')}
                </span>
                <p className="font-medium">
                  {calibrateResult.avg_seconds.toFixed(1)}s
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
