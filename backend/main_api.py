"""
main_api.py — Talent AI FastAPI Backend v2.5.0
Fixes v2.5:
  - google.generativeai → google.genai (шинэ SDK, requirements.txt-тай нийцүүлсэн)
  - Gemini multi-turn chat history зөв дамждаг
  - GraphRAG байхгүй/муу хариулсан ч Gemini ЗААВАЛ ажилладаг
  - User асуулт ҮРГЭЛЖ DB-д хадгалагддаг
  - "мэдээлэл хангалтгүй" гэж хариулах боломжгүй
"""

import os
import re
import logging
import asyncio
from typing import Optional, List, Dict, Any

from google import genai
from google.genai import types

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from db import (
    init_db, create_session, get_session, update_session_file,
    get_all_sessions, delete_session, save_message, get_messages,
)
from excel_processor import process_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("talent_ai")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

# google-genai SDK client
_genai_client: Optional[genai.Client] = None

def get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY environment variable not set")
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client


_search_engine = None

def get_local_search_engine():
    global _search_engine
    if _search_engine is None:
        try:
            from graphrag_engine import build_local_search_engine  # type: ignore
            _search_engine = build_local_search_engine()
            logger.info("GraphRAG initialised.")
        except Exception as exc:
            logger.warning("GraphRAG unavailable: %s", exc)
            raise
    return _search_engine


# ═══════════════════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════════════════

class AgentState(BaseModel):
    session_id: str
    user_prompt: str
    chat_history: List[Dict[str, Any]] = []
    has_excel: bool = False
    excel_stats: Optional[str] = Field(default=None)
    detected_test_name: Optional[str] = Field(default=None)
    graphrag_context: Optional[str] = Field(default=None)
    raw_analysis: Optional[str] = Field(default=None)
    final_output: Optional[str] = Field(default=None)


# ═══════════════════════════════════════════════════════════════════════════
#  TEXT CLEANUP
# ═══════════════════════════════════════════════════════════════════════════

_TEXT_REPLACEMENTS = {
    "Ниймэл": "Нийтэч", "ниймэл": "нийтэч", "Ниймтэй": "Нийтэч", "ниймтэй": "нийтэч",
    "Нийгэмч": "Нийтэч", "нийгэмч": "нийтэч", "Ниймч": "Нийтэч", "ниймч": "нийтэч",
    "Нийрч": "Нийтэч", "нийрч": "нийтэч", "Ний тэч": "Нийтэч", "ний тэч": "нийтэч",
    "Ниймц": "Нийтэч", "ниймц": "нийтэч", "Н ягт": "Нягт",
    "удирдамжийн": "удирдлагын", "Удирдамжийн": "Удирдлагын",
    "эергээр": "эерэгээр", "үр бүтээлтэй": "бүтээмжтэй", "үр бүтээл": "бүтээмж",
}

def apply_mongolian_regex_fixes(text: str) -> str:
    if not text:
        return text
    for old, new in _TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)
    patterns = [
        (r"^[ \t]*[-\*\+]\s+", "", re.MULTILINE),
        (r"^[ \t]*\d+[\.\)]\s+", "", re.MULTILINE),
        (r"\.{2,}", "…"), (r"\s{2,}", " "), (r" \n", "\n"), (r"\n{3,}", "\n\n"),
        (r"\bгэж\s+байна\b", "гэнэ"), (r"\bбайгаа\s+юм\b", "байна"),
        (r"\|.*?\|", ""), (r"_{1,2}([^_]+)_{1,2}", r"\1"), (r"#+\s", ""),
        (r"```[\s\S]*?\n```", ""), (r"`([^`]+)`", r"\1"), (r"[ \t]+$", ""),
    ]
    for item in patterns:
        text = re.sub(item[0], item[1], text, flags=item[2]) if len(item) == 3 else re.sub(item[0], item[1], text)
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════
#  СИСТЕМИЙН PROMPT
# ═══════════════════════════════════════════════════════════════════════════

