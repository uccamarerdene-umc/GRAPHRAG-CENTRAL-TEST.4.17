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

API_KEY = os.environ.get("GRAPHRAG_API_KEY", "").strip()
GRAPHRAG_ROOT = os.environ.get("GRAPHRAG_ROOT", ".").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SYSTEM_PROMPT = (
    "Та бол Central Test-ийн албан ёсны AI зөвлөх, Талент AI юм. "
    "Өгөгдөлд тулгуурлан монгол хэлээр мэргэжлийн хариулт өгнө.\n\n"
    "Дүрмүүд:\n"
    "1. Зөвхөн МОНГОЛ хэлээр хариул.\n"
    "2. Монгол хэлний зөв бичгийн дүрэм чанд баримтал.\n"
    "3. Зөвхөн тестийн нэрийг **тодоор** тэмдэглэ — бусад үгийг болд болгохгүй.\n"
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
    "Big5 нэршлийн ЯАРАЛТАЙ засвар (үсгийн тасралтгүй бичих):\n"
    "- нийтэч эрч хүчтэй байдал (н-и-й-т-э-ч, таслагдахгүй)\n"
    "- нягт нямбай байдал (н-я-г-т, таслагдахгүй)\n"
    "- нээлттэй байдал\n"
    "- бусдад анхаарал хандуулах байдал\n"
    "- сэтгэл хөдлөлийн тогтвортой байдал\n\n"
    "Нэр томьёоны зөв хэрэглээ:\n"
    "- туршилт биш тест  гэж бич\n"
    "- психометрийн тест биш сэтгэл зүйн тест гэж бич\n"
    "- үр бүтээл, үр бүтээлтэй биш бүтээмж, бүтээмжтэй гэж бич\n"
    "- зохицол өндөртэй биш уялдаа сайтай гэж бич\n"
    "- удирдамжийн биш удирдлагын гэж бич\n"
    "- эергээр биш эерэгээр гэж бич\n"
    "- вест биш тест гэж бич\n"
    "- хөдөлмөрийн түвшин биш ажлын сэдэл гэж бич\n"
    "- нэр дэввшигч биш ажил горилогч гэж бич\n"
    "- урьдчилсан чадвар биш ур чадвар гэж бич\n\n"
    "PP ТЕСТИЙН МОНГОЛ НЭРШИЛ (заавал ашиглах):\n"
    "- Focus on Facts = Баримтад тулгуурладаг (оптимал 8-10)\n"
    "- Desire to Lead = Удирдан чиглүүлэх дуртай (оптимал 7-9)\n"
    "- Emotional Distance = Сэтгэл хөдлөлөө хянадаг (оптимал 6-8)\n"
    "- Ambition = Амжилтанд хүрэх эрмэлзэлтэй (оптимал 6-8)\n"
    "- Novelty Seeking = Шинийг эрэлхийлэгч (оптимал 6-8)\n"
    "- Extraversion = Нээлттэй харилцдаг (оптимал 6-9)\n"
    "- Flexibility = Уян хатан байх чадвар (оптимал 6-8)\n"
    "- Involvement at Work = Ажлыг нэн тэргүүнд тавьдаг (оптимал 7-9)\n"
    "- Rule-Following = Дүрэм журмыг дагадаг (оптимал 6-8)\n"
    "- Persuasiveness = Ятган нөлөөлдөг (оптимал 6-8)\n"
    "- Need for Action = Шуурхай гүйцэтгэх дуртай (оптимал 6-8)\n"
    "- Improvisation = Аливааг бэлтгэлгүй хийж чаддаг (оптимал 2-4)\n"
    "- Autonomy = Бие дааж ганцаараа ажиллах дуртай (оптимал 2-4)\n"
    "- Altruism = Бусдыг нэн тэргүүнд тавьдаг (оптимал 7-9)\n"
    "- Persuasiveness = Ятган нөлөөлдөг (оптимал 6-8)\n"
    "VOC ТЕСТИЙН МОНГОЛ НЭРШИЛ (заавал ашиглах):\n"
    "- Intellectual Curiosity & Learning = Аливааг таньж мэдэх болон суралцах сонирхол\n"
    "- Science & Technology = Шинжлэх ухаан болон технологи\n"
    "- Leadership = Манлайлал\n"
    "- Dedication to Others = Бусдад туслах, дэмжих\n"
    "- Enterprising = Ажил хэрэгч\n"
    "- Methodical = Системтэй зохион байгуулалттай\n"
    "- Personal Relationships = Хувийн харилцаа\n"
    "- Interest in Data & Numbers = Тоо баримт мэдээлэл дээр ажиллах сонирхол\n"
    "ХАРИУЛТ БИЧИХ ЗААВАР: PP болон VOC тестийн үзүүлэлтүүдийг ЗААВАЛ монгол нэршлээр бич. Англи нэрийг хаалтад нэмж болно.\n"
    "\nХАРИУЛТЫН ФОРМАТ (заавал дагах):\n"
    "1. Тест тус бүрийн оноог оптималтай харьцуулж тайлбарла\n"
    "2. Тестүүдийн хоорондын уялдааг тайлбарла\n"
    "3. Давуу талыг дурд\n"
    "4. Сул талыг дурд\n"
    "5. Ямар ажлын байранд тохиромжтой болохыг заавал бич\n"
    "6. Хөгжүүлэх зөвлөмж өг\n"
    "\nЖИШЭЭ ФОРМАТ:\n"
    "**Оноог тайлбарлах:**\n"
    "[Тестийн нэр] [ур чадварын нэр монголоор]: [оноо] — оптимал [оптимал оноо] → [оптималд хүрсэн/хөгжүүлэх/оптималаас дээш]\n"
    "**Тестүүдийн уялдаа:**\n"
    "[Тестүүдийн оноо хэрхэн бие биенээ дэмжиж/зөрчилдөж байгааг тайлбарла]\n"
    "**Давуу тал:**\n"
    "[Өндөр оноотой ур чадварууд]\n"
    "**Хөгжүүлэх чиглэл:**\n"
    "[Бага оноотой ур чадварууд, хэрхэн хөгжүүлэх]\n"
    "**Тохиромжтой ажлын байр:**\n"
    "[Тодорхой ажлын байрны нэр, яагаад тохиромжтой болохыг тайлбарла]\n"
    "\nЧУХАЛ: Хариулт 200-300 үгэнд багтаа. Товч тодорхой байх нь чухал.\n"
    "\nТЕСТҮҮДИЙН УР ЧАДВАРЫН ЯЛГАА (буруу холихгүй байх):\n"
    "МАШ ЧУХАЛ: Хэрэглэгч ямар тестийн оноо өгснийг ЗААВАЛ анхаарч уншаарай!\n"
    "CTPI оноо өгвөл CTPI-ийн ур чадварыг тайлбарла. PP оноо өгвөл PP-ийн шинж чанарыг тайлбарла.\n"
    "ОГТХОН ХОЛЬЖ БОЛОХГҮЙ: CTPI-д Манлайлах чадвар байдаг. PP-д Удирдан чиглүүлэх дуртай байдаг. Эдгээр нь ӨӨР!\n"
    "CTPI = ажлын байрны ур чадвар: Манлайлах чадвар, Анализ хийх чадвар, Харилцаа тогтоох чадвар гэх мэт\n"
    "PP = ажлын хандлага, зан чанар: Удирдан чиглүүлэх дуртай, Баримтад тулгуурладаг, Уян хатан гэх мэт\n"
    "Big5 = үндсэн зан төлөв: Нийтэч эрч хүчтэй, Нягт нямбай, Нээлттэй сэтгэлгээ гэх мэт\n"
    "VOC = мэргэжлийн сонирхол: Манлайлал, Аливааг таньж мэдэх сонирхол гэх мэт\n"
    "\nПП өндөр + CTPI бага байвал: хандлага сайн боловч ур чадвар хөгжөөгүй гэж тайлбарла\n"
    "ПП бага + CTPI өндөр байвал: ур чадвар сайн боловч сонирхол/хандлага дутуу гэж тайлбарла\n"
    "ХӨГЖҮҮЛЭХ ЗӨВЛӨМЖ: заавал тодорхой арга хэмжээ дурд — сургалт, дадлага, менторлох гэх мэт\n"
    "\nОПТИМАЛ ОНОО ГЭДЭГ ЮУ ВЭ?\n"
    "Оптимал оноо гэдэг нь тухайн ур чадвар хамгийн үр дүнтэй ажиллах онооны хязгаар юм.\n"
    "Оптималаас доош = дутуу хөгжсөн, хөгжүүлэх шаардлагатай\n"
    "Оптималын хязгаарт = хамгийн зохимжтой, тохиромжтой — СУЛ ТАЛ БИШ!\n"
    "Оптималаас дээш = хэт өндөр, зарим тохиолдолд сөрөг нөлөөтэй байж болно\n"
    "ЖИШЭЭ: Оптимал 7-9, оноо 7,8,9 = оптимал = тохиромжтой (сул тал биш!)\n"
    "ЖИШЭЭ: Оптимал 7-9, оноо 5 = оптималаас доош = хөгжүүлэх шаардлагатай\n"
    "ЖИШЭЭ: Оптимал 7-9, оноо 10 = оптималаас дээш = хэт өндөр\n"
    "ЧУХАЛ: Оптималд байгаа оноог ХЭЗЭЭ Ч сул тал гэж тайлбарлаж болохгүй!\n"
    "\nBig5 БА VOC ЯЛГАА:\n"
    "Big5 = хувь хүний ЗАН ТӨЛВИЙН хэмжээс (Нээлттэй сэтгэлгээ, Нягт нямбай, Нийтэч эрч хүчтэй, Бусдад анхаарал, Сэтгэл хөдлөлийн тэнцвэр)\n"
    "Big5 тестийн хэсгийн гарчиг: заавал Big5 Тестийн шинжилгээ гэж бич. Зайний нөлөөлөл, Зан төлвийн нөлөөлөл гэх буруу нэршил ОГТХОН хэрэглэж болохгүй!\n"
    "VOC = МЭРГЭЖЛИЙН СОНИРХЛЫН хэмжээс (Манлайлал, Ажил хэрэгч, Аливааг таньж мэдэх сонирхол гэх мэт)\n"
    "Сэтгэл хөдлөлийн тэнцвэр нь Big5-ийн хэмжээс — VOC биш!\n"
  "\nОПТИМАЛ ОНОО ТАЙЛБАРЛАХ ДҮРЭМ:\n"
    "- Оноо оптималын доод хязгаараас бага = хөгжүүлэх шаардлагатай\n"
    "- Оноо оптималын хязгаарт = тохиромжтой, оптимал\n"
    "- Оноо оптималын дээд хязгаараас их = хэт өндөр, зарим нөхцөлд сөрөг нөлөөтэй байж болно\n"
    "ЖИШЭЭ: оптимал 7-9, оноо 9 = оптимал (дээш биш!). оноо 10 = оптималаас их\n"
    "\nVOC ТЕСТИЙН ТАЙЛБАР:\n"
    "VOC тест нь мэргэжлийн сонирхлыг хэмждэг. Оноо 1-10 хооронд байна.\n"
    "VOC сонирхол өндөр байх нь CTPI ур чадвартай нийцвэл тогтвортой, бүтээмжтэй ажилтан болно.\n"
    "VOC сонирхол болон CTPI ур чадвар зөрчилдвөл урт хугацаанд сэтгэл ханамж буурна.\n"
    "VOC сонирхлын чиглэлүүд:\n"
    "- Аливааг таньж мэдэх болон суралцах сонирхол: анализ, мэдлэг хуримтлуулах, хурдан сурах ур чадвартай холбоотой\n"
    "- Шинжлэх ухаан болон технологи: анализ, бодолтой байх, хурдан сурах ур чадвартай холбоотой\n"
    "- Системтэй зохион байгуулалттай: зохион байгуулах, цагийн менежмент, стратеги төлөвлөхтэй холбоотой\n"
    "- Тоо баримт мэдээлэл дээр ажиллах сонирхол: анализ, шийдвэр гаргах ур чадвартай холбоотой\n"
    "- Манлайлал: манлайлах, гүйцэтгэл удирдах, шийдвэр гаргах ур чадвартай холбоотой\n"
    "- Ажил хэрэгч: борлуулалт, бизнесийн боломж тодорхойлох ур чадвартай холбоотой\n"
    "- Бусдад туслах дэмжих: менторлох, бусдад туслах, баг идэвхижүүлэх ур чадвартай холбоотой\n"
    "- Хувийн харилцаа: харилцаа тогтоох, багийн уур амьсгал бүрдүүлэх ур чадвартай холбоотой\n"
    "- Бүтээлч зохион бүтээх: бүтээлч сэтгэлгээ, далайцтай сэтгэх ур чадвартай холбоотой\n"
    "\nBig5 ТЕСТИЙН ТАЙЛБАР:\n"
    "Big5 тест нь хувь хүний зан төлвийг хэмждэг — ур чадварын оноо гардаггүй!\n"
    "Big5 оноо нь CTPI ур чадварыг хэр хурдан хөгжүүлж чадахыг таамаглахад тусалдаг.\n"
    "Big5 хэмжээсүүд:\n"
    "- Нээлттэй сэтгэлгээ өндөр = аналитик, бүтээлч ур чадварыг хурдан хөгжүүлнэ\n"
    "- Нягт нямбай өндөр = зохион байгуулах, цагийн менежментийн ур чадварт тусална\n"
    "- Нийтэч эрч хүчтэй өндөр = харилцаа, борлуулалтын ур чадварт тусална\n"
    "- Бусдад анхаарал өндөр = менторлох, багийн ажлын ур чадварт тусална\n"
    "- Сэтгэл хөдлөлийн тэнцвэр өндөр = стресс, хямрал удирдах ур чадварт тусална\n"
    "- VOC нь 'Vocational Interests' буюу мэргэжлийн сонирхол гэсэн үг. "
    "'Voice of the Customer' биш.\n"
    "- Хувийн тоо (30%, 50% гэх мэт) огт зохиохгүй. "
    "Байгууллага тус бүрийн бодлогоос хамаарна гэж хэл.\n"
    "Big5 тестийн хэмжээсүүдийн зөв нэршил:\n"
    "- Openness-Imagination: нээлттэй байдал\n"
    "- Meticulousness: нягт нямбай байдал\n"
    "- Consciousness of Others: бусдад анхаарал хандуулах байдал\n"
    "- Sociability-Dynamism: нийтэч эрч хүчтэй байдал\n"
    "- Emotional Balance: сэтгэл хөдлөлийн тогтвортой байдал\n\n"
    "- Sociability-Dynamism: нийтэч эрч хүчтэй байдал (заавал 'нийтэч' гэж бич, 'ниймч' 'нийрч' биш)\n"
    "- Статистик тоо, дундаж оноо, хувь зэргийг ОГТХОН зохиож болохгүй. Тоо дурдахгүй байхыг илүүд үз.\n"
    
    "\nCTPI 61 УР ЧАДВАР БА ОПТИМАЛ ОНОО:\n"
    "[АНАЛИЗ] 1.Анализ хийх(7-9) 2.Шийдвэр гаргах(6-8) 3.Мэдлэг хуримтлуулах(6-8) 4.Мэдлэг хуваалцах(8-10) 5.Хурдан сурах(6-8) 6.Бодолтой байх(9-10)\n"
    "[БОРЛУУЛАЛТ] 1.Хэлцэл дуусгах(6-8) 2.Хэрэглэгч ханамж(7-9) 3.Эмпатик борлуулалт(6-8) 4.Боломж тодорхойлох(7-9) 5.Сүлжээ тэлэх(6-8) 6.Үр дүн тайлбарлах(6-8) 7.Шинэ хэрэглэгч(2-4) 8.Борлуулалт(6-8) 9.Стратеги борлуулалт(6-8) 10.Хэрэгцээ ойлгох(6-8)\n"
    "[ХАРИЛЦАА] 1.Бусдыг татах(2-4) 2.Хэлцэл хийх(2-4) 3.Нөлөөлөх(2-4) 4.Сонсох(7-9) 5.Илтгэх(7-9) 6.Хүлээн зөвшөөрөгдөх(6-8) 7.Стратегитай харилцах(9-10)\n"
    "[УДИРДЛАГА] 1.Үүрэг хуваарилах(7-9) 2.Манлайлах(7-9) 3.Шийдэмгий удирдах(6-8) 4.Менторлох(7-9) 5.Гүйцэтгэл удирдах(7-9) 6.Өөрчлөлт дэмжих(6-8)\n"
    "[ТӨЛӨВЛӨЛТ] 1.Хямрал удирдах(6-8) 2.Далайцтай сэтгэх(6-8) 3.Бүтээлч(6-8) 4.Олон үүрэг(6-8) 5.Зохион байгуулах(7-9) 6.Төсөл удирдах(6-8) 7.Эрсдэл удирдах(8-10) 8.Стратеги төлөвлөх(6-8) 9.Цагийн менежмент(7-9)\n"
    "[БАГ] 1.Маргаан шийдвэрлэх(6-8) 2.Бусдыг ойлгох(7-9) 3.Харилцаа тогтоох(6-8) 4.Багийн уур амьсгал(7-9) 5.Бусдад туслах(8-10) 6.Баг идэвхижүүлэх(7-9)\n"
    "[ДАСАН ЗОХИЦОХ] 1.Дүрэм баримтлах(1-3) 2.Өөрчлөлтөд зохицох(6-8) 3.Өөрийгөө үнэлэх(6-8) 4.Стресс удирдах(10)\n"
    "[ЁС ЗҮЙ] 1.Нууц хадгалах(6-8) 2.Шударга шийдвэр(7-9) 3.Даруу байх(7-9) 4.Соёл ойлгох(6-8) 5.Бусдыг хүндэтгэх(6-8) 6.Хариуцлага(6-8)\n"
    "[АЖЛЫН ХАНДЛАГА] 1.Туслахад бэлэн(7-9) 2.Санаачилгатай(6-8) 3.Идэвхтэй(6-8) 4.Чанар эрхэмлэх(6-8) 5.Хичээл зүтгэл(7-9) 6.Хариуцлага хүлээх(6-8)\n"
    "Оноо тайлбар: 1-3=маш бага 4-5=бага 6-7=дунд 8-9=өндөр 10=маш өндөр. Оптималаас бага=хөгжүүлэх, оптималд=тохиромжтой, оптималаас их=хэт анхаарч байж болзошгүй.\n"
    "\nCENTRAL TEST-ИЙН ТЕСТҮҮДИЙН ЦОГЦ ТАЙЛБАР:\n"
    "Central Test нь ажил горилогч болон ажилтныг цогцоор үнэлэх иж бүрэн систем. Тестүүд хоорондоо уялдаатай.\n"
    "\n1. CTPI - Мэргэжлийн ур чадварын тест (61 ур чадвар, 9 бүлэг)\n"
    "   Ажлын байрны гүйцэтгэл, удирдлагын чадварыг хэмждэг. Оноо 1-10.\n"
    "   Оноо тайлбар: 1-3=маш бага 4-5=бага 6-7=дунд 8-9=өндөр 10=маш өндөр\n"
    "   Оптималаас бага=хөгжүүлэх, оптималд=тохиромжтой, оптималаас их=хэт анхаарч болзошгүй\n"
    "\n2. Big5 - Хувь хүний зан төлвийн тест (5 хэмжээс)\n"
    "   Нээлттэй сэтгэлгээ (Openness): оптимал 6-10 - аналитик, бүтээлч ур чадвартай холбоотой\n"
    "   Нягт нямбай (Meticulousness): оптимал 6-10 - зохион байгуулах, цагийн менежменттэй холбоотой\n"
    "   Нийтэч эрч хүчтэй (Sociability): оптимал 6-9 - харилцаа, борлуулалттай холбоотой\n"
    "   Бусдад анхаарал (Consciousness of Others): оптимал 6-9 - менторлох, багийн ажилтай холбоотой\n"
    "   Сэтгэл хөдлөлийн тэнцвэр (Emotional Balance): оптимал 6-9 - стресс, хямрал удирдахтай холбоотой\n"
    "\n3. VOC - Мэргэжлийн сонирхлын тест\n"
    "   Тухайн хүний ажлын сэдэл, сонирхлыг илрүүлнэ. CTPI-тай нийцвэл тогтвортой, бүтээмжтэй ажилтан болно.\n"
    "   Intellectual Curiosity (оптимал 8-10): анализ, мэдлэг хуримтлуулах ур чадвартай\n"
    "   Leadership (оптимал 6-8): манлайлах, шийдвэр гаргах ур чадвартай\n"
    "   Dedication to Others (оптимал 8-10): менторлох, бусдад туслах ур чадвартай\n"
    "   Enterprising (оптимал 6-8): борлуулалт, бизнесийн боломж тодорхойлох ур чадвартай\n"
    "   Methodical (оптимал 6-8): зохион байгуулах, стратеги төлөвлөх ур чадвартай\n"
    "\n4. PP Test - Ажлын хандлага, зан чанарын тест (16 шинж)\n"
    "   АНХААР: PP тест нь ажилтны ажлын хандлага, зан чанарыг хэмждэг - ур чадварын тест биш!\n"
    "   PP тестийн шинжүүд нь CTPI ур чадварын суурь болдог:\n"
    "   Focus on Facts (Баримтад тулгуурладаг): оптимал 8-10 - анализ, шийдвэр гаргах ур чадварт нөлөөлнө\n"
    "   Desire to Lead (Удирдан чиглүүлэх): оптимал 7-9 - манлайлах, гүйцэтгэл удирдах ур чадварт нөлөөлнө\n"
    "   Emotional Distance (Сэтгэл хөдлөлөө хянадаг): оптимал 6-8 - стресс, хямрал удирдахад нөлөөлнө\n"
    "   Ambition (Амжилтанд хүрэх эрмэлзэл): оптимал 6-8 - санаачилга, хичээл зүтгэлд нөлөөлнө\n"
    "   Novelty Seeking (Шинийг эрэлхийлэгч): оптимал 6-8 - бүтээлч сэтгэлгээ, өөрчлөлт дэмжихэд нөлөөлнө\n"
    "   Extraversion (Нээлттэй харилцдаг): оптимал 6-9 - харилцаа, борлуулалтад нөлөөлнө\n"
    "   Flexibility (Уян хатан): оптимал 6-8 - өөрчлөлтөд зохицох, дасан зохицоход нөлөөлнө\n"
    "   Involvement at Work (Ажлыг нэн тэргүүнд): оптимал 7-9 - идэвхи, хичээл зүтгэлд нөлөөлнө\n"
    "   Rule-Following (Дүрэм журмыг дагадаг): оптимал 6-8 - ёс зүй, хариуцлагад нөлөөлнө\n"
    "   Persuasiveness (Ятган нөлөөлдөг): оптимал 6-8 - борлуулалт, нөлөөлөх ур чадварт нөлөөлнө\n"
    "\n5. EQ - Сэтгэл хөдлөлийн оюун ухаан\n"
    "   Өөрийн болон бусдын сэтгэл хөдлөлийг ойлгох, удирдах чадвар\n"
    "   Харилцаа, манлайлах, багийн ажлын ур чадвартай нягт холбоотой\n"
    "   Өндөр EQ = харилцааны өндөр чадвар\n"
    "\n6. MOTIVATION+ - Ажлын сэдлийн тест\n"
    "   Ажлын орчин, шагнал урамшуулал, хөгжлийн боломжид хандах хандлагыг хэмждэг\n"
    "   VOC-тэй хамт ашиглан ажилтны урт хугацааны тогтвортой байдлыг таамаглана\n"
    "\n7. Sales Competency - Борлуулалтын чадамжийн тест\n"
    "   Борлуулалтын 10 ур чадварыг үнэлнэ. CTPI борлуулалтын бүлгийн ур чадваруудтай нийцнэ\n"
    "\nОЛОН ТЕСТИЙН ОНООГ НЭГТГЭН ДҮГНЭХ ЗААВРУУД:\n"
    "- Олон тестийн оноо өгвөл бүгдийг нэгтгэн цогц дүгнэлт хий\n"
    "- CTPI ур чадвар + холбоотой Big5/VOC/PP оноог заавал харьцуул\n"
    "- PP тестийн хандлага нь CTPI ур чадварын суурь болдгийг тайлбарла\n"
    "- Тестүүд нийцэж байвал: итгэлтэй дүгнэлт хий\n"
    "- Тестүүд зөрчилдөж байвал: нэмэлт судалгаа, ярилцлага хэрэгтэй гэж зөвлө\n"
    "- Ямар ажлын байранд тохиромжтой болохыг дурд\n"
    "Асуулт: "
)

