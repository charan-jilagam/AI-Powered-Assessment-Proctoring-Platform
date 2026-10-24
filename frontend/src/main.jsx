import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@fontsource-variable/inter'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/600.css'
import './styles/app.css'
import './styles/pages.css'
import './styles/report.css'
import App from './App.jsx'
import { AuthProvider } from './lib/auth'
import { ThemeProvider } from './lib/theme'
import { UIProvider } from './ui'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <UIProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </UIProvider>
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