HMM_KNOWLEDGE = """
HMM (Harvard ManageMentor) СУРГАЛТЫН 42 МОДУЛЬ БА 61 ГОЛ УР ЧАДВАР:

МАНЛАЙЛАЛ (Leading People, Delegating, Persuading):
  Ур чадвар: Манлайлах, Үүрэг даалгавар шилжүүлэх, Нөлөөлөх, Шийдвэр гаргах

СТРАТЕГИ (Strategic Thinking, Innovation, Change Management):
  Ур чадвар: Стратеги сэтгэлгээ, Инноваци, Өөрчлөлтийн удирдлага, Алсын хараа

ХАРИЛЦАА (Difficult Interactions, Negotiating, Communication):
  Ур чадвар: Харилцааны ур чадвар, Хэлэлцээр хийх, Зөрчилдөөн шийдвэрлэх, Итгэлцэл

ГҮЙЦЭТГЭЛ (Project Management, Time Management, Coaching):
  Ур чадвар: Төслийн төлөвлөлт, Цагийн менежмент, Коучинг, Гүйцэтгэлийн хэмжүүр

БАЙГУУЛЛАГЫН СОЁЛ (Ethics at Work, Diversity, Hiring):
  Ур чадвар: Ёс зүй, Олон талт байдал, Баг бүрдүүлт, Ажлын байрны соёл

CTPI ТЕСТ — МАППИНГ (Удирдлагын болон менежерийн чадвар):
  Манлайлах чадвар (Оптимал 6-8):   0-5 → HMM: Leading People, Delegating (8 ур чадвар)
  Стратеги сэтгэлгээ (Оптимал 7-9): 0-6 → HMM: Strategic Thinking, Strategy Planning and Execution, Innovation (7 ур чадвар)
  Өөрчлөлт удирдах (Оптимал 6-8):   0-5 → HMM: Change Management, Resilience (5 ур чадвар)

PP ТЕСТ — МАППИНГ (Ажлын хандлага):
  Удирдан чиглүүлэх (Оптимал 7-9):  0-6 → HMM: Coaching, Leading People
  Ятган нөлөөлөх (Оптимал 6-8):     0-5 → HMM: Negotiating, Presentation Skills (12 ур чадвар)
  Стресс/Харилцаа (Оптимал 6-8):    0-5 → HMM: Difficult Interactions, Stress Management (10 ур чадвар)
  Дүрэм журмыг дагах (Оптимал 6-8): 0-5 → HMM: Ethics at Work
  Шуурхай гүйцэтгэх (Оптимал 6-8): 0-5 → HMM: Time Management, Project Management, Managing Up (10 ур чадвар)
  Коучинг/Гүйцэтгэл (Оптимал 6-8): 0-5 → HMM: Coaching, Feedback Essentials, Performance Measurement (9 ур чадвар)

Big5 ТЕСТ — МАППИНГ (Зан төлөвийн үнэлгээ):
  Нягт нямбай байдал (Оптимал 6-10):        0-5 → HMM: Process Improvement, Performance Measurement, Writing Skills, Finance Essentials (10 ур чадвар)
  Сэтгэл хөдлөлийн тогтвортой байдал (6-9): 0-5 → HMM: Difficult Interactions, Stress Management
  Нийтэч эрч хүчтэй байдал (6-9):           0-5 → HMM: Global Collaboration, Communication

СУРГАЛТЫН ТӨЛӨВЛӨГӨӨ ЗАГВАР:
  1-р АЛХАМ: Сул оноотой чиглэлүүдийг тодорхойл
  2-р АЛХАМ: Тохирох HMM модулиудыг тодорхой нэрлэ
  3-р АЛХАМ: Хугацааны эрэмбэ: 1-р сар (яаралтай) → 2-3-р сар (дунд) → 4-6-р сар (урт хугацаа)
  4-р АЛХАМ: Тус бүрийн хүлээгдэж буй үр дүнг тайлбарла
"""

