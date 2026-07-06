import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

interface Props {
  children: ReactNode
  fallbackTitle?: string
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

const isDev = process.env.NODE_ENV !== 'production'

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo })

    // In production, log to incidents endpoint
    if (!isDev) {
      try {
        fetch('/api/incidents', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            status_code: 500,
            error_code: 'FRONTEND_ERROR',
            message: `${error.name}: ${error.message}`,
            detail: {
              stack: error.stack,
              componentStack: errorInfo.componentStack,
              path: window.location.pathname,
            },
          }),
        }).catch(() => { /* best effort */ })
      } catch { /* best effort */ }
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  render() {
    if (this.state.hasError) {
      const { error, errorInfo } = this.state

      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
          <Card className="max-w-lg w-full">
            <CardContent className="p-6 space-y-4">
              <div className="text-center">
                <h2 className="text-xl font-semibold text-gray-900">
                  {this.props.fallbackTitle ?? 'Algo salió mal'}
                </h2>
                <p className="text-sm text-gray-500 mt-2">
                  Se ha producido un error inesperado en la aplicación.
                </p>
              </div>

              {isDev && error && (
                <div className="border border-accent-border bg-accent-subtle rounded-md p-4 text-sm text-accent">
                  <p className="font-mono font-semibold">
                    {error.name}: {error.message}
                  </p>
                  {error.stack && (
                    <pre className="mt-2 text-xs overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                      {error.stack}
                    </pre>
                  )}
                  {errorInfo?.componentStack && (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-xs font-semibold">
                        Component Stack
                      </summary>
                      <pre className="mt-1 text-xs overflow-x-auto whitespace-pre-wrap max-h-32 overflow-y-auto">
                        {errorInfo.componentStack}
                      </pre>
                    </details>
                  )}
                </div>
              )}

              {!isDev && (
                <p className="text-xs text-gray-400 text-center">
                  El error ha sido registrado. Si persiste, contacta al administrador.
                </p>
              )}

              <div className="flex justify-center gap-2">
                <Button variant="outline" onClick={this.handleReset}>
                  Reintentar
                </Button>
                <Button onClick={() => window.location.href = '/'}>
                  Ir al Inicio
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )
    }

    return this.props.children
  }
}
