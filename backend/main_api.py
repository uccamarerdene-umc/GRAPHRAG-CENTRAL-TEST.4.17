import os, re, uuid, time, logging, asyncio
import pandas as pd
import io
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path="/home/ec2-user/GRAPHRAG-CENTRAL-TEST.4.17/backend/.env", override=True)
except ImportError:
    pass
 
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] - %(message)s")
logger = logging.getLogger("graphrag_api")
 
import db as _db
_db.init_db()
import excel_processor as _ep
_excel_sessions = {}  # RAM cache
 
API_KEY = os.environ.get("GRAPHRAG_API_KEY", "").strip()
GRAPHRAG_ROOT = os.environ.get("GRAPHRAG_ROOT", ".").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
 
SYSTEM_PROMPT = (
    "Та бол Central Test-ийн албан ёсны AI зөвлөх, Талент AI юм. "
    "Өгөгдөлд тулгуурлан монгол хэлээр мэргэжлийн хариулт өгнө.\n\n"
    "Дүрмүүд:\n"
    "1. Зөвхөн МОНГОЛ хэлээр хариул.\n"
    "1а. ЧУХАЛ: Хариултыг НЭГДСЭН, ҮРГЭЛЖИЛСЭН өгүүлбэрээр бич. Хэсэг хэсэгт хуваахгүй. Хүснэгт, багана, markdown table огтхон гаргахгүй. Зөвхөн дараалсан өгүүлбэр, догол мөр ашигла.\n"
    "2. Монгол хэлний зөв бичгийн дүрэм чанд баримтал.\n"
    "3. Зөвхөн тестийн нэрийг **тодоор** тэмдэглэ — бусад үгийг болд болгохгүй.\n"
    "3а. Хариултыг ЗААВАЛ үргэлжилсэн өгүүлбэрээр бич. Хүснэгт, багана үүсгэхгүй. Markdown table (|) хэрэглэхгүй.\n"
    "4. Хариулт 150-250 үгэнд багтаа. Товч, тодорхой байх нь чухал.\n"
    "5. Өгөгдөлд байхгүй тоо, нэр, жишээ зохиож болохгүй. "
    "Ялангуяа дундаж оноо, хувь, статистик тоог ОГТХОН зохиохгүй.\n"
    "6. Ямар ч байгууллага, компани, ХХК-ийн нэрийг дурдаж болохгүй.\n"
    "7. Өгөгдөл дутуу байвал: 'Энэ асуултад хариулах мэдээлэл "
    "одоогоор хангалттай байхгүй байна. Central Test-ийн зөвлөхүүдтэй "
    "холбогдоно уу' гэж хариул.\n"
    "8. ЗӨВХӨН GraphRAG context-д байгаа тестүүдийг дурд. "
    "Context-д байхгүй тестийн нэрийг ОГТХОН санал болгохгүй. "
    "Жишээ нь: context зөвхөн CTPI агуулж байвал Big5, Sales, VOC-г дурдаж болохгүй.\n"
    "9. Central Test нь зөвхөн менежерийн тест биш — "
    "ажилтан сонгон шалгаруулалт, хөгжүүлэлт, карьерын чиг баримжаа, "
    "хувь хүний хөгжил зэрэгт ашиглагддаг сэтгэл зүйн үнэлгээний "
    "иж бүрэн шийдэл юм.\n\n"
    "10. Central Test-тэй огт хамааралгүй асуулт (газарзүй, улс төр, "
    "хоол, спорт гэх мэт) ирвэл: 'Би Central Test-ийн AI зөвлөх тул "
    "зөвхөн тестүүдтэй холбоотой асуулт хариулна' гэж хэл.\n"
    "11. Хоёрдмол утгатай асуулт ирвэл тодруулга хүс.\n"
    "12. Богино асуулт (10 үгнээс доош) → 100-150 үгэн хариулт өг.\n\n"
    "CTPI-ийн 4 үндсэн бүлэг (энэ нэршлийг ашигла):\n"
    "- Бусдыг удирдах хандлага\n"
    "- Өөрийгөө удирдах хандлага\n"
    "- Өөрчлөлтийг удирдах хандлага\n"
    "- Ажилдаа хандах хандлага\n\n"
    "Нэр томьёоны зөв хэрэглээ: туршилт→тест, психометрийн→сэтгэл зүйн, "
    "үр бүтээл→бүтээмж, зохицол өндөртэй→уялдаа сайтай, "
    "удирдамжийн→удирдлагын, эергээр→эерэгээр, вест→тест, "
    "хөдөлмөрийн түвшин→ажлын сэдэл, нэр дэвшигч→ажил горилогч.\n\n"
    "ОПТИМАЛ ОНОО: Оптималаас доош=хөгжүүлэх, оптималын хязгаарт=тохиромжтой(сул тал биш!), "
    "оптималаас дээш=хэт өндөр. "
    "ЧУХАЛ: Оптималд байгаа оноог ХЭЗЭЭ Ч сул тал гэж тайлбарлаж болохгүй!\n\n"
    "ТЕСТҮҮДИЙН УР ЧАДВАРЫН ЯЛГАА (зөвхөн context-д байгаа тестэд хамаарна):\n"
    "CTPI=ажлын байрны ур чадвар.\n"
    "ОГТХОН ХОЛЬЖ БОЛОХГҮЙ — context-д байхгүй тестийг дурдахгүй.\n\n"
    "ХАРИУЛТ БИЧИХ ФОРМАТ: 1)Оноог оптималтай харьцуулж тайлбарла "
    "2)Тестүүдийн уялдааг тайлбарла 3)Давуу тал 4)Сул тал 5)Тохиромжтой ажлын байр 6)Хөгжүүлэх зөвлөмж.\n\n"
    "CTPI 9 БҮЛЭГ: [АНАЛИЗ][БОРЛУУЛАЛТ][ХАРИЛЦАА][УДИРДЛАГА][ТӨЛӨВЛӨЛТ][БАГ][ДАСАН ЗОХИЦОХ][ЁС ЗҮЙ][АЖЛЫН ХАНДЛАГА].\n\n"
    "PROMPT GUARD — ЭХ СУРВАЛЖИЙН ХЯЗГААРЛАЛТ (ХАТУУ ДАГАХ):\n"
    "GraphRAG context дахь эх сурвалжийг заавал шалга.\n"
    "- Context ЗӨВХӨН PP / PP2 баримт агуулж байвал: CTPI, Big5, Sales Competency, VOC, EQ-ийн нэршлийг ОГТХОН дурдаж болохгүй.\n"
    "- Context ЗӨВХӨН CTPI баримт агуулж байвал: PP, Big5, Sales Competency-ийн нэрийг ашиглахгүй.\n"
    "- Context ЗӨВХӨН Big5 баримт агуулж байвал: CTPI, PP, Sales Competency-ийн нэрийг ашиглахгүй.\n"
    "- Context ЗӨВХӨН Sales Competency баримт агуулж байвал: CTPI, Big5, PP, VOC-ийн нэрийг ашиглахгүй.\n"
    "- Context олон тестийн баримт агуулж байвал: тест тус бүрийн мэдээллийг тусад нь дурд, хольж болохгүй.\n"
    "- Context-д байхгүй тестийн мэдээлэл хэрэгтэй бол: Энэ асуултад хариулах мэдээлэл одоогийн эх сурвалжид байхгүй байна гэж хариул.\n\n"
    "Асуулт: "
)
 

