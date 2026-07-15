import { Suspense } from "react";

import IntegrationControlCenter from "@/components/settings/integration-control-center";

export default function IntegrationsPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#f8f6f0]" />}>
      <IntegrationControlCenter />
    </Suspense>
  );
}
