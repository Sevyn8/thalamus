import { Route, Routes } from 'react-router'

import { AuthBoundary } from '../auth/AuthBoundary'
import { Shell } from '../components/Shell'
import { Audit } from './Audit'
import { BatchUpload } from './BatchUpload'
import { Callback } from './Callback'
import { CanonicalExplorer } from './CanonicalExplorer'
import { Connect } from './Connect'
import { ConnectorHealth } from './ConnectorHealth'
import { Credentials } from './Credentials'
import { Dashboard } from './Dashboard'
import { DataQuality } from './DataQuality'
import { DevLogin } from './DevLogin'
import { IngestionRuns } from './IngestionRuns'
import { NotificationsRoute } from './NotificationsRoute'
import { OnboardSquare } from './OnboardSquare'
import { SchemaDrift } from './SchemaDrift'
import { SourceTemplates } from './SourceTemplates'
import { Sources } from './Sources'
import { TemplateDetail } from './TemplateDetail'

// Router-agnostic route registry. /dev/login is public (bare, no Shell). Everything under
// AuthBoundary renders inside the Shell. Ingestion Runs (GET /api/v1/runs, bronze/D111) and
// Canonical Explorer (GET /api/v1/canonical/store-sku-positions) are wired to real endpoints.
// Connector Health is wired to GET /api/v1/connector-health (Phase B, D116) under a premium lock
// (faded real content). Schema Drift and Credentials are premium-locked lock-message-only surfaces.
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/dev/login" element={<DevLogin />} />
      {/* Auth0 redirect target (real mode); public, outside AuthBoundary. */}
      <Route path="/callback" element={<Callback />} />
      <Route element={<AuthBoundary />}>
        <Route element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="/templates" element={<SourceTemplates />} />
          <Route path="/templates/:templateId" element={<TemplateDetail />} />
          <Route path="/templates/:templateId/upload" element={<BatchUpload />} />
          <Route path="/pipelines" element={<Sources />} />
          <Route path="/data-quality" element={<DataQuality />} />
          <Route path="/schema-drift" element={<SchemaDrift />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/notifications" element={<NotificationsRoute />} />
          <Route path="/connect" element={<Connect />} />
          {/* Onboard Square (e2e slice steps 6-7) - provisions the api-source + ACTIVE snapshot
              template via the real BFF, then views connector health. Does not fire a pull. */}
          <Route path="/onboard-square" element={<OnboardSquare />} />
          {/* Ingestion Runs — real (GET /api/v1/runs over bronze, D111). */}
          <Route path="/ingestion-runs" element={<IngestionRuns />} />
          {/* Canonical Explorer — real (GET /api/v1/canonical/store-sku-positions). */}
          <Route path="/canonical" element={<CanonicalExplorer />} />
          {/* Connector Health — real (GET /api/v1/connector-health, D116 Phase B). */}
          <Route path="/connector-health" element={<ConnectorHealth />} />
          <Route path="/credentials" element={<Credentials />} />
        </Route>
      </Route>
    </Routes>
  )
}
