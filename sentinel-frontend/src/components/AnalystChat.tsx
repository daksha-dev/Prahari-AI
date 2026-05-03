import { useState, useRef, useEffect } from 'react';
import { Send, ChevronRight, Minimize2 } from 'lucide-react';
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion';
import type { ChatMessage } from '../lib/types';
import { cn } from '../lib/utils';
import { streamChat } from '../lib/api';
import { useLanguage } from '../lib/language';
import LanguageSelector from './LanguageSelector';

interface AnalystChatProps {
  isOpen: boolean;
  isDesktop?: boolean;
  onClose: () => void;
}

export default function AnalystChat({ isOpen, isDesktop, onClose }: AnalystChatProps) {
  const { language, t } = useLanguage();
  const reduceMotion = useReducedMotion();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isTyping]);

  useEffect(() => {
    if (isOpen) {
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [isOpen]);

  useEffect(() => {
    const handleGlobalFocus = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    const handleRequestedFocus = () => {
      window.setTimeout(() => inputRef.current?.focus(), 0);
    };
    window.addEventListener('keydown', handleGlobalFocus);
    window.addEventListener('sentinel:focus-chat', handleRequestedFocus);
    return () => {
      window.removeEventListener('keydown', handleGlobalFocus);
      window.removeEventListener('sentinel:focus-chat', handleRequestedFocus);
    };
  }, []);

  const handleSend = async () => {
    if (!input.trim() || isTyping) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
    };
    const assistantId = (Date.now() + 1).toString();

    setMessages(prev => [...prev, userMsg, {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
      toolCalls: [],
    }]);
    setInput('');
    setIsTyping(true);

    try {
      await streamChat(
        [...messages, userMsg].map(msg => ({ role: msg.role, content: msg.content })),
        (event) => {
          if (event.type === 'error') {
            setMessages(prev => prev.map(msg => msg.id === assistantId ? {
              ...msg,
              content: event.message,
            } : msg));
          }
          if (event.type === 'tool_call') {
            setMessages(prev => prev.map(msg => msg.id === assistantId ? {
              ...msg,
              toolCalls: [
                ...(msg.toolCalls || []),
                { id: `${event.name}-${Date.now()}`, name: event.name, status: 'pending' },
              ],
            } : msg));
          }
          if (event.type === 'tool_result') {
            setMessages(prev => prev.map(msg => msg.id === assistantId ? {
              ...msg,
              toolCalls: (msg.toolCalls || []).map(call => (
                call.name === event.name ? { ...call, status: 'complete' } : call
              )),
            } : msg));
          }
          if (event.type === 'token') {
            setMessages(prev => prev.map(msg => msg.id === assistantId ? {
              ...msg,
              content: `${msg.content}${event.content}`,
            } : msg));
          }
          if (event.type === 'done') {
            setMessages(prev => prev.map(msg => msg.id === assistantId && !msg.content.trim() ? {
              ...msg,
              content: 'I checked the evidence, but no narrative answer was returned.',
            } : msg));
            setIsTyping(false);
          }
        },
        language,
      );
    } catch (error) {
      console.error('Failed to stream chat', error);
      setMessages(prev => prev.map(msg => msg.id === assistantId ? {
        id: assistantId,
        role: 'assistant',
        content: 'Prahari is briefly unavailable. Evidence remains accessible.',
        timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
        toolCalls: msg.toolCalls,
      } : msg));
    } finally {
      setIsTyping(false);
    }
  };

  const suggestedPrompts = [t('prompt_worry'), t('prompt_unusual'), t('prompt_health')];

  const content = (
    <div className={cn(
      'h-full flex flex-col bg-bg-soft',
      isDesktop ? 'w-[380px] border-l border-border' : 'w-full max-w-[420px]',
    )}>
      <div className="h-[56px] shrink-0 flex items-center justify-between px-6 bg-bg-base border-b border-border">
        <div className="font-caption text-text-secondary tracking-widest uppercase">{t('sentinel_analyst')}</div>
        <div className="flex items-center gap-3">
          <LanguageSelector compact />
          {!isDesktop && (
            <button
              onClick={onClose}
              className="h-8 w-8 cursor-pointer rounded-md text-text-secondary transition-colors duration-150 hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base"
            >
              <Minimize2 size={16} />
            </button>
          )}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 scroll-smooth">
        {messages.length === 0 && (
          <div className="flex h-full flex-col justify-center gap-6">
            <div className="font-caption text-text-tertiary uppercase tracking-wider">{t('ask_anything')}</div>
            <div className="flex w-full flex-col gap-2">
              {suggestedPrompts.map((q, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setInput(q);
                    window.setTimeout(() => inputRef.current?.focus(), 0);
                  }}
                  className="flex h-10 w-full cursor-pointer items-center justify-between border-l border-border bg-transparent px-3 text-left font-sans text-body text-text-primary transition-colors duration-150 hover:border-accent hover:bg-bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base"
                >
                  {q}
                  <ChevronRight size={14} className="text-text-tertiary transition-colors duration-150 group-hover:text-accent" />
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-y-6">
          {messages.map((msg) => (
            <div key={msg.id} className={cn('flex flex-col gap-y-2', msg.role === 'user' ? 'items-end' : 'items-start')}>
              <div className={cn(
                'max-w-full whitespace-pre-wrap font-sans text-body leading-relaxed',
                msg.role === 'user' ? 'rounded-sm bg-accent px-4 py-3 text-bg-base' : 'text-text-primary',
              )}>
                {msg.content || (msg.role === 'assistant' && isTyping && !msg.toolCalls?.length ? '...' : '')}
              </div>

              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div className="w-full space-y-1">
                  {msg.toolCalls.map((call) => (
                    <div key={call.id} className="flex items-center gap-2 font-mono text-[10px] text-text-secondary">
                      <span className="opacity-50">---</span>
                      <span className="uppercase">{call.status === 'complete' ? t('consulted') : t('consulting')} {call.name}</span>
                      <span className="flex-1 border-b border-border border-dashed opacity-50" />
                    </div>
                  ))}
                </div>
              )}

              {msg.citations && msg.citations.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {msg.citations.map((cite) => (
                    <button key={cite.id} className="h-8 cursor-pointer rounded-md border border-border bg-bg-elevated px-2 font-mono text-[10px] text-text-tertiary transition-colors duration-150 hover:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base">
                      {cite.label}
                    </button>
                  ))}
                </div>
              )}

              <span className="font-mono text-[10px] text-text-tertiary uppercase">{msg.timestamp}</span>
            </div>
          ))}

          {isTyping && !messages[messages.length - 1]?.content && (
            <div className="flex flex-col gap-2 items-start">
              <div className="font-mono text-[10px] text-accent">{t('sentinel_analyzing')}</div>
            </div>
          )}
        </div>
      </div>

      <div
        className="h-20 shrink-0 cursor-text bg-bg-base border-t border-border px-6 py-4"
        onClick={() => inputRef.current?.focus()}
      >
        <div className="relative flex h-full flex-col gap-2">
          <textarea
            ref={inputRef}
            value={input}
            disabled={false}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={t('ask_placeholder')}
            className="h-8 min-h-8 w-full resize-none border-none bg-transparent p-0 text-body text-text-primary outline-none placeholder:text-text-tertiary focus-visible:ring-0"
            rows={1}
          />
          <div className="flex items-center justify-between border-t border-border/50 pt-2">
            <span className="font-caption text-text-tertiary text-[10px]">{t('enter_to_send')}</span>
            <button
              onClick={handleSend}
              disabled={!input.trim() || isTyping}
              className="h-8 w-8 cursor-pointer rounded-md text-text-secondary transition-colors duration-150 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:text-text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-base"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  if (isDesktop) return content;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-bg-base/80 backdrop-blur-sm z-50"
          />
          <motion.div
            initial={reduceMotion ? { opacity: 0 } : { x: '100%' }}
            animate={reduceMotion ? { opacity: 1 } : { x: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { x: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed right-0 top-0 bottom-0 z-[70] flex w-full max-w-[420px] flex-col bg-bg-soft"
          >
            {content}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
