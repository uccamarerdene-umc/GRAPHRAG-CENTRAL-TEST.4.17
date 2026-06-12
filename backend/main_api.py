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
    "8. CTPI нэг тестэд хэт голлохгүй. Асуулттай холбоотой бол "
    "**Big5**, **EQ**, **VOC**, **PP Test**, **MOTIVATION+**, "
    "**Sales Competency** зэрэг тестүүдийг тэнцүү дурд.\n"
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
    "Big5 нэршлийн ЯАРАЛТАЙ засвар:\n"
    "- нийтэч эрч хүчтэй байдал\n"
    "- нягт нямбай байдал\n"
    "- нээлттэй байдал\n"
    "- бусдад анхаарал хандуулах байдал\n"
    "- сэтгэл хөдлөлийн тогтвортой байдал\n\n"
    "Нэр томьёоны зөв хэрэглээ: туршилт→тест, психометрийн→сэтгэл зүйн, "
    "үр бүтээл→бүтээмж, зохицол өндөртэй→уялдаа сайтай, "
    "удирдамжийн→удирдлагын, эергээр→эерэгээр, вест→тест, "
    "хөдөлмөрийн түвшин→ажлын сэдэл, нэр дэвшигч→ажил горилогч.\n\n"
    "PP ТЕСТИЙН МОНГОЛ НЭРШИЛ: Focus on Facts=Баримтад тулгуурладаг(оптимал 8-10), "
    "Desire to Lead=Удирдан чиглүүлэх дуртай(7-9), Emotional Distance=Сэтгэл хөдлөлөө хянадаг(6-8), "
    "Ambition=Амжилтанд хүрэх эрмэлзэлтэй(6-8), Novelty Seeking=Шинийг эрэлхийлэгч(6-8), "
    "Extraversion=Нээлттэй харилцдаг(6-9), Flexibility=Уян хатан байх чадвар(6-8), "
    "Involvement at Work=Ажлыг нэн тэргүүнд тавьдаг(7-9), Rule-Following=Дүрэм журмыг дагадаг(6-8), "
    "Persuasiveness=Ятган нөлөөлдөг(6-8), Need for Action=Шуурхай гүйцэтгэх дуртай(6-8), "
    "Improvisation=Аливааг бэлтгэлгүй хийж чаддаг(2-4), Autonomy=Бие дааж ганцаараа ажиллах дуртай(2-4), "
    "Altruism=Бусдыг нэн тэргүүнд тавьдаг(7-9).\n\n"
    "VOC ТЕСТИЙН МОНГОЛ НЭРШИЛ: Intellectual Curiosity=Аливааг таньж мэдэх болон суралцах сонирхол, "
    "Science & Technology=Шинжлэх ухаан болон технологи, Leadership=Манлайлал, "
    "Dedication to Others=Бусдад туслах дэмжих, Enterprising=Ажил хэрэгч, "
    "Methodical=Системтэй зохион байгуулалттай, Personal Relationships=Хувийн харилцаа, "
    "Interest in Data & Numbers=Тоо баримт мэдээлэл дээр ажиллах сонирхол.\n\n"
    "ОПТИМАЛ ОНОО: Оптималаас доош=хөгжүүлэх, оптималын хязгаарт=тохиромжтой(сул тал биш!), "
    "оптималаас дээш=хэт өндөр. "
    "ЧУХАЛ: Оптималд байгаа оноог ХЭЗЭЭ Ч сул тал гэж тайлбарлаж болохгүй!\n\n"
    "ТЕСТҮҮДИЙН УР ЧАДВАРЫН ЯЛГАА: CTPI=ажлын байрны ур чадвар, PP=ажлын хандлага зан чанар, "
    "Big5=үндсэн зан төлөв, VOC=мэргэжлийн сонирхол. ОГТХОН ХОЛЬЖ БОЛОХГҮЙ.\n\n"
    "ХАРИУЛТ БИЧИХ ФОРМАТ: 1)Оноог оптималтай харьцуулж тайлбарла "
    "2)Тестүүдийн уялдааг тайлбарла 3)Давуу тал 4)Сул тал 5)Тохиромжтой ажлын байр 6)Хөгжүүлэх зөвлөмж.\n\n"
    "CTPI 9 БҮЛЭГ: [АНАЛИЗ][БОРЛУУЛАЛТ][ХАРИЛЦАА][УДИРДЛАГА][ТӨЛӨВЛӨЛТ][БАГ][ДАСАН ЗОХИЦОХ][ЁС ЗҮЙ][АЖЛЫН ХАНДЛАГА]. "
    "Big5: Нээлттэй(6-10), Нягт нямбай(6-10), Нийтэч эрч(6-9), Бусдад анхаарал(6-9), Сэтгэл хөдлөлийн тэнцвэр(6-9). "
    "VOC сонирхол өндөр+CTPI ур чадвар нийцвэл=тогтвортой бүтээмжтэй ажилтан. "
    "PP хандлага нь CTPI ур чадварын суурь болдог.\n\n"
    "Асуулт: "
)
 
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
 