# ---------------------------------------------------------------------------
# Prompt Guard helper — GraphRAG context-оос тест тодорхойлох
# ---------------------------------------------------------------------------
_CONTEXT_TEST_PATTERNS = {
    # Тест бүрийг ЗӨВХӨН тухайн тестийн файлын нэр/code-р илрүүлнэ
    # Агуулгын үгээр илрүүлэхгүй — давхцал гарна
    "ctpi":             [r"\bctpi\b", r"ctpi.?tailan", r"ctpi.?report"],
    "big5":             [r"\bbig.?5\b", r"big5.?tailan", r"big5.?report",
                         r"five.?factor", r"\bneo\b"],
    "pp":               [r"\bpp2\b", r"professional.?profile.?2",
                         r"pp2.?tailan", r"pp.?test.?tailan"],
    "pp test":          [r"\bpp.?test\b"],
    "voc":              [r"\bvoc\b", r"voc.?tailan"],
    "eq":               [r"\beq\b", r"eq.?tailan", r"emotional.?intelligence.?report"],
    "motivation":       [r"\bmotivation\+?\b", r"motivation.?tailan"],
    "sales competency": [r"\bsales.?competency\b", r"sales.?profile",
                         r"borluulalt.?tailan"],
}

def _detect_tests_from_context(context_text: str) -> list:
    """GraphRAG context-оос ямар тест илэрснийг тодорхойлно."""
    import re as _re
    found = []
    low = context_text.lower()
    for label, pats in _CONTEXT_TEST_PATTERNS.items():
        if any(_re.search(p, low, _re.IGNORECASE) for p in pats):
            found.append(label)
    return found

