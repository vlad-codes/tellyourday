import { useState } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { open } from '@tauri-apps/plugin-shell';
import type { AppStatus } from '../types';

interface Props {
  status: AppStatus;
  onRetry: () => void;
}

const MODELS = [
  { ram: '8 GB',  model: 'llama3.2:3b',  size: '2.0 GB' },
  { ram: '16 GB', model: 'llama3.1:8b',  size: '4.7 GB' },
  { ram: '32 GB', model: 'qwen2.5:32b',  size: '20 GB'  },
];

const EMBED_MODEL = 'nomic-embed-text';
const EMBED_SIZE  = '274 MB';

const API = 'http://localhost:8000';

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }

  return (
    <div className="relative group mt-3">
      <pre className="bg-slate-900/90 dark:bg-black/60 text-slate-100
                      text-[12px] font-mono rounded-xl px-4 py-3
                      border border-white/[0.08] leading-relaxed overflow-x-auto">
        {code}
      </pre>
      <button
        onClick={copy}
        className="absolute top-2 right-2 text-[10px] px-2 py-1 rounded-lg
                   bg-white/10 hover:bg-white/20 text-slate-300 hover:text-white
                   transition-all duration-150 opacity-0 group-hover:opacity-100"
      >
        {copied ? '✓ Copied' : 'Copy'}
      </button>
    </div>
  );
}

type PullPhase =
  | { phase: 'idle' }
  | { phase: 'pulling'; status: string; pct: number }
  | { phase: 'done' }
  | { phase: 'error'; message: string };

function PullProgress({ pullState }: { pullState: PullPhase }) {
  if (pullState.phase === 'idle' || pullState.phase === 'done') return null;

  if (pullState.phase === 'error') {
    return (
      <p className="mt-2 text-[11px] text-red-400 leading-relaxed">
        {pullState.message}
      </p>
    );
  }

  const { status, pct } = pullState;
  return (
    <div className="mt-3">
      <div className="w-full rounded-full bg-indigo-100/40 dark:bg-white/[0.06] h-1.5">
        <div
          className="h-full rounded-full bg-indigo-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-1.5 text-[11px] text-slate-400 dark:text-slate-500 leading-relaxed truncate">
        {status || 'Connecting…'}
        {pct > 0 && <span className="ml-1.5 font-mono text-indigo-400">{pct}%</span>}
      </p>
    </div>
  );
}

function usePull(onDone: () => void) {
  const [pullState, setPullState] = useState<PullPhase>({ phase: 'idle' });

  function startPull(model: string) {
    setPullState({ phase: 'pulling', status: 'Starting…', pct: 0 });

    const es = new EventSource(`${API}/pull-model?model=${encodeURIComponent(model)}`);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as {
          status: string;
          completed?: number;
          total?: number;
          error?: string;
        };

        if (data.status === 'done') {
          es.close();
          setPullState({ phase: 'done' });
          setTimeout(onDone, 800);
          return;
        }

        if (data.status === 'error') {
          es.close();
          setPullState({ phase: 'error', message: data.error ?? 'Unknown error' });
          return;
        }

        const pct =
          data.total && data.total > 0
            ? Math.round(((data.completed ?? 0) / data.total) * 100)
            : 0;
        setPullState({ phase: 'pulling', status: data.status, pct });
      } catch {
        // ignore parse errors mid-stream
      }
    };

    es.onerror = () => {
      // EventSource auto-reconnects on network drops — only error out on persistent failure
      // We leave the state as-is so the progress bar stays visible during reconnect
    };
  }

  function reset() {
    setPullState({ phase: 'idle' });
  }

  return { pullState, startPull, reset };
}

