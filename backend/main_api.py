"""
main_api.py — Talent AI FastAPI Backend v2.5.0
Fixes v2.5:
  - google.generativeai → google.genai (шинэ SDK, requirements.txt-тай нийцүүлсэн)
  - Gemini multi-turn chat history зөв дамждаг
  - GraphRAG байхгүй/муу хариулсан ч Gemini ЗААВАЛ ажилладаг
  - User асуулт ҮРГЭЛЖ DB-д хадгалагддаг
  - "мэдээлэл хангалтгүй" гэж хариулах боломжгүй

Энэ хувилбар: GIT main_api.py-г суурь болгож, системийн prompt-ыг
CENTRAL TEST-ийн иж бүрэн мэдлэгийн сан (7 тест) болон хариулт бичих
нарийвчилсан загвараар баяжуулсан.
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
═══════════════════════════════════════════════════
CENTRAL TEST ТЕСТҮҮДИЙН ИЖ БҮРЭН МЭДЛЭГИЙН САН
═══════════════════════════════════════════════════

1. CTPI — Мэргэжлийн ур чадварын тест (61 ур чадвар, 9 бүлэг, оноо 1-10)
   Оноо тайлбар: 1-3=маш бага, 4-5=бага, 6-7=дунд, 8-9=өндөр, 10=маш өндөр
   Оптималаас доош=хөгжүүлэх шаардлагатай
   Оптималын хязгаарт=тохиромжтой (СУЛ ТАЛ БИШ!)
   Оптималаас дээш=хэт өндөр, зарим нөхцөлд сөрөг нөлөөтэй

  CTPI ТЕСТ — 61 УР ЧАДВАР ↔ HARVARD MANAGEMENTOR МОДУЛИЙН ТОХИРУУЛГА

  АНАЛИЗ, ДҮН ШИНЖИЛГЭЭ ХИЙХ ЧАДАМЖ
  Анализ хийх чадвар (Оптимал 1–10):	доош → HMM: Decision Making, Business acumen
  Шийдвэр гаргах чадвар (Оптимал 6–9):	доош → HMM: Decision Making
  Мэдлэг, туршлага хуримтлуулах чадвар (Оптимал 2–9):	доош → HMM: Career management
  Мэдлэг туршлагаа хуваалцах чадвар (Оптимал 6–10):	доош → HMM: Coaching, Leveraging Your Network
  Аливааг хурдан сурах чадвар (Оптимал 2–10):	доош → HMM: Digital Intelligence, Career management
  Бодолтой байх чадвар (Оптимал 1–10):	доош → HMM: Strategic Thinking

  БОРЛУУЛАЛТЫН ЧАДАМЖ
  Хэлцэл тохиролцоог амжилттай дуусгах чадвар (Оптимал 6–9):	доош → HMM: Negotiating, "NEGOTIATING" case
  Хэрэглэгчийг сэтгэл ханамжтай байлгах чадвар (Оптимал 6–9):	доош → HMM: Customer Focus
  Хэрэглэгчийн сэтгэл хөдлөл мэдрэмжийг нэн тэргүүнд тавих чадвар (Оптимал 6–9):	доош → HMM: Customer Focus
  Бизнесийн боломжийг тодорхойлох чадвар (Оптимал 7–10):	доош → HMM: Business acumen, Business Case Development
  Хүмүүсийг холбох, танилын хүрээгээ тэлэх чадвар (Оптимал 6–10):	доош → HMM: Leveraging Your Network
  Үр дүнг төсөөлүүлэн тайлбарлах чадвар (Оптимал 2–10):	доош → HMM: Presentation skill, Persuading Others
  Шинэ хэрэглэгч олох чадвар (Оптимал 2–10):	доош → HMM: Marketing Essentials
  Борлуулалт хийх чадвар (Оптимал 2–10):	доош → HMM: Persuading Others
  Стратеги борлуулалт хийх чадвар (Оптимал 2–9):	доош → HMM: Strategic Thinking, Persuading Others
  Хэрэглэгчийн хэрэгцээг ойлгох чадвар (Оптимал 6–9):	доош → HMM: Customer Focus

  ХАРИЛЦААНЫ ЧАДАМЖ
  Бусдыг татах чадвар (Оптимал 2–10):	доош → HMM: Persuading Others
  Тохиролцол, хэлцэл хийх чадвар (Оптимал 2–10):	доош → HMM: Negotiating, "NEGOTIATING" case
  Бусдад нөлөөлөх чадвар (Оптимал 2–10):	доош → HMM: Persuading Others
  Сонсох чадвар (Оптимал 6–9):	доош → HMM: Feedback Essentials, Difficult Interactions
  Илтгэх чадвар (Оптимал 6–9):	доош → HMM: Presentation skill
  Бусдад хүлээн зөвшөөрөгдөх чадвар (Оптимал 6–10):	доош → HMM: Diversity, belonging and inclusion
  Стратегитай харилцах чадвар (Оптимал 6–10):	доош → HMM: Persuading Others, Global Collaboration

  МЕНЕЖМЕНТИЙН ЧАДАМЖ
  Үүрэг даалгаврыг оновчтой хуваарилах чадвар (Оптимал 6–10):	доош → HMM: Delegating
  Манлайлах чадвар (Оптимал 2–10):	доош → HMM: Leading People, Delegating
  Өөртөө итгэлтэй, шийдэмгий удирдах чадвар (Оптимал 6–10):	доош → HMM: Leading People, Decision Making
  Менторлох чадвар (Оптимал 6–10):	доош → HMM: Coaching, Developing Employees
  Гүйцэтгэлийг удирдах чадвар (Оптимал 2–9):	доош → HMM: Performance Measurement, Coaching
  Өөрчлөлтийг дэмжих чадвар (Оптимал 6–10):	доош → HMM: Change Management, Resilience

  СТРАТЕГИТАЙГААР АЖЛАА ТӨЛӨВЛӨЖ, ҮНЭЛЭХ ЧАДАМЖ
  Хямралыг удирдах чадвар (Оптимал 2–9):	доош → HMM: Crisis Management
  Далайцтай сэтгэх чадвар (Оптимал 2–10):	доош → HMM: Strategic Thinking
  Бүтээлч, шинэлэг сэтгэлгээтэй байх чадвар (Оптимал 2–10):	доош → HMM: Innovation, Strategic Thinking
  Олон үүрэг даалгаврыг зэрэг гүйцэтгэх чадвар (Оптимал 2–9):	доош → HMM: Time Management
  Зохион байгуулах чадвар (Оптимал 1–10):	доош → HMM: Process Improvement, Performance Measurement
  Төслийг удирдах чадвар (Оптимал 6–10):	доош → HMM: Project Management
  Эрсдэлийг удирдах чадвар (Оптимал 2–10):	доош → HMM: Crisis Management, Decision Making
  Стратеги төлөвлөгөө боловсруулах чадвар (Оптимал 2–10):	доош → HMM: Strategic Thinking, Strategy Planning, Innovation
  Цагийн менежмент (Оптимал 6–9):	доош → HMM: Time Management, Project Management, Managing Up
  Уран сайхны мэдрэмж (Оптимал ):	доош → HMM: Innovation

  ХАРИЛЦАА ХОЛБОО ТОГТООЖ, УДИРДАХ ЧАДАМЖ
  Маргааныг шийдвэрлэх чадвар (Оптимал 2–9):	доош → HMM: Difficult Interactions, Negotiating
  Бусдыг ойлгох чадвар (Оптимал 6–9):	доош → HMM: Diversity, belonging and inclusion, Feedback Essentials
  Харилцаа тогтоох чадвар (Оптимал 6–10):	доош → HMM: Communication, Global Collaboration
  Багийн уур амьсгалыг бүрдүүлэх чадвар (Оптимал 6–10):	доош → HMM: Team Management
  Бусдад туслах (Оптимал 7–10):	доош → HMM: Team Management, Coaching
  Багийг идэвхижүүлэх чадвар (Оптимал 6–10):	доош → HMM: Team Management, Leading People

  ӨӨРИЙГӨӨ ТАНЬЖ МЭДЭХ, УДИРДАХ ЧАДАМЖ
  Дүрэм журам зааварчилгааг баримтлах чадвар (Оптимал 1–10):	доош → HMM: Ethic at work
  Өөрчлөлтөд хурдан зохицох чадвар (Оптимал 6–10):	доош → HMM: Change Management, Resilience
  Өөрийгөө бодитоор үнэлэх чадвар (Оптимал 6–10):	доош → HMM: Career management, Feedback Essentials
  Стрессээ удирдах чадвар (Оптимал 6–10):	доош → HMM: Stress management

  БАЙГУУЛЛАГЫН ҮНЭТ ЗҮЙЛ, СОЁЛ, ЭЕРЭГ УУР АМЬСГАЛЫГ БҮРДҮҮЛЭХ ЧАДАМЖ
  Мэдээллийн нууцыг хадгалах чадвар (Оптимал 1–10):	доош → HMM: Ethic at work
  Зорилтод шалгуурын дагуу шударга шийдвэр гаргах чадвар (Оптимал 6–9):	доош → HMM: Ethic at work, Decision Making
  Даруу төлөв байх чадвар (Оптимал 6–10):	доош → HMM: Ethic at work
  Бусдын соёл, ялгаатай байдлыг ойлгох чадвар (Оптимал 6–10):	доош → HMM: Diversity, belonging and inclusion
  Бусдыг хүндэтгэх чадвар (Оптимал 6–9):	доош → HMM: Diversity, belonging and inclusion
  Үүрэг хариуцлагаа ухамсарлах чадвар (Оптимал 6–10):	доош → HMM: Ethic at work

  АЖИЛДАА ХАНДАХ ХАНДЛАГА, ОРОЛЦООГ ТОДОРХОЙЛОХ ЧАДАМЖ
  Туслахад хэзээд бэлэн байх чадвар (Оптимал 6–10):	доош → HMM: Managing Your Boss, Team Management
  Санаачилгатай байх чадвар (Оптимал 6–10):	доош → HMM: Innovation
  Идэвхи, оролцоотой байх чадвар (Оптимал 6–10):	доош → HMM: Team Management
  Чанарыг эрхэмлэдэг (Оптимал 6–10):	доош → HMM: Process Improvement
  Хичээл зүтгэл гаргах чадвар (Оптимал 7–10):	доош → HMM: Goal Setting
  Хариуцлага хүлээх чадвар (Оптимал 6–10):	доош → HMM: Ethic at work, Performance Measurement

1. CTPI Менежерийн тест → ОПТИМАЛ МУЖ (10):

2. Big5 — Хувь хүний зан төлвийн тест (5 хэмжээс, оноо 1-10)
   Нээлттэй байдал (Openness-Imagination): оптимал 10
   Нягт нямбай байдал (Meticulousness): оптимал 10
   Нийтэч эрч хүчтэй байдал (Sociability-Dynamism): оптимал 10 ← "нийтэч" гэж бич!
   Бусдад анхаарал хандуулах байдал (Consciousness of Others): оптимал 10
   Big5 оноо нь CTPI ур чадварыг хэр хурдан хөгжүүлж чадахыг таамаглана.

3. PP Test — Ажилтны хандлага, ур чадварын тест (16 шинж, оноо 1-10)
   PP нь ажилтны хандлага ур чадварыг тодорхойлох тест юм.
   Баримтад тулгуурладаг (Focus on Facts): оптимал 10
   Удирдан чиглүүлэх дуртай (Desire to Lead): оптимал 10
   Сэтгэл хөдлөлөө хянадаг (Emotional Distance): оптимал 10
   Амжилтанд хүрэх эрмэлзэлтэй (Ambition): оптимал 10
   Шинийг эрэлхийлэгч (Novelty Seeking): оптимал 10
   Нээлттэй харилцдаг (Extraversion): оптимал 10
   Уян хатан байх чадвар (Flexibility): оптимал 10
   Ажлыг нэн тэргүүнд тавьдаг (Involvement at Work): оптимал 10
   Дүрэм журмыг дагадаг (Rule-Following): оптимал 10
   Ятган нөлөөлдөг (Persuasiveness): оптимал 10
   Шуурхай гүйцэтгэх дуртай (Need for Action): оптимал 10
   Аливааг бэлтгэлгүй хийж чаддаг (Improvisation): оптимал 10
   Бие дааж ганцаараа ажиллах дуртай (Autonomy): оптимал 10
   Бусдыг нэн тэргүүнд тавьдаг (Altruism): оптимал 10

4. VOC — Ажил мэргэжил, карьерийн чиг баримжаа тодорхойлох тест
   Аливааг таньж мэдэх болон суралцах сонирхол (Intellectual Curiosity): оптимал 10
   Шинжлэх ухаан болон технологи (Science & Technology)
   Манлайлал (Leadership): оптимал 10
   Бусдад туслах дэмжих (Dedication to Others): оптимал 10
   Ажил хэрэгч (Enterprising): оптимал 10
   Системтэй зохион байгуулалттай (Methodical): оптимал 10
   Тоо баримт мэдээлэл дээр ажиллах сонирхол (Interest in Data & Numbers): оптимал 10

5. EQ — Сэтгэл хөдлөлийн оюун ухаан
   Өөрийн болон бусдын сэтгэл хөдлөлийг ойлгох, удирдах чадвар.
   Өндөр EQ = өндөр харилцааны чадвар.
   Өөрийгөө таних (Self knowledge): оптимал 9-10
   Өөрийгөө үнэлэх (Self regard): оптимал 8-10
   Өөртөө итгэлтэй байх (Self  confidence): оптимал 7-10
   Өөдрөг үзэлтэй (Optimism): оптимал 7-10
   Тэсвэр хатуужилтай (Resilience): оптимал 9-10
   Өөртөө урам зориг өгөх (Self-Motivation): оптимал 7-10
   Өөрийгөө хянах (Self-control): оптимал 6-8
   Ялгаатай байдалд зохицох (Dealing with diversity): оптимал 8-10
   Өөрийн үзэл бодолд тууштай (Assertiveness): оптимал 9-10
   Сэтгэл хөдлөлөө илэрхийлэх чадвартай (Expressing emotions): оптимал 7-10
   Бусдыг ойлгох чадвартай (Empathy): оптимал 7-10
   Эвлэрүүлэн зуучлах чадвартай (Mediation): оптимал 9-10
   Бусдад урам зориг өгөх чадвартай (Motivating-others): оптимал 9-10
   Ухаалаг эв дүйтэй (Tactfulness): оптимал 8-10
   Уян хатан (Flexibility): оптимал 9-10

6. MOTIVATION+ — Ажлын сэдлийн тест
   Ажилтны ажлын байран дахь сэдэлжүүлэгч хүчин зүйл ба тэдгээрийн сэтгэл ханамжийн түвшинг тодорхойлох тест.
   Магтаал сайшаал хүртэх : оптимал 10
   Өөрийн хязгаарыг сорих : оптимал 10
   Суралцах хүсэл эрмэлзэл : оптимал 10
   Карьер хөгжлүүлэх боломж : оптимал 10
   Өрсөлдөөн : оптимал 10
   Идэвхтэй хөдөлгөөн : оптимал 10
   Бие даан чөлөөтэй ажиллах орчин : оптимал 10
   Баталгаат байдал: оптимал 10
   Эрүүл тэнцвэртэй байдал : оптимал 10
   Нийгмийн орчин : оптимал 10
   Олон нийтэд үйлчлэх : оптимал 10
   Бусдыг хөгжүүлэх : оптимал 10
   Нөлөөлөх : оптимал 10
   Санаагаа хуваалцах : оптимал 10

7. Sales Competency — Борлуулалтын чадамжийн тест
   Борлуулалтын 10 ур чадварыг үнэлнэ.
   Үйлчлүүлэгч харилцагчийг өөртөө татах чадвар : оптимал 10
   Тэмцэх даван туулах чадвар : оптимал 10
   Эрэл хайгуул хийх чадвар : оптимал 10
   Харилцаа холбоо тогтоох чадвар : оптимал 10
   Хэрэглэгчийг сэтгэл ханамжтай байлгах чадвар : оптимал 10
   Стратеги борлуулалт хийх чадвар : оптимал 10
   Үр дүнг төсөөлүүлэн тайлбарлах чадвар : оптимал 10
   Хэрэглэгчийн хэрэгцээг ойлгох чадвар : оптимал 10
   Хэлцэл тохиролцоог амжилттай дуусгах чадвар : оптимал 10
   Бусдыг татах чадвар : оптимал 10
   Өөрийгөө хянах чадвар : оптимал 10
   Борлуулалтын овсгоо самбаа : оптимал 10


═══════════════════════════════════════════════════
ХАРИУЛТ БИЧИХ НАРИЙВЧИЛСАН ЗАГВАР
═══════════════════════════════════════════════════

ТООН ОНОО ЗААВАЛ ХАРУУЛАХ ЖИШЭЭ:
  "Болдын Манлайлах чадвар: 45/100 (оптимал: 65+) — оптималаас 20 оноогоор доогуур байна.
   Энэ нь Harvard ManageMentor хөтөлбөрийн Leading People, Delegating модулиудыг
   нэн тэргүүнд судлах шаардлагатайг харуулж байна."

БҮЛГИЙН ШИНЖИЛГЭЭНИЙ ЗАГВАР:
  1. Дундаж оноо + оптималтай харьцуулалт
  2. Хамгийн өндөр оноотой 1-3 ажилтан (давуу тал)
  3. Хамгийн бага оноотой 1-3 ажилтан (хөгжүүлэх хэрэгтэй)
  4. Хамгийн сул болон хамгийн хүчтэй ур чадварын чиглэл

ОЛОН ТЕСТИЙН НЭГТГЭЛ:
  PP өндөр + CTPI бага = хандлага сайн, ур чадвар хөгжөөгүй
  PP бага + CTPI өндөр = ур чадвар сайн, сонирхол/хандлага дутуу
  VOC + CTPI нийцвэл = тогтвортой, бүтээмжтэй ажилтан
  Тестүүд зөрчилдөвөл = нэмэлт ярилцлага шаардлагатай

СУРГАЛТЫН ТӨЛӨВЛӨГӨӨ ЗАГВАР:
  1-р АЛХАМ: Ажилтан бүрийн оноог оптималтай харьцуулж тодорхойл
  2-р АЛХАМ: Тохирох HMM модулиудыг нэрлэ
  3-р АЛХАМ: 1-р сар (яаралтай) → 2-3-р сар (дунд) → 4-6-р сар (урт хугацаа)
  4-р АЛХАМ: Хүлээгдэж буй үр дүн

НЭР ТОМЬЁОНЫ ЗӨВ ХЭРЭГЛЭЭ:
  туршилт → тест | психометрийн → сэтгэл зүйн | үр бүтээл → бүтээмж
  зохицол өндөртэй → уялдаа сайтай | удирдамжийн → удирдлагын
  эергээр → эерэгээр | нэр дэвшигч → ажил горилогч
  нийтэч (зөв) ← нийрч/ниймч (буруу)

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
        "- Оптимал мужид байгаа оноог сул тал гэж хэлж болохгүй.\n"
        "- ТООН ОНОО ЗААВАЛ ХАРУУЛАХ: ажилтан бүрийн оноог тодорхой дурдана. Жишээ: 'Манлайлах чадвар: 45/100 (оптимал: 65+)'. Оноо оптимал мужаас хэр зайтайг тайлбарла.\n"
        "- Бүлгийн шинжилгээнд: дундаж оноо, хамгийн өндөр/бага оноотой ажилтан, хамгийн сул болон хамгийн хүчтэй чиглэлийг тодорхойл.\n\n"
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
