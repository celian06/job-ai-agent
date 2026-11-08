import streamlit as st
import pandas as pd

# Page configuration
st.set_page_config(page_title="AI Job Agent", layout="wide")
st.title("AI Job Agent - Tableau de bord")

# Data loading function
@st.cache_data(ttl=10)
def load_data():
    try:
        return pd.read_csv("job_offers.csv")
    except FileNotFoundError:
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.info("Aucune offre n'a encore ete trouvee.")
else:
    st.sidebar.header("Filtres")
    
    # Handle legacy CSV files that do not have the 'Site' column yet
    if "Site" not in df.columns:
        df["Site"] = "LinkedIn / Indeed"
    
    df["Site"] = df["Site"].fillna("Other")
    
    # Filters setup
    cv_options = df["Recommended_CV"].dropna().unique().tolist()
    selected_cvs = st.sidebar.multiselect("CV Recommande", cv_options, default=cv_options)
    
    min_score = st.sidebar.slider("Score minimum", 65, 100, 65)
    
    phd_only = st.sidebar.checkbox("[THESE] Uniquement les offres de these", value=False)
    
    # Apply filters
    mask = (df["Recommended_CV"].isin(selected_cvs)) & (df["Score"] >= min_score)
    if phd_only and "Is_PhD" in df.columns:
        mask = mask & (df["Is_PhD"] == True)
        
    filtered_df = df[mask].sort_values(by="Score", ascending=False)
    
    st.metric("Offres correspondantes", len(filtered_df))
    
    # Extract unique sites to create tabs
    available_sites = filtered_df["Site"].unique().tolist()
    
    if available_sites:
        # Create Streamlit tabs dynamically based on found sites
        tabs = st.tabs(available_sites)
        
        # Populate each tab with its specific job offers
        for index, site_name in enumerate(available_sites):
            with tabs[index]:
                site_df = filtered_df[filtered_df["Site"] == site_name]
                
                for idx, row in site_df.iterrows():
                    badge = "[THESE] " if row.get("Is_PhD", False) else ""
                    expander_title = f"[{row['Score']}/100] {badge}{row['Title']} chez {row['Company']}"
                    
                    with st.expander(expander_title):
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.markdown(f"**CV Recommande :** {row['Recommended_CV']} (en {row.get('Language_Recommendation', 'FR')})")
                            st.markdown(f"**Resume de l'offre :** {row.get('Summary', 'Non disponible')}")
                            st.markdown(f"**Motif de l'IA :** {row['Reason']}")
                        
                        with col2:
                            st.link_button("Voir l'offre", row['Link'])
    else:
        st.warning("Aucune offre ne correspond a ces criteres.")