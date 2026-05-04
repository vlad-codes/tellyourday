import { useEffect, useRef, useState } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import type { KeyboardEvent } from 'react';
import type { ChatMessage, Mode } from '../types';
import ChatMessageBubble from './ChatMessage';
const API = 'http://localhost:8000';

const INTRO_FIRST: Record<Mode, string> = {
  day: "Hey. I'm Telmi.\n\nTell me what's been going on. Whatever's on your mind — I'm here.",
  mind: "Hey. I'm Telmi.\n\nBring me something you haven't quite worked out. A situation, a decision, something you keep circling. We'll look at it together.",
};

const INTRO_RETURNING: Record<Mode, string> = {
  day: "Hey. What's been going on?",
  mind: "What are you trying to figure out?",
};

interface ChatProps {
  mode: Mode;
  selectedModel: string;
  isReturning: boolean;
  onHistoryChange: (history: ChatMessage[]) => void;
}

export default function Chat({
  mode,
  selectedModel,
  isReturning,
  onHistoryChange,
}: ChatProps) {
  const intro = isReturning ? INTRO_RETURNING[mode] : INTRO_FIRST[mode];
  const initialHistory: ChatMessage[] = [{ role: 'assistant', content: intro }];
  const [history, setHistory] = useState<ChatMessage[]>(initialHistory);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    onHistoryChange(history);
  }, [history]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  async function sendMessage(text: string) {
    if (!text.trim() || isStreaming) return;
    setError(null);

    const userMsg: ChatMessage = { role: 'user', content: text.trim() };
    const nextHistory = [...history, userMsg];
    setHistory(nextHistory);
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    setHistory((h) => [...h, { role: 'assistant', content: '' }]);
    setIsStreaming(true);

    abortRef.current = new AbortController();

    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: userMsg.content,
          mode,
          history: nextHistory,
          selected_model: selectedModel,
        }),
        signal: abortRef.current.signal,
      });

      if (!res.ok) throw new Error(`Server error ${res.status}`);

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let accumulated = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        accumulated += decoder.decode(value, { stream: true });
        setHistory((h) => [
          ...h.slice(0, -1),
          { role: 'assistant', content: accumulated },
        ]);
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('fetch') || msg.includes('NetworkError') || msg.includes('Failed')) {
        setError('Cannot reach the backend. Is `uvicorn api:app` running on port 8000?');
      } else {
        setError(msg);
      }
      setHistory((h) => h.slice(0, -1));
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
  }

  const modeLabel = mode === 'day' ? 'Your Day' : 'Your Mind';
  const modeIcon = mode === 'day' ? '📓' : '💭';

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div
        className="shrink-0 px-6 flex items-center gap-2.5
                   border-b border-slate-200/50 dark:border-white/[0.07]
                   bg-white/30 dark:bg-white/[0.03] backdrop-blur-sm"
        style={{ paddingTop: '12px', paddingBottom: '12px' }}
        onMouseDown={() => getCurrentWindow().startDragging()}
      >
        <span className="text-base leading-none">{modeIcon}</span>
        <h2 className="text-[13px] font-semibold text-slate-700 dark:text-slate-200 tracking-tight">
          {modeLabel}
        </h2>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="max-w-2xl mx-auto">
          {history.map((msg, i) => {
            const isLast = i === history.length - 1;
            const isStreamingThis = isLast && isStreaming && msg.role === 'assistant';
            return (
              <ChatMessageBubble
                key={i}
                message={msg}
                isStreaming={isStreamingThis}
              />
            );
          })}

          {error && (
            <div className="fade-in mt-3 rounded-2xl
                            bg-red-50/80 dark:bg-red-900/20
                            border border-red-200/60 dark:border-red-700/40
                            text-red-700 dark:text-red-400 text-[13px] p-3.5 leading-relaxed
                            backdrop-blur-sm">
              {error}
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Floating input */}
      <div className="shrink-0 px-4 pb-4 pt-2">
        <div className="max-w-2xl mx-auto">
          <div
            className="input-float flex items-end gap-2 rounded-2xl
                       bg-white/90 dark:bg-slate-800/80
                       border border-slate-200/70 dark:border-white/[0.09]
                       backdrop-blur-md
                       focus-within:ring-2 focus-within:ring-indigo-400/30
                       focus-within:border-indigo-300/60 dark:focus-within:border-indigo-500/40
                       px-4 py-3 transition-all duration-200"
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              placeholder={mode === 'day' ? 'How was your day?' : "What's on your mind?"}
              className="flex-1 resize-none bg-transparent text-[14px]
                         text-slate-800 dark:text-slate-100
                         placeholder-slate-400 dark:placeholder-slate-500
                         focus:outline-none leading-relaxed
                         min-h-[22px] max-h-40
                         disabled:opacity-50 disabled:cursor-not-allowed"
            />
            {isStreaming ? (
              <button
                onClick={() => abortRef.current?.abort()}
                aria-label="Stop"
                className="shrink-0 w-8 h-8 rounded-xl
                           bg-slate-200 hover:bg-slate-300 active:bg-slate-400
                           dark:bg-slate-600 dark:hover:bg-slate-500
                           text-slate-600 dark:text-slate-200 flex items-center justify-center
                           transition-all duration-150 mb-0.5"
              >
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="4" y="4" width="16" height="16" rx="2" />
                </svg>
              </button>
            ) : (
              <button
                onClick={() => sendMessage(input)}
                disabled={!input.trim()}
                aria-label="Send"
                className="shrink-0 w-8 h-8 rounded-xl
                           bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700
                           dark:bg-indigo-500 dark:hover:bg-indigo-400
                           text-white flex items-center justify-center
                           transition-all duration-150 mb-0.5
                           shadow-sm shadow-indigo-500/30
                           disabled:opacity-30 disabled:cursor-not-allowed
                           disabled:shadow-none"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18" />
                </svg>
              </button>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
