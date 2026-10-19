import {
  useState,
  useRef,
  useImperativeHandle,
  forwardRef,
  useEffect,
} from "react";
import Message from "./Message.tsx";
import type { MessageData } from "./Message.tsx";
import { API_BASE, authHeaders, getIdToken } from "../api/client";

export interface ChatWindowHandle {
  sendMessage: (message: string) => boolean;
  clearMessages: () => void;
  loadMessages: (messages: MessageData[]) => void;
}

interface ChatWindowProps {
  threadId: string;
}

const ChatWindow = forwardRef<ChatWindowHandle, ChatWindowProps>(
  function ChatWindow({ threadId }, ref) {
    const [messages, setMessages] = useState<MessageData[]>([]);
    const nextId = useRef(0);
    const threadIdRef = useRef(threadId);
    const activeRequest = useRef<AbortController | null>(null);

    useEffect(() => {
      threadIdRef.current = threadId;
      return () => {
        activeRequest.current?.abort();
      };
    }, [threadId]);

    async function streamAssistantReply(userMessage: string) {
      const controller = new AbortController();
      activeRequest.current = controller;
      const token = getIdToken();
      const assistantMessageId = nextId.current++;
      const isCurrent = () =>
        !controller.signal.aborted && getIdToken() === token;
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMessageId,
          content: "",
          role: "assistant",
          isLoading: true,
        },
      ]);
      try {
        const response = await fetch(`${API_BASE}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({
            message: userMessage,
            thread_id: threadIdRef.current,
          }),
          signal: controller.signal,
        });
        if (
          !response.ok ||
          !response.headers.get("content-type")?.includes("text/event-stream")
        ) {
          throw new Error("Chat unavailable");
        }
        const reader = response.body?.getReader();
        if (!reader) throw new Error("Chat stream unavailable");
        const decoder = new TextDecoder();
        let buffer = "";
        while (isCurrent()) {
          const { done, value } = await reader.read();
          if (done || !isCurrent()) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split(/\r?\n\r?\n/);
          buffer = events.pop() ?? "";
          for (const event of events) {
            const data = event
              .split(/\r?\n/)
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (!data) continue;
            if (data === "[DONE]") return;
            const text = JSON.parse(data);
            if (typeof text !== "string")
              throw new Error("Invalid chat response");
            if (!isCurrent()) return;
            setMessages((prev) =>
              prev.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      content: message.content + text,
                      isLoading: false,
                    }
                  : message,
              ),
            );
          }
        }
      } catch {
        if (isCurrent()) {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    content:
                      message.content ||
                      "Unable to respond. Sign in again or retry.",
                    isLoading: false,
                  }
                : message,
            ),
          );
        }
      } finally {
        if (isCurrent()) {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantMessageId
                ? { ...message, isLoading: false }
                : message,
            ),
          );
        }
        if (activeRequest.current === controller) activeRequest.current = null;
      }
    }

    function sendMessage(message: string) {
      if (activeRequest.current && !activeRequest.current.signal.aborted)
        return false;
      setMessages((prev) => [
        ...prev,
        { id: nextId.current++, content: message, role: "user" },
      ]);
      void streamAssistantReply(message);
      return true;
    }

    useImperativeHandle(ref, () => ({
      sendMessage,
      clearMessages: () => {
        activeRequest.current?.abort();
        setMessages([]);
      },
      loadMessages: (next) => {
        activeRequest.current?.abort();
        setMessages(next);
        nextId.current = next.reduce(
          (max, m) => Math.max(max, m.id + 1),
          nextId.current,
        );
      },
    }));

    return (
      <div className="chat-body">
        <div className="chat-window">
          {messages.map((message) => (
            <Message key={message.id} message={message} />
          ))}
        </div>
      </div>
    );
  },
);

export default ChatWindow;
