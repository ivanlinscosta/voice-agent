import { useVoiceAgent } from './hooks/useVoiceAgent';
import { useState, useRef, useEffect } from 'react';
import { formatUsd } from './utils/costEstimate';
import type { ConnectionStatus } from './types';

const statusLabels: Record<ConnectionStatus | 'muted', string> = {
  disconnected: 'Agent Offline',
  connecting: 'Agent Connecting',
  listening: 'Agent Listening',
  thinking: 'Agent Thinking',
  speaking: 'Agent Speaking',
  error: 'Agent Error',
  muted: 'Agent Muted',
};

function TranscriptEntry({ entry }: { entry: { id: string; role: 'user' | 'assistant'; text: string } }) {
  const isUser = entry.role === 'user';
  return (
    <div className={`message ${entry.role}`}>
      {!isUser && (
        <div className="avatar-container">
          <div className="avatar assistant-avatar">
            <span role="img" aria-label="assistant">👩‍🦰</span>
          </div>
          <div className="online-dot"></div>
        </div>
      )}
      <div className="message-content">
        <span className="message-label">{isUser ? 'You' : 'TAI Agent'}</span>
        <div className="message-text">{entry.text}</div>
      </div>
      {isUser && (
        <div className="avatar-container">
          <div className="avatar user-avatar">
            <span role="img" aria-label="user">👩</span>
          </div>
        </div>
      )}
    </div>
  );
}

function ErrorToast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="error-toast" role="alert">
      <span>{message}</span>
      <button onClick={onDismiss} aria-label="Close error">×</button>
    </div>
  );
}

