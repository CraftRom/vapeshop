import React from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { registerGlobalClientLogging } from './logger'
import './styles.css'

registerGlobalClientLogging()

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
