import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertCircle, CheckCircle2, ChevronDown, ChevronRight, CloudUpload, Database,
  FileText, Filter, MessageSquare, Search, Sparkles, Wrench, Phone, Building2, ListChecks,
} from 'lucide-react';

type Stage = 'idle' | 'running' | 'pending' | 'failed' | 'done';

export interface PipelineViewProps {
  statusData: any;
  logsData: any;
  isUploading: boolean;
  ingestDone: boolean;
  extractionStatus: string;
  indexingStatus: string;
  extractionErrorText: string;
  indexingErrorText: string;
  isTriggeringExtraction: boolean;
  isTriggeringIndexing: boolean;
  isResetting: boolean;
  resetStatus: string;
  onTriggerExtraction: () => void;
  onTriggerIndexing: () => void;
  onResetFailed: () => void;
}

const FACT_STYLE: Record<string, { label: string; chip: string; icon: any }> = {
  service_contact: { label: 'Service contact', chip: 'bg-sky-100 text-sky-700', icon: Phone },
  process_info: { label: 'Process', chip: 'bg-violet-100 text-violet-700', icon: ListChecks },
  facility_info: { label: 'Facility', chip: 'bg-amber-100 text-amber-700', icon: Building2 },
};
const factStyle = (t: string) =>
  FACT_STYLE[t] ?? { label: t.replace(/_/g, ' '), chip: 'bg-slate-100 text-slate-600', icon: Wrench };

const toStage = (s: string): Stage =>
  s === 'in-progress' ? 'running' : s === 'pending-idle' ? 'pending' : s === 'failed' ? 'failed' : s === 'completed' ? 'done' : 'idle';

const parse = (raw: string | undefined) => {
  try { return raw ? JSON.parse(raw) : {}; } catch { return {}; }
};

const fmt = (n: number | undefined) => (n ?? 0).toLocaleString();

const STAGE_COLORS: Record<Stage, { ring: string; bg: string; text: string; label: string }> = {
  idle: { ring: '#cbd5e1', bg: 'bg-slate-100', text: 'text-slate-400', label: 'Idle' },
  pending: { ring: '#f59e0b', bg: 'bg-amber-100', text: 'text-amber-600', label: 'Waiting' },
  running: { ring: '#3b82f6', bg: 'bg-blue-100', text: 'text-blue-600', label: 'Running' },
  failed: { ring: '#ef4444', bg: 'bg-red-100', text: 'text-red-600', label: 'Failed' },
  done: { ring: '#10b981', bg: 'bg-emerald-100', text: 'text-emerald-600', label: 'Done' },
};

/** Circular progress ring with an icon in the middle. */
function StageNode({ icon: Icon, title, stage, progress, count, sub }: {
  icon: any; title: string; stage: Stage; progress: number; count: string; sub: string;
}) {
  const c = STAGE_COLORS[stage];
  const r = 34;
  const circ = 2 * Math.PI * r;
  const pct = stage === 'done' ? 100 : Math.max(0, Math.min(100, progress));
  return (
    <div className="flex flex-col items-center text-center w-32 shrink-0">
      <div className={`relative w-24 h-24 ${stage === 'running' ? 'pv-glow' : ''}`}>
        <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
          <circle cx="40" cy="40" r={r} fill="none" stroke="#e2e8f0" strokeWidth="6" />
          <circle
            cx="40" cy="40" r={r} fill="none" stroke={c.ring} strokeWidth="6" strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={circ * (1 - pct / 100)}
            style={{ transition: 'stroke-dashoffset 0.8s ease, stroke 0.3s' }}
          />
        </svg>
        <div className={`absolute inset-3 rounded-full flex items-center justify-center ${c.bg} ${c.text}`}>
          {stage === 'done' ? <CheckCircle2 size={28} className="pv-pop" /> :
           stage === 'failed' ? <AlertCircle size={28} /> : <Icon size={28} />}
        </div>
      </div>
      <div className="mt-2 text-sm font-bold text-slate-800">{title}</div>
      <div className="text-lg font-extrabold text-slate-900 leading-tight">{count}</div>
      <div className="text-[11px] text-slate-500">{sub}</div>
      <span className={`mt-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${c.bg} ${c.text}`}>{c.label}</span>
    </div>
  );
}

