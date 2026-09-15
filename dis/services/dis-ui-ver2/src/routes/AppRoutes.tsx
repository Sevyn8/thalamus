import { Route, Routes } from 'react-router'

import { devRoutes } from '@devAuthSeam'
import { AuthBoundary } from '../auth/AuthBoundary'
import { Shell } from '../components/Shell'
import { Audit } from './Audit'
import { BatchUpload } from './BatchUpload'
import { Callback } from './Callback'
import { CanonicalExplorer } from './CanonicalExplorer'
import { Connect } from './Connect'
import { CsvRoute } from './connect/CsvRoute'
import { CloverCallback } from './connect/clover/CloverCallback'
import { CloverJourney } from './connect/clover/CloverJourney'
import { CloverLaunch } from './connect/clover/CloverLaunch'
import { SquareCallback } from './connect/square/SquareCallback'
import { SquareJourney } from './connect/square/SquareJourney'
import { ConnectorHealth } from './ConnectorHealth'
import { Credentials } from './Credentials'
import { Dashboard } from './Dashboard'
import { DataQuality } from './DataQuality'
import { IngestionRuns } from './IngestionRuns'
import { NotificationsRoute } from './NotificationsRoute'
import { OnboardSquare } from './OnboardSquare'
import { SchemaDrift } from './SchemaDrift'
import { SignIn } from './SignIn'
import { SourceTemplates } from './SourceTemplates'
import { Sources } from './Sources'
import { TemplateDetail } from './TemplateDetail'

// Router-agnostic route registry. ONE registry for every build; the only variable part is
// devRoutes, which '@devAuthSeam' resolves at build time - the dev variant contributes
// /dev/login (public, bare, no Shell) and the production variant contributes nothing, so no
// production chunk carries the persona picker. Everything under
// AuthBoundary renders inside the Shell. Ingestion Runs (GET /api/v1/runs, over bronze) and
// Canonical Explorer (GET /api/v1/canonical/store-sku-positions) are wired to real endpoints.
// Connector Health is wired to GET /api/v1/connector-health under a premium lock
// (faded real content). Schema Drift and Credentials are premium-locked lock-message-only surfaces.
export function AppRoutes() {
  return (
    <Routes>
      {devRoutes}
      {/* Production sign-in entry point; public, outside AuthBoundary. */}
      <Route path="/signin" element={<SignIn />} />
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
          {/* Manual CSV journey: the UNCHANGED CsvWizard hosted at its own route. */}
          <Route path="/connect/csv" element={<CsvRoute />} />
          {/* Square journey (S3): register -> connect (OAuth) -> first pull. */}
          <Route path="/connect/square" element={<SquareJourney />} />
          {/* Square OAuth callback (registered Square redirect URL). Inside AuthBoundary so the
              Bearer is present; App.tsx skipRedirectCallback keeps the Auth0 SDK off its query. */}
          <Route path="/connectors/square/callback" element={<SquareCallback />} />
          {/* Clover journey (C3): register -> install -> connect (OAuth) -> first pull. */}
          <Route path="/connect/clover" element={<CloverJourney />} />
          {/* Registered Clover redirect URI; forwards to launch preserving the query. */}
          <Route path="/connectors/clover/callback" element={<CloverCallback />} />
          {/* The divert-catcher (D4). Also the merchant-initiated App Market landing. */}
          <Route path="/connectors/clover/launch" element={<CloverLaunch />} />
          {/* Onboard Square: DEV UTILITY (provisioning parity tool), hidden from nav. The
              customer journey is /connect/square. */}
          <Route path="/onboard-square" element={<OnboardSquare />} />
          {/* Ingestion Runs — real (GET /api/v1/runs over bronze). */}
          <Route path="/ingestion-runs" element={<IngestionRuns />} />
          {/* Canonical Explorer — real (GET /api/v1/canonical/store-sku-positions). */}
          <Route path="/canonical" element={<CanonicalExplorer />} />
          {/* Connector Health — real (GET /api/v1/connector-health). */}
          <Route path="/connector-health" element={<ConnectorHealth />} />
          <Route path="/credentials" element={<Credentials />} />
        </Route>
      </Route>
    </Routes>
  )
}
