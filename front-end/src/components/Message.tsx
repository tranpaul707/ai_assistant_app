export interface MessageData {
    id: string;
    role: "user" | "assistant";
    content: string;
  }

interface MessageProps {
    message: MessageData;
}

const Message = ({ message }) => {

    return (
    <div className={`message ${message.role}`}>
        <p> {message.content} </p>
    </div>
  )
}

export default Message