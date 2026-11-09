import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import ollama
import pandas as pd
from jobspy import scrape_jobs
from email.utils import formataddr
import subprocess
import time
import urllib.request
import sys
import datetime
from dotenv import load_dotenv
import pymupdf

log_file = open("agent.log", "a", encoding="utf-8", buffering=1)
sys.stdout = log_file
sys.stderr = log_file

print(f"\n========================================")
print(f"Démarrage de la tâche : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"========================================")

CSV_FILE = "job_offers.csv"
SEEN_FILE = "seen_jobs.txt"
MODEL_NAME = "qwen2.5-coder:1.5b"

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_LOGIN = os.getenv("SMTP_LOGIN")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

CV_1_PATH = "cvs/cv-e-sante-celian-digiovanni-2026.pdf"
CV_2_PATH = "cv-industrie-celian-digiovanni-2026.pdf"


def load_candidate_profile(filepath="profil_candidat.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        print(f"Erreur : Le fichier {filepath} est introuvable.")
        return ""

CANDIDATE_PROFILE = load_candidate_profile()

def load_prompt_template(filepath="prompt_evaluation.txt"):
    with open(filepath, "r", encoding="utf-8") as file:
        return file.read()

PROMPT_TEMPLATE = load_prompt_template()

def extract_text_from_pdf(pdf_path: str) -> str:
    extracted_text = ""
    try:
        with pymupdf.open(pdf_path) as pdf_document:
            for page in pdf_document:
                extracted_text += page.get_text()
        return extracted_text.strip()
    except Exception as error:
        print(f"Error reading PDF {pdf_path}: {error}")
        return ""
    
CV_1_TEXT = extract_text_from_pdf(CV_1_PATH)
CV_2_TEXT = extract_text_from_pdf(CV_2_PATH)

def pre_filter_job(title: str, description: str) -> bool:
    """
    Filtre intelligent basé sur le domaine : 
    Souple sur la santé/thèse, strict sur l'industrie (Python + IA obligatoires).
    """
    text = (title + " " + description).lower()
    
    # 1. Élimination du bruit (les faux positifs du scraper)
    bad_keywords = ["infirmier", "médecin", "aide-soignant", "pharmacien", "comptable", "manutentionnaire", "react", "angular", "développeur web"]
    if any(bad in text for bad in bad_keywords):
        return False
        
    # 2. Définition des lexiques
    health_keywords = ["santé", "health", "médical", "medical", "biomedical", "clinique", "clinical", "inserm", "e-santé", "e-health", "hôpital", "hospital", "patient", "soin"]
    phd_keywords = ["thèse", "these", "phd", "doctorat", "doctorant", "post-doc"]
    
    python_keyword = "python"
    
    ai_signal_keywords = ["intelligence artificielle", " ia ", " ai ", "machine learning", "deep learning", "pytorch", "tensorflow", "cnn", "traitement du signal", "signal processing", "séries temporelles", "time series", "algorithme", "classification", "edge ai"]
    
    data_it_keywords = ["traitement de données", "data processing", "base de données", "database", "sql", "data scientist", "data engineer", "développement logiciel", "software", "informatique"]

    # --- APPLICATION DE LA LOGIQUE ---

    # Cas A : Les thèses passent toujours la barrière du pré-filtre
    if any(kw in text for kw in phd_keywords):
        return True
        
    # Évaluation des présences
    is_health = any(kw in text for kw in health_keywords)
    has_python = python_keyword in text
    has_ai_signal = any(kw in text for kw in ai_signal_keywords)
    has_data_it = any(kw in text for kw in data_it_keywords)

    # Cas B : Domaine de la Santé -> Souplesse
    # On accepte si ça touche à Python, à la Data, ou à l'IA.
    if is_health:
        if has_python or has_data_it or has_ai_signal:
            return True
            
    # Cas C : Autres domaines (Défense, Industrie, etc.) -> Stricte
    # Il FAUT Python ET des compétences dures en IA/Signal.
    if not is_health:
        if has_python and has_ai_signal:
            return True
            
    # Si l'offre ne rentre dans aucune de ces cases, on la rejette instantanément (0.001s)
    return False

def save_single_match(match_data: dict):
    """Enregistre une offre validée instantanément dans le CSV sans attendre la fin du script."""
    df_new = pd.DataFrame([match_data])
    if os.path.exists(CSV_FILE):
        try:
            df_old = pd.read_csv(CSV_FILE)
            df_combined = pd.concat([df_old, df_new]).drop_duplicates(subset=["Link"])
            df_combined.to_csv(CSV_FILE, index=False, encoding="utf-8")
        except Exception:
            df_new.to_csv(CSV_FILE, index=False, encoding="utf-8")
    else:
        df_new.to_csv(CSV_FILE, index=False, encoding="utf-8")

def send_email_notification(matches: list):
    matches_count = len(matches)
    subject = f"AI Job Agent: {matches_count} nouvelle(s) offre(s) retenue(s)"

    # Séparation basée sur le domaine (CV) et le type de poste (Thèse)
    theses = [job for job in matches if job.get('Is_PhD', False)]
    esante = [job for job in matches if job['Recommended_CV'] == 'e-Santé' and not job.get('Is_PhD', False)]
    industries = [job for job in matches if job['Recommended_CV'] == 'Industrie' and not job.get('Is_PhD', False)]

    body = f"Bonjour Célian,\n\nL'agent IA a détecté {matches_count} nouvelle(s) offre(s) :\n\n"

    def format_jobs(job_list, category_name):
        text = ""
        if job_list:
            text += f"--- {category_name} ({len(job_list)}) ---\n"
            for job in job_list:
                lang = "Anglais" if job.get('Language_Recommendation', 'FR') == 'EN' else "Français"
                text += f"[{job['Score']}/100] {job['Title']} ({job['Company']})\n"
                text += f"   - CV recommandé: {job['Recommended_CV']} ({lang})\n"
                text += f"   - Résumé: {job.get('Summary', 'Non disponible')}\n"
                text += f"   - Motif: {job['Reason']}\n"
                text += f"   - Lien: {job['Link']}\n\n"
        return text

    body += format_jobs(theses, "🎓 THÈSES & RECHERCHE ACADÉMIQUE")
    body += format_jobs(esante, "🏥 E-SANTÉ & INGÉNIERIE BIOMÉDICALE")
    body += format_jobs(industries, "⚙️ INDUSTRIE, DÉFENSE & IA EMBARQUÉE")

    body += "Lance 'streamlit run app.py' pour consulter les détails."

    msg = MIMEMultipart()
    msg["From"] = formataddr(("AI Job Agent", SENDER_EMAIL))
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_LOGIN, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        print("Notification email envoyée avec succès via iCloud SMTP.")
    except Exception as e:
        print(f"Erreur lors de l'envoi de l'email via iCloud: {e}")

def unload_ollama_model(model_name: str = "qwen2.5-coder:1.5b"):
    try:
        url = "http://localhost:11434/api/generate"
        data = json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2)
        print(f"Model {model_name} successfully unloaded from memory.")
    except Exception as e:
        print(f"Could not unload model: {e}")

def ensure_ollama_running():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        print("Ollama server is active.")
    except Exception:
        print("Starting Ollama server in background...")
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=DETACHED_PROCESS
        )
        time.sleep(5)