def _fix_text(text: str) -> str:
    """Нэршлийн автомат засвар — нэг удаа дуудна."""
    for wrong, right in _TEXT_REPLACEMENTS.items():
        text = text.replace(wrong, right)
    text = re.sub(r'Ний[а-яёөүА-ЯЁӨҮA-Za-z]*\s+эрч', 'Нийтэч эрч', text)
    text = re.sub(r'ний[а-яёөүА-ЯЁӨҮA-Za-z]*\s+эрч', 'нийтэч эрч', text)
    text = re.sub(r'(Нийл|Нийм|Нийр|Нийг|Нийс|Нийд|Нийх)[а-яёөүА-ЯЁӨҮ]*\s+эрч', 'Нийтэч эрч', text)
    text = re.sub(r'(нийл|нийм|нийр|нийг|нийс|нийд|нийх)[а-яёөүА-ЯЁӨҮ]*\s+эрч', 'нийтэч эрч', text)
    return text
 
 
# ---------------------------------------------------------------------------
# Gemini дуудлага — retry + rate-limit handling
# ---------------------------------------------------------------------------
def _gemini_generate(gc, prompt: str, model: str = "gemini-2.5-flash") -> str:
    """
    Retry with exponential backoff.
    503 болон 429 алдааг барьж, дахин оролдоно.
    """
    max_retries = 5
    for attempt in range(max_retries):
        try:
            resp = gc.models.generate_content(model=model, contents=prompt)
            return resp.text.strip()
        except Exception as err:
            err_str = str(err)
            retryable = any(code in err_str for code in ("503", "429", "RESOURCE_EXHAUSTED", "rate limit"))
            if retryable and attempt < max_retries - 1:
                wait = 2 ** attempt   # 1, 2, 4, 8, 16 секунд
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
            excel_info = (
                f"\n\n[Excel өгөгдлийн контекст]\n"
                f"Нийт ажилтан: {excel_ctx['rows']}\n"
                f"Баганууд: {excel_ctx['columns']}\n"
                f"Өгөгдлийн хураангуй:\n{excel_ctx['summary']}\n"
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
        answer = _fix_text(answer)
 
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
    "1. ХАРИУЛТЫН ФОРМАТ — уг бүтцийг хэзээ ч өөрчилж болохгүй, ХҮСНЭГТ АШИГЛАХГҮЙ:\n"
    "---\n"
    "ТАЛЕНТ АЙ: ХҮНИЙ НӨӨЦИЙН СЭТГЭЛ ЗҮЙН ДҮН ШИНЖИЛГЭЭ\n"
    "Эх сурвалж: [Тестийн нэрс] | Хамрах хүрээ: [Нийт мөр болон тоон утгын хэмжээ]\n"
    "Шинжээч: Талент АЙ (Хиймэл оюун ухаант зөвлөх систем)\n\n"
    "⚖️ ЕРӨНХИЙ ТОЙМ & СИСТЕМИЙН ДҮГНЭЛТ\n"
    "[Байгууллагын багийн нийт дундаж үзүүлэлт болон соёлын ерөнхий тойм.]\n\n"
    "👤 БАЙГУУЛЛАГЫН ДҮР ТӨРХ, СОЁЛЫН ГҮНЗГИЙ ДҮН ШИНЖИЛГЭЭ\n"
    "Сэтгэл зүйн хэв маяг: [...]\n"
    "Хүчтэй талууд: [...]\n"
    "Стратегийн зөрчилдөөний эрсдэл (Критик цэг): [...]\n"
    "Шинжилгээ: [...]\n\n"
    "📈 ТАЛЕНТ МЕНЕЖМЕНТ & ХЭРЭГЖИХҮЙЦ ЗӨВЛӨМЖ\n"
    "Байгууллагын оношлогоо: [...]\n"
    "Санал болгох бүтэц / Үүрэг: [...]\n"
    "Богино хугацааны хөгжлийн дасгал (Actionable Insight): [...]\n"
    "---\n\n"
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
        prompt = _ep.build_excel_prompt(
            {**processed, "prompt_data": summary_text}, question, EXCEL_PROMPT
        )
 
        # Retry дотор дуудна
        answer = _gemini_generate(_gemini_client, prompt)
        answer = _fix_text(answer)
 
        session_id = request.headers.get("X-Session-Id", "default")
        ctx = {
            "summary": processed["summary"],
            "columns": processed["columns"],
            "rows": processed["rows"],
            "detected_tests": processed["detected_tests"],
            "filename": filename,
        }
        _excel_sessions[session_id] = ctx
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
