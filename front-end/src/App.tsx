import AssistantIcon from "./components/AssistantIcon.tsx";
import { useState, useRef } from "react";
import Message from "./components/Message.tsx";
import type { MessageData } from "./components/Message.tsx";

const App = () => {
  const [messages, setMessages] = useState<MessageData[]>([]);
  const [txt, setTxt] = useState("");
  const nextId = useRef(0);

  async function sendMessage(message: string) {
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
        message: message,
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

        const data = dataLine.slice(5)

        let text = JSON.parse(data)

        setMessages(prev => 
          prev.map(message => 
            message.id === assistantMessageId && message.role === "assistant" ?
            {...message, content: message.content + text, isLoading: false} 
            : message))
      }


    }
  }

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const currentMessage = txt.trim();
    if (!currentMessage) return;

    setMessages([...messages, {id: nextId.current++, content: currentMessage, role: "user"}])

    sendMessage(currentMessage);
    setTxt("");
  }

  return (
    <div className="container">
      <div className="chat-pop-up">
        <div className="chat-header">
          <div className="header-info">
            <AssistantIcon />

            <h2 className="text-info">Knowledge Assistant</h2>
          </div>
        </div>

        {/* Chat Body */}
        <div className="chat-body">
          <div className="chat-window">
            {messages.map((message) => (
              <Message key={message.id} message={message} />
            ))}
          </div>
        </div>

        <div className="chat-footer">
          <form onSubmit={handleSubmit}> 
            <textarea 
              className="scrollable-textbox" 
              placeholder="Enter your message"
              id="chat-input"
              value={txt}
              onChange={(e) => setTxt(e.target.value)}
              />

            <button type="submit" id="submit-input">
              Submit
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default App;
