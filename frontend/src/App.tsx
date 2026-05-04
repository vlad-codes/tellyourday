import { useEffect, useRef, useState } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { invoke } from '@tauri-apps/api/core';
import { getVersion } from '@tauri-apps/api/app';
import type { AppStatus, ChatMessage, Mode } from './types';
import Sidebar from './components/Sidebar';
import Chat from './components/Chat';
import ArchiveModal from './components/ArchiveModal';
import Onboarding from './components/Onboarding';

const API = 'http://localhost:8000';

type UpdateState = 'idle' | 'checking' | 'up-to-date' | 'available' | 'error';

function useUpdateCheck() {
  const [state, setState] = useState<UpdateState>('idle');
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [releaseUrl, setReleaseUrl] = useState<string | null>(null);

  async function check() {
    setState('checking');
    try {
      const current = await getVersion();
      const res = await fetch('https://api.github.com/repos/vlad-codes/telmi-journal/releases/latest');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const latest = (data.tag_name as string).replace(/^v/, '');
      setLatestVersion(latest);
      setReleaseUrl(data.html_url as string);
      setState(latest !== current ? 'available' : 'up-to-date');
    } catch {
      setState('error');
    }
  }

  return { state, latestVersion, releaseUrl, check };
}

interface StatusResponse {
  ollama_running: boolean;
  models: string[];
  embedding_ok: boolean;
}

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';
export type ModelStatus = 'ready' | 'switching' | 'saving';

