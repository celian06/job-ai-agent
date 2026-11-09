import streamlit as st
import pandas as pd
import os
import pymupdf
import ollama
from docx import Document
from docx.shared import Pt
import io

# Page configuration
st.set_page_config(page_title="AI Job Agent", layout="wide")
st.title("AI Job Agent - Tableau de bord")

# Chargement automatique des CVs en mémoire au démarrage
@st.cache_resource
def load_cv_texts():
    def full_text(path):
        with pymupdf.open(path) as doc:
            return "\n".join([page.get_text() for page in doc])
    try:
        return full_text("cvs/cv-e-sante-celian-digiovanni-2026-en.pdf"), full_text("cvs/cv-industrie-celian-digiovanni-2026.pdf")
    except Exception:
        return "", ""

CV_1_TEXT, CV_2_TEXT = load_cv_texts()

# Fonction de génération de lettre de motivation via Ollama
def generate_cover_letter(job_title: str, company: str, description: str, recommended_cv_text: str, candidate_profile: str) -> str:
    # Lecture du prompt depuis le fichier externe
    try:
        with open("prompt_lettre.txt", "r", encoding="utf-8") as file_prompt:
            prompt_template = file_prompt.read()
    except FileNotFoundError:
        prompt_template = """Tu es un assistant expert en rédaction de candidatures professionnelles.
Rédige une lettre de motivation percutante, professionnelle et personnalisée en FRANÇAIS pour le poste suivant.
N'inclus pas d'objets ou de balises superflues, commence directement par l'en-tête de la lettre ou la formule de civilité.

PROFIL DU CANDIDAT :
{candidate_profile}

DONNÉES DU CV UTILISÉ :
{recommended_cv_text}

OFFRE D'EMPLOI :
Poste : {job_title}
Entreprise : {company}
Description : {description}

Consignes :
- Mets en valeur les expériences les plus pertinentes du CV qui correspondent à l'offre.
- Adopte un ton professionnel, motivé et précis.
- Structure la lettre de manière classique (Introduction, Corps technique, Conclusion avec appel à l'action).
"""

    try:
        formatted_prompt = prompt_template.format(
            candidate_profile=candidate_profile,
            recommended_cv_text=recommended_cv_text,
            job_title=job_title,
            company=company,
            description=description
        )
    except KeyError as e:
        return f"Erreur de formatage dans prompt_lettre.txt : variable manquante {e}"

    try:
        response = ollama.chat(
            model="qwen2.5-coder:1.5b",
            messages=[{"role": "user", "content": formatted_prompt}],
            keep_alive=0
        )
        return response['message']['content']
    except Exception as e:
        return f"Erreur lors de la génération avec Ollama : {e}"

# Fonction pour créer un fichier Word (.docx) en mémoire et retourner ses octets
def create_docx_from_text(text: str) -> bytes:
    doc = Document()
    
    # Ajout du texte ligne par ligne avec un espacement propre
    for line in text.split("\n"):
        p = doc.add_paragraph(line)
        # Style de police professionnel par défaut (Calibri, taille 11)
        p.paragraph_format.space_after = Pt(4) if 'docx' in globals() else 4
        
    # Sauvegarde en mémoire tampon (bytes)
    doc_io = io.BytesIO()
    doc.save(doc_io)
    doc_io.seek(0)
    return doc_io.getvalue()

# Data loading function
@st.cache_data(ttl=10)
def load_data():
    try:
        df = pd.read_csv("job_offers.csv")
    except FileNotFoundError:
        return pd.DataFrame()
    
    if "Site" not in df.columns:
        df["Site"] = "LinkedIn / Indeed"
    if "Status" not in df.columns:
        df["Status"] = "À postuler"
        
    df["Site"] = df["Site"].fillna("Other")
    df["Status"] = df["Status"].fillna("À postuler")
    return df

df = load_data()

if df.empty:
    st.info("Aucune offre n'a encore ete trouvee.")
