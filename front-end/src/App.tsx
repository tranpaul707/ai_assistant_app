import AssistantIcon from './components/AssistantIcon.tsx';

const App = () => {
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
              <div className="chat-bot-message"> 
                
              </div>
            </div>
          </div>

          <div className="chat-footer">
            <input className="message" type="text" placeholder="Your Message.."/>
          </div>


          </div>
    </div>
  );
};

export default App;