# ---------------------------------------------------------------------------
# Нэршлийн засвар — нэг л газар тодорхойлно, хаа сайгүй ашиглана
# ---------------------------------------------------------------------------
_TEXT_REPLACEMENTS = {
    "Ниймэл": "Нийтэч", "ниймэл": "нийтэч",
    "Ниймтэй": "Нийтэч", "ниймтэй": "нийтэч",
    "Нийгэмч": "Нийтэч", "нийгэмч": "нийтэч",
    "Ниймч": "Нийтэч", "ниймч": "нийтэч",
    "Нийрч": "Нийтэч", "нийрч": "нийтэч",
    "Ний тэч": "Нийтэч", "ний тэч": "нийтэч",
    "Ниймц": "Нийтэч", "ниймц": "нийтэч",
    "Н ягт": "Нягт",
    "удирдамжийн": "удирдлагын", "Удирдамжийн": "Удирдлагын",
    "эергээр": "эерэгээр",
    "үр бүтээлтэй": "бүтээмжтэй", "үр бүтээл": "бүтээмж",
}
 
# Глобал зөвшөөрөгдсөн тестүүд
_allowed_tests: list = []

def set_allowed_tests(tests: list):
    global _allowed_tests
    _allowed_tests = [t.lower() for t in tests] if tests else []

