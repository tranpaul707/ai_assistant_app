export interface MessageData {
  id: number;
  content: string;
  role: "user" | "assistant";
}

interface MessageProps {
  message: MessageData;
  isLoading: boolean;
}

const Message = ({ message, isLoading }: MessageProps) => {
  const className =
    message.role === "user" ? "chat-human-message" : "chat-bot-message";

  return (
    <div className={className}>
      {isLoading ? <p> AI is thinking</p> : <p>{message.content}</p>}
    </div>
  );
};

export default Message;
