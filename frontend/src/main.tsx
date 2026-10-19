import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'
import { consumeTokenFromUrl } from './api/client.ts'

// Consume JWT from SAML redirect before rendering
// (stores in localStorage, removes from URL via history.replaceState)
consumeTokenFromUrl();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
