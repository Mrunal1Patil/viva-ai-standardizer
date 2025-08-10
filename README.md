VIVA AI Standardizer

AI-powered tool that turns raw publisher spreadsheets into VIVA’s Ideal format in minutes — safely, inside your network.

	
  •	✅ Reads human “instructions” (PDF/XLSX/TXT)
  •	🧠 Builds a JSON transformation plan with a local LLM (Llama-3 via Ollama)
	•	🧩 Applies the plan deterministically in Pandas
	•	🛠 Falls back to rule-based mappings (ACS, etc.) when AI is unsure
	•	🔐 No cloud calls — sensitive data never leaves your machine/VPC

⸻

Demo (high level)
	1.	Upload Ideal template (XLSX), Raw spreadsheet, and Instructions.
	2.	Click Generate.
	3.	Download: ideal_filled.xlsx, transform_log.yaml, summary.json.

⸻

Architecture
[React (Vite)]  →  [Spring Boot API]  →  [FastAPI AI Service]  →  [Ollama Llama-3 (local)]
     ↑                      ↓                   ↓
   User UI            File proxying       JSON plan + Pandas executor
                                        + deterministic fallback rules

Tech Stack
	•	Frontend: React + Vite, plain CSS
	•	Backend API: Spring Boot (Java 21), RestTemplate, CORS enabled
	•	AI Service: FastAPI (Python 3.10+), Pandas, PyMuPDF (PDF text), OpenPyXL
	•	Local LLM: Ollama + llama3:instruct (no internet needed after pull)
	•	Storage: Local job folders per run (XLSX/JSON/YAML outputs)

 Prerequisites
	•	Node 18+
	•	Java 21 + Maven (wrapper included: ./mvnw)
	•	Python 3.10+ (venv recommended)
	•	Ollama installed and model pulled:
 ollama pull llama3:instruct

 Quick Start

1) Frontend (React)
cd frontend
npm install
npm run dev
# opens http://localhost:5173

2) Spring Boot API
cd standardizer-api
./mvnw spring-boot:run
# runs on http://localhost:8080
CORS is allowed for http://localhost:5173. Adjust in CorsConfig.java if needed.

3) AI Service (FastAPI)
cd ai-service
python3 -m venv .venv
source .venv/bin/activate  
pip install -r requirements.txt  # or:
# pip install fastapi uvicorn pandas openpyxl pymupdf

uvicorn main:app --reload --port 8001
# health: http://localhost:8001/health


File Flow
	1.	Frontend uploads files → POST /api/process (Spring)
	2.	Spring streams files to AI service → gets back jobId
	3.	Spring auto-calls POST /finalize/{jobId} (AI runs plan)
	4.	Frontend shows ready links:
	•	/api/download/{jobId}/ideal → ideal_filled.xlsx
	•	/api/download/{jobId}/log → transform_log.yaml
	•	/api/download/{jobId}/summary → summary.json

 How the AI works
	•	The AI service extracts text from instructions.pdf (or reads instructions.xlsx/txt)
 	•	It asks the local LLM for a JSON plan
  	•	The Python executor applies the plan in Pandas (safe, deterministic).
	•	If the plan doesn’t improve the sheet, it falls back to canned ACS mappings.
	•	A YAML log lists every applied step.

 Security & Privacy
	•	No cloud calls for data — processing happens locally.
	•	ai-service/jobs/ contains per-run files; it’s excluded by .gitignore.
	•	Never commit real spreadsheets to GitHub.
	•	If needed, run all services in a private VPC/host behind your firewall.

 Acknowledgements

Built end-to-end as a GRA project at VIVA — focusing on time savings, accuracy, and data privacy with local AI.
