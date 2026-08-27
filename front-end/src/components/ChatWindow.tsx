import { useState, useRef, useImperativeHandle, forwardRef } from "react";
import Message from "./Message.tsx";
import type { MessageData } from "./Message.tsx";

export interface ChatWindowHandle {
  sendMessage: (message: string) => void;
}

const ChatWindow = forwardRef<ChatWindowHandle>(function ChatWindow(_, ref) {
  const [messages, setMessages] = useState<MessageData[]>([]);
  const nextId = useRef(0);

  async function streamAssistantReply(userMessage: string) {
    const assistantMessageId = nextId.current++;

    setMessages((prev) => [
      ...prev,
      { id: assistantMessageId, content: "", role: "assistant", isLoading: true },
    ]);

    const response = await fetch("http://127.0.0.1:8000/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: userMessage,
      }),
    });

    const reader = response.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";

      for (const event of events) {
        const dataLine = event
          .split("\n")
          .find((line) => line.startsWith("data:"));

        if (!dataLine) continue;

        const data = dataLine.slice(5);
        const text = JSON.parse(data);

        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantMessageId && message.role === "assistant"
              ? { ...message, content: message.content + text, isLoading: false }
              : message
          )
        );
      }
    }
  }

  function sendMessage(message: string) {
    setMessages((prev) => [
      ...prev,
      { id: nextId.current++, content: message, role: "user" },
    ]);
    streamAssistantReply(message);
  }

  useImperativeHandle(ref, () => ({ sendMessage }));

  return (
    <div className="chat-body">
      <div className="chat-window">
        {messages.map((message) => (
          <Message key={message.id} message={message} />
        ))}
      </div>
    </div>
  );
});

export default ChatWindow;
