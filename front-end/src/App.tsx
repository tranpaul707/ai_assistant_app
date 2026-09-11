import { useState, useRef, useCallback, useEffect } from "react";
import AssistantIcon from "./components/AssistantIcon.tsx";
import ChatWindow from "./components/ChatWindow.tsx";
import type { ChatWindowHandle } from "./components/ChatWindow.tsx";
import type { MessageData } from "./components/Message.tsx";
import FileUpload from "./components/FileUpload.tsx";
import type { UploadStatus } from "./components/FileUpload.tsx";
import GoogleSignin from "./components/GoogleSignin.tsx";
import { API_BASE, authHeaders } from "./api/client";

interface ThreadSummary {
  thread_id: string;
  title: string;
  updated_at?: string;
}

function newThreadId(): string {
  return crypto.randomUUID();
}

const App = () => {
  const [txt, setTxt] = useState("");
  const [activeThreadId, setActiveThreadId] = useState<string>(() => newThreadId());
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const chatRef = useRef<ChatWindowHandle>(null);

  const refreshThreads = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/threads`, {
        headers: { ...authHeaders() },
      });
      if (!response.ok) return;
      const data = await response.json();
      setThreads(data.threads ?? []);
    } catch {
      /* ignore — Redis may be down during early boot */
    }
  }, []);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  const clearPendingFile = () => {
    setPendingFile(null);
    const input = document.getElementById("file-input") as HTMLInputElement | null;
    if (input) input.value = "";
  };

  const handleNewChat = () => {
    const id = newThreadId();
    setActiveThreadId(id);
    chatRef.current?.clearMessages();
  };

  const handleSelectThread = async (threadId: string) => {
    if (threadId === activeThreadId) return;
    setActiveThreadId(threadId);
    try {
      const response = await fetch(`${API_BASE}/threads/${threadId}`, {
        headers: { ...authHeaders() },
      });
      if (!response.ok) {
        chatRef.current?.clearMessages();
        return;
      }
      const data = await response.json();
      const messages = (data.messages ?? []) as MessageData[];
      chatRef.current?.loadMessages(messages);
    } catch {
      chatRef.current?.clearMessages();
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const currentMessage = txt.trim();
    if (!currentMessage) return;

    chatRef.current?.sendMessage(currentMessage);
    setTxt("");
    window.setTimeout(() => void refreshThreads(), 800);
  };

  return (
    <div className="container">
      <div className="chat-shell">
        <aside className="chat-sidebar" aria-label="Conversation history">
          <div className="chat-sidebar__header">
            <h3 className="chat-sidebar__title">Chats</h3>
            <button type="button" className="new-chat-button" onClick={handleNewChat}>
              New Chat
            </button>
          </div>
          <nav className="chat-sidebar__list">
            {threads.length === 0 ? (
              <p className="chat-sidebar__empty">No conversations yet</p>
            ) : (
              threads.map((thread) => (
                <button
                  key={thread.thread_id}
                  type="button"
                  className={
                    thread.thread_id === activeThreadId
                      ? "chat-sidebar__item chat-sidebar__item--active"
                      : "chat-sidebar__item"
                  }
                  onClick={() => void handleSelectThread(thread.thread_id)}
                  title={thread.title || "Chat"}
                >
                  <span className="chat-sidebar__item-label">
                    {thread.title || "New chat"}
                  </span>
                </button>
              ))
            )}
          </nav>
        </aside>

        <div className="chat-pop-up">
          <div className="chat-header">
            <div className="header-info">
              <AssistantIcon />

              <h2 className="text-info">Knowledge Assistant</h2>

              <GoogleSignin onAuthChange={() => void refreshThreads()} />
            </div>
          </div>

          <ChatWindow ref={chatRef} threadId={activeThreadId} />

          <div className="chat-footer">
            <form className="compose-form" onSubmit={handleSubmit}>
              {pendingFile && (
                <div className="compose-attachments" aria-live="polite">
                  <span className="file-chip" title={pendingFile.name}>
                    <span className="file-chip__name">{pendingFile.name}</span>
                    {uploadStatus === "uploading" ? (
                      <span className="file-chip__hint">Uploading…</span>
                    ) : (
                      <button
                        type="button"
                        className="file-chip__clear"
                        aria-label={`Remove ${pendingFile.name}`}
                        onClick={clearPendingFile}
                      >
                        ×
                      </button>
                    )}
                  </span>
                </div>
              )}

              <div className="compose-row">
                <textarea
                  className="scrollable-textbox"
                  placeholder="Enter your message"
                  id="chat-input"
                  value={txt}
                  onChange={(e) => setTxt(e.target.value)}
                />

                <FileUpload
                  file={pendingFile}
                  status={uploadStatus}
                  onFileChange={setPendingFile}
                  onStatusChange={setUploadStatus}
                />

                <button type="submit" id="submit-input">
                  Submit
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;