export default function App() {
  const [appStatus, setAppStatus] = useState<AppStatus>('loading');
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [mode, setMode] = useState<Mode>('day');
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [sessionKey, setSessionKey] = useState<Record<Mode, number>>({ day: 0, mind: 0 });
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveTimestamp, setArchiveTimestamp] = useState<string | undefined>(undefined);
  const [isDark, setIsDark] = useState(() => localStorage.getItem('theme') === 'dark');
  const [calendarRefreshKey, setCalendarRefreshKey] = useState(0);
  const [isReturning, setIsReturning] = useState(() => !!localStorage.getItem('telmi_introduced'));
  const [modelStatus, setModelStatus] = useState<ModelStatus>('ready');
  const switchingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const update = useUpdateCheck();

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
  }, [isDark]);

  const historyRef = useRef<Record<Mode, ChatMessage[]>>({ day: [], mind: [] });
  const savedRef = useRef<Record<Mode, boolean>>({ day: false, mind: false });
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (appStatus === 'ready' || appStatus === 'no-ollama' || appStatus === 'no-model') return;
    let cancelled = false;

    async function poll() {
      while (!cancelled) {
        try {
          const r = await fetch(`${API}/status`);
          if (!r.ok) throw new Error('not ok');
          const s: StatusResponse = await r.json();
          if (cancelled) return;

          if (!s.ollama_running) {
            const installed: boolean = await invoke('check_ollama_installed');
            if (cancelled) return;
            if (!installed) { setAppStatus('no-ollama'); return; }
            // Installed but not yet running — show spinner and keep polling
            if (appStatus !== 'starting-ollama') setAppStatus('starting-ollama');
            await new Promise((res) => setTimeout(res, 1000));
            continue;
          }

          if (s.models.length === 0) { setAppStatus('no-model'); return; }
          setModels(s.models); setSelectedModel(s.models[0]); setAppStatus('ready'); return;
        } catch {
          await new Promise((res) => setTimeout(res, 1200));
        }
      }
    }

    poll();
    return () => { cancelled = true; };
  }, [appStatus]); // eslint-disable-line react-hooks/exhaustive-deps

  // Tauri close handler — auto-save all modes with unsaved history
  useEffect(() => {
    if (appStatus !== 'ready') return;
    const win = getCurrentWindow();
    let unlistenFn: (() => void) | null = null;

    win.onCloseRequested(async (event) => {
      event.preventDefault();
      try {
        const modes: Mode[] = ['day', 'mind'];
        for (const m of modes) {
          const h = historyRef.current[m];
          if (!savedRef.current[m] && h.length > 1) {
            await doSave(m, h);
          }
        }
      } catch {}
      await invoke('quit_app');
    }).then((fn) => { unlistenFn = fn; });

    return () => { unlistenFn?.(); };
  }, [appStatus]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleModelChange(model: string) {
    setSelectedModel(model);
    setModelStatus('switching');
    if (switchingTimerRef.current) clearTimeout(switchingTimerRef.current);
    switchingTimerRef.current = setTimeout(() => setModelStatus('ready'), 2000);
  }

  async function doSave(m: Mode, history: ChatMessage[]): Promise<boolean> {
    if (history.length <= 1) return false;
    setSaveStatus('saving');
    setModelStatus('saving');
    try {
      const res = await fetch(`${API}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: m, history, selected_model: selectedModel }),
      });
      if (!res.ok) throw new Error('save failed');
      savedRef.current[m] = true;
      localStorage.setItem('telmi_introduced', '1');
      setIsReturning(true);
      setSaveStatus('saved');
      setModelStatus('ready');
      setCalendarRefreshKey((k) => k + 1);
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2500);
      return true;
    } catch {
      setSaveStatus('error');
      setModelStatus('ready');
      return false;
    }
  }

  function handleHistoryChange(m: Mode, history: ChatMessage[]) {
    historyRef.current[m] = history;
    savedRef.current[m] = false;
  }

  async function handleNewSession() {
    const history = historyRef.current[mode];
    if (!savedRef.current[mode] && history.length > 1) {
      await doSave(mode, history);
    }
    savedRef.current[mode] = false;
    historyRef.current[mode] = [];
    setSessionKey((prev) => ({ ...prev, [mode]: prev[mode] + 1 }));
  }

  function handleDayClick(timestamp: string) {
    setArchiveTimestamp(timestamp);
    setArchiveOpen(true);
  }

  function handleArchiveClose() {
    setArchiveOpen(false);
    setArchiveTimestamp(undefined);
  }

  if (appStatus !== 'ready') {
    return <Onboarding status={appStatus} onRetry={() => setAppStatus('loading')} />;
  }

  return (
    <div className="flex h-screen overflow-hidden w-full">
      <Sidebar
        models={models}
        selectedModel={selectedModel}
        onModelChange={handleModelChange}
        modelStatus={modelStatus}
        mode={mode}
        onModeChange={setMode}
        onOpenArchive={() => setArchiveOpen(true)}
        onDayClick={handleDayClick}
        calendarRefreshKey={calendarRefreshKey}
        saveStatus={saveStatus}
        onNewSession={handleNewSession}
      />
      {archiveOpen && (
        <ArchiveModal
          onClose={handleArchiveClose}
          initialChatTimestamp={archiveTimestamp}
        />
      )}
      {/* Update check button */}
      <div className="fixed top-[9px] right-14 z-20 flex items-center">
        {update.state === 'idle' && (
          <button
            onClick={update.check}
            className="h-[22px] px-2 flex items-center rounded-md text-[10px]
                       text-slate-400 dark:text-slate-500
                       border border-slate-200/70 dark:border-white/[0.08]
                       hover:text-slate-600 dark:hover:text-slate-300
                       hover:border-slate-300/80 dark:hover:border-white/[0.14]
                       transition-all duration-150"
          >
            Check for updates
          </button>
        )}
        {update.state === 'checking' && (
          <span className="h-[22px] px-2 flex items-center rounded-md text-[10px]
                           text-slate-400 dark:text-slate-500
                           border border-slate-200/70 dark:border-white/[0.08]">
            Checking…
          </span>
        )}
        {update.state === 'up-to-date' && (
          <span className="h-[22px] px-2 flex items-center rounded-md text-[10px]
                           text-emerald-500 dark:text-emerald-400
                           border border-emerald-300/50 dark:border-emerald-400/25">
            Up to date
          </span>
        )}
        {update.state === 'available' && (
          <a
            href={update.releaseUrl ?? '#'}
            target="_blank"
            rel="noreferrer"
            className="h-[22px] px-2 flex items-center rounded-md text-[10px]
                       text-indigo-500 dark:text-indigo-400
                       border border-indigo-300/50 dark:border-indigo-400/25
                       hover:border-indigo-400/70 dark:hover:border-indigo-400/50
                       transition-all duration-150"
          >
            v{update.latestVersion} available →
          </a>
        )}
        {update.state === 'error' && (
          <button
            onClick={update.check}
            className="h-[22px] px-2 flex items-center rounded-md text-[10px]
                       text-red-400 dark:text-red-400
                       border border-red-300/50 dark:border-red-400/25
                       hover:border-red-400/70 dark:hover:border-red-400/50
                       transition-all duration-150"
          >
            Retry
          </button>
        )}
      </div>

      <button
        onClick={() => setIsDark((d) => !d)}
        aria-label="Toggle dark mode"
        className="fixed top-1 right-4 z-20
                   w-8 h-8 flex items-center justify-center rounded-lg
                   text-slate-400 dark:text-slate-500
                   hover:text-slate-600 dark:hover:text-slate-300
                   hover:bg-slate-100/70 dark:hover:bg-white/[0.07]
                   transition-all duration-150"
      >
        {isDark ? (
          <svg className="w-[15px] h-[15px]" fill="none" viewBox="0 0 24 24"
               stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M12 3v2m0 14v2M5.636 5.636l1.414 1.414m9.9 9.9 1.414 1.414M3 12h2m14 0h2M5.636 18.364l1.414-1.414m9.9-9.9 1.414-1.414M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z" />
          </svg>
        ) : (
          <svg className="w-[15px] h-[15px]" fill="none" viewBox="0 0 24 24"
               stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        )}
      </button>
      <main className="flex-1 overflow-hidden chat-bg">
        <Chat
          key={`${mode}-${sessionKey[mode]}`}
          mode={mode}
          selectedModel={selectedModel}
          isReturning={isReturning}
          onHistoryChange={(h) => handleHistoryChange(mode, h)}
        />
      </main>
    </div>
  );
}
