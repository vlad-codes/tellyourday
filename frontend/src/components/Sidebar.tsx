import { getCurrentWindow } from '@tauri-apps/api/window';
import type { Mode } from '../types';
import LifeDashboard from './LifeDashboard';

interface SidebarProps {
  models: string[];
  selectedModel: string;
  onModelChange: (model: string) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onOpenArchive: () => void;
  onDayClick: (timestamp: string) => void;
  isDark: boolean;
  onToggleDark: () => void;
  calendarRefreshKey: number;
}

export default function Sidebar({
  models,
  selectedModel,
  onModelChange,
  mode,
  onModeChange,
  onOpenArchive,
  onDayClick,
  isDark,
  onToggleDark,
  calendarRefreshKey,
}: SidebarProps) {
  return (
    <aside className="glass-sidebar w-60 shrink-0 flex flex-col h-full z-10">
      {/* Traffic-light drag region */}
      <div
        className="h-10 shrink-0 cursor-default"
        onMouseDown={() => getCurrentWindow().startDragging()}
      />

      {/* App identity */}
      <div className="px-5 pb-4 flex items-end justify-between shrink-0">
        <div>
          <h1 className="text-[15px] font-semibold tracking-tight text-slate-800 dark:text-slate-100 leading-none">
            Telmi
          </h1>
          <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-1 leading-none">
            Your private journal AI
          </p>
        </div>
        <button
          onClick={onToggleDark}
          aria-label="Toggle dark mode"
          className="text-sm text-slate-400 dark:text-slate-500
                     hover:text-slate-600 dark:hover:text-slate-300
                     transition-colors duration-150 leading-none mb-0.5"
        >
          {isDark ? '○' : '●'}
        </button>
      </div>

      {/* Scrollable main content */}
      <div className="flex flex-col gap-4 px-3 py-3 flex-1 min-h-0 overflow-y-auto">

        {/* Mode selector */}
        <div>
          <span className="block text-[10px] font-semibold text-slate-400 dark:text-slate-500
                           uppercase tracking-widest px-2 mb-2">
            Mode
          </span>
          <div className="flex flex-col gap-1">
            <ModeButton
              active={mode === 'day'}
              onClick={() => onModeChange('day')}
              icon="📓"
              label="Your Day"
            />
            <ModeButton
              active={mode === 'mind'}
              onClick={() => onModeChange('mind')}
              icon="💭"
              label="Your Mind"
            />
          </div>
        </div>

        {/* Divider */}
        <div className="h-px bg-slate-200/60 dark:bg-white/[0.06] mx-2" />

        {/* Model selector */}
        <div>
          <label className="block text-[10px] font-semibold text-slate-400 dark:text-slate-500
                            uppercase tracking-widest px-2 mb-2">
            Model
          </label>
          <div className="relative">
            <select
              value={selectedModel}
              onChange={(e) => onModelChange(e.target.value)}
              disabled={models.length === 0}
              className="w-full appearance-none rounded-xl px-3 py-2 pr-8 text-[13px]
                         bg-white/60 dark:bg-white/[0.06]
                         border border-slate-200/80 dark:border-white/[0.08]
                         text-slate-700 dark:text-slate-200
                         focus:outline-none focus:ring-2 focus:ring-indigo-400/40
                         disabled:opacity-50 cursor-pointer
                         transition-all duration-150"
            >
              {models.length === 0 ? (
                <option value="">Connecting…</option>
              ) : (
                models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))
              )}
            </select>
            <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2
                             text-slate-400 dark:text-slate-500 text-[10px]">
              ▾
            </span>
          </div>
        </div>

      </div>

      {/* Life Dashboard — pinned at bottom */}
      <LifeDashboard onDayClick={onDayClick} onOpenArchive={onOpenArchive} refreshKey={calendarRefreshKey} />
    </aside>
  );
}

function ModeButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: string;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left text-[13px] rounded-xl px-3 py-2.5
        flex items-center gap-2.5 transition-all duration-150
        ${active
          ? 'bg-indigo-500/10 dark:bg-indigo-400/15 text-indigo-700 dark:text-indigo-300 font-medium border border-indigo-300/40 dark:border-indigo-400/20'
          : 'text-slate-600 dark:text-slate-300 hover:bg-white/50 dark:hover:bg-white/[0.06] border border-transparent hover:border-slate-200/60 dark:hover:border-white/[0.08]'
        }`}
    >
      <span className="text-base leading-none">{icon}</span>
      <span>{label}</span>
    </button>
  );
}
