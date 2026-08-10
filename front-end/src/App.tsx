import AssistantIcon from './components/AssistantIcon.tsx';

const App = () => {
  return (
    <div className = "container">
      <div className = "chat-pop-up">
        <div className = "chat-logo">
          <div className = "chat-header">
            <div className = "header-info">
              <div className = "logo-icon">
                <AssistantIcon/>
                <h2 className = "text-info">
                  Knowledge Assistant
                </h2>
              </div>
            </div>
          </div>

          {/* Chat Body */}
          <div className="chat-body">
            <div className="chat-bot-message">
              <input type="text" placeholder="Enter Message.."/>
            </div>
          </div>


          </div>
      </div>
    </div>
  );
};

export default App;
