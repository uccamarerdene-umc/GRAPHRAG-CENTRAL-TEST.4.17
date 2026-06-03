'use client'
 
import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
 
const API_URL = ''
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || '';
 
const STORAGE_KEY = 'ct_chat_history'
 
const SUGGESTIONS = [
  'CTPI тест гэж юу вэ?',
  'Big5 болон EQ ялгаа',
  'Борлуулалтын ур чадвар',
  'Тест үнэ хэд вэ?',
]
 
const TESTS = ['Sales Competency', 'MOTIVATION+', 'PP тест', 'PP Test', 'Big5', 'CTPI', 'VOC', 'EQ']
 
function addTestLinks(text) {
  if (!text) return text
  const url = 'https://talenthub.mn/login'
  TESTS.forEach(test => {
    const e = test.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    text = text.replace(
      new RegExp('(?<!\\[)\\*\\*(' + e + '[^*]*)\\*\\*(?!\\])', 'g'),
      '**[$1](' + url + ')**'
    )
    text = text.replace(
      new RegExp('(?<!\\[|\\*)\\b(' + e + ')\\b(?![\\]*\\(])', 'g'),
      '[$1](' + url + ')'
    )
  })
  return text
}
 
function cleanAnswer(text) {
  if (!text) return ''
  text = addTestLinks(text)
  return text
    .replace(/^SUCCESS:.*\n?/gim, '')
    .replace(/^INFO:.*\n?/gim, '')
    .replace(/^WARNING:.*\n?/gim, '')
    .replace(/^ERROR:.*\n?/gim, '')
    .replace(/^Answer:\s*/im, '')
    .replace(/\[Data:[^\]]*\]/g, '')
    .trim()
}
 
