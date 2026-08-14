import AssistantIcon from './components/AssistantIcon.tsx';
import { useState } from "react";
import Message from './components/Message.tsx';
import type { MessageData } from "./components/Message.tsx";

const App = () => {

  const [messages, setMessages] = useState<MessageData[]> ([
    {id: 1, content: "Hello", role: "user"}
  ]);

  return (
    <div className = "container">
      <div className = "chat-pop-up">
          <div className = "chat-header">
            <div className = "header-info">
              
              <AssistantIcon/>

              <h2 className = "text-info">
                  Knowledge Assistant
              </h2>
            </div>
          </div>

          {/* Chat Body */}
          <div className="chat-body">
            <div className="chat-window">
              {messages.map(message => (
                <Message 
                  key={message.id}
                  message={message}
                  isLoading={false}
                  />
              ))};
            </div>
          </div>

          <div className="chat-footer">
            <input className="message" type="text" placeholder="Your Message.." id="chat-input"/>
            <button type="submit" id="submit-input"> Submit </button>
          </div>


          </div>
    </div>
  );
};

export default App;
