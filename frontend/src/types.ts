export type Mode = 'day' | 'mind';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface SaveResponse {
  title: string;
  summary: string;
  timestamp: string;
  profile_update: string | null;
}

export interface Entry {
  timestamp: string;
  title: string;
  summary: string;
  has_chat: boolean;
}

export interface CalendarDay {
  date: string;      // YYYY-MM-DD
  timestamp: string; // full "YYYY-MM-DD HH:MM:SS"
  title: string;
  summary: string;
}

export interface StatsData {
  streak: number;
  total: number;
  this_month: number;
  avg_per_week: number;
  achievements: string[];
}
