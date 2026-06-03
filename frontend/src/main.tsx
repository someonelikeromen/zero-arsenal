import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './router'
import { ToastStack } from './components/ToastStack'
import { ConfirmDialog } from './components/ConfirmDialog'
import { applyTheme, useUIStore } from './stores/ui'
import './index.css'

// 启动时应用持久化的主题
applyTheme(useUIStore.getState().theme)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
    <ToastStack />
    <ConfirmDialog />
  </React.StrictMode>
)
