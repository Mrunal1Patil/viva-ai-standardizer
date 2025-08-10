from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from pathlib import Path
import uuid, shutil, json, subprocess, re
import pandas as pd

app = FastAPI()

# ---------- storage ----------
JOBS_DIR = Path("./jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# ---------- health ----------
@app.get("/health")
def health():
    return {"status": "ok"}

# ---------- helpers ----------
def read_instructions_text(job_dir: Path) -> str:
    """Read instructions.* (pdf/xlsx/xls/txt) into plain text."""
    instr = next(job_dir.glob("instructions*"), None)
    if not instr:
        return ""
    suffix = instr.suffix.lower()
    try:
        if suffix == ".pdf":
            import fitz  # PyMuPDF
            doc = fitz.open(instr)
            return "\n".join(page.get_text() for page in doc)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(instr)
            return "\n".join(df.astype(str).fillna("").values.flatten())
        else:
            return instr.read_text(errors="ignore")
    except Exception as e:
        return f"[INSTRUCTIONS_READ_ERROR] {e}"

def call_ollama(prompt: str) -> str:
    """Call local Llama 3 via Ollama (ensure `ollama pull llama3:instruct`)."""
    proc = subprocess.run(
        ["ollama", "run", "llama3:instruct"],
        input=prompt,
        text=True,
        capture_output=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Ollama error: {proc.stderr.strip() or proc.stdout}")
    return proc.stdout

def extract_json_block(text: str) -> str:
    """Extract JSON from model output (tries fenced ```json blocks first)."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # fallback: find the first {...} JSON-looking block
    m2 = re.search(r"(\{.*\})", text, re.DOTALL)
    return m2.group(1).strip() if m2 else ""

def build_plan_prompt(raw_cols, ideal_cols, instructions_text: str) -> str:
    """
    Ask the model for a JSON plan instead of Python code.
    """
    return f"""
You are a data standardization planner. Read the instructions and produce a concise JSON PLAN
describing how to map RAW columns to IDEAL columns. Do NOT include any prose, ONLY JSON.

JSON SCHEMA (strict):
{{
  "mappings": [
    {{"op":"copy", "source":"<raw col>", "target":"<ideal col>"}},
    {{"op":"concat", "sources":["<raw col A>", "<raw col B>"], "separator":" ", "target":"<ideal col>"}},
    {{"op":"date_copy", "source":"<raw date col>", "target":"<ideal date col>"}},
    {{"op":"calendar_year", "source":"<raw date col>", "target":"Calendar Year"}},
    {{"op":"fiscal_year_july_june", "source":"<raw date col>", "target":"Fiscal Year"}},
    {{"op":"numeric_copy", "source":"<raw numeric col>", "target":"<ideal col>", "decimals":2}},
    {{"op":"fill_const", "value":"<constant string>", "target":"<ideal col>"}}
  ],
  "notes": ["any short notes about assumptions or skipped rules"]
}}

Rules:
- Only use columns that exist in RAW/IDEAL when possible. If uncertain, include but the executor will skip missing ones.
- If instructions mention ACS agreement string, include fill_const for "Agreement".
- If instructions mention concat for names, use op "concat".
- For date:
  - Use "date_copy" for Publication Date copies.
  - Use "calendar_year" for extracting year.
  - Use "fiscal_year_july_june" for VIVA FY rule (FY = year + (month>=7)).
- For APC or money fields, use "numeric_copy" with "decimals":2.
- Keep JSON compact.

RAW_COLUMNS = {list(map(str, raw_cols))}
IDEAL_COLUMNS = {list(map(str, ideal_cols))}

INSTRUCTIONS (verbatim):
{instructions_text}
""".strip()

def safe_to_datetime(series):
    s = pd.to_datetime(series, errors="coerce")
    return s

def apply_plan(plan: dict, raw_df: pd.DataFrame, ideal_df: pd.DataFrame):
    """
    Execute the JSON plan deterministically with Pandas.
    Returns (new_ideal_df, steps[])
    """
    steps = []
    # ensure row count
    if len(ideal_df) == 0 and not raw_df.empty:
        ideal_df = pd.DataFrame(columns=ideal_df.columns, index=range(len(raw_df)))

    def has(df, col): return col in df.columns

    mappings = plan.get("mappings", []) if isinstance(plan, dict) else []
    for m in mappings:
        try:
            op = m.get("op")
            if op == "copy":
                src, tgt = m.get("source"), m.get("target")
                if has(raw_df, src) and has(ideal_df, tgt):
                    ideal_df[tgt] = raw_df[src]
                    steps.append(f'Mapped "{src}" → "{tgt}"')
                else:
                    steps.append(f'Skipped copy "{src}"→"{tgt}" (missing col)')

            elif op == "concat":
                srcs, sep, tgt = m.get("sources", []), m.get("separator", " "), m.get("target")
                if all(has(raw_df, s) for s in srcs) and has(ideal_df, tgt):
                    vals = [raw_df[s].fillna("").astype(str).str.strip() for s in srcs]
                    out = vals[0]
                    for v in vals[1:]:
                        out = (out + sep + v).str.strip()
                    # normalize empty to NaN
                    out = out.replace({"^\\s*$": None}, regex=True)
                    ideal_df[tgt] = out
                    steps.append(f'Concatenated {srcs} → "{tgt}"')
                else:
                    steps.append(f'Skipped concat {srcs}→"{tgt}" (missing col)')

            elif op == "date_copy":
                src, tgt = m.get("source"), m.get("target")
                if has(raw_df, src) and has(ideal_df, tgt):
                    dt = safe_to_datetime(raw_df[src])
                    ideal_df[tgt] = dt.dt.date
                    steps.append(f'Date copy "{src}" → "{tgt}"')
                else:
                    steps.append(f'Skipped date_copy "{src}"→"{tgt}" (missing col)')

            elif op == "calendar_year":
                src, tgt = m.get("source"), m.get("target")
                if has(raw_df, src) and has(ideal_df, tgt):
                    dt = safe_to_datetime(raw_df[src])
                    ideal_df[tgt] = dt.dt.year
                    steps.append(f'Calendar Year from "{src}" → "{tgt}"')
                else:
                    steps.append(f'Skipped calendar_year "{src}"→"{tgt}" (missing col)')

            elif op == "fiscal_year_july_june":
                src, tgt = m.get("source"), m.get("target")
                if has(raw_df, src) and has(ideal_df, tgt):
                    dt = safe_to_datetime(raw_df[src])
                    ideal_df[tgt] = dt.dt.year + (dt.dt.month >= 7).astype("Int64")
                    steps.append(f'Fiscal Year (July–June) from "{src}" → "{tgt}"')
                else:
                    steps.append(f'Skipped fiscal_year "{src}"→"{tgt}" (missing col)')

            elif op == "numeric_copy":
                src, tgt = m.get("source"), m.get("target")
                decimals = int(m.get("decimals", 2))
                if has(raw_df, src) and has(ideal_df, tgt):
                    ideal_df[tgt] = pd.to_numeric(raw_df[src], errors="coerce").round(decimals)
                    steps.append(f'Numeric copy "{src}" → "{tgt}" (round {decimals})')
                else:
                    steps.append(f'Skipped numeric_copy "{src}"→"{tgt}" (missing col)')

            elif op == "fill_const":
                val, tgt = m.get("value"), m.get("target")
                if has(ideal_df, tgt):
                    ideal_df[tgt] = val
                    steps.append(f'Filled constant "{val}" → "{tgt}"')
                else:
                    steps.append(f'Skipped fill_const "{val}"→"{tgt}" (missing col)')

            else:
                steps.append(f"Unknown op '{op}' skipped")
        except Exception as e:
            steps.append(f"[PLAN_APPLY_ERROR] {e}")

    return ideal_df, steps

def apply_fallback_acs(raw_df: pd.DataFrame, ideal_df: pd.DataFrame):
    """Deterministic ACS rules if AI plan fails, so user always gets a filled sheet."""
    steps = []
    if len(ideal_df) == 0 and not raw_df.empty:
        ideal_df = pd.DataFrame(columns=ideal_df.columns, index=range(len(raw_df)))
    def has(df, col): return col in df.columns

    if "Agreement" in ideal_df.columns:
        ideal_df["Agreement"] = "ACS"
        steps.append('Set Agreement = "ACS"')

    if has(raw_df, "Manuscript DOI") and "Article DOI" in ideal_df.columns:
        ideal_df["Article DOI"] = raw_df["Manuscript DOI"]
        steps.append("Manuscript DOI → Article DOI")

    if all(has(raw_df, c) for c in ["Corresponding Author First Name", "Corresponding Author Last Name"]) \
       and "Author Name" in ideal_df.columns:
        first = raw_df["Corresponding Author First Name"].fillna("").astype(str)
        last  = raw_df["Corresponding Author Last Name"].fillna("").astype(str)
        ideal_df["Author Name"] = (first.str.strip() + " " + last.str.strip()).str.strip().replace({"^\\s*$": None}, regex=True)
        steps.append("Corresponding Author First/Last → Author Name")

    if has(raw_df, "Manuscript Title Text") and "Article Title" in ideal_df.columns:
        ideal_df["Article Title"] = raw_df["Manuscript Title Text"]
        steps.append("Manuscript Title Text → Article Title")

    if has(raw_df, "Journal Title Name") and "Journal Title" in ideal_df.columns:
        ideal_df["Journal Title"] = raw_df["Journal Title Name"]
        steps.append("Journal Title Name → Journal Title")

    if has(raw_df, "ASAP Pub Date"):
        dt = pd.to_datetime(raw_df["ASAP Pub Date"], errors="coerce")
        if "Publication Date" in ideal_df.columns:
            ideal_df["Publication Date"] = dt.dt.date
            steps.append("ASAP Pub Date → Publication Date")
        if "Calendar Year" in ideal_df.columns:
            ideal_df["Calendar Year"] = dt.dt.year
            steps.append("Calendar Year from ASAP Pub Date")
        if "Fiscal Year" in ideal_df.columns:
            ideal_df["Fiscal Year"] = dt.dt.year + (dt.dt.month >= 7).astype("Int64")
            steps.append("Fiscal Year (July–June) from ASAP Pub Date")

    if has(raw_df, "Transacting Profile Name") and "Author Affiliation" in ideal_df.columns:
        ideal_df["Author Affiliation"] = raw_df["Transacting Profile Name"]
        steps.append("Transacting Profile Name → Author Affiliation")

    if has(raw_df, "Retail Price") and "APC" in ideal_df.columns:
        ideal_df["APC"] = pd.to_numeric(raw_df["Retail Price"], errors="coerce").round(2)
        steps.append("Retail Price → APC (2 decimals)")

    if has(raw_df, "Purchase License Summary") and "License" in ideal_df.columns:
        ideal_df["License"] = raw_df["Purchase License Summary"]
        steps.append("Purchase License Summary → License")

    if has(raw_df, "Journal Type Code") and "Gold or Hybrid OA" in ideal_df.columns:
        ideal_df["Gold or Hybrid OA"] = raw_df["Journal Type Code"]
        steps.append("Journal Type Code → Gold or Hybrid OA")

    return ideal_df, steps

# ---------- process (save inputs) ----------
@app.post("/process")
async def process_files(
    ideal: UploadFile = File(...),
    raw: UploadFile = File(...),
    instructions: UploadFile = File(...)
):
    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    def save(upload: UploadFile, name: str):
        with open(job_dir / name, "wb") as f:
            shutil.copyfileobj(upload.file, f)

    save(ideal, "ideal_upload.xlsx")
    save(raw, "raw_upload.xlsx")
    save(instructions, instructions.filename or "instructions_upload")

    return JSONResponse({
        "jobId": job_id,
        "status": "saved_inputs",
        "paths": {"jobDir": str(job_dir.resolve())},
        "received": {
            "ideal": ideal.filename,
            "raw": raw.filename,
            "instructions": instructions.filename
        }
    })

# ---------- finalize (AI JSON plan → deterministic executor, with fallback) ----------
@app.post("/finalize/{job_id}")
def finalize(job_id: str):
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)

    raw_path = job_dir / "raw_upload.xlsx"
    ideal_path = job_dir / "ideal_upload.xlsx"
    if not raw_path.exists() or not ideal_path.exists():
        return JSONResponse({"error": "missing input files"}, status_code=400)

    # 1) read instructions to text file
    instr_text = read_instructions_text(job_dir)
    (job_dir / "instructions.txt").write_text(instr_text)

    # 2) load sheets
    raw_df = pd.read_excel(raw_path)
    ideal_df = pd.read_excel(ideal_path)
    if len(ideal_df) == 0 and not raw_df.empty:
        ideal_df = pd.DataFrame(columns=ideal_df.columns, index=range(len(raw_df)))

    # 3) ask LLM for a JSON plan
    ai_steps = []
    plan_json = ""
    try:
        prompt = build_plan_prompt(raw_df.columns.tolist(), ideal_df.columns.tolist(), instr_text[:4000])
        llm_out = call_ollama(prompt)
        plan_json = extract_json_block(llm_out)
    except Exception as e:
        ai_steps.append(f"[AI_CALL_ERROR] {e}")

    # Save raw model output and extracted plan
    (job_dir / "plan_raw.txt").write_text(llm_out if 'llm_out' in locals() else "")
    (job_dir / "plan.json").write_text(plan_json or "{}")

    # 4) parse and apply plan
    new_ideal_df = ideal_df.copy()
    if plan_json:
        try:
            plan = json.loads(plan_json)
            new_ideal_df, plan_steps = apply_plan(plan, raw_df, new_ideal_df)
            ai_steps.extend(plan_steps)
        except Exception as e:
            ai_steps.append(f"[PLAN_PARSE_ERROR] {e}")
    else:
        ai_steps.append("No JSON plan extracted")

    # 5) if AI didn’t improve anything, fallback to ACS rules
    def nonnull_counts(df):
        return {c: int(df[c].notna().sum()) for c in df.columns}
    before_counts = nonnull_counts(ideal_df)
    after_counts  = nonnull_counts(new_ideal_df)
    changed = any(after_counts.get(c, 0) > before_counts.get(c, 0) for c in new_ideal_df.columns)

    if not changed:
        fb_df, fb_steps = apply_fallback_acs(raw_df, ideal_df)
        new_ideal_df = fb_df
        ai_steps.append("FALLBACK: Applied deterministic ACS rules")
        ai_steps.extend(fb_steps)

    # 6) outputs
    final_ideal = job_dir / "ideal_filled.xlsx"
    new_ideal_df.to_excel(final_ideal, index=False)

    (job_dir / "transform_log.yaml").write_text(
        "steps:\n" + "\n".join(f"  - {s}" for s in ai_steps)
    )

    (job_dir / "summary.json").write_text(json.dumps({
        "rows_in_raw": int(len(raw_df)),
        "rows_in_ideal": int(len(new_ideal_df)),
        "plan_chars": len(plan_json),
        "notes": "AI JSON plan executed deterministically; ACS fallback used if plan had no effect."
    }, indent=2))

    return {"jobId": job_id, "status": "finalized", "message": "AI plan executed (w/ fallback if needed)"}

# ---------- download ----------
@app.get("/download/{job_id}/{kind}")
def download(job_id: str, kind: str):
    job_dir = JOBS_DIR / job_id
    mapping = {
        "ideal": job_dir / "ideal_filled.xlsx",
        "log": job_dir / "transform_log.yaml",
        "summary": job_dir / "summary.json",
    }
    path = mapping.get(kind)
    if not path or not path.exists():
        return JSONResponse({"error": "file not ready"}, status_code=404)
    return FileResponse(path)
