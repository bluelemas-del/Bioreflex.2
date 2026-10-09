import os
import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(current_dir, "nhanes_raw")

print("[1/3] جاري قراءة ملفات NHANES الخام...")
cbc = pd.read_sas(os.path.join(data_dir, "CBC_J.xpt"))
demo = pd.read_sas(os.path.join(data_dir, "DEMO_J.xpt"))
biopro = pd.read_sas(os.path.join(data_dir, "BIOPRO_J.xpt"))
glu = pd.read_sas(os.path.join(data_dir, "GLU_J.xpt"))
ins = pd.read_sas(os.path.join(data_dir, "INS_J.xpt"))
crp = pd.read_sas(os.path.join(data_dir, "HSCRP_J.xpt"))

print("[2/3] جاري معالجة وتوحيد الأعمدة السريرية بدقة...")

# 1. الديموغرافيا
df_demo = demo[["SEQN", "RIAGENDR", "RIDAGEYR"]].copy()
df_demo.rename(columns={"RIAGENDR": "gender_code", "RIDAGEYR": "age"}, inplace=True)
df_demo["gender"] = df_demo["gender_code"].map({1.0: "male", 2.0: "female"})
df_demo.drop(columns=["gender_code"], inplace=True)

# 2. صورة الدم الكاملة CBC
df_cbc = cbc[["SEQN", "LBXWBCSI", "LBXRBCSI", "LBXHGB", "LBXMCVSI", "LBXPLTSI"]].copy()
df_cbc.rename(columns={
    "LBXWBCSI": "wbc",
    "LBXRBCSI": "rbc",
    "LBXHGB": "hgb",
    "LBXMCVSI": "mcv",
    "LBXPLTSI": "platelets"
}, inplace=True)

# 3. الكيمياء الحيوية (استخراج مرن للأعمدة المتطابقة)
biopro_cols = {"SEQN": "SEQN"}
for c in biopro.columns:
    if "SAS" in c:  # AST
        biopro_cols[c] = "ast"
    elif "SAT" in c:  # ALT
        biopro_cols[c] = "alt"
    elif "SCR" in c:  # Creatinine
        biopro_cols[c] = "creatinine"

df_biopro = biopro[list(biopro_cols.keys())].copy().rename(columns=biopro_cols)

# 4. السكر والأنسولين
df_glu = glu[["SEQN", "LBXGLU"]].copy().rename(columns={"LBXGLU": "fasting_glucose"})
df_ins = ins[["SEQN", "LBXIN"]].copy().rename(columns={"LBXIN": "fasting_insulin"})

# 5. بروتين الالتهاب hs-CRP
df_crp = crp[["SEQN", "LBXHSCRP"]].copy().rename(columns={"LBXHSCRP": "crp"})

# دمج السجلات
merged_df = df_demo.merge(df_cbc, on="SEQN", how="inner")
merged_df = merged_df.merge(df_biopro, on="SEQN", how="left")
merged_df = merged_df.merge(df_glu, on="SEQN", how="left")
merged_df = merged_df.merge(df_ins, on="SEQN", how="left")
merged_df = merged_df.merge(df_crp, on="SEQN", how="left")

# ترقيم وطني موحد للمرضى
merged_df.rename(columns={"SEQN": "patient_id"}, inplace=True)
merged_df["patient_id"] = "IQ-LAB-" + merged_df["patient_id"].astype(int).astype(str)

# فلترة العينات المكتملة مخبرياً في الـ CBC
cleaned_df = merged_df.dropna(subset=["hgb", "rbc", "mcv"]).copy()
cleaned_df = cleaned_df[cleaned_df["rbc"] > 0]

output_csv = os.path.join(current_dir, "iraq_lab_cohort.csv")
cleaned_df.to_csv(output_csv, index=False)

print(f"[3/3] تم بنجاح! تم استخراج وحفظ {len(cleaned_df):,} مريض حقيقي في: {output_csv}")