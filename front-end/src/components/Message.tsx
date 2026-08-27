export interface MessageData {
  id: number;
  content: string;
  role: "user" | "assistant";
  isLoading?: boolean;
}

interface MessageProps {
  message: MessageData;
}

const Message = ({ message }: MessageProps) => {
  const className =
    message.role === "user" ? "chat-human-message" : "chat-bot-message";

  return (
    <div className={className} style={{whiteSpace: "pre-wrap"}}>
      {message.isLoading ? <p>AI is thinking...</p> : <p>{message.content}</p>}
    </div>
  );
};

export default Message;
