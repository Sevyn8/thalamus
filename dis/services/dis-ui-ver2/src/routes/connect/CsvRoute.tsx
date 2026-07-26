import { useNavigate } from 'react-router'

import { CsvWizard } from './CsvWizard'

// The Manual CSV journey route (/connect/csv). A thin wrapper that hosts the UNCHANGED
// CsvWizard under the shared Connect page head; Back returns to the source-card grid. The
// CsvWizard itself is untouched (its onBack prop is the only seam).
export function CsvRoute() {
  const navigate = useNavigate()
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connect a Data Source</h1>
        </div>
      </div>
      <CsvWizard onBack={() => navigate('/connect')} />
    </>
  )
}
