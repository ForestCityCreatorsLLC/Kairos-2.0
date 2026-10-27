import React, { useEffect, useState } from 'react';
import {
  Brain,
  Check,
  CircleAlert,
  CircleCheck,
  CircleX,
  Copy,
  Cpu,
  Database,
  FileCheck2,
  Gauge,
  GitBranch,
  KeyRound,
  Mic,
  RefreshCw,
  ShieldCheck,
  SquareTerminal,
  Volume2,
  Zap,
} from 'lucide-react';
import {
  EnvVerificationReport,
  HermesStatusSnapshot,
  VoiceStateSnapshot,
  kairosApi,
} from '../../api/client.ts';
import { ToastKind } from '../../components/ToastCenter.tsx';

interface SettingsWorkspaceProps {
  refreshTick?: number;
  externalVerifySignal?: { seq: number; live: boolean };
  ttsEnabled?: boolean;
  onToggleTtsEnabled?: () => void;
  neuralTts?: boolean;
  onChangeNeuralTts?: (val: boolean) => void;
  ttsVoice?: string;
  onChangeTtsVoice?: (voice: string) => void;
  onVaultMutated?: () => void;
  onNotify?: (kind: ToastKind, title: string, detail?: string) => void;
}

const VOICE_PRESETS = ['Kore', 'Puck', 'Aoede', 'Charon', 'Fenrir'];

