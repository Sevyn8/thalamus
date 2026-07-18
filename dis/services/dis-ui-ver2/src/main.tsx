import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Fonts under Vite via @fontsource (dis-ui's mechanism; self-contained, no runtime Google
// Fonts fetch). The DIS V2 mockups specify IBM Plex Sans (400/500/600/700) for UI and IBM
// Plex Mono (400/500/600) for ids/metrics; index.css binds the 'IBM Plex Sans' / 'IBM Plex
// Mono' families these register.
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-sans/700.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'

import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
