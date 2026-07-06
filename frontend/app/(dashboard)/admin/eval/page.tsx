"use client";

import { useTranslation } from "react-i18next";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AppShell } from "@/components/layout/AppShell";
import { SuperadminGuard } from "@/components/SuperadminGuard";
import { EvalDatasetsTab } from "@/components/features/EvalDatasetsTab";
import { EvalRunsTab } from "@/components/features/EvalRunsTab";

function EvalPageInner() {
  const { t } = useTranslation();

  return (
    <AppShell title={t('eval.dashboard.title')}>
      <div className="flex flex-col gap-6">
        <div>
          <p className="mt-1 text-muted-foreground">
            {t('eval.dashboard.subtitle')}
          </p>
        </div>

        <Tabs defaultValue="evaluaciones" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="datasets">{t('eval.datasets.title')}</TabsTrigger>
            <TabsTrigger value="evaluaciones">{t('eval.evaluations.title')}</TabsTrigger>
          </TabsList>

          <TabsContent value="datasets" className="mt-6">
            <EvalDatasetsTab />
          </TabsContent>

          <TabsContent value="evaluaciones" className="mt-6">
            <EvalRunsTab />
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}

export default function EvalPage() {
  return (
    <SuperadminGuard>
      <EvalPageInner />
    </SuperadminGuard>
  );
}