/** Line between nodes with animated packets while `active`. */
function Conveyor({ active, color, failed }: { active: boolean; color: string; failed?: boolean }) {
  return (
    <div className="relative flex-1 min-w-[40px] h-24 flex items-center">
      <div className="relative w-full h-1 rounded-full bg-slate-200 overflow-hidden">
        {active && [0, 1, 2].map(i => (
          <span
            key={i}
            className="pv-packet absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full"
            style={{ background: color, animationDelay: `${i * 0.6}s` }}
          />
        ))}
        {!active && <div className={`h-full ${failed ? 'bg-red-300' : 'bg-slate-300'}`} style={{ width: failed ? '40%' : 0 }} />}
      </div>
      <ChevronRight size={16} className="absolute right-0 text-slate-400" />
    </div>
  );
}

function Funnel({ steps, footnote }: { steps: { label: string; value: number; color: string; note?: string }[]; footnote?: string }) {
  const max = Math.max(1, ...steps.map(s => s.value));
  return (
    <div className="space-y-2">
      {steps.map((s, i) => {
        const w = Math.max(6, (s.value / max) * 100);
        const prev = i > 0 ? steps[i - 1].value : null;
        const kept = prev && prev > 0 ? Math.round((s.value / prev) * 100) : null;
        return (
          <div key={s.label} className="flex items-center gap-3">
            <div className="w-36 text-xs font-medium text-slate-600 text-right shrink-0">{s.label}</div>
            <div className="flex-1 flex justify-center">
              <div
                className="h-8 rounded-md flex items-center justify-center text-white text-xs font-bold shadow-sm transition-all duration-700"
                style={{ width: `${w}%`, background: s.color }}
              >
                {fmt(s.value)}
              </div>
            </div>
            <div className="w-28 text-[11px] text-slate-400 shrink-0">
              {s.note ?? (kept !== null ? `${kept}% of previous` : '')}
            </div>
          </div>
        );
      })}
      {footnote && <p className="text-[11px] text-slate-400 pt-1">{footnote}</p>}
    </div>
  );
}