def _fix_text(text: str, allowed: list = None) -> str:
    """Нэршлийн автомат засвар — нэг удаа дуудна."""
    for wrong, right in _TEXT_REPLACEMENTS.items():
        text = text.replace(wrong, right)
    text = re.sub(r'Ний[а-яёөүА-ЯЁӨҮA-Za-z]*\s+эрч', 'Нийтэч эрч', text)
    text = re.sub(r'ний[а-яёөүА-ЯЁӨҮA-Za-z]*\s+эрч', 'нийтэч эрч', text)
    text = re.sub(r'(Нийл|Нийм|Нийр|Нийг|Нийс|Нийд|Нийх)[а-яёөүА-ЯЁӨҮ]*\s+эрч', 'Нийтэч эрч', text)
    text = re.sub(r'(нийл|нийм|нийр|нийг|нийс|нийд|нийх)[а-яёөүА-ЯЁӨҮA-Za-z]*\s+эрч', 'нийтэч эрч', text)
    # Зөвшөөрөгдөөгүй тестийн нэрийг арилгах
    check = allowed if allowed is not None else _allowed_tests
    if check:
        all_tests = ["CTPI", "Big5", "PP Test", "PP тест", "VOC", "EQ", "MOTIVATION+", "Sales Competency", "SALES"]
        for t in all_tests:
            if not any(t.lower() in a for a in check):
                # **TestName** болон TestName бүх хэлбэрийг арилгах
                text = re.sub(rf'\*\*{re.escape(t)}\*\*', '', text)
                text = re.sub(rf'\*{re.escape(t)}\*', '', text)
                # "TestName тестийн", "TestName-ийн" гэх мэт
                text = re.sub(rf'{re.escape(t)}[- ийн]*тест[^.]*\.', '', text, flags=re.IGNORECASE)
                text = re.sub(rf'{re.escape(t)}[- ийн]*үр дүн[^.]*\.', '', text, flags=re.IGNORECASE)
                # Үлдсэн TestName дурдлага бүрийг арилгах
                pat = re.escape(t)
                text = re.sub(pat + r'[- ийн]*тест[^.]*\.', '', text, flags=re.IGNORECASE)
                text = re.sub(pat + r'[- ийн]*үр дүн[^.]*\.', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\b' + pat + r'\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()
 
 
# ---------------------------------------------------------------------------
# Gemini дуудлага — retry + rate-limit handling
# ---------------------------------------------------------------------------
def _gemini_generate(gc, prompt: str, model: str = "gemini-2.5-flash") -> str:
    """
    Retry with exponential backoff.
    503 болон 429 алдааг барьж, дахин оролдоно.
    """
    max_retries = 8
    for attempt in range(max_retries):
        try:
            from google.genai import types as _gtypes
            resp = gc.models.generate_content(
                model=model,
                contents=prompt,
                config=_gtypes.GenerateContentConfig(
                    system_instruction=(
                        "Та Central Test-ийн AI зөвлөх. "
                        "ХАМГИЙН ЧУХАЛ ДҮРЭМ: Хэрэв prompt дотор PROMPT GUARD байвал "
                        "тэнд заасан байхгүй тестүүдийг ОГТХОН дурдаж болохгүй. "
                        "Зөвхөн илэрсэн тестийн өгөгдөлд үндэслэн хариул."
                    )
                )
            )
            return resp.text.strip()
        except Exception as err:
            err_str = str(err)
            retryable = any(code in err_str for code in ("503", "429", "RESOURCE_EXHAUSTED", "rate limit", "UNAVAILABLE"))
            if retryable and attempt < max_retries - 1:
                wait = min(2 ** attempt, 60)  # 1, 2, 4, 8, 16, 32, 60, 60 секунд
                logger.warning(f"Gemini алдаа ({err_str[:80]}), {wait}s хүлээж дахин оролдоно...")
                time.sleep(wait)
            else:
                raise
 
 
_search_engine = None
_gemini_client = None
 
def _load_graphrag():
    global _search_engine, _gemini_client
    os.environ["OPENAI_API_KEY"] = GEMINI_KEY
    from google import genai as gai
    _gemini_client = gai.Client(api_key=GEMINI_KEY)
    from graphrag.config.load_config import load_config
    from graphrag.query.factory import get_local_search_engine
    from graphrag.query.indexer_adapters import (
        read_indexer_entities,
        read_indexer_relationships,
        read_indexer_reports,
        read_indexer_text_units,
    )
    from graphrag_vectors import create_vector_store, VectorStoreType, VectorStoreConfig, IndexSchema
    root = Path(GRAPHRAG_ROOT)
    output = root / "output"
    config = load_config(root_dir=root)
    e  = pd.read_parquet(output / "entities.parquet")
    r  = pd.read_parquet(output / "relationships.parquet")
    c  = pd.read_parquet(output / "community_reports.parquet")
    t  = pd.read_parquet(output / "text_units.parquet")
    cm = pd.read_parquet(output / "communities.parquet")
    entities          = read_indexer_entities(e, cm, community_level=2)
    relationships     = read_indexer_relationships(r)
    community_reports = read_indexer_reports(c, cm, community_level=2)
    text_units        = read_indexer_text_units(t)
    vs_config = VectorStoreConfig(
        type=VectorStoreType.LanceDB,
        db_uri=str(output / "lancedb"),
        vector_size=3072,
    )
    schema = IndexSchema(index_name="entity_description")
    store = create_vector_store(vs_config, schema)
    store.connect()
 
    class GeminiEmbedder:
        def embed(self, text):
            res = _gemini_client.models.embed_content(
                model="gemini-embedding-001", contents=text
            )
            return res.embeddings[0].values
 
        def embedding(self, input, **kwargs):
            vecs = [self.embed(t) for t in input] if isinstance(input, list) else [self.embed(input)]
            class R:
                def __init__(self, v):
                    self.embeddings = [type("E", (), {"values": x})() for x in v]
                @property
                def first_embedding(self):
                    return self.embeddings[0].values
            return R(vecs)
 
    _search_engine = get_local_search_engine(
        config=config,
        reports=community_reports,
        text_units=text_units,
        entities=entities,
        relationships=relationships,
        covariates={},
        description_embedding_store=store,
        response_type="multiple paragraphs",
    )
    if hasattr(_search_engine, "context_builder") and \
       hasattr(_search_engine.context_builder, "text_embedder"):
        _search_engine.context_builder.text_embedder = GeminiEmbedder()
    logger.info("Engine loaded OK")
 
 
@asynccontextmanager
async def lifespan(app):
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _load_graphrag)
        logger.info("Startup complete")
    except Exception as ex:
        logger.error(f"Startup failed: {ex}")
    yield
 
 
