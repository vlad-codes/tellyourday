import { useEffect, useMemo, useRef, useState } from 'react';
import type { CalendarDay, StatsData } from '../types';

const API = 'http://localhost:8000';

const WEEKDAY_LABELS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

interface Props {
  onDayClick: (timestamp: string) => void;
  onOpenArchive: () => void;
  refreshKey: number;
}

function streakMessage(n: number): { num: string | null; label: string } {
  if (n === 0)   return { num: null, label: 'Start today.' };
  if (n === 1)   return { num: null, label: 'Day one.' };
  if (n === 7)   return { num: null, label: 'One week straight.' };
  if (n === 14)  return { num: null, label: 'Two weeks straight.' };
  if (n === 21)  return { num: null, label: 'Three weeks straight.' };
  if (n === 30)  return { num: null, label: 'Thirty days. Impressive.' };
  if (n === 100) return { num: null, label: '100 days. Seriously.' };
  if (n === 365) return { num: null, label: 'A full year.' };
  return { num: String(n), label: 'days in a row.' };
}

function computeStreak(days: CalendarDay[]): number {
  const dates = new Set(days.map((d) => d.date));
  const cursor = new Date();
  let streak = 0;
  while (true) {
    const key = cursor.toISOString().slice(0, 10);
    if (!dates.has(key)) break;
    streak++;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

const ACHIEVEMENTS: { id: string; icon: string; label: string }[] = [
  { id: 'first_entry', icon: '✍️', label: 'First Entry' },
  { id: 'week_streak', icon: '🔥', label: 'Week Streak' },
  { id: 'month_streak', icon: '💪', label: 'Month Strong' },
  { id: 'bookworm',     icon: '📖', label: 'Bookworm (50 entries)' },
  { id: 'century',      icon: '💯', label: 'Century Club (100 entries)' },
];

const STREAK_MILESTONES = [3, 7, 14, 21, 30, 100, 365];

function nextStreakMilestone(streak: number): { next: number; prev: number } | null {
  const next = STREAK_MILESTONES.find((m) => m > streak);
  if (next === undefined) return null;
  const prev = [...STREAK_MILESTONES].reverse().find((m) => m <= streak) ?? 0;
  return { next, prev };
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number): number {
  // Monday = 0 … Sunday = 6
  return (new Date(year, month, 1).getDay() + 6) % 7;
}

function toDateKey(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export default function LifeDashboard({ onDayClick, onOpenArchive, refreshKey }: Props) {
  const today = useMemo(() => new Date(), []);
  const todayKey = useMemo(() => today.toISOString().slice(0, 10), [today]);

  const [calDays, setCalDays] = useState<CalendarDay[]>([]);
  const [fetchError, setFetchError] = useState(false);
  const [currentMonth, setCurrentMonth] = useState<Date>(
    new Date(today.getFullYear(), today.getMonth(), 1),
  );
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const [hoverPos, setHoverPos] = useState<{ top: number; left: number } | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [statsOpen, setStatsOpen] = useState(false);
  const [statsPinned, setStatsPinned] = useState(false);
  const [statsPos, setStatsPos] = useState<{ bottom: number; left: number } | null>(null);
  const statsButtonRef = useRef<HTMLButtonElement>(null);
  const statsCloseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [hoveredBadge, setHoveredBadge] = useState<string | null>(null);

  useEffect(() => {
    if (!statsOpen) return;
    fetch(`${API}/stats`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data) setStats(data as StatsData); })
      .catch(() => {});
  }, [statsOpen, refreshKey]);

  function statsMouseEnter() {
    if (statsCloseTimer.current) clearTimeout(statsCloseTimer.current);
    const rect = statsButtonRef.current?.getBoundingClientRect();
    if (rect) setStatsPos({ bottom: window.innerHeight - rect.bottom, left: rect.right + 10 });
    setStatsOpen(true);
  }

  function statsMouseLeave() {
    if (statsPinned) return;
    statsCloseTimer.current = setTimeout(() => setStatsOpen(false), 80);
  }

  useEffect(() => {
    if (!statsPinned) return;
    function handleOutside(e: MouseEvent) {
      if (!statsButtonRef.current?.contains(e.target as Node)) {
        setStatsPinned(false);
        setStatsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [statsPinned]);

  useEffect(() => {
    setFetchError(false);
    fetch(`${API}/calendar-data`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: unknown) => {
        if (!Array.isArray(data)) return;
        setCalDays(data as CalendarDay[]);
      })
      .catch(() => setFetchError(true));
  }, [refreshKey]);

  // Keep last entry per date (chronological order → last wins)
  const entriesByDate = useMemo(() => {
    const map = new Map<string, CalendarDay>();
    for (const d of calDays) map.set(d.date, d);
    return map;
  }, [calDays]);

  const streak = useMemo(() => computeStreak(calDays), [calDays]);

  const year = currentMonth.getFullYear();
  const month = currentMonth.getMonth();
  const daysInMonth = getDaysInMonth(year, month);
  const firstDow = getFirstDayOfWeek(year, month);
  const isCurrentMonth = year === today.getFullYear() && month === today.getMonth();

  function prevMonth() {
    setCurrentMonth(new Date(year, month - 1, 1));
  }
  function nextMonth() {
    setCurrentMonth(new Date(year, month + 1, 1));
  }

  function handleDayEnter(date: string, e: React.MouseEvent) {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setHoverPos({ top: rect.top - 8, left: rect.right + 10 });
    setHoveredDate(date);
  }
  function handleDayLeave() {
    setHoveredDate(null);
    setHoverPos(null);
  }

  const hoveredEntry = hoveredDate ? (entriesByDate.get(hoveredDate) ?? null) : null;

  // Build grid: leading empty cells + day numbers
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  return (
    <div className="border-t border-slate-200/60 dark:border-white/[0.06]">
      {/* Header toggle */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="w-full px-4 pt-3 pb-2 flex items-center justify-between
                   hover:bg-white/30 dark:hover:bg-white/[0.03] transition-colors duration-150"
      >
        <span className="text-[10px] font-semibold text-slate-400 dark:text-slate-500
                         uppercase tracking-widest">
          Your Journey
        </span>
        <span
          className={`text-[11px] text-slate-400 dark:text-slate-500
                      transition-transform duration-200 leading-none
                      ${collapsed ? '' : 'rotate-180'}`}
        >
          ▾
        </span>
      </button>

      {/* Calendar — collapsible */}
      {!collapsed && (
        <div className="px-3 pb-3 fade-in">
          {/* Month navigation */}
          <div className="flex items-center justify-between mb-2 px-0.5">
            <button
              onClick={prevMonth}
              className="w-6 h-6 flex items-center justify-center rounded-lg
                         text-slate-400 dark:text-slate-500
                         hover:text-indigo-500 dark:hover:text-indigo-400
                         hover:bg-indigo-50/60 dark:hover:bg-indigo-900/30
                         transition-colors duration-100 text-[13px] leading-none"
            >
              ‹
            </button>
            <span className="text-[11px] font-medium text-slate-600 dark:text-slate-300 tabular-nums">
              {MONTH_NAMES[month]} {year}
            </span>
            <button
              onClick={nextMonth}
              disabled={isCurrentMonth}
              className="w-6 h-6 flex items-center justify-center rounded-lg
                         text-slate-400 dark:text-slate-500
                         hover:text-indigo-500 dark:hover:text-indigo-400
                         hover:bg-indigo-50/60 dark:hover:bg-indigo-900/30
                         transition-colors duration-100 text-[13px] leading-none
                         disabled:opacity-20 disabled:cursor-default disabled:hover:bg-transparent
                         disabled:hover:text-slate-400"
            >
              ›
            </button>
          </div>

          {/* Weekday headers */}
          <div className="grid grid-cols-7 mb-1">
            {WEEKDAY_LABELS.map((d) => (
              <div
                key={d}
                className="text-center text-[9px] font-semibold
                           text-slate-400/70 dark:text-slate-600 py-0.5 uppercase tracking-wide"
              >
                {d}
              </div>
            ))}
          </div>

          {/* Day cells */}
          <div className="grid grid-cols-7 gap-y-0.5">
            {cells.map((day, i) => {
              if (!day) return <div key={`e-${i}`} />;

              const dateKey = toDateKey(year, month, day);
              const hasEntry = entriesByDate.has(dateKey);
              const isToday = dateKey === todayKey;
              const entry = entriesByDate.get(dateKey);

              return (
                <div
                  key={dateKey}
                  onMouseEnter={hasEntry ? (e) => handleDayEnter(dateKey, e) : undefined}
                  onMouseLeave={hasEntry ? handleDayLeave : undefined}
                  onClick={hasEntry && entry ? () => onDayClick(entry.timestamp) : undefined}
                  className={[
                    'relative flex flex-col items-center justify-start',
                    'pt-0.5 pb-1.5 rounded-lg select-none',
                    'text-[11px] tabular-nums leading-5',
                    'transition-colors duration-100',
                    isToday
                      ? 'ring-1 ring-indigo-400/50 dark:ring-indigo-400/35 bg-indigo-50/60 dark:bg-indigo-900/25'
                      : '',
                    hasEntry
                      ? 'cursor-pointer font-medium text-slate-700 dark:text-slate-200 hover:bg-indigo-50/80 dark:hover:bg-indigo-900/30'
                      : 'text-slate-400/60 dark:text-slate-600',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  {day}
                  {hasEntry && (
                    <span className="absolute bottom-0.5 w-[5px] h-[5px] rounded-full
                                     bg-indigo-500 dark:bg-indigo-400" />
                  )}
                </div>
              );
            })}
          </div>

        </div>
      )}

      {/* Action buttons */}
      <div className="px-3 pb-3 pt-1 flex gap-1">
        <button
          onClick={onOpenArchive}
          className="flex-1 text-[13px] rounded-xl px-3 py-2.5
                     flex items-center justify-center gap-2 group
                     text-slate-500 dark:text-slate-400
                     hover:bg-white/50 dark:hover:bg-white/[0.06]
                     border border-transparent
                     hover:border-slate-200/60 dark:hover:border-white/[0.08]
                     transition-all duration-150"
        >
          <svg className="w-4 h-4 text-slate-400 dark:text-slate-500 group-hover:text-indigo-500 dark:group-hover:text-indigo-400 transition-colors"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <circle cx="11" cy="11" r="7" />
            <path strokeLinecap="round" d="m21 21-4.35-4.35" />
          </svg>
          <span>Archive</span>
        </button>
        <button
          ref={statsButtonRef}
          onMouseEnter={statsMouseEnter}
          onMouseLeave={statsMouseLeave}
          onClick={() => {
            if (statsPinned) { setStatsPinned(false); setStatsOpen(false); }
            else setStatsPinned(true);
          }}
          className="flex-1 text-[13px] rounded-xl px-3 py-2.5
                     flex items-center justify-center gap-2 group
                     text-slate-500 dark:text-slate-400
                     hover:bg-white/50 dark:hover:bg-white/[0.06]
                     border border-transparent
                     hover:border-slate-200/60 dark:hover:border-white/[0.08]
                     transition-all duration-150"
        >
          <svg className="w-4 h-4 text-slate-400 dark:text-slate-500 group-hover:text-indigo-500 dark:group-hover:text-indigo-400 transition-colors"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.5h4.5v6H3v-6zm6.75-6H14.25v12H9.75V7.5zm6.75 3H21v9h-4.5v-9z" />
          </svg>
          <span>Stats</span>
        </button>
      </div>

      {/* Stats popup */}
      {statsOpen && statsPos && (
        <div
          className="glass-popup fixed z-[200] w-56 rounded-2xl p-4"
          style={{ bottom: statsPos.bottom, left: statsPos.left }}
          onMouseEnter={() => { if (statsCloseTimer.current) clearTimeout(statsCloseTimer.current); }}
          onMouseLeave={statsMouseLeave}
        >
          {/* Tail */}
          <div className="absolute -left-1.5 bottom-4 w-3 h-3 rotate-45
                          bg-white/88 dark:bg-slate-900/88
                          border-l border-b border-slate-200/60 dark:border-white/[0.09]" />

          <p className="text-[10px] font-semibold text-indigo-500 dark:text-indigo-400
                        uppercase tracking-widest mb-3">
            Your stats
          </p>

          {/* Streak hero */}
          {(() => {
            const s = stats?.streak ?? streak;
            const milestone = nextStreakMilestone(s);
            const progress = milestone
              ? (s - milestone.prev) / (milestone.next - milestone.prev)
              : 1;
            return (
              <div className="mb-3">
                <div className="flex items-baseline gap-1.5 mb-0.5">
                  {s > 0 && <span className="text-[13px]">🔥</span>}
                  <span className="text-[22px] font-bold leading-none
                                   text-amber-500 dark:text-amber-400">
                    {s}
                  </span>
                  <span className="text-[11px] text-slate-400 dark:text-slate-500">
                    {s === 1 ? 'day in a row' : 'days in a row'}
                  </span>
                </div>
                {milestone ? (
                  <div className="flex items-center gap-2 mt-1.5">
                    <div className="flex-1 h-0.5 rounded-full bg-slate-200 dark:bg-white/[0.08] overflow-hidden">
                      <div
                        className="h-full rounded-full bg-indigo-500 dark:bg-indigo-400 transition-all duration-500"
                        style={{ width: `${Math.min(progress * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500 shrink-0">
                      → {milestone.next}d
                    </span>
                  </div>
                ) : (
                  <p className="text-[10px] text-indigo-400 dark:text-indigo-500 mt-1">✦ Legend</p>
                )}
              </div>
            );
          })()}

          {/* Counts grid */}
          <div className="grid grid-cols-2 gap-x-3 gap-y-2 mb-3">
            {[
              { val: stats?.total ?? '—', label: 'total' },
              { val: stats?.this_month ?? '—', label: 'this month' },
            ].map(({ val, label }) => (
              <div key={label}>
                <div className="text-[18px] font-bold leading-none
                                text-slate-700 dark:text-slate-100">
                  {val}
                </div>
                <div className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">
                  {label}
                </div>
              </div>
            ))}
            <div className="col-span-2">
              <span className="text-[15px] font-semibold text-slate-700 dark:text-slate-100">
                {stats?.avg_per_week ?? '—'}
              </span>
              <span className="text-[10px] text-slate-400 dark:text-slate-500 ml-1.5">
                per week
              </span>
            </div>
          </div>

          {/* Badge shelf */}
          <div className="pt-2.5 border-t border-slate-200/60 dark:border-white/[0.07]">
            <p className="text-[10px] font-semibold text-indigo-500 dark:text-indigo-400
                          uppercase tracking-widest mb-2">
              Achievements
            </p>
            <div className="flex gap-1.5">
              {ACHIEVEMENTS.map(({ id, icon, label }) => {
                const earned = stats?.achievements.includes(id) ?? false;
                return (
                  <span
                    key={id}
                    onMouseEnter={() => setHoveredBadge(label)}
                    onMouseLeave={() => setHoveredBadge(null)}
                    className="text-[16px] leading-none transition-opacity duration-200 cursor-default"
                    style={{ opacity: earned ? 1 : 0.15 }}
                  >
                    {icon}
                  </span>
                );
              })}
            </div>
            <div className="h-3.5 mt-1">
              {hoveredBadge && (
                <p className="text-[10px] text-slate-400 dark:text-slate-500 truncate">
                  {hoveredBadge}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Hover popup — fixed, appears to the right of the sidebar */}
      {hoveredEntry && hoverPos && (
        <div
          className="glass-popup fixed z-[200] w-52 rounded-2xl p-3.5 pointer-events-none"
          style={{ top: hoverPos.top, left: hoverPos.left }}
        >
          <div className="text-[10px] font-semibold text-indigo-500 dark:text-indigo-400
                          uppercase tracking-wider mb-1.5">
            {new Date(`${hoveredDate}T12:00:00`).toLocaleDateString('en-GB', {
              day: 'numeric',
              month: 'long',
              year: 'numeric',
            })}
          </div>
          <div className="text-[13px] font-semibold text-slate-800 dark:text-slate-100
                          mb-1.5 leading-snug">
            {hoveredEntry.title || '—'}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400
                          leading-relaxed line-clamp-4">
            {hoveredEntry.summary}
          </div>
          <div className="mt-2.5 text-[10px] text-indigo-400/60 dark:text-indigo-500/60
                          flex items-center gap-1">
            <span>Open chat</span>
            <span>→</span>
          </div>
        </div>
      )}
    </div>
  );
}