function AiMessage({ text }) {
  return (
    <div className="msg ai">
      <div className="ai-avatar">
        <i className="fa-solid fa-wand-magic-sparkles" />
      </div>
      <div className="ai-bubble">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({href, children}) => (
              <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
            ),
            strong: ({children}) => {
              const str = Array.isArray(children) ? children.join('') : String(children || '')
              const matched = TESTS.some(t => str.includes(t))
              if (matched) {
                return <a href="https://talenthub.mn/login" target="_blank" rel="noopener noreferrer"><strong>{children}</strong></a>
              }
              return <strong>{children}</strong>
            }
          }}
        >
          {text}
        </ReactMarkdown>
      </div>
    </div>
  )
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
 
  const sendMessage = async (text) => {
    const msg = (text || input).trim()
    if (!msg || loading) return
 
    setShowHero(false)
    setMessages(prev => [...prev, { role: 'user', text: msg }])
    setInput('')
    setLoading(true)
 
    try {
      const res = await fetch(`${API_URL}/ask`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({ prompt: msg, method: 'local' }),
      })
 
      const data = await res.json()
 
      if (!res.ok || data.error) {
        setMessages(prev => [...prev, { role: 'error', text: data.error || 'Алдаа гарлаа.' }])
      } else {
        const answer = cleanAnswer(data.answer || 'Мэдээлэл олдсонгүй.')
        setMessages(prev => [...prev, { role: 'ai', text: answer }])
        saveHistory(msg, answer)
      }
    } catch {
      setMessages(prev => [...prev, { role: 'error', text: 'Сервертэй холбогдож чадсангүй.' }])
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
    setInput('')
    inputRef.current?.focus()
  }
 
  // Group history by date
  const groupHistory = () => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yesterday = new Date(today - 86400000)
    const week = new Date(today - 6 * 86400000)
    const month30 = new Date(today - 29 * 86400000)
    const todayItems = history.filter(i => new Date(i.id) >= today)
    const yesterdayItems = history.filter(i => new Date(i.id) >= yesterday && new Date(i.id) < today)
    const weekItems = history.filter(i => new Date(i.id) >= week && new Date(i.id) < yesterday)
    const month30Items = history.filter(i => new Date(i.id) >= month30 && new Date(i.id) < week)
    const olderItems = history.filter(i => new Date(i.id) < month30)
    const groups = []
    if (todayItems.length) groups.push({ label: 'Өнөөдөр', items: todayItems })
    if (yesterdayItems.length) groups.push({ label: 'Өчигдөр', items: yesterdayItems })
    if (weekItems.length) groups.push({ label: 'Өмнөх 7 хоног', items: weekItems })
    if (month30Items.length) groups.push({ label: 'Өмнөх 30 хоног', items: month30Items })
    const monthGroups = {}
    olderItems.forEach(item => {
      const d = new Date(item.id)
      const key = d.getFullYear() + '-' + d.getMonth()
      const label = d.toLocaleString('mn-MN', { month: 'long', year: 'numeric' })
      if (!monthGroups[key]) monthGroups[key] = { label, items: [] }
      monthGroups[key].items.push(item)
    })
    Object.values(monthGroups).forEach(g => groups.push(g))
    return groups
  }
 
  return (
    <div className="layout">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="logo">
          <div className="logo-icon">
            <i className="fa-solid fa-wand-magic-sparkles" />
          </div>
          <span className="logo-text">TALENT <span>AI</span></span>
        </div>
 
        <button className="new-chat-btn" onClick={newChat}>
          <i className="fa-solid fa-plus" style={{fontSize:12}} />
          Шинэ чат эхлэх
        </button>
 
        <div className="history-label">Чатны түүх</div>
        <div className="history-list">
          {groupHistory().map((group, idx) => (
            <div key={idx}>
              <div className="history-section-label">{group.label}</div>
              {group.items.map(item => (
                <div
                  key={item.id}
                  className="history-item"
                  onClick={() => loadChat(item)}
                  title={item.question}
                >
                  {item.question.substring(0, 34)}{item.question.length > 34 ? '…' : ''}
                </div>
              ))}
            </div>
          ))}
        </div>
      </aside>
 
      {/* ── Main ── */}
      <main className="main">
        <div className="chat-area">
          {showHero && (
            <div className="hero">
              <div className="orb-container">
                <div className="orb" />
                <div className="orb-ring" />
                <div className="orb-ring-2" />
              </div>
              <h1>TALENT <span>AI Зөвлөх</span></h1>
              <p className="hero-sub">
                Central Test-ийн талаар мэдэхийг хүсч байгаа зүйлээ асуугаарай. Бодит өгөгдөлд тулгуурлан хариулна.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s, i) => (
                  <button key={i} className="chip" onClick={() => sendMessage(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
 
          <div className="messages">
            {messages.map((msg, i) => {
              if (msg.role === 'user') {
                return (
                  <div key={i} className="msg user">{msg.text}</div>
                )
              }
              if (msg.role === 'error') {
                return (
                  <div key={i} className="msg ai error">
                    <div className="ai-avatar" style={{background:'rgba(239,68,68,0.2)'}}>
                      <i className="fa-solid fa-exclamation" style={{color:'#FCA5A5'}} />
                    </div>
                    <div className="ai-bubble">{msg.text}</div>
                  </div>
                )
              }
              return <AiMessage key={i} text={msg.text} />
            })}
 
            {loading && (
              <div className="typing-wrapper">
                <div className="ai-avatar">
                  <i className="fa-solid fa-wand-magic-sparkles" />
                </div>
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
                <i className="fa-solid fa-circle-notch fa-spin" style={{fontSize:11}} /> Шинжилж байна...
              </div>
            )}
            <div className="input-row">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                placeholder="Асуултаа бичнэ үү..."
                disabled={loading}
              />
              <button
                className="send-btn"
                onClick={() => sendMessage()}
                disabled={loading || !input.trim()}
              >
                <i className="fa-solid fa-arrow-up" />
              </button>
            </div>
          </div>
          <div className="input-hint">Enter дарж илгээх · Central Test-ийн мэдээллийн санд тулгуурласан</div>
        </div>
      </main>
 
      {/* ── Right panel ── */}
      <aside className="instructions">
        <div className="instr-label">Ашиглах заавар</div>
 
        <div className="card-3d">
          <div className="card-icon">
            <i className="fa-solid fa-lightbulb" style={{color:'var(--primary-light)'}} />
          </div>
          <h4>Асуулт асуух</h4>
          <p>Central test-ийн талаар тодорхой асуулт бичиж Enter дарна уу.</p>
        </div>
 
        <div className="card-3d">
          <div className="card-icon">
            <i className="fa-solid fa-bolt" style={{color:'var(--primary-light)'}} />
          </div>
          <h4>Өгөгдөлд суурилсан хариулт</h4>
          <p>Ур чадвар болон тестийн талаар секундын дотор дэлгэрэнгүй хариулт авна.</p>
        </div>
 
        <div className="card-3d">
          <div className="card-icon">
            <i className="fa-solid fa-shield-halved" style={{color:'var(--primary-light)'}} />
          </div>
          <h4>Боломжит тестүүд</h4>
          <p>Доорх тестүүдийн талаар мэдээлэл авах боломжтой:</p>
          <div className="tests-grid" style={{marginTop: 10}}>
            {['CTPI','Big5','VOC','PP Test','EQ','MOTIVATION+','Sales Competency'].map(t => (
              <span key={t} className="test-badge">
                <i className="fa-solid fa-circle" style={{fontSize:5}} /> {t}
              </span>
            ))}
          </div>
        </div>
 
        <div className="card-3d">
          <div className="card-icon">
            <i className="fa-solid fa-phone" style={{color:'var(--primary-light)'}} />
          </div>
          <h4>Холбоо барих</h4>
          <p>📞 8804-7823</p>
          <p style={{marginTop:6}}>
            <a href="https://www.facebook.com/unitedconsultingmanagement" target="_blank">
              🔵 United Consulting Management
            </a>
          </p>
        </div>
      </aside>
    </div>
  )
}