export const SettingsWorkspace: React.FC<SettingsWorkspaceProps> = ({
  refreshTick = 0,
  externalVerifySignal,
  ttsEnabled = true,
  onToggleTtsEnabled,
  neuralTts = true,
  onChangeNeuralTts,
  ttsVoice = 'Kore',
  onChangeTtsVoice,
  onVaultMutated,
  onNotify,
}) => {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof kairosApi.getHealth>> | null>(
    null
  );
  const [apiReport, setApiReport] = useState<EnvVerificationReport | null>(null);
  const [hermesStatus, setHermesStatus] = useState<HermesStatusSnapshot | null>(null);
  const [voiceState, setVoiceState] = useState<VoiceStateSnapshot | null>(null);
  const [cogTelemetry, setCogTelemetry] = useState<Awaited<
    ReturnType<typeof kairosApi.getCognitiveVoiceTelemetry>
  > | null>(null);
  const [kvHandshake, setKvHandshake] = useState<Awaited<
    ReturnType<typeof kairosApi.verifyLmStudioKvCache>
  > | null>(null);
  const [verifyingKv, setVerifyingKv] = useState(false);
  const [refreshingDiag, setRefreshingDiag] = useState(false);
  const [hermesQuickFact, setHermesQuickFact] = useState('');
  const [hermesBanner, setHermesBanner] = useState('');
  const [testingLive, setTestingLive] = useState(false);
  const [repoName, setRepoName] = useState('KAIROS 2.0');
  const [gitOutput, setGitOutput] = useState('');
  const [syncingGit, setSyncingGit] = useState<'' | 'status' | 'pull'>('');
  const [syncingOrgCatalog, setSyncingOrgCatalog] = useState(false);
  const [orgCatalogSummary, setOrgCatalogSummary] = useState('');
  const [syncSummary, setSyncSummary] = useState('');
  const [syncResult, setSyncResult] = useState('');
  const [syncingVault, setSyncingVault] = useState(false);
  const [copiedMcp, setCopiedMcp] = useState(false);

  const loadDiagnostics = async () => {
    await Promise.all([
      kairosApi
        .getHealth()
        .then(setHealth)
        .catch(() => {}),
      kairosApi
        .verifyEnvApis(false)
        .then(setApiReport)
        .catch(() => {}),
      kairosApi
        .getHermesStatus()
        .then(setHermesStatus)
        .catch(() => {}),
      kairosApi
        .getVoiceState()
        .then(setVoiceState)
        .catch(() => {}),
      kairosApi
        .getCognitiveVoiceTelemetry()
        .then(setCogTelemetry)
        .catch(() => {}),
    ]);
  };

  useEffect(() => {
    loadDiagnostics().catch(() => {});
  }, [refreshTick]);

  useEffect(() => {
    if (!externalVerifySignal || externalVerifySignal.seq === 0) return;
    setTestingLive(true);
    kairosApi
      .verifyEnvApis(externalVerifySignal.live)
      .then(setApiReport)
      .catch((err) => {
        const msg = err instanceof Error ? err.message : 'Unable to verify APIs';
        onNotify?.('error', 'API Verification Failed', msg);
      })
      .finally(() => setTestingLive(false));
  }, [externalVerifySignal?.seq]);

  const handleRefreshDiagnostics = async () => {
    if (refreshingDiag) return;
    setRefreshingDiag(true);
    try {
      await loadDiagnostics();
    } finally {
      setRefreshingDiag(false);
    }
  };

  const handleRunLiveVerification = async () => {
    setTestingLive(true);
    try {
      const report = await kairosApi.verifyEnvApis(true);
      setApiReport(report);
      onNotify?.(
        'success',
        'Live API Verification Complete',
        `${report.configured_count}/${report.total_count} integrations configured`
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Live connectivity test failed';
      onNotify?.('error', 'Live API Verification Failed', msg);
    } finally {
      setTestingLive(false);
    }
  };

  const handleVerifyKvCache = async () => {
    if (verifyingKv) return;
    setVerifyingKv(true);
    try {
      const res = await kairosApi.verifyLmStudioKvCache();
      setKvHandshake(res);
      const latestTel = await kairosApi.getCognitiveVoiceTelemetry().catch(() => null);
      if (latestTel) setCogTelemetry(latestTel);
      if (res.online) {
        onNotify?.(
          'success',
          'LM Studio KV Prefix Verified',
          `Model ${res.model} • Warmed TTFT ${res.warmed_ttft_ms} ms`
        );
      } else {
        onNotify?.(
          'warning',
          'LM Studio Offline / Unreachable',
          res.error || 'Start LM Studio on 127.0.0.1:1234 to benchmark KV prefix cache.'
        );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'KV cache verification failed';
      onNotify?.('error', 'KV Cache Handshake Failed', msg);
    } finally {
      setVerifyingKv(false);
    }
  };

  const handlePatchVoiceSidecar = async (
    patch: Parameters<typeof kairosApi.updateVoiceConfig>[0]
  ) => {
    try {
      const updated = await kairosApi.updateVoiceConfig(patch);
      setVoiceState(updated);
    } catch {
      onNotify?.(
        'warning',
        'Voice Sidecar Offline',
        'Start start_kairos_2.bat so Voice Sidecar (:8421) is online.'
      );
    }
  };

  const handleRetainQuickFact = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hermesQuickFact.trim()) return;
    try {
      const res = await kairosApi.retainHermesMemory({
        fact: hermesQuickFact.trim(),
        target: 'memory',
        section: 'System Preferences & Operator Rules',
        is_private: /#private\b/i.test(hermesQuickFact),
      });
      setHermesQuickFact('');
      setHermesBanner(`Saved to ${res.rel_path}`);
      window.setTimeout(() => setHermesBanner(''), 3000);
      onVaultMutated?.();
      kairosApi
        .getHermesStatus()
        .then(setHermesStatus)
        .catch(() => {});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to retain Hermes fact';
      onNotify?.('error', 'Hermes Retain Failed', msg);
    }
  };

  const handleGitSync = async (action: 'status' | 'pull') => {
    if (syncingGit) return;
    if (!repoName.trim()) {
      onNotify?.('warning', 'Repository Required', 'Enter KAIROS 2.0 or a folder name under 04_Resources/Code_and_Research.');
      return;
    }
    setSyncingGit(action);
    try {
      const res = await kairosApi.syncGitHubRepo(repoName.trim(), action);
      setGitOutput(res.output || res.message || JSON.stringify(res));
      if (action === 'pull') {
        onVaultMutated?.();
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : `Git ${action} failed`;
      setGitOutput(msg);
      onNotify?.('error', `Git ${action.toUpperCase()} Failed`, msg);
    } finally {
      setSyncingGit('');
    }
  };

  const handleSyncFccOrgCatalog = async () => {
    if (syncingOrgCatalog) return;
    setSyncingOrgCatalog(true);
    try {
      const res = await kairosApi.syncGitHubOrgToVault('ForestCityCreatorsLLC');
      setOrgCatalogSummary(
        `Synced ${res.repo_count} repo(s) (${res.private_count} private) → ${res.catalog_rel_path}`
      );
      onVaultMutated?.();
      onNotify?.(
        'success',
        'Synced ForestCityCreatorsLLC GitHub Catalog',
        `${res.repo_count} repo(s) indexed in ${res.catalog_rel_path}`
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'GitHub organization sync failed';
      onNotify?.('error', 'GitHub Org Sync Failed', msg);
    } finally {
      setSyncingOrgCatalog(false);
    }
  };

  const handleVaultCodeSync = async (e: React.FormEvent) => {
    e.preventDefault();
    if (syncingVault) return;
    setSyncingVault(true);
    try {
      const res = await kairosApi.syncCodeChangesToVault(syncSummary.trim());
      setSyncSummary('');
      setSyncResult(
        res.ledger_updated
          ? `Updated ${res.ledger_rel_path} (${res.tracked_file_count} files tracked: +${res.added.length} ~${res.modified.length} -${res.deleted.length})`
          : `Canopy Vault already in sync (${res.tracked_file_count} tracked files verified)`
      );
      onVaultMutated?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Vault code sync failed';
      onNotify?.('error', 'Vault Code Sync Failed', msg);
    } finally {
      setSyncingVault(false);
    }
  };

  const handleCopyMcpSnippet = async () => {
    try {
      await navigator.clipboard.writeText(mcpSnippet);
      setCopiedMcp(true);
      window.setTimeout(() => setCopiedMcp(false), 2200);
      onNotify?.('info', 'Copied MCP Config', 'second_brain_mcp JSON copied to clipboard');
    } catch {
      onNotify?.('warning', 'Clipboard Unavailable', 'Select and copy the JSON block manually.');
    }
  };

  const resolvedRepoRoot = (
    health?.project_root || 'C:\\Users\\igxxg\\OneDrive\\Documents\\GitHub\\Kairos-2.0'
  ).replace(/\//g, '\\');

  const mcpSnippet = JSON.stringify(
    {
      mcpServers: {
        second_brain_mcp: {
          command: `${resolvedRepoRoot}\\.venv\\Scripts\\python.exe`,
          args: ['-m', 'services.kairos_core.mcp_server'],
          cwd: resolvedRepoRoot,
        },
      },
    },
    null,
    2
  );

  const renderStatusBadge = (status: string) => {
    if (
      status === 'verified' ||
      status === 'configured' ||
      status === 'ready' ||
      status === 'live_ok'
    ) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 border border-emerald-500/35 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
          <CircleCheck className="h-3 w-3" /> {status.toUpperCase()}
        </span>
      );
    }
    if (
      status === 'warning' ||
      status === 'optional' ||
      status === 'optional_missing' ||
      status === 'offline'
    ) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 border border-amber-500/35 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
          <CircleAlert className="h-3 w-3" /> {status.toUpperCase()}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/15 border border-rose-500/35 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
        <CircleX className="h-3 w-3" /> {status.toUpperCase()}
      </span>
    );
  };

  const memoryBulletsCount = (hermesStatus?.memory_body || '')
    .split(/\r?\n/)
    .filter((ln) => ln.trim().startsWith('- ')).length;

  return (
    <div className="flex-1 overflow-y-auto p-6 bg-kairos-bg space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-base font-bold text-white">
            KAIROS 2.0 System, Cognitive Voice VRAM, Hermes Continuity, `.env` APIs &amp; MCP Configuration
          </h1>
          <p className="text-xs text-slate-400">
            Local-first Canopy Vault OS diagnostics, 16 GB GPU VRAM envelope &amp; KV prefix cache
            telemetry, spoken Voice Co-Pilot controls (`:8421`), Hermes memory, and
            `second_brain_mcp` stdio bridge.
          </p>
        </div>

        <button
          type="button"
          disabled={refreshingDiag}
          onClick={handleRefreshDiagnostics}
          title="Refresh health, Voice Sidecar, 16 GB VRAM budget & API diagnostics"
          className="flex items-center gap-1.5 rounded-lg border border-kairos-border bg-kairos-panel px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-kairos-card disabled:opacity-50"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${refreshingDiag ? 'animate-spin text-emerald-300' : ''}`}
          />
          Refresh Diagnostics
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-1.5">
          <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
            <Database className="h-4 w-4" /> Obsidian Vault (`Vault_Root`)
          </div>
          <div className="font-mono text-xs text-white break-all">
            {health?.vault_path ||
              'C:\\Users\\igxxg\\OneDrive\\Documents\\FCC Business Docs\\Canopy Vault'}
          </div>
          <div className="text-[11px] text-slate-400">
            SQLite WAL + FTS5 Shadow Index: `_System/Cache/vault_index.sqlite`
          </div>
        </div>

        <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-1.5">
          <div className="flex items-center gap-2 text-xs font-bold text-cyan-300">
            <Cpu className="h-4 w-4" /> Dual-AI Router (`Auto` + Live Web Grounding)
          </div>
          <div className="text-xs text-white">
            Local Brain:{' '}
            <span className="font-mono text-emerald-300">
              {health?.lmstudio_model || 'gemma-4'}
            </span>{' '}
            ({health?.lmstudio_url || 'http://127.0.0.1:1234/v1'})
          </div>
          <div className="text-xs text-white">
            Cloud Brain:{' '}
            <span className="font-mono text-cyan-300">
              {health?.gemini_configured
                ? `Gemini Connected (${health?.gemini_model || 'gemini-2.5-flash'})`
                : 'GEMINI_API_KEY not set (Local Fallback)'}
            </span>
          </div>
        </div>

        <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-1.5">
          <div className="flex items-center gap-2 text-xs font-bold text-amber-300">
            <ShieldCheck className="h-4 w-4" /> Hard Privacy Firewall
          </div>
          <p className="text-xs text-slate-300">
            Notes in `03_Personal/Finance/` or tagged `#private` are strictly locked to Local{' '}
            `Gemma 4` + local speech and NEVER fail over to external cloud APIs.
          </p>
        </div>
      </div>

      {/* Cognitive Voice Architecture, 16 GB VRAM Envelope & LM Studio KV Prefix Pinning */}
      <div className="rounded-xl border border-emerald-500/35 bg-kairos-panel p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
            <Gauge className="h-4 w-4" /> Cognitive Voice Architecture &amp; 16 GB GPU VRAM Envelope
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {cogTelemetry && (
              <span
                className={`rounded-full border px-2.5 py-0.5 text-[10px] font-semibold font-mono ${
                  cogTelemetry.vram_envelope.within_vram_ceiling
                    ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                    : 'border-rose-500/40 bg-rose-500/15 text-rose-300'
                }`}
              >
                {cogTelemetry.vram_envelope.full_stack_budget_gb} GB /{' '}
                {cogTelemetry.vram_envelope.gpu_envelope_gb} GB (DWM Headroom:{' '}
                {cogTelemetry.vram_envelope.dwm_safety_headroom_gb} GB)
              </span>
            )}
            <button
              type="button"
              disabled={verifyingKv}
              onClick={handleVerifyKvCache}
              className="flex items-center gap-1.5 rounded-lg border border-cyan-500/45 bg-cyan-500/15 px-2.5 py-1 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50"
            >
              <Zap className="h-3.5 w-3.5" />
              {verifyingKv ? 'Testing KV Prefix...' : 'Verify LM Studio KV Cache'}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
          <div className="rounded-lg border border-kairos-border bg-kairos-bg p-2.5 space-y-0.5">
            <div className="text-[10px] uppercase text-slate-400">Resident / Ceiling</div>
            <div className="font-mono text-emerald-300 font-semibold">
              {cogTelemetry?.vram_envelope.active_resident_vram_gb ?? 9.56} GB active • ≤{' '}
              {cogTelemetry?.vram_envelope.vram_ceiling_gb ?? 11.86} GB cap
            </div>
          </div>
          <div className="rounded-lg border border-kairos-border bg-kairos-bg p-2.5 space-y-0.5">
            <div className="text-[10px] uppercase text-slate-400">LM Studio KV Prefix</div>
            <div className="font-mono text-cyan-300 font-semibold">
              {cogTelemetry?.kv_prefix_pinned !== false ? 'messages[0] Pinned' : 'Unpinned'} • TTFT{' '}
              {cogTelemetry?.local_kv_stats.last_ttft_ms ?? 0} ms
            </div>
          </div>
          <div className="rounded-lg border border-kairos-border bg-kairos-bg p-2.5 space-y-0.5">
            <div className="text-[10px] uppercase text-slate-400">Episodic Vector Store</div>
            <div className="font-mono text-purple-300 font-semibold">
              CPU ONNX ({cogTelemetry?.episodic_memory.gpu_vram_mb ?? 0} MB GPU) •{' '}
              {cogTelemetry?.episodic_memory.last_query_ms ?? 0} ms
            </div>
          </div>
          <div className="rounded-lg border border-kairos-border bg-kairos-bg p-2.5 space-y-0.5">
            <div className="text-[10px] uppercase text-slate-400">Speculative Circuit Breaker</div>
            <div className="font-mono text-amber-300 font-semibold">
              Lag {cogTelemetry?.lag_threshold_sec ?? 0.5}s • Cloud{' '}
              {cogTelemetry?.cloud_circuit_breaker_sec ?? 2.2}s
            </div>
          </div>
        </div>

        {cogTelemetry && cogTelemetry.voice_tools.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="text-slate-400">Shielded Voice Tools (`cancel_on_interruption=False`):</span>
            {cogTelemetry.voice_tools.map((tName) => (
              <span
                key={tName}
                className="rounded border border-emerald-500/30 bg-kairos-bg px-2 py-0.5 font-mono text-[10px] text-emerald-300"
              >
                {tName}
              </span>
            ))}
          </div>
        )}

        {kvHandshake && (
          <div
            className={`rounded-lg border px-3 py-2 text-xs font-mono ${
              kvHandshake.online
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
            }`}
          >
            {kvHandshake.online
              ? `✓ LM Studio Online (${kvHandshake.model}) • Warmed TTFT: ${kvHandshake.warmed_ttft_ms} ms • <150ms SLA: ${kvHandshake.meets_150ms_sla ? 'PASS' : 'WARN'} • index[0] Pinned: ${kvHandshake.index_0_pinned}`
              : `⚠ LM Studio Offline (${kvHandshake.model}): ${kvHandshake.error || 'Unreachable'} • index[0] Pinned: ${kvHandshake.index_0_pinned}`}
          </div>
        )}
      </div>

      {/* Hermes Knowledge Continuity + Voice Co-Pilot Sidecar (:8421) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-purple-500/35 bg-kairos-panel p-4 space-y-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-purple-300">
              <Brain className="h-4 w-4" /> 🪽 Hermes Persistent Knowledge Continuity
            </div>
            <span className="rounded bg-purple-500/15 border border-purple-500/30 px-2 py-0.5 font-mono text-[10px] text-purple-200">
              {memoryBulletsCount} memories • {hermesStatus?.skill_count ?? 0} `SKL-*` skills
            </span>
          </div>
          <p className="text-[11px] text-slate-400">
            Curated bounded memory (`{hermesStatus?.memory_rel || '04_Resources/Hermes/MEMORY.md'}` &amp;{' '}
            `{hermesStatus?.user_rel || '04_Resources/Hermes/USER.md'}`) + procedural `SKL-*.md`
            skills injected automatically into KAIROS &amp; CrewAI prompts.
          </p>
          {hermesStatus && hermesStatus.skills.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {hermesStatus.skills.slice(0, 4).map((sk) => (
                <span
                  key={sk.skill_id}
                  className="rounded-md border border-kairos-border bg-kairos-bg px-2 py-0.5 text-[10px] text-cyan-300 font-mono"
                >
                  {sk.skill_id}: {sk.title.slice(0, 28)}
                </span>
              ))}
            </div>
          )}
          <form onSubmit={handleRetainQuickFact} className="flex items-center gap-2 pt-1">
            <input
              type="text"
              value={hermesQuickFact}
              onChange={(e) => setHermesQuickFact(e.target.value)}
              placeholder="Retain durable operator rule or preference in Hermes MEMORY.md..."
              className="flex-1 rounded border border-kairos-border bg-kairos-bg px-2.5 py-1.5 text-xs text-white"
            />
            <button
              type="submit"
              className="rounded-lg bg-purple-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-purple-400"
            >
              Retain
            </button>
          </form>
          {hermesBanner && (
            <div className="text-[11px] text-emerald-300 font-mono">✓ {hermesBanner}</div>
          )}
        </div>

        <div className="rounded-xl border border-emerald-500/35 bg-kairos-panel p-4 space-y-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
              <Mic className="h-4 w-4" /> Voice Co-Pilot &amp; Spoken TTS (`127.0.0.1:8421`)
            </div>
            <span className="rounded bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 font-mono text-[10px] text-emerald-300">
              Sidecar: {voiceState ? voiceState.status : 'STANDBY'}
            </span>
          </div>
          <p className="text-[11px] text-slate-400">
            Configure spoken reply voice output across TopBar, Docked Chat Drawer, and KAIROS
            Assistant Workspace.
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => onToggleTtsEnabled?.()}
              className={`flex items-center gap-1 rounded-lg border px-2.5 py-1 font-medium ${
                ttsEnabled
                  ? 'border-emerald-500/40 bg-emerald-500/20 text-emerald-200'
                  : 'border-kairos-border bg-kairos-bg text-slate-400'
              }`}
            >
              <Volume2 className="h-3.5 w-3.5" /> Spoken Replies: {ttsEnabled ? 'ON' : 'MUTED'}
            </button>

            <button
              type="button"
              onClick={() => {
                const next = !neuralTts;
                onChangeNeuralTts?.(next);
                handlePatchVoiceSidecar({ neural_tts: next });
              }}
              className={`rounded-lg border px-2.5 py-1 font-medium ${
                neuralTts
                  ? 'border-cyan-500/40 bg-cyan-500/20 text-cyan-200'
                  : 'border-kairos-border bg-kairos-bg text-slate-400'
              }`}
            >
              Gemini Neural TTS: {neuralTts ? 'ON' : 'Browser Fallback'}
            </button>

            <select
              value={ttsVoice}
              onChange={(e) => {
                onChangeTtsVoice?.(e.target.value);
                handlePatchVoiceSidecar({ tts_voice: e.target.value });
              }}
              className="rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1 text-xs text-white"
            >
              {VOICE_PRESETS.map((v) => (
                <option key={v} value={v}>
                  Voice: {v}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] pt-0.5">
            <button
              type="button"
              onClick={() =>
                handlePatchVoiceSidecar({ hands_free: !voiceState?.hands_free })
              }
              className={`rounded border px-2 py-0.5 ${
                voiceState?.hands_free
                  ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                  : 'border-kairos-border bg-kairos-bg text-slate-400'
              }`}
            >
              Hands-Free Loop: {voiceState?.hands_free ? 'ON' : 'OFF'}
            </button>
            <button
              type="button"
              onClick={() =>
                handlePatchVoiceSidecar({ wake_word_only: !voiceState?.wake_word_only })
              }
              className={`rounded border px-2 py-0.5 ${
                voiceState?.wake_word_only
                  ? 'border-amber-500/40 bg-amber-500/15 text-amber-300'
                  : 'border-kairos-border bg-kairos-bg text-slate-400'
              }`}
            >
              &ldquo;Hey Kairos&rdquo; Wake-Word Filter: {voiceState?.wake_word_only ? 'ON' : 'OFF'}
            </button>
          </div>
        </div>
      </div>

      {/* .env API Keys & Live Endpoint Verification */}
      <div className="rounded-xl border border-cyan-500/35 bg-kairos-panel p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="flex items-center gap-2 text-xs font-bold text-cyan-300">
              <KeyRound className="h-4 w-4" /> `.env` API Keys &amp; Live Endpoint Verification
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">
              All secret tokens are masked (`••••`) for security. Click{' '}
              <strong>Run Live API Connectivity Test</strong> (or run `.\verify_apis.bat` in
              PowerShell) to ping live endpoints.
            </p>
          </div>

          <div className="flex items-center gap-2">
            {apiReport && (
              <span className="rounded-lg border border-kairos-border bg-kairos-bg px-2.5 py-1 text-[11px] font-mono text-slate-300">
                {apiReport.configured_count}/{apiReport.total_count} Configured •{' '}
                {apiReport.live_tested ? 'Live Pinged' : 'Static Check'}
              </span>
            )}
            <button
              type="button"
              disabled={testingLive}
              onClick={handleRunLiveVerification}
              className="flex items-center gap-1.5 rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50"
            >
              <Zap className="h-3.5 w-3.5" />
              {testingLive ? 'Testing Live Endpoints...' : 'Run Live API Connectivity Test'}
            </button>
          </div>
        </div>

        {apiReport && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-kairos-border text-[10px] uppercase text-slate-400">
                <tr>
                  <th className="py-2 pr-3">Integration</th>
                  <th className="py-2 pr-3">`.env` Key(s)</th>
                  <th className="py-2 pr-3">Masked Value</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Diagnostic Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-kairos-border/60">
                {apiReport.checks.map((chk) => (
                  <tr key={chk.id}>
                    <td className="py-2 pr-3 font-semibold text-white">{chk.name}</td>
                    <td className="py-2 pr-3 font-mono text-[11px] text-slate-400">
                      {chk.env_keys_label ||
                        (Array.isArray(chk.env_keys) ? chk.env_keys.join(', ') : chk.env_keys)}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[11px] text-emerald-300">
                      {chk.masked_key || chk.masked}
                    </td>
                    <td className="py-2 pr-3">{renderStatusBadge(chk.status)}</td>
                    <td className="py-2 pr-3 text-[11px] text-slate-300">{chk.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Automatic Codebase -> Canopy Vault Change Sync */}
      <form
        onSubmit={handleVaultCodeSync}
        className="rounded-xl border border-emerald-500/35 bg-kairos-panel p-4 space-y-2.5"
      >
        <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
          <FileCheck2 className="h-4 w-4" /> Automatic Codebase → Canopy Vault Change Sync
        </div>
        <p className="text-xs text-slate-400">
          Runs automatically on every server boot and `run_tests.bat` execution, or click below to
          append any newly modified codebase files into{' '}
          `01_Business/OS_Updates/KAIROS_2_0_Change_Ledger.md` and recalculate `_Project_Index.md`
          rollups.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={syncSummary}
            onChange={(e) => setSyncSummary(e.target.value)}
            placeholder="Optional change note (e.g. Propagated Hermes & Wiki across all workspaces)..."
            className="flex-1 min-w-[260px] rounded border border-kairos-border bg-kairos-bg px-3 py-1.5 text-xs text-white"
          />
          <button
            type="submit"
            disabled={syncingVault}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncingVault ? 'animate-spin' : ''}`} />
            {syncingVault ? 'Syncing Ledger...' : 'Sync Code Changes to Vault'}
          </button>
        </div>
        {syncResult && <div className="text-xs text-emerald-300 font-mono">✓ {syncResult}</div>}
      </form>

      {/* GitHub Research Repo Sync (`04_Resources/Code_and_Research/`) */}
      <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-bold text-cyan-300">
            <GitBranch className="h-4 w-4" /> ForestCityCreatorsLLC GitHub &amp; Vault Resource Sync (`04_Resources/Code_and_Research/`)
          </div>
          <button
            type="button"
            disabled={syncingOrgCatalog}
            onClick={handleSyncFccOrgCatalog}
            className="flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${syncingOrgCatalog ? 'animate-spin' : ''}`} />
            {syncingOrgCatalog ? 'Syncing FCC Catalog...' : 'Sync ForestCityCreatorsLLC Catalog → Vault'}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={repoName}
            onChange={(e) => setRepoName(e.target.value)}
            placeholder="KAIROS 2.0 or repo folder in 04_Resources/Code_and_Research..."
            className="w-72 rounded border border-kairos-border bg-kairos-bg px-3 py-1.5 text-xs text-white font-mono"
          />
          <button
            type="button"
            disabled={Boolean(syncingGit)}
            onClick={() => handleGitSync('status')}
            className="flex items-center gap-1 rounded border border-kairos-border bg-kairos-card px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${syncingGit === 'status' ? 'animate-spin' : ''}`} /> Git Status
          </button>
          <button
            type="button"
            disabled={Boolean(syncingGit)}
            onClick={() => handleGitSync('pull')}
            className="flex items-center gap-1 rounded bg-emerald-500/20 border border-emerald-500/40 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-50"
          >
            {syncingGit === 'pull' ? 'Pulling...' : 'Git Pull'}
          </button>
        </div>
        {orgCatalogSummary && (
          <div className="text-xs text-cyan-300 font-mono">✓ {orgCatalogSummary}</div>
        )}
        {gitOutput && (
          <pre className="rounded border border-kairos-border bg-kairos-bg p-2.5 font-mono text-[11px] text-slate-300 whitespace-pre-wrap">
            {gitOutput}
          </pre>
        )}
      </div>

      <div className="rounded-xl border border-kairos-border bg-kairos-panel p-4 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-bold text-purple-300">
            <SquareTerminal className="h-4 w-4" /> MCP Server Registration (`second_brain_mcp`)
          </div>
          <button
            type="button"
            onClick={handleCopyMcpSnippet}
            className="flex items-center gap-1 rounded border border-purple-500/40 bg-purple-500/15 px-2.5 py-1 text-[11px] font-semibold text-purple-200 hover:bg-purple-500/25"
          >
            {copiedMcp ? (
              <>
                <Check className="h-3 w-3 text-emerald-300" /> Copied!
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" /> Copy JSON
              </>
            )}
          </button>
        </div>
        <p className="text-xs text-slate-400">
          Add this block to Claude Desktop, Cursor, or Antigravity MCP config to expose all 18
          Canopy Vault, Projects, Monthly Calendar, Project Wiki &amp; Hermes tools over stdio:
        </p>
        <pre className="rounded-lg border border-kairos-border bg-kairos-bg p-3 font-mono text-xs text-emerald-300 overflow-x-auto">
          {mcpSnippet}
        </pre>
      </div>
    </div>
  );
};
