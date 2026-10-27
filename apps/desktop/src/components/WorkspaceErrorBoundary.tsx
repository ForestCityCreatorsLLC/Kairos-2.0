import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface WorkspaceErrorBoundaryProps {
  workspaceName: string;
  containerClassName?: string;
  resetKey?: string | number | boolean;
  children: React.ReactNode;
}

interface WorkspaceErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

/**
 * Isolates render exceptions inside an individual KAIROS 2.0 workspace or drawer
 * so the TopBar Voice Co-Pilot, Left Sidebar, and sibling tabs remain live.
 */
export class WorkspaceErrorBoundary extends React.Component<
  WorkspaceErrorBoundaryProps,
  WorkspaceErrorBoundaryState
> {
  constructor(props: WorkspaceErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, errorMessage: '' };
  }

  static getDerivedStateFromError(error: unknown): WorkspaceErrorBoundaryState {
    const msg = error instanceof Error ? error.message : String(error || 'Unexpected UI error');
    return { hasError: true, errorMessage: msg };
  }

  componentDidUpdate(prevProps: WorkspaceErrorBoundaryProps): void {
    if (
      this.state.hasError &&
      (prevProps.workspaceName !== this.props.workspaceName ||
        prevProps.resetKey !== this.props.resetKey)
    ) {
      this.setState({ hasError: false, errorMessage: '' });
    }
  }

  private handleReset = (): void => {
    this.setState({ hasError: false, errorMessage: '' });
  };

  render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    const wrapperCls =
      this.props.containerClassName ||
      'flex-1 flex min-w-0 items-center justify-center p-6 bg-kairos-bg';

    return (
      <div className={wrapperCls}>
        <div className="max-w-md w-full rounded-2xl border border-rose-500/40 bg-kairos-panel p-5 space-y-3 shadow-xl">
          <div className="flex items-center gap-2 text-sm font-bold text-rose-300">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{this.props.workspaceName} Isolated Render Guard</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            An unexpected UI exception was caught in <strong>{this.props.workspaceName}</strong>.
            Your Canopy Vault files and KAIROS Core services remain unaffected.
          </p>
          {this.state.errorMessage && (
            <div className="rounded-lg border border-kairos-border bg-kairos-bg px-3 py-2 font-mono text-[11px] text-rose-200 break-words">
              {this.state.errorMessage}
            </div>
          )}
          <div className="flex justify-end">
            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3.5 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-400 transition"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Recover {this.props.workspaceName}
            </button>
          </div>
        </div>
      </div>
    );
  }
}
