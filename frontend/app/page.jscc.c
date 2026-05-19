
'use client'

import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const API_URL = 'http://43.201.22.227'
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || 'AQ.Ab8RN6KBxGEfeFaXXDLDpCph9NDHIe_vFU_uYNGAs1X9s-q7ig'

const STORAGE_KEY = 'ct_chat_history'

function cleanAnswer(text) {
  if (!text) return ''
  return text
    .replace(/^SUCCESS:.*\n?/gim, '')
    .replace(/^INFO:.*\n?/gim, '')
    .replace(/^WARNING:.*\n?/gim, '')
    .replace(/^ERROR:.*\n?/gim, '')
    .replace(/^Answer:\s*/im, '')
    .replace(/\[Data:[^\]]*\]/g, '')
    .trim()
}

export default function Home() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState([])
  const [showHero, setShowHero] = useState(true)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      setHistory(saved)
    } catch {}
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return

    setShowHero(false)
    setMessages(prev => [...prev, { role: 'user', text }])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(`${API_URL}/ask`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({ prompt: text, method: 'local' }),
      })

      const data = await res.json()

      if (!res.ok || data.error) {
        setMessages(prev => [...prev, { role: 'error', text: data.error || 'Алдаа гарлаа.' }])
      } else {
        const answer = cleanAnswer(data.answer || 'Мэдээлэл олдсонгүй.')
        setMessages(prev => [...prev, { role: 'ai', text: answer }])
        saveHistory(text, answer)
      }
    } catch {
      setMessages(prev => [...prev, { role: 'error', text: '❌ Сервертэй холбогдож чадсангүй.' }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const saveHistory = (q, a) => {
    const item = { id: Date.now(), question: q, answer: a }
    const updated = [item, ...history].slice(0, 15)
    setHistory(updated)
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(updated)) } catch {}
  }

  const loadChat = (item) => {
    setShowHero(false)
    setMessages([
      { role: 'user', text: item.question },
      { role: 'ai', text: item.answer },
    ])
  }

  const newChat = () => {
    setMessages([])
    setShowHero(true)
  }

  return (
    <div className="layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="logo">
          <i className="fa-solid fa-wand-magic-sparkles" />
          Talent AI
        </div>
        <button className="new-chat-btn" onClick={newChat}>
          <i className="fa-solid fa-plus" />
          Шинэ чат эхлэх
        </button>
        <div className="history-label">ЧАТНЫ ТҮҮХ</div>
        <div className="history-list">
          {history.map(item => (
            <div
              key={item.id}
              className="history-item"
              onClick={() => loadChat(item)}
              title={item.question}
            >
              {item.question.substring(0, 40)}...
            </div>
          ))}
        </div>
      </aside>

      {/* Main chat */}
      <main className="main">
        <div className="chat-area">
          {showHero && (
            <div className="hero">
              <div className="orb" />
              <h1>TALENT AI <span>Зөвлөх</span></h1>
              <p> TALENT AI хиймэл оюун ухаант зөвлөх</p>
            </div>
          )}

          <div className="messages">
            {messages.map((msg, i) => (
              <div key={i} className={`msg ${msg.role}`}>
                {msg.role === 'ai' ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.text}
                  </ReactMarkdown>
                ) : (
                  msg.text
                )}
              </div>
            ))}

            {loading && (
              <div className="msg ai">
                <div className="typing">
                  <span /><span /><span />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
        <div className="input-area">
          <div className="input-box">
            {loading && (
              <div className="loader-text">
                <i className="fa-solid fa-circle-notch fa-spin" /> Шинжилж байна...
              </div>
            )}
            <div className="input-row">
              <i className="fa-solid fa-plus" style={{ color: '#ccc' }} />
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendMessage()}
                placeholder="Асуултаа энд бичнэ үү..."
                disabled={loading}
              />
              <button
                className="send-btn"
                onClick={sendMessage}
                disabled={loading || !input.trim()}
              >
                <i className="fa-solid fa-arrow-up" />
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* Instructions */}
      <aside className="instructions">
        <div className="instr-label">АШИГЛАХ ЗААВАР</div>
        <div className="card-3d">
          <i className="fa-solid fa-lightbulb" style={{ color: 'var(--primary)', fontSize: 20 }} />
          <h4>Асуулт асуух</h4>
          <p>Сонирхсон асуултаа асууна уу.</p>
        </div>
        <div className="card-3d">
          <i className="fa-solid fa-bolt" style={{ color: 'var(--primary)', fontSize: 20 }} />
          <h4>Шуурхай хариу</h4>
          <p>Оновчтой товч, хариулт өгнө.</p>
        </div>
        <div className="card-3d">
          <i className="fa-solid fa-shield-halved" style={{ color: 'var(--primary)', fontSize: 20 }} />
          <h4>Мэргэжлийн зөвлөгөө</h4>
          <p>Бүх хариулт Talent AI-ийн мэдээллийн санд тулгуурласан.</p>
        </div>
      </aside>
    </div>
  )
}
