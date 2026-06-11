import pandas as pd
import io, re

TEST_PATTERNS = {
    "CTPI": [r"ctpi", r"манлайлах", r"анализ хийх", r"шийдвэр гаргах", r"харилцаа тогтоох", r"менторлох", r"бүтээлч"],
    "Big5": [r"big.?5", r"нийтэч", r"нягт нямбай", r"нээлттэй", r"openness", r"meticulousness", r"sociability", r"emotional.?balance", r"consciousness"],
    "PP": [r"\bpp\b", r"focus.?on.?facts", r"desire.?to.?lead", r"ambition", r"extraversion", r"flexibility"],
    "VOC": [r"\bvoc\b", r"мэргэжлийн сонирхол", r"intellectual.?curiosity", r"enterprising", r"methodical"],
    "EQ": [r"\beq\b", r"emotional.?intell", r"сэтгэл хөдлөлийн"],
    "MOTIVATION": [r"motivation", r"сэдэл"],
    "SALES": [r"sales", r"борлуулалт"],
}

def detect_test_type(columns):
    cols_lower = " ".join(str(c).lower() for c in columns)
    found = {}
    for test, patterns in TEST_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, cols_lower, re.IGNORECASE):
                found[test] = True
                break
    return found

def find_name_column(df):
    name_hints = ["нэр", "name", "ажилтны нэр", "хэн", "овог нэр", "овог", "employee"]
    for col in df.columns:
        if any(h in str(col).lower() for h in name_hints):
            return col
    for col in df.columns:
        if df[col].dtype == object:
            return col
    return None

def smart_column_selection(df, max_cols=20):
    num_cols = df.select_dtypes(include="number").columns.tolist()
    text_cols = df.select_dtypes(exclude="number").columns.tolist()
    name_col = find_name_column(df)
    keep_text = [name_col] if name_col and name_col in df.columns else text_cols[:2]
    if len(num_cols) <= max_cols:
        return df[keep_text + num_cols], 0, len(num_cols)
    stds = df[num_cols].std().sort_values(ascending=False)
    selected_num = stds.head(max_cols).index.tolist()
    dropped = len(num_cols) - max_cols
    return df[keep_text + selected_num], dropped, len(num_cols)

def process_excel(file_bytes, filename, question):
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))

    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]

    original_col_count = len(df.columns)
    num_cols_all = df.select_dtypes(include="number").columns.tolist()
    name_col = find_name_column(df)
    detected_tests = detect_test_type(list(df.columns))

    dropped_cols = 0
    if len(num_cols_all) > 20:
        df, dropped_cols, _ = smart_column_selection(df, max_cols=20)
        num_cols = df.select_dtypes(include="number").columns.tolist()
    else:
        num_cols = num_cols_all

    summary_parts = []
    test_list = ", ".join(detected_tests.keys()) if detected_tests else "Тодорхойгүй"
    summary_parts.append(f"Файл: {filename}")
    summary_parts.append(f"Нийт мөр: {len(df)}, Нийт багана: {original_col_count}")
    summary_parts.append(f"Илэрсэн тестүүд: {test_list}")
    if dropped_cols > 0:
        summary_parts.append(f"⚠ {dropped_cols} багана орхигдлоо (хамгийн ялгаатай 20-г авлаа)")
    summary_parts.append(f"Баганууд: {list(df.columns)}")
    summary_parts.append("")

    if len(df) <= 30:
        summary_parts.append("=== Бүх өгөгдөл ===")
        summary_parts.append(df.to_string(index=False))
    else:
        if num_cols:
            df2 = df.copy()
            df2["__avg__"] = df2[num_cols].mean(axis=1).round(2)
            top5 = df2.nlargest(5, "__avg__").drop(columns=["__avg__"])
            bot5 = df2.nsmallest(5, "__avg__").drop(columns=["__avg__"])
            summary_parts.append("=== ТОП 5 мөр ===")
            summary_parts.append(top5.to_string(index=False))
            summary_parts.append("\n=== Хамгийн бага оноотой 5 мөр ===")
            summary_parts.append(bot5.to_string(index=False))
        summary_parts.append("\n=== Статистик ===")
        summary_parts.append(df[num_cols].describe().round(2).to_string())

    summary = "\n".join(summary_parts)
    raw_data = df.head(200).fillna("").to_dict(orient="records")

    return {
        "summary": summary,
        "columns": list(df.columns),
        "rows": len(df),
        "raw_data": raw_data,
        "detected_tests": list(detected_tests.keys()),
        "dropped_cols": dropped_cols,
        "name_col": name_col,
        "num_cols": num_cols,
        "prompt_data": summary,
    }

def build_excel_prompt(processed, question, base_prompt):
    test_ctx = ""
    if processed["detected_tests"]:
        test_ctx = f"\nИлэрсэн тестүүд: {', '.join(processed['detected_tests'])}\n"
    else:
        test_ctx = "\nАнхааруулга: Тестийн нэрийг автоматаар тодорхойлж чадсангүй.\n"
    return base_prompt + test_ctx + f"\nАсуулт: {question}\n\nӨгөгдөл:\n{processed['prompt_data']}"