def build_system_prompt(state: AgentState, graphrag_context: str = "") -> str:
    prompt = (
        "Та бол ХИЙМЭЛ ОЮУН УХААНТ ЗӨВЛӨХ — 'Таlent AI' юм.\n\n"
        "🔴 ХАМГИЙН ЧУХАЛ ДҮРЭМ:\n"
        "- 'Мэдээлэл хангалтгүй', 'холбогдоно уу', 'одоогоор байхгүй' гэж ХЭЗЭЭ Ч хариулж болохгүй.\n"
        "- Өмнөх чатны түүхэнд тестийн оноо, шинжилгээ байвал ЗААВАЛ тэр дээр үндэслэн хариулна.\n"
        "- Chat history хоосон байвал ч HMM мэдлэгийн санд үндэслэн хариулна.\n"
        "- Follow-up асуулт ирэхэд өмнөх бүх хариулт дээр нэмж хариулна.\n\n"
        "🟡 ФОРМАТЫН ДҮРЭМ:\n"
        "- Зөвхөн МОНГОЛ хэлээр, урсгал өгүүлбэрээр бич.\n"
        "- Зураас (-), од (*), тоон жагсаалт ашиглахгүй.\n"
        "- Тестийн нэрсийг **CTPI**, **PP**, **Big5** тодоор тэмдэглэ.\n"
        "- HMM модулийн нэрийг 'Harvard ManageMentor хөтөлбөрийн [нэр]' гэж дурд.\n"
        "- Оптимал мужид байгаа оноог сул тал гэж хэлж болохгүй.\n\n"
        + HMM_KNOWLEDGE
    )
    if state.has_excel and state.excel_stats:
        _all_t = ["CTPI","Big5","PP","VOC","EQ","MOTIVATION+","Sales Competency"]
        _dt = state.detected_test_name or ""
        _dtl = [x.strip() for x in re.split(r"[,\s]+", _dt) if x.strip()]
        _forb = [t for t in _all_t if not any(t.lower() in d.lower() for d in _dtl)] if _dtl else []
        _eg = ("\n[EXCEL PROMPT GUARD]\n"
               + "Энэ файлд ЗӨВХӨН: " + (_dt or "?") + "\n"
               + ("ХОРИГЛОНО: " + ", ".join(_forb) + "\n" if _forb else "")
               + "Хориглосон тестийн нэрийг НЭГ Ч УДАА дурдахгүй.\n") if _dtl else ""
        prompt += "\n\n📊 EXCEL ӨГӨГДЛИЙН ХУРААНГУЙ (ЭНЭ ДЭЭР ҮНДЭСЛЭН ХАРИУЛ):\n" + state.excel_stats + "\n" + _eg
    if graphrag_context:
        prompt += f"\n\n📚 НЭМЭЛТ МЭДЛЭГ (GraphRAG):\n{graphrag_context}\n"
    return prompt


# ═══════════════════════════════════════════════════════════════════════════
#  GEMINI HELPERS (google-genai SDK)
# ═══════════════════════════════════════════════════════════════════════════

async def gemini_chat(system_prompt: str, history: List[Dict], user_message: str) -> str:
    """
    google-genai SDK-р multi-turn chat дуудна.
    history: [{"role": "user"|"model", "parts": ["text"]}]
    """
    client = get_genai_client()

    # History-г types.Content list болгоно
    contents = []
    for msg in history:
        role = msg.get("role", "user")
        parts = msg.get("parts", [])
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part(text=p) for p in parts if p],
            )
        )
    # Одоогийн хэрэглэгчийн асуулт нэм
    contents.append(
        types.Content(role="user", parts=[types.Part(text=user_message)])
    )

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.7,
        max_output_tokens=4096,
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    return response.text or ""


async def gemini_simple(system_prompt: str, user_message: str) -> str:
    """Энгийн нэг удаагийн Gemini дуудалт."""
    client = get_genai_client()
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.5,
        max_output_tokens=4096,
    )
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=GEMINI_MODEL,
        contents=user_message,
        config=config,
    )
    return response.text or ""


# ═══════════════════════════════════════════════════════════════════════════
#  AGENT 1 — Router
# ═══════════════════════════════════════════════════════════════════════════

