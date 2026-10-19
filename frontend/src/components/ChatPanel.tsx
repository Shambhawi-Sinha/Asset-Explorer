/**
 * ChatPanel.tsx — RAG diagnostic chatbot panel
 *
 * Used in AssetDrillDown, scoped to the currently selected asset.
 * Sends question to POST /api/chat — FastAPI calls Azure OpenAI + Azure AI Search.
 * All Azure credentials stay server-side (BFF pattern).
 *
 * Features:
 *   - Starter question chips (common diagnostic questions for this asset)
 *   - Message history with source citations
 *   - Auto-scroll to latest message
 *   - Enter to submit, Shift+Enter for newline
 */

import { useState, useRef, useEffect } from 'react';
import type { ChatMessage } from '../types';
import { sendChatMessage } from '../api/client';

interface Props {
  assetId: string;
  assetName: string;
}

function starterQuestions(assetId: string): string[] {
  return [
    `Why is ${assetId} showing elevated thermal aging?`,
    `What work orders are open for ${assetId}?`,
    `What defects were found in the last inspection of ${assetId}?`,
    `What is the overload history for ${assetId}?`,
  ];
}

export default function ChatPanel({ assetId, assetName }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async (question: string) => {
    if (!question.trim() || loading) return;
    const userMsg: ChatMessage = { role: 'user', content: question };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const result = await sendChatMessage(question);
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: result.answer,
        sources: result.sources,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err) {
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}. Please try again.`,
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  return (
    <div className="chat-panel">
      {/* Starter chips */}
      {messages.length === 0 && (
        <div className="chat-starters">
          <p className="starters-label">Suggested questions for {assetName}:</p>
          <div className="starter-chips">
            {starterQuestions(assetId).map((q, i) => (
              <button key={i} className="starter-chip" onClick={() => send(q)}>
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Message history */}
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`chat-bubble ${msg.role}`}>
            <p className="bubble-content">{msg.content}</p>
            {msg.sources && msg.sources.length > 0 && msg.sources[0] !== 'mock-mode — RAG pipeline not active' && (
              <div className="bubble-sources">
                <span className="sources-label">Sources: </span>
                {msg.sources.map((s, j) => (
                  <span key={j} className="source-tag">{s}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="chat-bubble assistant loading">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="chat-input-row">
        <textarea
          className="chat-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about transformer health, work orders, inspections… (Enter to send)"
          rows={2}
          disabled={loading}
        />
        <button
          className="chat-send-btn"
          onClick={() => send(input)}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