export function App() {
  const defaultWsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = import.meta.env.VITE_WS_URL || `${defaultWsProtocol}//${window.location.host}/api/ws/voice`;

  const [showError, setShowError] = useState(false);
  const [textInput, setTextInput] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const {
    status,
    selectedModel,
    setSelectedModel,
    transcripts,
    sessionDuration,
    estimatedCost,
    error,
    connect,
    disconnect,
    formatDuration,
    isMuted,
    toggleMute,
    sendText,
  } = useVoiceAgent({
    wsUrl,
    onError: (_msg) => {
      setShowError(true);
    },
  });

  const isConnecting = status === 'connecting';
  const isDisconnectedOrError = status === 'disconnected' || status === 'error';
  const isSessionActive = !isDisconnectedOrError && !isConnecting;

  const displayStatus = isSessionActive && isMuted ? 'muted' : status;

  const handleMicClick = async () => {
    if (isDisconnectedOrError) {
      setShowError(false);
      await connect();
    } else if (isSessionActive) {
      toggleMute();
    }
  };

  const pendingTextRef = useRef<string | null>(null);

  const handleSendText = async () => {
    const text = textInput.trim();
    if (!text || isConnecting) return;

    if (isDisconnectedOrError) {
      setShowError(false);
      setTextInput('');
      pendingTextRef.current = text;
      await connect();
      const pending = pendingTextRef.current;
      const sent = pending ? sendText(pending) : false;
      pendingTextRef.current = null;
      if (!sent) {
        setTextInput(text);
      }
      return;
    }

    if (sendText(text)) {
      setTextInput('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      void handleSendText();
    }
  };

  const dismissError = () => {
    setShowError(false);
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [transcripts]);

  return (
    <div className="app">
      <main className="card">
        <header className="header">
          <div className="header-left">
            <h1 className="title">TAI Agent</h1>
            <p className="subtitle">Voice & Text Conversational Assistant</p>
          </div>
          <div className="header-right">
            <div className="provider-label">Provider</div>
            <div className="provider-dropdown-container">
              <button 
                className="provider-dropdown-btn" 
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                disabled={!isDisconnectedOrError}
              >
                <div className="provider-icon"></div>
                <span className="provider-name">
                  {selectedModel === 'gemini-live' ? 'Google Gemini Live' : 'Amazon Nova 2 Sonic'}
                </span>
                <svg className="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </button>
              {isDropdownOpen && isDisconnectedOrError && (
                <div className="provider-dropdown-menu">
                  <button 
                    className="provider-dropdown-item"
                    onClick={() => { setSelectedModel('gemini-live'); setIsDropdownOpen(false); }}
                  >
                    Google Gemini Live
                  </button>
                  <button 
                    className="provider-dropdown-item"
                    onClick={() => { setSelectedModel('nova-sonic'); setIsDropdownOpen(false); }}
                  >
                    Amazon Nova 2 Sonic
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <div className="divider"></div>

        <section className="chat-area">
          <div className="conversation" role="log" aria-live="polite" aria-label="Chat history">
            {transcripts.length === 0 ? (
              <div className="empty-chat">
                No messages yet. Start talking or typing!
              </div>
            ) : (
              transcripts.map((entry: { id: string; role: 'user' | 'assistant'; text: string }) => (
                <TranscriptEntry key={entry.id} entry={entry} />
              ))
            )}
            <div ref={chatEndRef} />
          </div>
        </section>

        <section className="voice-panel">
          <div className="status-chips">
            <div className="chip chip-session">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="chip-icon">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="22"/>
                <line x1="8" y1="19" x2="8" y2="22"/>
                <line x1="16" y1="19" x2="16" y2="22"/>
              </svg>
              {isSessionActive ? 'Voice Session Active' : 'Voice Session Idle'}
            </div>
            <div className="chip chip-status">
              <div className={`status-dot ${displayStatus}`}></div>
              {statusLabels[displayStatus]}
            </div>
          </div>

          <div className="metrics-pill">
            <span className="cost">{formatUsd(estimatedCost)}</span>
            <span className="metrics-divider">|</span>
            <span className="timer">{formatDuration(sessionDuration)}</span>
          </div>

          <div className="controls-row">
            {isSessionActive && (
              <button 
                className="end-call-button"
                onClick={disconnect}
                aria-label="End Voice Session"
                title="End call"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="end-call-icon">
                  <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-3.33-2.67m-2.67-3.34a19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91"></path>
                  <line x1="22" y1="2" x2="2" y2="22"></line>
                </svg>
              </button>
            )}
            <div className="mic-container">
              <button 
                className={`mic-button ${isSessionActive ? 'active' : ''} ${isMuted ? 'muted' : ''}`}
                onClick={handleMicClick}
                disabled={isConnecting}
                aria-label={isSessionActive ? (isMuted ? 'Unmute' : 'Mute') : 'Start Voice Session'}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="mic-icon">
                  {isMuted ? (
                    <>
                      <line x1="1" y1="1" x2="23" y2="23"></line>
                      <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"></path>
                      <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"></path>
                      <line x1="12" y1="19" x2="12" y2="22"></line>
                    </>
                  ) : (
                    <>
                      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                      <line x1="12" y1="19" x2="12" y2="22"/>
                      <line x1="8" y1="19" x2="8" y2="22"/>
                      <line x1="16" y1="19" x2="16" y2="22"/>
                    </>
                  )}
                </svg>
              </button>
              {isSessionActive && !isMuted && <div className="mic-halo"></div>}
              {isSessionActive && !isMuted && <div className="mic-halo-2"></div>}
            </div>
          </div>

          <div className="mic-caption">
            Click to Mute / Pause Voice Session
          </div>
        </section>

        <section className="composer">
          <input 
            type="text" 
            className="text-input" 
            placeholder="Type your query here..." 
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isConnecting}
          />
          <button 
            className="send-button" 
            onClick={handleSendText}
            disabled={!textInput.trim() || isConnecting}
          >
            Send
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="send-icon">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </section>
      </main>

      {showError && error && (
        <ErrorToast message={error} onDismiss={dismissError} />
      )}
    </div>
  );
}