def agent_router(state: AgentState) -> AgentState:
    try:
        session = get_session(state.session_id)
    except Exception as exc:
        logger.warning("[Agent 1] DB lookup failed: %s", exc)
        return state.model_copy(update={"has_excel": False})

    if not session:
        return state.model_copy(update={"has_excel": False})

    d = dict(session)
    excel_stats = d.get("summary")
    detected_test = d.get("test_name")
    if not excel_stats:
        return state.model_copy(update={"has_excel": False})

    return state.model_copy(update={
        "has_excel": True,
        "excel_stats": excel_stats,
        "detected_test_name": detected_test,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  AGENT 2 — Psychometric Expert
# ═══════════════════════════════════════════════════════════════════════════

async def agent_psychometric_expert(state: AgentState) -> AgentState:
    logger.info("[Agent 2] Processing (history=%d msgs)...", len(state.chat_history))

    # GraphRAG — optional
    graphrag_context = ""
    try:
        engine = get_local_search_engine()
        prompt_lower = state.user_prompt.lower()
        follow_kw = ["тус", "дээрх", "төлөвлөгөө", "үүнээс", "дараагийн",
                     "сургалт", "хөгжил", "зөвлөмж", "өгнө үү", "гаргаж"]
        is_follow_up = any(kw in prompt_lower for kw in follow_kw) and len(state.chat_history) > 0
        _dtq = state.detected_test_name or "Central Test"
        query = f"{_dtq} сургалтын төлөвлөгөө хөгжлийн арга" if is_follow_up else f"{state.user_prompt}\n{state.excel_stats or ''}"
        result = await asyncio.to_thread(engine.search, query)
        raw_ctx = result.response if hasattr(result, "response") else str(result)
        BAD = ["хангалттай байхгүй байна", "холбогдоно уу", "мэдээлэл одоогоор", "insufficient"]
        if not any(p in raw_ctx for p in BAD):
            graphrag_context = raw_ctx
    except Exception as exc:
        logger.warning("[Agent 2] GraphRAG skip: %s", exc)

    system_prompt = build_system_prompt(state, graphrag_context)

    # DB history → Gemini format
    gemini_history = []
    for msg in state.chat_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content:
            continue
        gemini_history.append({
            "role": "user" if role == "user" else "model",
            "parts": [content],
        })

    logger.info("[Agent 2] Gemini call with %d history turns", len(gemini_history))

    raw_analysis = ""
    try:
        raw_analysis = await gemini_chat(system_prompt, gemini_history, state.user_prompt)
        logger.info("[Agent 2] Gemini responded (%d chars)", len(raw_analysis))
    except Exception as exc:
        logger.error("[Agent 2] Gemini failed: %s", exc)
        raw_analysis = "Системд техникийн алдаа гарлаа. Түр хүлээгээд дахин оролдоно уу."

    return state.model_copy(update={"raw_analysis": raw_analysis, "graphrag_context": graphrag_context})


# ═══════════════════════════════════════════════════════════════════════════
#  AGENT 3 — Formatter
# ═══════════════════════════════════════════════════════════════════════════

async def agent_critic_formatter(state: AgentState) -> AgentState:
    if not state.raw_analysis:
        return state.model_copy(update={"final_output": "Шинжилгээний үр дүн олдсонгүй."})

    if (("ТАЛЕНТ АЙ:" in state.raw_analysis or "Harvard ManageMentor" in state.raw_analysis)
            and len(state.raw_analysis) > 100
            and "[Үргэлжилсэн" not in state.raw_analysis):
        return state.model_copy(update={"final_output": apply_mongolian_regex_fixes(state.raw_analysis)})

    data_scope = "Бүлгийн дүн шинжилгээ (Excel)" if state.has_excel else "Хувь хүний оноо"
    test_names = state.detected_test_name or "Central Test"

    formatter_sys = (
        "You are a Mongolian content formatter for Talent AI. "
        "Output the full analysis faithfully in Mongolian flowing paragraphs. "
        "No placeholders. No bullets, dashes, numbered lists. "
        "Keep all Harvard ManageMentor references exactly.\n"
        "Start with:\n"
        "──────────────────────────────────────────────────────────────\n"
        f"ТАЛЕНТ АЙ: ХҮНИЙ НӨӨЦИЙН СЭТГЭЛ ЗҮЙ\n"
        f"Эх сурвалж: {test_names} | Хамрах хүрээ: {data_scope}\n"
        f"Шинжээч: Талент АЙ\n"
        "──────────────────────────────────────────────────────────────\n"
    )

    formatted = ""
    try:
        formatted = await gemini_simple(formatter_sys, state.raw_analysis)
    except Exception as exc:
        logger.error("[Agent 3] Failed: %s", exc)
        formatted = state.raw_analysis

    if "[Үргэлжилсэн" in formatted or len(formatted) < 50:
        formatted = state.raw_analysis

    return state.model_copy(update={"final_output": apply_mongolian_regex_fixes(formatted)})


# ═══════════════════════════════════════════════════════════════════════════
#  PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

async def run_pipeline(session_id: str, user_message: str) -> str:
    try:
        raw_history = get_messages(session_id, limit=30)
    except Exception:
        raw_history = []

    cleaned_history = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in raw_history if m.get("content")
    ]

    state = AgentState(
        session_id=session_id,
        user_prompt=user_message,
        chat_history=cleaned_history,
    )

    state = agent_router(state)
    state = await agent_psychometric_expert(state)
    state = await agent_critic_formatter(state)

    final = state.final_output or ""

    # ҮРГЭЛЖ хадгална
    save_message(session_id, "user", user_message)
    if final and len(final) > 10:
        save_message(session_id, "assistant", final)

    return final


# ═══════════════════════════════════════════════════════════════════════════
#  FASTAPI
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Talent AI API", version="2.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # "*" origins-тай хамт True тавих боломжгүй (browser хориглоно)
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("Talent AI API v2.5.0 started")

def resolve_session_id(body_sid: Optional[str], request: Request) -> str:
    return (body_sid or "").strip() or request.headers.get("X-Session-Id", "").strip()


class AskRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    prompt: Optional[str] = None  # хуучин frontend нийцэл

class AskResponse(BaseModel):
    answer: str

@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: Request, body: AskRequest):
    session_id = resolve_session_id(body.session_id, request)
    user_message = (body.message or body.prompt or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id шаардлагатай.")
    if not user_message:
        raise HTTPException(status_code=400, detail="message шаардлагатай.")
    try:
        answer = await run_pipeline(session_id, user_message)
    except Exception as exc:
        logger.exception("Pipeline crashed: %s", exc)
        raise HTTPException(status_code=500, detail="Шинжилгээний системд алдаа гарлаа.")
    return AskResponse(answer=answer)


@app.post("/analyze-excel")
async def analyze_excel_endpoint(
    request: Request,
    file: UploadFile = File(...),
    question: str = Form(default="Энэ өгөгдлийг дүн шинжилгээ хийж дүгнэлт гарга"),
    session_id: Optional[str] = Form(default=None),
):
    sid = resolve_session_id(session_id, request)
    if not sid:
        raise HTTPException(status_code=400, detail="session_id шаардлагатай.")
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="Зөвхөн .xlsx, .xls, .csv файл зөвшөөрнө.")
    try:
        file_bytes = await file.read()
        result = process_excel(file_bytes, file.filename, question=question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Файл боловсруулахад алдаа: {exc}")

    detected_tests = result.get("detected_tests", [])
    primary_test = detected_tests[0] if detected_tests else "Тодорхойгүй"
    update_session_file(
        session_id=sid, filename=file.filename,
        summary=result.get("summary", ""), test_name=primary_test,
        rows=result.get("rows", 0), columns=result.get("columns", []),
        raw_data=result.get("raw_data", []),
    )
    try:
        answer = await run_pipeline(sid, question)
    except Exception as exc:
        logger.exception("Pipeline crashed after excel upload: %s", exc)
        answer = "Файл хадгалагдлаа. Дараагийн асуултаа бичнэ үү."
    return {"status": "processed", "session_id": sid, "test_name": primary_test, "answer": answer}


@app.post("/upload-excel")
async def upload_excel_endpoint(
    request: Request,
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(default=None),
):
    sid = resolve_session_id(session_id, request)
    if not sid:
        raise HTTPException(status_code=400, detail="session_id шаардлагатай.")
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="Unsupported format.")
    try:
        file_bytes = await file.read()
        result = process_excel(file_bytes, file.filename, question="")
        detected_tests = result.get("detected_tests", [])
        primary_test = detected_tests[0] if detected_tests else "Тодорхойгүй"
        update_session_file(
            session_id=sid, filename=file.filename,
            summary=result.get("summary", ""), test_name=primary_test,
            rows=result.get("rows", 0), columns=result.get("columns", []),
            raw_data=result.get("raw_data", []),
        )
        return {"status": "processed", "session_id": sid, "test_name": primary_test}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/sessions")
async def create_session_endpoint():
    return {"session_id": create_session()}

@app.get("/sessions")
async def list_sessions_endpoint():
    return {"sessions": get_all_sessions()}

@app.delete("/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "2.5.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_api:app", host="0.0.0.0", port=8000, reload=True)
