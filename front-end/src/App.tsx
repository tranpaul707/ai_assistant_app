import { useState, useRef } from "react";
import AssistantIcon from "./components/AssistantIcon.tsx";
import ChatWindow from "./components/ChatWindow.tsx";
import type { ChatWindowHandle } from "./components/ChatWindow.tsx";
import FileUpload from "./components/FileUpload.tsx";

const App = () => {
  const [txt, setTxt] = useState("");
  const chatRef = useRef<ChatWindowHandle>(null);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const currentMessage = txt.trim();
    if (!currentMessage) return;

    chatRef.current?.sendMessage(currentMessage);
    setTxt("");
  };

  return (
    <div className="container">
      <div className="chat-pop-up">
        <div className="chat-header">
          <div className="header-info">
            <AssistantIcon />

            <h2 className="text-info">Knowledge Assistant</h2>
          </div>
        </div>

        <ChatWindow ref={chatRef} />

        <div className="chat-footer">
          <form onSubmit={handleSubmit}>
            <textarea
              className="scrollable-textbox"
              placeholder="Enter your message"
              id="chat-input"
              value={txt}
              onChange={(e) => setTxt(e.target.value)}
            />

            <FileUpload />

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