/** Messages on the left, structured facts on the right. */
function MessagesToFacts({ status, running, noiseCount }: { status: any; running: boolean; noiseCount: number }) {
  const recent: any[] = useMemo(() => status?.facts?.recent ?? [], [status]);
  const byType: Record<string, number> = status?.facts?.by_type ?? {};
  const seen = useRef<Set<string>>(new Set());
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  // Flag facts that appeared since the last poll so they can animate in.
  useEffect(() => {
    const first = seen.current.size === 0;
    const added = recent.filter(f => !seen.current.has(f.fact_id)).map(f => f.fact_id);
    recent.forEach(f => seen.current.add(f.fact_id));
    if (!first && added.length) {
      setFresh(new Set(added));
      const t = setTimeout(() => setFresh(new Set()), 2500);
      return () => clearTimeout(t);
    }
  }, [recent]);

  const bubbleWidths = ['w-4/5', 'w-3/5', 'w-11/12', 'w-2/3', 'w-3/4'];
  return (
    <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1.3fr] gap-4 items-stretch">
      <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
        <div className="text-xs font-bold uppercase tracking-wide text-slate-400 mb-3 flex items-center gap-1.5">
          <MessageSquare size={13} /> Chat messages
        </div>
        <div className="space-y-2">
          {bubbleWidths.map((w, i) => (
            <div key={i} className={`${w} ${i % 2 ? 'ml-auto bg-emerald-100' : 'bg-white border border-slate-200'} rounded-2xl px-3 py-2 ${running ? 'pv-bubble' : ''}`}
                 style={{ animationDelay: `${i * 0.5}s` }}>
              <div className="h-1.5 rounded bg-slate-300/70 w-full mb-1" />
              <div className="h-1.5 rounded bg-slate-300/50 w-2/3" />
            </div>
          ))}
          {noiseCount > 0 && (
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400 pt-1">
              <Filter size={12} /> {fmt(noiseCount)} noise messages filtered out
            </div>
          )}
        </div>
      </div>

      <div className="hidden md:flex flex-col items-center justify-center text-slate-400">
        <div className={`p-3 rounded-full ${running ? 'bg-blue-100 text-blue-600 pv-glow' : 'bg-slate-100'}`}>
          <Sparkles size={22} className={running ? 'animate-pulse' : ''} />
        </div>
        <div className="text-[10px] font-semibold mt-1">LLM</div>
        <ChevronRight className="mt-1" />
      </div>

      <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs font-bold uppercase tracking-wide text-slate-400 flex items-center gap-1.5">
            <FileText size={13} /> Latest facts
          </div>
          <div className="flex gap-1 flex-wrap justify-end">
            {Object.entries(byType).map(([t, n]) => (
              <span key={t} className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${factStyle(t).chip}`}>
                {factStyle(t).label} · {n}
              </span>
            ))}
          </div>
        </div>
        {recent.length === 0 ? (
          <div className="text-sm text-slate-400 py-6 text-center">Facts will appear here as they are extracted.</div>
        ) : (
          <div className="space-y-2">
            {recent.slice(0, 5).map(f => {
              const st = factStyle(f.fact_type);
              const Icon = st.icon;
              return (
                <div key={f.fact_id}
                     className={`flex items-center gap-3 bg-white border rounded-lg px-3 py-2 shadow-sm ${fresh.has(f.fact_id) ? 'pv-slide-in border-blue-300' : 'border-slate-200'}`}>
                  <span className={`p-1.5 rounded-md ${st.chip}`}><Icon size={14} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-slate-800 truncate">{f.title}</div>
                    <div className="text-[10px] text-slate-400">{st.label}</div>
                  </div>
                  {fresh.has(f.fact_id) && <span className="text-[10px] font-bold text-blue-600">NEW</span>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function describeEvent(e: any): { text: string; tone: 'info' | 'ok' | 'warn' | 'err' } | null {
  const p = parse(e.details);
  switch (`${e.stage}:${e.event_type}`) {
    case 'ingestion:import_started': return { text: `Started reading ${p.chat_name ?? 'chat export'}`, tone: 'info' };
    case 'ingestion:import_completed': return { text: `Import finished${p.new_messages_inserted != null ? ` — ${p.new_messages_inserted} new messages` : ''}`, tone: 'ok' };
    case 'ingestion:parse_failure': return { text: `Couldn't parse line ${p.line_number ?? '?'}`, tone: 'warn' };
    case 'extraction:background_task_started': return { text: 'Fact extraction started', tone: 'info' };
    case 'extraction:background_task_progress': return { text: `Extracted ${fmt(p.facts_extracted_so_far)} facts so far · ${fmt(p.remaining_pending)} messages left`, tone: 'info' };
    case 'extraction:background_task_completed': return { text: 'Fact extraction finished', tone: 'ok' };
    case 'extraction:background_task_failed': return { text: `Extraction failed: ${p.error ?? 'unknown error'}`, tone: 'err' };
    case 'indexing:background_task_started': return { text: 'Vector indexing started', tone: 'info' };
    case 'indexing:background_task_progress': return { text: `Indexed ${fmt(p.vectors_indexed_so_far)} facts · ${fmt(p.remaining_pending)} left`, tone: 'info' };
    case 'indexing:background_task_completed': return { text: 'Vector indexing finished', tone: 'ok' };
    case 'indexing:background_task_failed': return { text: `Indexing failed: ${p.error ?? 'unknown error'}`, tone: 'err' };
    default:
      if (e.status === 'error') return { text: `${e.stage}: ${e.event_type.replace(/_/g, ' ')}`, tone: 'err' };
      return null;
  }
}

const TONE: Record<string, string> = {
  info: 'bg-blue-400', ok: 'bg-emerald-500', warn: 'bg-amber-500', err: 'bg-red-500',
};

const ago = (iso: string) => {
  const t = Date.parse(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

/** Estimate throughput + ETA from the progress events of the latest run of a stage. */
function estimateRate(events: any[], stage: string) {
  const prog = events.filter(e => e.stage === stage && e.event_type === 'background_task_progress');
  if (prog.length < 2) return null;
  const trace = prog[0].trace_id;
  const same = prog.filter(e => e.trace_id === trace);
  if (same.length < 2) return null;
  const newest = same[0], oldest = same[same.length - 1];
  const dtMin = (Date.parse(newest.timestamp) - Date.parse(oldest.timestamp)) / 60000;
  const drop = (parse(oldest.details).remaining_pending ?? 0) - (parse(newest.details).remaining_pending ?? 0);
  if (!(dtMin > 0) || drop <= 0) return null;
  const perMin = drop / dtMin;
  const left = parse(newest.details).remaining_pending ?? 0;
  return { perMin, etaMin: left / perMin };
}

function Confetti() {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444'];
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 h-0 overflow-visible">
      {Array.from({ length: 24 }).map((_, i) => (
        <span key={i} className="pv-confetti absolute w-2 h-2 rounded-sm"
              style={{ left: `${(i * 4.1) % 100}%`, background: colors[i % colors.length], animationDelay: `${(i % 6) * 0.12}s` }} />
      ))}
    </div>
  );
}

function ActionButton({ onClick, disabled, busy, label, busyLabel, tone = 'blue' }: {
  onClick: () => void; disabled?: boolean; busy: boolean; label: string; busyLabel: string; tone?: 'blue' | 'red';
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 rounded-lg text-xs font-bold text-white shadow-sm transition-all disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed ${tone === 'red' ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'}`}
    >
      {busy ? busyLabel : label}
    </button>
  );
}

export default function PipelineView(props: PipelineViewProps) {
  const {
    statusData: s, logsData, isUploading, ingestDone, extractionStatus, indexingStatus,
    extractionErrorText, indexingErrorText, isTriggeringExtraction, isTriggeringIndexing,
    isResetting, resetStatus, onTriggerExtraction, onTriggerIndexing, onResetFailed,
  } = props;
  const [showTech, setShowTech] = useState(false);
  const [celebrate, setCelebrate] = useState(false);

  const ex = toStage(extractionStatus);
  const ix = toStage(indexingStatus);
  const ing: Stage = isUploading ? 'running' : ingestDone ? 'done' : 'idle';

  const m = s.messages ?? {};
  const noise = m.total_skipped_noise ?? 0;
  const stored = (m.total_new ?? 0) + (m.total_failed ?? 0) + (m.total_extracted ?? 0) + noise;
  const toExtract = stored - noise;
  const exPct = toExtract > 0 ? ((m.total_extracted ?? 0) / toExtract) * 100 : 0;
  const factsTotal = s.facts?.total ?? 0;
  const vectors = s.vectors?.active ?? 0;
  const ixTotal = vectors + (s.facts?.pending_indexing ?? 0);
  const ixPct = ixTotal > 0 ? (vectors / ixTotal) * 100 : 0;
  const lastImport = s.history?.[0];

  // Fire a short celebration when a stage transitions from running to done.
  const prev = useRef({ ex, ix });
  useEffect(() => {
    const wasRunning = prev.current.ex === 'running' || prev.current.ix === 'running';
    const nowAllDone = ex !== 'running' && ix !== 'running' && ex !== 'failed' && ix !== 'failed' && ex !== 'pending' && ix !== 'pending';
    prev.current = { ex, ix };
    if (wasRunning && nowAllDone) {
      setCelebrate(true);
      const t = setTimeout(() => setCelebrate(false), 4000);
      return () => clearTimeout(t);
    }
  }, [ex, ix]);

  const events: any[] = logsData?.events ?? [];
  const feed = events.map(e => ({ e, d: describeEvent(e) })).filter(x => x.d).slice(0, 8);
  const exRate = estimateRate(events, 'extraction');
  const ixRate = estimateRate(events, 'indexing');
  const rate = ex === 'running' ? exRate : ix === 'running' ? ixRate : null;
  const rateUnit = ex === 'running' ? 'msgs' : 'facts';

  return (
    <div className="relative bg-white border border-slate-200 shadow-sm rounded-2xl overflow-hidden">
      {celebrate && <Confetti />}

      {/* Header */}
      <div className="px-6 py-5 bg-gradient-to-r from-slate-900 via-indigo-900 to-blue-800 text-white flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Activity size={20} className={ex === 'running' || ix === 'running' ? 'animate-pulse' : ''} />
            Ingestion &amp; Processing Pipeline
          </h2>
          <p className="text-xs text-blue-200 mt-1">
            {celebrate ? '🎉 All caught up — your chat is ready to search.'
              : ex === 'running' ? 'Reading messages and pulling out facts…'
              : ix === 'running' ? 'Embedding facts into the search index…'
              : ex === 'failed' || ix === 'failed' ? 'Something needs attention below.'
              : ex === 'pending' || ix === 'pending' ? 'Work is queued and waiting for you to start it.'
              : vectors > 0 ? 'Everything is processed and searchable.' : 'Upload a chat export to get started.'}
          </p>
        </div>
        <div className="flex gap-5 text-center">
          {[['Messages', stored], ['Facts', factsTotal], ['Indexed', vectors]].map(([l, v]) => (
            <div key={l as string}>
              <div className="text-2xl font-extrabold leading-none">{fmt(v as number)}</div>
              <div className="text-[10px] uppercase tracking-wide text-blue-200">{l}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="p-6 space-y-8">
        {/* 1. Conveyor */}
        <div className="flex items-start justify-between overflow-x-auto pb-2">
          <StageNode icon={CloudUpload} title="Ingest" stage={ing} progress={100}
            count={lastImport ? fmt(lastImport.total) : '—'}
            sub={lastImport ? (lastImport.messages === 0 ? `${fmt(lastImport.skipped)} duplicates` : `${fmt(lastImport.messages)} new`) : 'no uploads yet'} />
          <Conveyor active={ing === 'running' || ex === 'running'} color="#3b82f6" />
          <StageNode icon={MessageSquare} title="Extract" stage={ex} progress={exPct}
            count={`${fmt(m.total_extracted)} / ${fmt(toExtract)}`} sub="messages processed" />
          <Conveyor active={ex === 'running' || ix === 'running'} color="#8b5cf6" failed={ex === 'failed'} />
          <StageNode icon={FileText} title="Facts" stage={factsTotal > 0 ? (ex === 'running' ? 'running' : 'done') : 'idle'}
            progress={100} count={fmt(factsTotal)} sub="structured facts" />
          <Conveyor active={ix === 'running'} color="#10b981" failed={ix === 'failed'} />
          <StageNode icon={Database} title="Index" stage={ix} progress={ixPct}
            count={`${fmt(vectors)} / ${fmt(ixTotal)}`} sub="facts searchable" />
        </div>

        {/* Actions + ETA */}
        <div className="flex flex-wrap items-center gap-3 bg-slate-50 border border-slate-200 rounded-xl px-4 py-3">
          {ex === 'pending' && <ActionButton onClick={onTriggerExtraction} busy={isTriggeringExtraction} busyLabel="Starting…" label={`Extract ${fmt(m.total_new)} pending messages`} />}
          {ex === 'failed' && (
            <>
              <ActionButton tone="red" onClick={onResetFailed} disabled={isResetting} busy={isResetting} busyLabel="Resetting…" label={`Retry ${fmt(m.total_failed)} failed`} />
              {(m.total_new ?? 0) > 0 && <ActionButton onClick={onTriggerExtraction} busy={isTriggeringExtraction} busyLabel="Resuming…" label="Resume extraction" />}
            </>
          )}
          {(ix === 'pending' || ix === 'failed') && (s.facts?.pending_indexing ?? 0) > 0 &&
            <ActionButton onClick={onTriggerIndexing} busy={isTriggeringIndexing} busyLabel="Starting…" label={ix === 'failed' ? 'Resume indexing' : `Index ${fmt(s.facts?.pending_indexing)} pending facts`} />}
          {rate ? (
            <div className="text-sm text-slate-700">
              <span className="font-bold">{Math.round(rate.perMin)} {rateUnit}/min</span>
              <span className="text-slate-400"> · </span>
              <span>~{rate.etaMin < 1 ? '<1' : Math.ceil(rate.etaMin)} min left</span>
            </div>
          ) : (ex === 'running' || ix === 'running') ? (
            <div className="text-sm text-blue-600 animate-pulse">Measuring speed…</div>
          ) : (ex === 'idle' || ex === 'done') && (ix === 'idle' || ix === 'done') ? (
            <div className="text-sm text-slate-400">Nothing waiting — no action needed.</div>
          ) : null}
          {resetStatus && <span className="text-xs text-slate-500">{resetStatus}</span>}
        </div>

        {/* 2. Messages -> Facts */}
        <section>
          <h3 className="text-sm font-bold text-slate-700 mb-3">From chatter to knowledge</h3>
          <MessagesToFacts status={s} running={ex === 'running'} noiseCount={noise} />
        </section>

        {/* 3. Funnel */}
        <section>
          <h3 className="text-sm font-bold text-slate-700 mb-3">Where messages end up</h3>
          <Funnel
            steps={[
              { label: 'Messages stored', value: stored, color: '#6366f1' },
              { label: 'Kept after noise filter', value: toExtract, color: '#3b82f6' },
              { label: 'Processed by LLM', value: m.total_extracted ?? 0, color: '#8b5cf6' },
              { label: 'Facts created', value: factsTotal, color: '#a855f7', note: 'merged & de-duplicated' },
              { label: 'Indexed for search', value: vectors, color: '#10b981' },
            ]}
            footnote={`${fmt(noise)} filtered as noise${(m.total_failed ?? 0) > 0 ? ` · ${fmt(m.total_failed)} failed` : ''}${lastImport ? ` · last import skipped ${fmt(lastImport.skipped)} duplicates` : ''}. Facts can be fewer than messages because several messages merge into one fact.`}
          />
        </section>

        {/* 5. Activity feed */}
        <section>
          <h3 className="text-sm font-bold text-slate-700 mb-3 flex items-center gap-2"><Search size={14} /> Live activity</h3>
          {feed.length === 0 ? (
            <div className="text-sm text-slate-400">No activity yet.</div>
          ) : (
            <ul className="space-y-2">
              {feed.map(({ e, d }, i) => (
                <li key={`${e.timestamp}-${i}`} className="flex items-start gap-3 text-sm">
                  <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${TONE[d!.tone]} ${i === 0 && d!.tone === 'info' ? 'animate-pulse' : ''}`} />
                  <span className="text-slate-700 flex-1 break-words">{d!.text}</span>
                  <span className="text-[11px] text-slate-400 shrink-0">{ago(e.timestamp)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Technical details */}
        <div>
          <button onClick={() => setShowTech(v => !v)} className="text-xs font-semibold text-slate-500 hover:text-slate-700 flex items-center gap-1">
            {showTech ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Technical details
          </button>
          {showTech && (
            <div className="mt-2 space-y-2 text-xs">
              <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-x-auto text-slate-600">{JSON.stringify({ messages: s.messages, facts: { total: s.facts?.total, pending_indexing: s.facts?.pending_indexing }, vectors: s.vectors, models: s.current_models }, null, 2)}</pre>
              {extractionErrorText && <div className="p-2 bg-red-50 text-red-700 border border-red-100 rounded-lg font-mono whitespace-pre-wrap break-words">Extraction: {extractionErrorText}</div>}
              {indexingErrorText && <div className="p-2 bg-red-50 text-red-700 border border-red-100 rounded-lg font-mono whitespace-pre-wrap break-words">Indexing: {indexingErrorText}</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