export default function Onboarding({ status, onRetry }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col">
      {/* Drag region */}
      <div
        className="h-10 shrink-0 cursor-default"
        onMouseDown={() => getCurrentWindow().startDragging()}
      />

      {/* Centered card */}
      <div className="flex-1 flex items-center justify-center px-8 pb-10">
        <div className="w-full max-w-sm fade-in">

          {/* Logo */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl
                            bg-indigo-500/15 border border-indigo-400/20 mb-4">
              <span className="text-2xl">📓</span>
            </div>
            <h1 className="text-[22px] font-semibold tracking-tight
                           text-slate-800 dark:text-slate-100">
              Telmi
            </h1>
            <p className="text-[13px] text-slate-400 dark:text-slate-500 mt-1">
              Your private journal AI
            </p>
          </div>

          {status === 'loading'          && <LoadingScreen />}
          {status === 'starting-ollama'  && <StartingOllamaScreen onRetry={onRetry} />}
          {status === 'no-ollama'        && <NoOllamaScreen onRetry={onRetry} />}
          {status === 'no-model'         && <NoModelScreen onRetry={onRetry} />}
        </div>
      </div>
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="text-center">
      <div className="inline-flex items-center gap-2.5 text-[13px] text-slate-500 dark:text-slate-400">
        <span className="w-4 h-4 border-2 border-indigo-400/30 border-t-indigo-500
                         rounded-full animate-spin shrink-0" />
        Connecting to backend…
      </div>
      <p className="text-[11px] text-slate-400/60 dark:text-slate-600 mt-3">
        This may take a few seconds on first launch.
      </p>
    </div>
  );
}

function StartingOllamaScreen({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="text-center">
      <div className="inline-flex items-center gap-2.5 text-[13px] text-slate-500 dark:text-slate-400">
        <span className="w-4 h-4 border-2 border-indigo-400/30 border-t-indigo-500
                         rounded-full animate-spin shrink-0" />
        Starting Ollama…
      </div>
      <p className="text-[11px] text-slate-400/60 dark:text-slate-600 mt-3">
        This usually takes a few seconds.
      </p>
      <button
        onClick={onRetry}
        className="mt-6 text-[12px] text-slate-400 dark:text-slate-500
                   hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
      >
        Try again
      </button>
    </div>
  );
}

function NoOllamaScreen({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="glass-card rounded-2xl p-6">
      <div className="flex items-start gap-3 mb-4">
        <span className="text-[18px] leading-none mt-0.5">⚠️</span>
        <div>
          <h2 className="text-[15px] font-semibold text-slate-800 dark:text-slate-100 leading-snug">
            Ollama not found
          </h2>
          <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
            Telmi needs Ollama to run AI models locally. Install it once and Telmi will
            start it automatically on launch.
          </p>
        </div>
      </div>

      <button
        onClick={() => open('https://ollama.com/download/mac')}
        className="w-full text-[13px] font-medium text-white
                   bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700
                   rounded-xl px-4 py-2.5 transition-all duration-150
                   shadow-sm shadow-indigo-500/30"
      >
        Download Ollama →
      </button>
      <p className="text-[11px] text-slate-400/70 dark:text-slate-600 mt-2 text-center">
        Opens ollama.com in your browser. After installing, relaunch Telmi.
      </p>

      <div className="mt-5 space-y-4">
        <div>
          <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400
                        uppercase tracking-wider mb-1">
            Or via Homebrew
          </p>
          <CodeBlock code="brew install ollama" />
        </div>
      </div>

      <button
        onClick={onRetry}
        className="mt-5 w-full text-[12px] text-slate-400 dark:text-slate-500
                   hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
      >
        Try again
      </button>
    </div>
  );
}

