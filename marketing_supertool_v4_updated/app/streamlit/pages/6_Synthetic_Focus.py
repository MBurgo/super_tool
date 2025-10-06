import streamlit as st, json, pandas as pd
from core.synthetic_focus import evaluate_copy_across_personas
from core.models import Persona
import pathlib

st.title("Synthetic Focus (Standalone)")

pfile = pathlib.Path("data/personas.json")
if not pfile.exists():
    st.warning("No personas found. Import via Personas page.")
    personas = []
else:
    raw = json.loads(pfile.read_text())
    personas = [Persona(**p) for p in raw]

copy_text = st.text_area("Paste copy to test", height=220)
if st.button("🧪 Run 50‑persona test") and copy_text.strip():
    summary, df, fig, clusters = evaluate_copy_across_personas(copy_text, personas[:50] or [])
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df, use_container_width=True, hide_index=True, height=350)
    st.markdown(summary, unsafe_allow_html=True)

    # Excel export
    from io import BytesIO
    def _to_excel(responses: pd.DataFrame, clusters: pd.DataFrame) -> BytesIO:
        out = BytesIO()
        with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
            responses.to_excel(writer, sheet_name="responses", index=False)
            clusters.to_excel(writer, sheet_name="clusters", index=False)
        out.seek(0); return out
    st.download_button("Download results (Excel)", data=_to_excel(df, clusters),
                       file_name="synthetic_focus_results.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