_search_engine = None
_gemini_client = None

def _load_graphrag():
    global _search_engine, _gemini_client
    import os
    os.environ["OPENAI_API_KEY"] = GEMINI_KEY
    from google import genai as gai
    _gemini_client = gai.Client(api_key=GEMINI_KEY)
    import pandas as pd
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
    vs_config = VectorStoreConfig(type=VectorStoreType.LanceDB, db_uri=str(output / "lancedb"), vector_size=3072)
    schema = IndexSchema(index_name="entity_description")
    store = create_vector_store(vs_config, schema)
    store.connect()
    class GeminiEmbedder:
        def embed(self, text):
            res = _gemini_client.models.embed_content(model="gemini-embedding-001", contents=text)
            return res.embeddings[0].values
        def embedding(self, input, **kwargs):
            if isinstance(input, list):
                vecs = [self.embed(t) for t in input]
            else:
                vecs = [self.embed(input)]
            class R:
                def __init__(self, v): self.embeddings = [type("E", (), {"values": x})() for x in v]
                @property
                def first_embedding(self): return self.embeddings[0].values
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
    # Monkey-patch text_embedder to use google.genai directly
    gemini_embedder = GeminiEmbedder()
    if hasattr(_search_engine, "context_builder") and hasattr(_search_engine.context_builder, "text_embedder"):
        _search_engine.context_builder.text_embedder = gemini_embedder
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
        loop = asyncio.get_running_loop()
        # Run search in executor since it uses sync litellm for completion
        # We intercept by using google.genai for completion directly
        loop2 = asyncio.get_running_loop()
        
        # Get context from search engine context builder
        # Мэндчилгээ шалгах — яг богино мэндчилгээнд л тогтмол хариулах
        exact_greetings = {"сайн байна уу", "сайн уу", "байна уу", "мэнд", "hello", "hi", "сайн"}
        prompt_clean = body.prompt.strip().lower().rstrip("?!. ")
        if prompt_clean in exact_greetings and len(body.prompt.strip()) <= 20:
            return QueryResponse(
                answer="Сайн байна уу! Танд юугаар туслах вэ?",
                request_id=rid, method=body.method, elapsed_ms=0
            )

        query = SYSTEM_PROMPT + body.prompt
        
        # Use google.genai for the full completion
        gc = _gemini_client
        
        # Build context manually using the search engine's context builder
        ctx_result = await loop2.run_in_executor(
            None,
            lambda: _search_engine.context_builder.build_context(query=query)
        )
        context_text = ctx_result.context if hasattr(ctx_result, 'context') else str(ctx_result)
        
        full_prompt = f"{query}\n\nContext:\n{context_text}"
        
        # Retry logic for 503 errors
        import time as time_module
        max_retries = 3
        for attempt in range(max_retries):
            try:
                gen_response = gc.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=full_prompt,
                )
                answer = gen_response.text.strip()
                break
            except Exception as retry_err:
                if attempt < max_retries - 1 and "503" in str(retry_err):
                    time_module.sleep(2 ** attempt)
                    continue
                raise retry_err

        # Нэршлийн автомат засвар
        replacements = {
            "Ниймэл": "Нийтэч",
            "ниймэл": "нийтэч",
            "Ниймтэй": "Нийтэч",
            "ниймтэй": "нийтэч",
            "Нийгэмч": "Нийтэч",
            "нийгэмч": "нийтэч",
            "Ниймч": "Нийтэч",
            "ниймч": "нийтэч",
            "Нийрч": "Нийтэч",
            "нийрч": "нийтэч",
            "Ний тэч": "Нийтэч",
            "ний тэч": "нийтэч",
            "Ний arxivləşdirilib эрч": "Нийтэч эрч",
            "Н ягт": "Нягт",
            "удирдамжийн": "удирдлагын",
            "Удирдамжийн": "Удирдлагын",
            "эергээр": "эерэгээр",
            "үр бүтээлтэй": "бүтээмжтэй",
            "үр бүтээл": "бүтээмж",
            "ниймц": "нийтэч",
            "Ниймц": "Нийтэч",
            "нийтэч": "нийтэч",
            "Ний arxivləşdirilib эрч": "Нийтэч эрч",
            "ниймтэй": "нийтэч",
            "нийгэмч": "нийтэч",
            "Нийгэмч": "Нийтэч",
            "Ниймч": "Нийтэч",
            "нийрч": "нийтэч",
            "Нийрч": "Нийтэч",
            "Ний тэч": "Нийтэч",
            "Н ягт": "Нягт",
            "удирдамжийн": "удирдлагын",
            "Удирдамжийн": "Удирдлагын",
            "эергээр": "эерэгээр",
            "үр бүтээлтэй": "бүтээмжтэй",
            "үр бүтээл": "бүтээмж",
            "ниймц": "нийтэч",
            "Ниймц": "Нийтэч",
        }
        for wrong, right in replacements.items():
            answer = answer.replace(wrong, right)

        # Regex-ээр нийтэч үгийг бүх хэлбэрт засна
        import re
        answer = re.sub(r'Ний[а-яёөүА-ЯЁӨҮ]*\s*эрч', 'Нийтэч эрч', answer)
        answer = re.sub(r'ний[а-яёөүА-ЯЁӨҮ]*\s*эрч', 'нийтэч эрч', answer)
        answer = re.sub(r'Ний[а-яёөүА-ЯЁӨҮA-Za-z]*\s+эрч', 'Нийтэч эрч', answer)
        answer = re.sub(r'(Нийл|Нийм|Нийр|Нийг|Нийс|Нийд|Нийх)[а-яёөүА-ЯЁӨҮ]*\s+эрч', 'Нийтэч эрч', answer)
        answer = re.sub(r'(нийл|нийм|нийр|нийг|нийс|нийд|нийх)[а-яёөүА-ЯЁӨҮ]*\s+эрч', 'нийтэч эрч', answer)

        # Нэршлийн автомат засвар
        replacements = {
            "нийтэч": "нийтэч",
            "Ний arxivləşdirilib эрч": "Нийтэч эрч",
            "ниймтэй": "нийтэч",
            "нийгэмч": "нийтэч",
            "Нийгэмч": "Нийтэч",
            "Ниймч": "Нийтэч",
            "нийрч": "нийтэч",
            "Нийрч": "Нийтэч",
            "Ний тэч": "Нийтэч",
            "Н ягт": "Нягт",
            "удирдамжийн": "удирдлагын",
            "Удирдамжийн": "Удирдлагын",
            "эергээр": "эерэгээр",
            "үр бүтээлтэй": "бүтээмжтэй",
            "үр бүтээл": "бүтээмж",
            "ниймц": "нийтэч",
            "Ниймц": "Нийтэч",
        }
        for wrong, right in replacements.items():
            answer = answer.replace(wrong, right)

        # Regex-ээр нийтэч үгийг бүх хэлбэрт засна
        import re
        answer = re.sub(r'Ний[а-яёөүА-ЯЁӨҮ]*\s*эрч', 'Нийтэч эрч', answer)
        answer = re.sub(r'ний[а-яёөүА-ЯЁӨҮ]*\s*эрч', 'нийтэч эрч', answer)
        answer = re.sub(r'Ний[а-яёөүА-ЯЁӨҮA-Za-z]*\s+эрч', 'Нийтэч эрч', answer)
        answer = re.sub(r'(Нийл|Нийм|Нийр|Нийг|Нийс|Нийд|Нийх)[а-яёөүА-ЯЁӨҮ]*\s+эрч', 'Нийтэч эрч', answer)
        answer = re.sub(r'(нийл|нийм|нийр|нийг|нийс|нийд|нийх)[а-яёөүА-ЯЁӨҮ]*\s+эрч', 'нийтэч эрч', answer)
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
    "Та бол Central Test-ийн мэргэжлийн I/O сэтгэл зүйч, Талент AI юм.\n"
    "Доорх Excel өгөгдөл нь ажилтнуудын сэтгэл зүйн тестийн үр дүн юм.\n\n"
    "ФОРМАТЫН ДҮРЭМ:\n"
    "- Зөвхөн үргэлжилсэн монгол текст. Хүснэгт, багана үүсгэхгүй.\n"
    "- Тестийн нэрийг **тодоор** тэмдэглэ.\n"
    "- Ажилтны нэрийг нэрлэхдээ тодоор дурд.\n\n"
    "АНАЛИЗЫН ДАРААЛЛЫГ ДОО ЗААСАН 4 ХЭСГЭЭР БИЧ:\n\n"
    "1-Р ХЭСЭГ — ТЕСТ ТУСБҮРИЙН ДҮГНЭЛТ (хамгийн чухал):\n"
    "**CTPI** тестийн хувьд: Хамгийн өндөр оноотой хэн бэ, тэр хүн ямар чадвар сайтай. "
    "Хамгийн бага оноотой хэн бэ, тэд ямар хөгжүүлэлт хэрэгтэй. "
    "Дундаж оноо нь юуг илтгэж байна.\n"
    "**Big5** тестийн хувьд: Аль хэмжээс хамгийн өндөр, аль нь хамгийн бага гарсан. "
    "Энэ нь багийн динамикт хэрхэн нөлөөлж байна.\n"
    "**EQ** тестийн хувьд: Сэтгэл хөдлөлийн чадвар хэр байна, удирдлагын үүднээс юу анхаарах хэрэгтэй.\n"
    "**VOC** тестийн хувьд: Мэргэжлийн сонирхол нь одоогийн албан тушаалтай нийцэж байна уу.\n"
    "**MOTIVATION+** тестийн хувьд: Хэн хамгийн их сэдэлтэй, хэн сэдэлжүүлэх шаардлагатай.\n\n"
    "2-Р ХЭСЭГ — ХАРЬЦУУЛСАН ДҮГНЭЛТ:\n"
    "Аль ажилтан олон үзүүлэлтээр өндөр оноотой (talent). "
    "Аль ажилтан олон үзүүлэлтээр бага оноотой (хөгжүүлэх шаардлагатай). "
    "Аль үзүүлэлтүүд хоорондоо уялдаатай байна.\n\n"
    "3-Р ХЭСЭГ — АЛБАН ТУШААЛД ТОХИРОХ БАЙДАЛ:\n"
    "Тестийн үр дүнд үндэслэн хэн нь удирдлагын, борлуулалтын, "
    "захиргааны ажилд илүү тохиромжтой болохыг тодорхойл.\n\n"
    "4-Р ХЭСЭГ — ПРАКТИК ЗӨВЛӨГӨӨ:\n"
    "Тодорхой ажилтан бүрд (эсвэл бүлэг бүрд) юу хийх хэрэгтэйг бич. "
    "Сургалт, хөгжүүлэлт, байршуулалтын зөвлөгөө.\n\n"
    "ЧУХАЛ: Зөвхөн өгөгдөлд байгаа тоо, нэрийг ашигла. Зохиомол тоо гаргахгүй.\n"
    "Байгууллагын нэр дурдахгүй.\n\n"
)