def evaluate_job_offer(title: str, description: str) -> dict:
    short_description = description[:1200]

    # Injection dynamique des variables dans le texte à trous
    prompt = PROMPT_TEMPLATE.format(
        CANDIDATE_PROFILE=CANDIDATE_PROFILE,
        CV_1=CV_1_TEXT,
        CV_2=CV_2_TEXT,
        title=title,
        short_description=short_description
    )

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        keep_alive=0
    )

    try:
        parsed = json.loads(response["message"]["content"])
        return {
            "score": parsed.get("score", 0),
            "match": parsed.get("match", False),
            "cv_target": parsed.get("cv_target", "Industrie"),
            "is_phd": parsed.get("is_phd", False),
            "language_recommendation": parsed.get("language_recommendation", "FR"),
            "description_summary": parsed.get("description_summary", "Résumé indisponible."),
            "reason": parsed.get("reason", "")
        }
    except Exception:
        return {
            "score": 0, 
            "match": False, 
            "cv_target": "Industrie", 
            "is_phd": False, 
            "language_recommendation": "FR", 
            "description_summary": "", 
            "reason": "Erreur JSON"
        }

def fetch_filtered_jobs():
    """Récupère les offres d'emploi uniquement depuis LinkedIn et Indeed (France) sur 2 mois."""
    print("Scraping d'offres multi-requêtes depuis LinkedIn et Indeed (France)...")
    
    search_queries = [
        "Machine Learning",
        "Deep Learning",
        "Signal Processing",
        "AI Engineer",
        "Phd",
        "Intelligence Artificielle Santé",
        "Classification",
        "Traitement du Signal",
        "Traitement de données"
    ]
    
    all_jobs = []
    for query in search_queries:
        print(f" -> Recherche en cours pour : '{query}'")
        try:
            jobs = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                location="France",
                results_wanted=10,
                hours_old=1440,
                country_indeed='France'
            )
            all_jobs.append(jobs)
        except Exception as e:
            print(f"Erreur sur la requête '{query}': {e}")
            
    if all_jobs:
        df_combined = pd.concat(all_jobs, ignore_index=True)
        if not df_combined.empty:
            df_combined = df_combined.drop_duplicates(subset=["job_url"])
            return df_combined
            
    return pd.DataFrame()