function NoModelScreen({ onRetry }: { onRetry: () => void }) {
  const [selectedModel, setSelectedModel] = useState(MODELS[0].model);
  const [embedDone, setEmbedDone] = useState(false);

  const chatPull = usePull(onRetry);
  const embedPull = usePull(() => setEmbedDone(true));

  const isPulling =
    chatPull.pullState.phase === 'pulling' ||
    embedPull.pullState.phase === 'pulling';

  const chatDone = chatPull.pullState.phase === 'done';
  const selectedMeta = MODELS.find((m) => m.model === selectedModel)!;

  return (
    <div className="glass-card rounded-2xl p-6">
      <div className="flex items-start gap-3 mb-4">
        <span className="text-[18px] leading-none mt-0.5">📦</span>
        <div>
          <h2 className="text-[15px] font-semibold text-slate-800 dark:text-slate-100 leading-snug">
            No model installed
          </h2>
          <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
            Choose a model that fits your RAM and download it directly.
          </p>
        </div>
      </div>

      {/* Model picker */}
      <div className={`space-y-1.5 mb-4 ${isPulling ? 'pointer-events-none opacity-60' : ''}`}>
        {MODELS.map((m) => (
          <button
            key={m.model}
            onClick={() => setSelectedModel(m.model)}
            className={`w-full text-left rounded-xl px-3.5 py-2.5 flex items-center justify-between
                        transition-all duration-150 border
                        ${selectedModel === m.model
                          ? 'bg-indigo-500/10 dark:bg-indigo-400/15 border-indigo-300/40 dark:border-indigo-400/20'
                          : 'bg-white/40 dark:bg-white/[0.04] border-slate-200/60 dark:border-white/[0.07] hover:bg-white/60 dark:hover:bg-white/[0.08]'
                        }`}
          >
            <div>
              <span className="text-[13px] font-medium text-slate-700 dark:text-slate-200 font-mono">
                {m.model}
              </span>
              <span className="text-[11px] text-slate-400 dark:text-slate-500 ml-2">
                {m.size}
              </span>
            </div>
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              {m.ram}
            </span>
          </button>
        ))}
      </div>

      {/* Download button + progress */}
      {!chatDone ? (
        <>
          <button
            onClick={() => chatPull.startPull(selectedModel)}
            disabled={isPulling}
            className="w-full text-[13px] font-medium text-white
                       bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700
                       rounded-xl px-4 py-2.5 transition-all duration-150
                       shadow-sm shadow-indigo-500/30
                       disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {isPulling && chatPull.pullState.phase === 'pulling'
              ? 'Downloading…'
              : `Download ${selectedMeta.model} (${selectedMeta.size})`}
          </button>
          <PullProgress pullState={chatPull.pullState} />
        </>
      ) : (
        <div className="flex items-center gap-2 text-[13px] text-emerald-500 font-medium py-1">
          <span>✓</span>
          <span>{selectedModel} downloaded</span>
        </div>
      )}

      {/* Embed model — shown after chat model is done or as optional */}
      {(chatDone || chatPull.pullState.phase === 'idle') && !embedDone && (
        <div className="mt-4 px-3.5 py-3 rounded-xl bg-slate-100/60 dark:bg-white/[0.04]
                        border border-slate-200/50 dark:border-white/[0.06]">
          <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed mb-2">
            <span className="font-semibold text-slate-600 dark:text-slate-300">Optional:</span>
            {' '}For semantic search (from 15 entries on), also download{' '}
            <span className="font-mono text-[10.5px]">{EMBED_MODEL}</span>{' '}
            ({EMBED_SIZE}).
          </p>
          <button
            onClick={() => embedPull.startPull(EMBED_MODEL)}
            disabled={embedPull.pullState.phase === 'pulling'}
            className="w-full text-[12px] font-medium
                       text-indigo-600 dark:text-indigo-400
                       bg-indigo-50/80 dark:bg-indigo-400/10
                       hover:bg-indigo-100/80 dark:hover:bg-indigo-400/20
                       border border-indigo-200/60 dark:border-indigo-400/20
                       rounded-lg px-3 py-2 transition-all duration-150
                       disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {embedPull.pullState.phase === 'pulling'
              ? 'Downloading…'
              : `Download ${EMBED_MODEL}`}
          </button>
          <PullProgress pullState={embedPull.pullState} />
        </div>
      )}

      {embedDone && (
        <div className="mt-3 flex items-center gap-2 text-[11px] text-emerald-500">
          <span>✓</span>
          <span>{EMBED_MODEL} downloaded — semantic search enabled</span>
        </div>
      )}

      {/* Manual fallback */}
      {!isPulling && (
        <details className="mt-4 group">
          <summary className="text-[11px] text-slate-400 dark:text-slate-500 cursor-pointer
                              hover:text-slate-500 dark:hover:text-slate-400 transition-colors
                              list-none flex items-center gap-1">
            <span className="group-open:rotate-90 inline-block transition-transform duration-150">▶</span>
            Manual install via terminal
          </summary>
          <div className="mt-2">
            <CodeBlock code={`ollama pull ${selectedModel}`} />
            <CodeBlock code={`ollama pull ${EMBED_MODEL}`} />
          </div>
        </details>
      )}

      <button
        onClick={onRetry}
        className="mt-5 w-full text-[13px] font-medium text-white
                   bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700
                   rounded-xl px-4 py-2.5 transition-all duration-150
                   shadow-sm shadow-indigo-500/30"
      >
        Model ready — continue →
      </button>
    </div>
  );
}