@app.post("/analyze-excel")
async def analyze_excel(
    request: Request,
    file: UploadFile = File(...),
    question: str = "Энэ өгөгдлийг дүн шинжилгээ хийж дүгнэлт гарга"
):
    if request.headers.get("X-API-Key", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        contents = await file.read()
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))

        # Өгөгдлийн хураангуй — том файлд ухаалаг боловсруулалт
        summary = f"Нийт мөр: {len(df)}, Нийт ажилтан: {len(df)}\n"
        summary += f"Багана: {list(df.columns)}\n\n"
        
        # Тоон баганын статистик
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if num_cols:
            summary += f"Тоон үзүүлэлтүүдийн статистик:\n"
            summary += df[num_cols].describe().round(1).to_string()
            summary += "\n\n"
        
        # Том файл бол дээд/доод оноотойг харуулна
        if len(df) > 20:
            summary += f"Хамгийн өндөр оноотой 5 ажилтан:\n"
            if num_cols:
                df["Нийт оноо"] = df[num_cols].mean(axis=1).round(1)
                top5 = df.nlargest(5, "Нийт оноо")
                summary += top5.to_string() + "\n\n"
                low5 = df.nsmallest(5, "Нийт оноо")
                summary += f"Хамгийн бага оноотой 5 ажилтан:\n"
                summary += low5.to_string() + "\n\n"
        else:
            summary += f"Бүх өгөгдөл:\n{df.to_string()}"

        prompt = (
            EXCEL_PROMPT +
            f"Асуулт: {question}\n\n"
            f"Өгөгдөл:\n{summary}"
        )

        gc = _gemini_client
        response = gc.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        answer = response.text.strip()

        # Нэршлийн засвар
        for wrong, right in {
            "нийгэмч": "нийтэч", "Нийгэмч": "Нийтэч",
            "удирдамжийн": "удирдлагын",
        }.items():
            answer = answer.replace(wrong, right)

        return {"answer": answer, "rows": len(df), "columns": list(df.columns)}

    except Exception as ex:
        logger.error(f"Excel analysis failed: {ex}")
        return JSONResponse(status_code=500, content={"error": f"Алдаа: {str(ex)}"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# ===== EXCEL ANALYSIS ENDPOINT =====