app = FastAPI(title="Central Test", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
 
 
class QueryRequest(BaseModel):
    prompt: str
    method: str = "local"
 
 
class QueryResponse(BaseModel):
    answer: str
    request_id: str
    method: str
    elapsed_ms: int
 
 
@app.post("/ask", response_model=QueryResponse)
async def ask_graph(request: Request, body: QueryRequest):
    if request.headers.get("X-API-Key", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if _search_engine is None:
        return JSONResponse(status_code=503, content={"error": "Engine not loaded."})
 
    rid = str(uuid.uuid4())[:8]
    t0 = time.time()
    try:
        # Мэндчилгээний шуурхай хариулт
        exact_greetings = {"сайн байна уу", "сайн уу", "байна уу", "мэнд", "hello", "hi", "сайн"}
        prompt_clean = body.prompt.strip().lower().rstrip("?!. ")
        if prompt_clean in exact_greetings and len(body.prompt.strip()) <= 20:
            return QueryResponse(
                answer="Сайн байна уу! Танд юугаар туслах вэ?",
                request_id=rid, method=body.method, elapsed_ms=0,
            )
 
        # Excel session context
        session_id = request.headers.get("X-Session-Id", "default")
        excel_ctx = _excel_sessions.get(session_id)
        if not excel_ctx:
            import json as _json
            try:
                with open(f"/tmp/excel_session_{session_id}.json") as sf:
                    excel_ctx = _json.load(sf)
                    _excel_sessions[session_id] = excel_ctx
            except Exception:
                excel_ctx = None
 
        if excel_ctx:
            _ex_dt = excel_ctx.get('detected_tests', [])
            _ex_dt = _ex_dt if isinstance(_ex_dt, list) else [str(_ex_dt)]
            _ex_forbidden = [t for t in ['CTPI','Big5','PP','VOC','EQ','MOTIVATION+','Sales Competency','SALES']
                             if not any(t.lower() in str(d).lower() for d in _ex_dt)]
            _ex_forbidden_str = ", ".join(_ex_forbidden) if _ex_forbidden else "байхгүй"
            excel_info = (
                f"\n\n[Excel өгөгдлийн контекст]\n"
                f"Нийт ажилтан: {excel_ctx['rows']}\n"
                f"Баганууд: {excel_ctx['columns']}\n"
                f"Илэрсэн тестүүд: {excel_ctx.get('detected_tests', '')}\n"
                f"Өгөгдлийн хураангуй:\n{excel_ctx['summary']}\n"
                f"[EXCEL PROMPT GUARD]\n"
                f"Энэ файлд ЗӨВХӨН байгаа тест: {excel_ctx.get('detected_tests', '')}\n"
                f"ХАТУУ ХОРИГЛОНО: {_ex_forbidden_str}\n"
                f"Дээрх ХОРИГЛОНО жагсаалтын тестийн нэр, нэршил, хэмжүүрийг хариултад НЭГ Ч УДАА дурдаж болохгүй.\n"
                f"Зөрчвөл хариулт БҮРЭН БУРУУ тооцогдоно.\n"
                f"Дээрх өгөгдөлд үндэслэн асуултад хариул.\n"
            )
            query = SYSTEM_PROMPT + excel_info + "\n\nАсуулт: " + body.prompt
        else:
            query = SYSTEM_PROMPT + body.prompt
 
        # Context builder
        loop = asyncio.get_running_loop()
        ctx_result = await loop.run_in_executor(
            None,
            lambda: _search_engine.context_builder.build_context(query=query),
        )
        context_text = ctx_result.context if hasattr(ctx_result, "context") else str(ctx_result)
        full_prompt = f"{query}\n\nContext:\n{context_text}"
 
        # Gemini дуудлага (retry дотор)
        answer = await loop.run_in_executor(
            None, lambda: _gemini_generate(_gemini_client, full_prompt)
        )
        if excel_ctx:
            detected_fix = excel_ctx.get("detected_tests", [])
            answer = _fix_text(answer, allowed=[t.lower() for t in detected_fix] if detected_fix else None)
        else:
            answer = _fix_text(answer, allowed=_detect_tests_from_context(context_text))

        # /ask post-filter: excel session-д байхгүй тестийн нэрийг арилгах
        if excel_ctx:
            import re as _re3
            detected_ask = excel_ctx.get("detected_tests", [])
            if isinstance(detected_ask, str):
                detected_ask = [detected_ask]
            all_tests = ["CTPI", "Big5", "PP", "PP Test", "VOC", "EQ", "MOTIVATION+", "Sales Competency"]
            missing_ask = [t for t in all_tests if not any(t.lower() in d.lower() for d in detected_ask)]
            for mt in missing_ask:
                import re as _re3
                answer = _re3.sub(rf'\*\*{_re3.escape(mt)}\*\*', mt, answer)
                answer = _re3.sub(rf'(?<!\w){_re3.escape(mt)}(?!\w)[^.]*тест[^.]*\.', '', answer)

        ms = int((time.time() - t0) * 1000)
        if not answer:
            return JSONResponse(status_code=502, content={"error": "Empty answer."})
        logger.info(f"[{rid}] OK {ms}ms")
        return QueryResponse(answer=answer, request_id=rid, method=body.method, elapsed_ms=ms)
 
    except Exception as ex:
        logger.error(f"[{rid}] Failed: {ex}")
        return JSONResponse(status_code=502, content={"error": "Search failed."})
 
 
@app.get("/health")
async def health():
    return {"status": "ok", "engine": _search_engine is not None}
 
 
EXCEL_PROMPT = (
    "Та бол Central Test-ийн албан ёсны арга зүйд мэргэшсэн ХҮНИЙ НӨӨЦИЙН ХИЙМЭЛ ОЮУН УХААНТ ЗӨВЛӨХ СИСТЕМ бөгөөд 'Талент АЙ' юм. "
    "Хэрэглэгчийн өгсөн Excel өгөгдөл болон тестийн үр дүнд сэтгэл зүйн гүнзгий дүн шинжилгээ (Psychometric Analysis) хийхдээ "
    "хувь ажилтан бүрээр биш, тухайн БАЙГУУЛЛАГЫН НИЙТ ДҮР ТӨРХ, БАГИЙН СОЁЛД нэгдсэн дүн шинжилгээ хийнэ.\n\n"
    "ЧАНД БАРИМТЛАХ ШАЛГУУР ШААРДЛАГУУД:\n\n"
    "ХАТУУ ДҮРЭМ — ЭНЭ ДҮРМИЙГ ЗӨРЧВӨЛ ХАРИУЛТ БУРУУ ТООЦОГДОНО:\n"
    "1. ХҮСНЭГТ, БАГАНА, MARKDOWN TABLE (|) ОГТХОН АШИГЛАХГҮЙ. ЗӨРЧВӨЛ БУРУУ!\n"
    "2. Зөвхөн өгөгдөлд байгаа ТЕСТИЙН нэрийг ашигла. CTPI өгвөл зөвхөн CTPI. Big5 өгвөл зөвхөн Big5. ОГТХОН ХОЛЬЖ БОЛОХГҮЙ!\n"
    "3. Бүх хариултыг ЗӨВХӨН үргэлжилсэн өгүүлбэр, догол мөрөөр бич.\n\n"
    "ТАЛЕНТ АЙ: ХҮНИЙ НӨӨЦИЙН СЭТГЭЛ ЗҮЙН ДҮН ШИНЖИЛГЭЭ\n"
    "Эх сурвалж: [Зөвхөн өгөгдөлд байгаа тестийн нэр] | Хамрах хүрээ: [Нийт мөр]\n"
    "Шинжээч: Талент АЙ\n\n"
    "⚖️ ЕРӨНХИЙ ТОЙМ\n"
    "Үргэлжилсэн өгүүлбэрээр бич. Хүснэгт огт гаргахгүй.\n\n"
    "👤 БАЙГУУЛЛАГЫН ДҮР ТӨРХ\n"
    "Үргэлжилсэн өгүүлбэрээр бич. Хүснэгт огт гаргахгүй.\n\n"
    "📈 ЗӨВЛӨМЖ\n"
    "Үргэлжилсэн өгүүлбэрээр бич. Хүснэгт огт гаргахгүй.\n\n"
    "2. Зөвхөн НЭГ ТЕСТ-ийн үр дүн оруулсан бол бусад тестийн нэр томьёо ашиглахыг ХАТУУ ХОРИГЛОНО.\n"
    "3. Excel-ээс орж ирж буй БҮХ МӨР, ТООН УТГА бүрийг бүрэн уншиж дундаж, хазайлтыг тооцно.\n"
    "4. Урт онолын тайлбар устга. Өгүүлбэр бүр нягт, стратегийн шийдвэрт туслах байна.\n"
    "НЭМЭЛТ ДҮРМҮҮД: Зөвхөн монгол хэлээр. Хүснэгт/markdown table(|) огтхон ашиглахгүй. "
    "Байгууллагын нэр дурдахгүй. Зохиомол тоо гаргахгүй.\n\n"
)
 
 
@app.post("/analyze-excel")
async def analyze_excel(
    request: Request,
    file: UploadFile = File(...),
    question: str = "Энэ өгөгдлийг дүн шинжилгээ хийж дүгнэлт гарга",
):
    if request.headers.get("X-API-Key", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        contents = await file.read()
        filename = file.filename or "file.xlsx"
        processed = _ep.process_excel(contents, filename, question)
        summary_text = processed["prompt_data"]
        if len(summary_text) > 30000:
            summary_text = summary_text[:30000] + "\n...[өгөгдлийн үргэлжлэл орхигдлоо]..."
        # Prompt Guard — зөвхөн илэрсэн тестийн нэрийг ашиглах
        detected = processed.get("detected_tests", [])
        if isinstance(detected, str):
            detected = [detected]
        detected_str = ", ".join(detected) if detected else "тодорхойгүй"
        all_possible = ["CTPI", "Big5", "PP", "VOC", "EQ", "MOTIVATION+", "Sales Competency"]
        missing = [t for t in all_possible if not any(t.lower() in d.lower() for d in detected)]
        missing_str = ", ".join(missing) if missing else ""

        guard = (
            f"\n\n╔══ PROMPT GUARD ══╗\n"
            f"Энэ файлд ЗӨВХӨН дараах тест(үүд) байна: {detected_str}\n"
        )
        if missing_str:
            guard += f"ОГТХОН дурдаж болохгүй тестүүд: {missing_str}\n"
        guard += (
            f"Дээрх байхгүй тестүүдийн нэр, үр дүн, хэмжүүрийг хариултад оруулбал БУРУУ хариулт болно.\n"
            f"╚════════════════════╝\n"
        )

        prompt = _ep.build_excel_prompt(
            {**processed, "prompt_data": summary_text}, question, EXCEL_PROMPT
        )
        prompt = prompt + guard

        # Retry дотор дуудна
        answer = _gemini_generate(_gemini_client, prompt)
        answer = _fix_text(answer, allowed=[t.lower() for t in detected])
 
        session_id = request.headers.get("X-Session-Id", "default")
        ctx = {
            "summary": processed["summary"],
            "columns": processed["columns"],
            "rows": processed["rows"],
            "detected_tests": processed["detected_tests"],
            "filename": filename,
            "last_answer": answer[:3000] if answer else "",
        }
        _excel_sessions[session_id] = ctx
        # /tmp файлд хадгална — backend restart хийсэн ч session хадгалагдана
        try:
            import json as _json_tmp
            with open(f"/tmp/excel_session_{session_id}.json", "w") as _sf:
                _json_tmp.dump(ctx, _sf, ensure_ascii=False)
        except Exception as _tmp_err:
            logger.warning(f"Tmp session save failed: {_tmp_err}")
        try:
            _db.save_excel_session(
                session_id=session_id,
                filename=filename,
                rows=processed["rows"],
                columns=processed["columns"],
                summary=processed["summary"],
                raw_data=processed["raw_data"],
            )
            _db.save_message(session_id, "user", f"📊 {filename} файл оруулав — {question}")
            _db.save_message(session_id, "ai", answer)
        except Exception as db_err:
            logger.warning(f"DB save failed: {db_err}")
 
        result = {
            "answer": answer,
            "rows": processed["rows"],
            "columns": processed["columns"],
            "detected_tests": processed["detected_tests"],
            "session_id": session_id,
            "filename": filename,
        }
        if processed["dropped_cols"] > 0:
            result["warning"] = (
                f"{processed['dropped_cols']} багана орхигдлоо — хамгийн ялгаатай 20 баганыг ашиглав"
            )
        return result
 
    except Exception as ex:
        logger.error(f"Excel analysis failed: {ex}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": f"Алдаа: {str(ex)}"})
 
 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