def is_system_busy() -> bool:
    heavy_apps = [
        "rocket league",
        "destiny 2",
        "witcher 3"
    ]
    
    try:
        cmd = 'powershell "Get-Process | Where-Object {$_.MainWindowTitle -ne \'\'} | Select-Object -ExpandProperty MainWindowTitle"'
        output = subprocess.check_output(cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        windows_titles = output.decode("utf-8", errors="ignore").lower()
        
        for app in heavy_apps:
            if app in windows_titles:
                return True
        return False
        
    except Exception as e:
        print(f"Erreur lors de la verification des fenetres : {e}")
        return False

def run_agent():

    if is_system_busy():
        print("Systeme occupe (jeu ou logiciel lourd en cours).", file=sys.__stdout__)
        print("L'agent se met en veille pour eviter les ralentissements. Execution reportee.")
        return

    ensure_ollama_running()

    print("Recherche des offres en cours sur LinkedIn et Indeed...", file=sys.__stdout__)
    
    jobs_df = fetch_filtered_jobs()

    if jobs_df.empty:
        print("Aucune offre trouvee.", file=sys.__stdout__)
        return

    print(f"Recherche terminee : {len(jobs_df)} offres brutes trouvees.", file=sys.__stdout__)

    seen_urls = set()
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen_urls = set(line.strip() for line in f)

    # --- PHASE 1 : Pre-filtrage ---
    jobs_to_evaluate = []
    
    for idx, row in jobs_df.iterrows():
        job_url = str(row.get("job_url", ""))
        title = str(row.get("title", ""))
        description = str(row.get("description", ""))

        if job_url in seen_urls:
            continue

        if not pre_filter_job(title, description):
            print("  |- [REJET RAPIDE] Ne correspond pas aux criteres.\n")
            with open(SEEN_FILE, "a", encoding="utf-8") as f:
                f.write(f"{job_url}\n")
            seen_urls.add(job_url)
            continue
            
        jobs_to_evaluate.append(row)

    print(f"Pre-filtrage termine : {len(jobs_to_evaluate)} offres vont etre analysees par l'IA.", file=sys.__stdout__)

    if not jobs_to_evaluate:
        unload_ollama_model()
        return

    # --- PHASE 2 : Analyse IA ---
    new_matches = []

    for row in jobs_to_evaluate:
        job_url = str(row.get("job_url", ""))
        title = str(row.get("title", ""))
        company = str(row.get("company", "N/A"))
        description = str(row.get("description", ""))

        site_source = "Other"
        if "linkedin" in job_url.lower():
            site_source = "LinkedIn"
        elif "indeed" in job_url.lower():
            site_source = "Indeed"

        print(f"Évaluation : {title} ({company})")

        eval_result = evaluate_job_offer(title, description)

        score = eval_result.get("score", 0)
        is_match = eval_result.get("match", False)
        cv_target = eval_result.get("cv_target", "Industrie")
        is_phd = eval_result.get("is_phd", False)
        language_rec = eval_result.get("language_recommendation", "FR")
        summary = eval_result.get("description_summary", "")
        reason = eval_result.get("reason", "")

        status = "MATCH" if is_match else "REJET"
        print(f"  |- [{status}] {score}/100 | CV: {cv_target} | Thèse: {is_phd}\n")

        with open(SEEN_FILE, "a", encoding="utf-8") as f:
            f.write(f"{job_url}\n")
        seen_urls.add(job_url)

        if is_match:
            match_item = {
                "Date": "Récent",
                "Company": company,
                "Title": title,
                "Link": job_url,
                "Score": score,
                "Recommended_CV": cv_target,
                "Language_Recommendation": language_rec,
                "Is_PhD": is_phd,
                "Summary": summary,
                "Reason": reason,
                "Site": site_source,
                "Status": "To Review",
                "Full_Description": description
            }
            new_matches.append(match_item)
            # Enregistrement immédiat dans le CSV pour éviter de perdre les données
            save_single_match(match_item)

    if new_matches:
        send_email_notification(new_matches)
        print(f"Termine ! {len(new_matches)} nouvelle(s) offre(s) pertinente(s) envoyee(s) par mail.", file=sys.__stdout__)
    else:
        print("Termine. Aucune nouvelle offre pertinente pour le moment.", file=sys.__stdout__)
        
    unload_ollama_model()

if __name__ == "__main__":
    run_agent()