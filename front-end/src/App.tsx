import AssistantIcon from "./components/AssistantIcon.tsx";
import { useState } from "react";
import Message from "./components/Message.tsx";
import type { MessageData } from "./components/Message.tsx";

const App = () => {
  const [messages, setMessages] = useState<MessageData[]>([
    {
      id: 1,
      content:
        "Hello World Hello WorlddHello WorlddHello Worldd Hello WorlddHello WorlddHello WorlddHello Worldd",
      role: "assistant",
    },
    {
      id: 2,
      content:
        "Hello World Hello WorlddHello WorlddHello Worldd Hello WorlddHello WorlddHello WorlddHello Worldd",
      role: "user",
    },
    { id: 3, content: "Hello Biatch", role: "assistant" },
    { id: 4, content: "Hey! How can I help you today?", role: "user" },
    {
      id: 5,
      content:
        "I'm working on a React chat interface and trying to understand how message history should work.",
      role: "assistant",
    },
    {
      id: 6,
      content:
        "That sounds like a great project. Are you storing the messages in useState?",
      role: "user",
    },
    {
      id: 7,
      content:
        "Yes, I'm using a MessageData[] array to keep track of the conversation.",
      role: "assistant",
    },
    {
      id: 8,
      content:
        "Nice. That makes it easy to add new messages and pass the list to your MessageList component.",
      role: "user",
    },
    {
      id: 9,
      content:
        "So whenever I call setMessages, React should automatically update the UI?",
      role: "assistant",
    },
    {
      id: 10,
      content:
        "Exactly. React will re-render the components that depend on the updated state.",
      role: "user",
    },
    {
      id: 11,
      content:
        "And each message should have a unique id so I can use it as the key when rendering the list.",
      role: "assistant",
    },
    {
      id: 12,
      content:
        "Correct. Using message.id as the key helps React keep track of each message between renders.",
      role: "user",
    },
    {
      id: 13,
      content:
        "Got it. I think I'm starting to understand how the pieces fit together.",
      role: "assistant",
    },
  ]);

  const [input, setInput] = useState("")
  const [txt, setTxt] = useState("")

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    setInput(txt)
    setTxt("")
    event.preventDefault()
    console.log("Submitted")
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
              <Message key={message.id} message={message} isLoading={false} />
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
