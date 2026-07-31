import { useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const message = input.trim()
    if (!message || isLoading) return

    const userId = crypto.randomUUID()
    const assistantId = crypto.randomUUID()

    setMessages((current) => [
      ...current,
      { id: userId, role: 'user', content: message },
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setInput('')
    setIsLoading(true)

    try {
      const response = await fetch('http://127.0.0.1:8000/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })

      if (!response.ok || !response.body) {
        throw new Error(`Request failed with status ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')

        const events = buffer.split('\n\n')
        buffer = events.pop() ?? ''

        for (const eventBlock of events) {
          const data = eventBlock
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => {
              const value = line.slice(5)
              return value.startsWith(' ') ? value.slice(1) : value
            })
            .join('\n')

          if (!data || data === '[DONE]') continue

          // The backend sends each token JSON-encoded so newlines survive
          // SSE framing.
          let token: string
          try {
            token = JSON.parse(data)
          } catch {
            token = data
          }

          if (!token) continue

          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? { ...item, content: item.content + token }
                : item,
            ),
          )
        }

        if (done) break
      }
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : 'Unable to reach the assistant.'

      setMessages((current) =>
        current.map((item) =>
          item.id === assistantId
            ? { ...item, content: `Error: ${detail}` }
            : item,
        ),
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <main className="chat-app">
      <header className="chat-header">
        <h1>Knowledge AI</h1>
        <p>Ask a question and stream an answer from your local model.</p>
      </header>

      <section className="messages" aria-live="polite">
        {messages.length === 0 && (
          <div className="empty-state">
            <h2>What would you like to know?</h2>
            <p>Your conversation will appear here.</p>
          </div>
        )}

        {messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <span className="message-label">
              {message.role === 'user' ? 'You' : 'Assistant'}
            </span>
            <p>{message.content || 'Thinking…'}</p>
          </article>
        ))}
      </section>

      <form className="composer" onSubmit={sendMessage}>
        <label className="sr-only" htmlFor="message">
          Message
        </label>
        <textarea
          id="message"
          placeholder="Ask a question…"
          rows={2}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }
          }}
        />
        <button disabled={!input.trim() || isLoading} type="submit">
          {isLoading ? 'Responding…' : 'Send'}
        </button>
      </form>
    </main>
  )
}

export default App