else:
    st.sidebar.header("Filtres")
    show_archived = st.sidebar.checkbox("Afficher les archives", value=False)
    
    if "Site" not in df.columns:
        df["Site"] = "LinkedIn / Indeed"
    df["Site"] = df["Site"].fillna("Other")
    
    cv_options = df["Recommended_CV"].dropna().unique().tolist()
    selected_cvs = st.sidebar.multiselect("CV Recommande", cv_options, default=cv_options)
    min_score = st.sidebar.slider("Score minimum", 65, 100, 65)
    phd_only = st.sidebar.checkbox("[THESE] Uniquement les offres de these", value=False)
    
    mask = (df["Recommended_CV"].isin(selected_cvs)) & (df["Score"] >= min_score)
    if phd_only and "Is_PhD" in df.columns:
        mask = mask & (df["Is_PhD"] == True)
        
    if not show_archived:
        mask = mask & (df["Status"] != "Archivé")
    else:
        mask = mask & (df["Status"] == "Archivé")
        
    filtered_df = df[mask].sort_values(by="Score", ascending=False)
    
    st.metric("Offres correspondantes", len(filtered_df))
    
    available_sites = filtered_df["Site"].unique().tolist()
    
    if available_sites:
        tabs = st.tabs(available_sites)
        
        for index, site_name in enumerate(available_sites):
            with tabs[index]:
                site_df = filtered_df[filtered_df["Site"] == site_name]
                
                for idx, row in site_df.iterrows():
                    badge = "[THESE] " if row.get("Is_PhD", False) else ""
                    current_status = row.get("Status", "À postuler")
                    status_tag = f" [{current_status}]" if current_status != "À postuler" else ""
                    expander_title = f"[{row['Score']}/100]{status_tag} {badge}{row['Title']} chez {row['Company']}"
                    
                    with st.expander(expander_title):
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.markdown(f"**CV Recommande :** {row['Recommended_CV']} (en {row.get('Language_Recommendation', 'FR')})")
                            st.markdown(f"**Statut actuel :** `{current_status}`")
                            st.markdown(f"**Resume de l'offre :** {row.get('Summary', 'Non disponible')}")
                            st.markdown(f"**Motif de l'IA :** {row['Reason']}")
                            
                            # Si la lettre a été générée, afficher le bouton de téléchargement Word (.docx)
                            docx_key = f"docx_bytes_{idx}"
                            if docx_key in st.session_state:
                                st.markdown("---")
                                st.success("Lettre de motivation prête !")
                                safe_company = str(row['Company']).replace(" ", "_").lower()
                                st.download_button(
                                    label="📥 Télécharger la lettre de motivation (Word .docx)",
                                    data=st.session_state[docx_key],
                                    file_name=f"lettre_motivation_{safe_company}.docx",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"dl_btn_{idx}"
                                )
                        
                        with col2:
                            st.link_button("Voir l'offre", row['Link'])
                            
                            # Sélecteur de statut interactif
                            status_options = ["À postuler", "CV envoyé", "Archivé"]
                            try:
                                current_index = status_options.index(current_status)
                            except ValueError:
                                current_index = 0
                                
                            new_status = st.selectbox(
                                "Modifier le statut", 
                                status_options, 
                                index=current_index, 
                                key=f"status_{idx}"
                            )
                            
                            if new_status != current_status:
                                df.loc[df.index == idx, "Status"] = new_status
                                df.to_csv("job_offers.csv", index=False)
                                st.rerun()
                                
                            st.markdown("---")
                            
                            # Bouton pour déclencher la rédaction et la conversion en Word
                            if st.button("Générer la lettre Word", key=f"btn_letter_{idx}"):
                                with st.spinner("Qwen rédige et formate votre lettre en Word (.docx)..."):
                                    try:
                                        with open("profil_candidat.txt", "r", encoding="utf-8") as f:
                                            profile_text = f.read()
                                    except FileNotFoundError:
                                        profile_text = "Profil non trouvé."
                                        
                                    cv_choice = str(row.get('Recommended_CV', '')).lower()
                                    if "1" in cv_choice or "sante" in cv_choice or "health" in cv_choice:
                                        selected_cv_text = CV_1_TEXT
                                    else:
                                        selected_cv_text = CV_2_TEXT
                                        
                                    # Gestion de la description complète ou du résumé (avec rétrocompatibilité)
                                    full_desc = row.get('Full_Description', '')
                                    if pd.isna(full_desc) or str(full_desc).strip() == "":
                                        texte_offre_pour_lettre = row.get('Summary', '')
                                    else:
                                        texte_offre_pour_lettre = str(full_desc)

                                    generated_text = generate_cover_letter(
                                        job_title=row['Title'],
                                        company=row['Company'],
                                        description=texte_offre_pour_lettre,
                                        recommended_cv_text=selected_cv_text,
                                        candidate_profile=profile_text
                                    )
                                    
                                    # Générer les octets du fichier Word
                                    docx_data = create_docx_from_text(generated_text)
                                    
                                    # Stocker dans le session state
                                    st.session_state[docx_key] = docx_data
                                    st.rerun()
    else:
        st.warning("Aucune offre ne correspond a ces criteres.")