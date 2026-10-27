import React from 'react';
import { AlertTriangle, CheckCircle2, Info, ShieldAlert, X } from 'lucide-react';

export type ToastKind = 'success' | 'warning' | 'error' | 'info';

export interface AppToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

interface ToastCenterProps {
  toasts: AppToastItem[];
  onDismiss: (id: number) => void;
}

export const ToastCenter: React.FC<ToastCenterProps> = ({ toasts, onDismiss }) => {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 left-4 z-50 flex flex-col gap-2 max-w-sm pointer-events-none">
      {toasts.map((t) => {
        const palette =
          t.kind === 'error'
            ? 'border-rose-500/50 bg-[#1A0D12]/95 text-rose-100'
            : t.kind === 'warning'
              ? 'border-amber-500/50 bg-[#1B160C]/95 text-amber-100'
              : t.kind === 'success'
                ? 'border-emerald-500/50 bg-[#0A1815]/95 text-emerald-100'
                : 'border-cyan-500/50 bg-[#0B1520]/95 text-cyan-100';

        const icon =
          t.kind === 'error' ? (
            <ShieldAlert className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
          ) : t.kind === 'warning' ? (
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
          ) : t.kind === 'success' ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
          ) : (
            <Info className="h-4 w-4 text-cyan-400 shrink-0 mt-0.5" />
          );

        return (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 shadow-[0_12px_36px_rgba(0,0,0,0.85)] backdrop-blur ${palette}`}
          >
            {icon}
            <div className="flex-1 min-w-0 text-xs">
              <div className="font-bold leading-snug">{t.title}</div>
              {t.detail && (
                <div className="mt-0.5 text-[11px] opacity-90 break-words leading-snug">
                  {t.detail}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => onDismiss(t.id)}
              className="rounded p-0.5 text-slate-400 hover:text-white shrink-0"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
