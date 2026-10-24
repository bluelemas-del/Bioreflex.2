import os
import io
import urllib.parse
import pandas as pd
import uvicorn
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, Patient, LabOrder, ClinicalResult
from clinical_engine import MasterClinicalEngine

app = FastAPI(title="BioReflex Pro - Clinical LIMS")

current_dir = os.path.dirname(os.path.abspath(__file__))
templates_dir = os.path.join(current_dir, "templates")
os.makedirs(templates_dir, exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 1. شاشة الاستقبال وقيد المرضى
@app.get("/", response_class=HTMLResponse)
def home_reception(request: Request, db: Session = Depends(get_db)):
    recent_orders = db.query(LabOrder).order_by(LabOrder.id.desc()).limit(20).all()
    total_patients = db.query(Patient).count()
    next_patient_id = f"IQ-{total_patients + 1001}"
    return templates.TemplateResponse(
        request=request,
        name="reception.html",
        context={
            "orders": recent_orders,
            "next_patient_id": next_patient_id,
            "active_page": "reception"
        }
    )

@app.post("/register-patient")
def register_patient(
    patient_id: str = Form(...),
    name: str = Form(...),
    age: int = Form(...),
    gender: str = Form(...),
    tests: list[str] = Form(...),
    db: Session = Depends(get_db)
):
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if not patient:
        patient = Patient(patient_id=patient_id, name=name, age=age, gender=gender)
        db.add(patient)
        db.flush()

    prices = {"CBC": 10000.0, "Liver": 15000.0, "Renal": 15000.0, "Metabolic": 20000.0, "Thyroid": 15000.0}
    base_cost = sum([prices.get(t, 10000.0) for t in tests])

    order = LabOrder(
        order_code=f"ORD-{db.query(LabOrder).count() + 1001}",
        patient_id=patient.id,
        base_price=base_cost,
        add_on_revenue=0.0,
        total_revenue=base_cost,
        status="Pending"
    )
    db.add(order)
    db.commit()
    return RedirectResponse(url="/", status_code=303)

# 2. إدخال وتطبيق نتائج الفحوصات السريرية في المختبر
@app.post("/submit-lab-test")
def submit_lab_test(
    order_id: int = Form(...),
    panel: str = Form(...),
    val1: float = Form(...),
    val2: float = Form(None),
    val3: float = Form(None),
    db: Session = Depends(get_db)
):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        return RedirectResponse(url="/lab-console", status_code=303)

    patient = order.patient
    eval_res = {}

    if panel == "CBC":
        eval_res = MasterClinicalEngine.evaluate_hematology(hgb=val1, rbc=(val2 or 4.5), mcv=(val3 or 80.0), gender=patient.gender)
        calc_idx = eval_res["indices"].get("mentzer")
    elif panel == "Liver":
        eval_res = MasterClinicalEngine.evaluate_liver(ast=val1, alt=(val2 or 30.0), age=patient.age)
        calc_idx = eval_res["indices"].get("fib4")
    elif panel == "Renal":
        eval_res = MasterClinicalEngine.evaluate_renal(creatinine=val1, age=patient.age, gender=patient.gender)
        calc_idx = eval_res["indices"].get("egfr")
    elif panel == "Thyroid":
        eval_res = MasterClinicalEngine.evaluate_thyroid(tsh=val1)
        calc_idx = eval_res["indices"].get("tsh")
    else:  # Metabolic
        eval_res = MasterClinicalEngine.evaluate_metabolic(glucose=val1, insulin=(val2 or 10.0))
        calc_idx = eval_res["indices"].get("homa_ir")

    order.status = "Completed"
    order.add_on_revenue = eval_res["added_iqd"]
    order.total_revenue = order.base_price + eval_res["added_iqd"]

    result = db.query(ClinicalResult).filter(ClinicalResult.order_id == order.id).first()
    if not result:
        result = ClinicalResult(order_id=order.id)
        db.add(result)

    result.panel_type = panel
    result.clinical_flag = eval_res["flag"]
    result.reflex_order = eval_res["reflex"]
    result.tube_alert = eval_res["tube_alert"]
    result.added_value_iqd = eval_res["added_iqd"]

    if panel == "CBC":
        result.hgb, result.rbc, result.mcv = val1, val2, val3
        result.mentzer_index = calc_idx
    elif panel == "Liver":
        result.ast, result.alt = val1, val2
        result.fib4_index = calc_idx
    elif panel == "Renal":
        result.creatinine = val1
        result.egfr_val = calc_idx
    elif panel == "Thyroid":
        result.tsh = val1
    elif panel == "Metabolic":
        result.glucose, result.insulin = val1, val2
        result.homa_ir = calc_idx

    db.commit()
    return RedirectResponse(url="/lab-console", status_code=303)

# 3. شاشة الفرز المخبري و Reflex
@app.get("/lab-console", response_class=HTMLResponse)
def lab_console_page(request: Request, db: Session = Depends(get_db)):
    results = db.query(ClinicalResult).order_by(ClinicalResult.id.desc()).limit(30).all()
    pending_orders = db.query(LabOrder).filter(LabOrder.status == "Pending").order_by(LabOrder.id.desc()).limit(15).all()
    return templates.TemplateResponse(
        request=request,
        name="lab_console.html",
        context={
            "results": results,
            "pending_orders": pending_orders,
            "active_page": "lab_console"
        }
    )

# 4. شاشة استيراد ملفات العينات
@app.get("/batch-upload", response_class=HTMLResponse)
@app.get("/batch_upload", response_class=HTMLResponse)
def batch_upload_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="batch_upload.html",
        context={"active_page": "batch_upload"}
    )

@app.post("/process-batch")
async def process_batch(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = await file.read()
    if file.filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(contents))
    else:
        df = pd.read_excel(io.BytesIO(contents))

    for _, row in df.iterrows():
        p_id = str(row.get("patient_id", f"IQ-BATCH-{db.query(Patient).count()+1}"))
        patient = db.query(Patient).filter(Patient.patient_id == p_id).first()
        if not patient:
            patient = Patient(
                patient_id=p_id,
                name=str(row.get("name", "مريض استيراد")),
                age=int(row.get("age", 35)),
                gender=str(row.get("gender", "female"))
            )
            db.add(patient)
            db.flush()

        order = LabOrder(
            order_code=f"ORD-{db.query(LabOrder).count() + 1001}",
            patient_id=patient.id,
            base_price=10000.0,
            status="Completed"
        )
        db.add(order)
        db.flush()

        hgb_val = float(row["hgb"]) if ("hgb" in row and pd.notna(row["hgb"])) else 13.0
        rbc_val = float(row["rbc"]) if ("rbc" in row and pd.notna(row["rbc"])) else 4.5
        mcv_val = float(row["mcv"]) if ("mcv" in row and pd.notna(row["mcv"])) else 85.0
        plt_val = float(row["platelets"]) if ("platelets" in row and pd.notna(row["platelets"])) else 250.0

        eval_res = MasterClinicalEngine.evaluate_hematology(hgb=hgb_val, rbc=rbc_val, mcv=mcv_val, platelets=plt_val, gender=patient.gender)

        order.add_on_revenue = eval_res["added_iqd"]
        order.total_revenue = order.base_price + eval_res["added_iqd"]

        res = ClinicalResult(
            order_id=order.id,
            panel_type="CBC",
            hgb=hgb_val,
            rbc=rbc_val,
            mcv=mcv_val,
            platelets=plt_val,
            mentzer_index=eval_res["indices"].get("mentzer"),
            clinical_flag=eval_res["flag"],
            reflex_order=eval_res["reflex"],
            tube_alert=eval_res["tube_alert"],
            added_value_iqd=eval_res["added_iqd"]
        )
        db.add(res)

    db.commit()
    return RedirectResponse(url="/lab-console", status_code=303)

# 5. لوحة الإدارة والأرباح
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    all_orders = db.query(LabOrder).all()
    all_results = db.query(ClinicalResult).all()

    total_orders = len(all_orders)
    total_base_rev = sum([o.base_price for o in all_orders if o.base_price])
    total_addon_rev = sum([o.add_on_revenue for o in all_orders if o.add_on_revenue])
    total_rev = total_base_rev + total_addon_rev

    critical_cases = [r for r in all_results if (r.hgb and r.hgb < 8.0) or (r.creatinine and r.creatinine > 3.0)]
    thalassemia_count = len([r for r in all_results if r.clinical_flag and "ثلاسيميا" in r.clinical_flag])
    iron_def_count = len([r for r in all_results if r.clinical_flag and "حديد" in r.clinical_flag])
    normal_count = len([r for r in all_results if r.clinical_flag and "طبيعي" in r.clinical_flag])

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "total_orders": total_orders,
            "total_base_rev": total_base_rev,
            "total_addon_rev": total_addon_rev,
            "total_rev": total_rev,
            "critical_count": len(critical_cases),
            "critical_cases": critical_cases[:5],
            "thalassemia_count": thalassemia_count,
            "iron_def_count": iron_def_count,
            "normal_count": normal_count,
            "active_page": "dashboard"
        }
    )

# 6. التقرير الطبي ومشاركة WhatsApp
@app.get("/report/{order_id}", response_class=HTMLResponse)
def print_report(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order:
        return HTMLResponse("الطلب غير موجود", status_code=404)

    patient = order.patient
    res = order.results

    tests_detail = []
    if res:
        p_type = res.panel_type or "CBC"
        if p_type == "CBC":
            hgb_val = res.hgb or 0.0
            h_stat = "نقص حاد" if hgb_val < 7.0 else ("نقص ملحوظ" if hgb_val < 12.0 else "ضمن المعدل الطبيعي")
            h_color = "text-rose-600 bg-rose-50" if hgb_val < 12.0 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "Hemoglobin (Hgb)", "val": hgb_val, "ref": "12.0 - 16.0", "unit": "g/dL", "status": h_stat, "color": h_color})

            rbc_val = res.rbc or 0.0
            r_stat = "نقص ملحوظ" if rbc_val < 3.5 else "ضمن المعدل الطبيعي"
            r_color = "text-amber-600 bg-amber-50" if rbc_val < 3.5 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "RBC Count", "val": rbc_val, "ref": "4.0 - 5.5", "unit": "10^12/L", "status": r_stat, "color": r_color})

            mcv_val = res.mcv or 0.0
            m_stat = "صغر حجم كريات (Microcytic)" if mcv_val < 80.0 else "ضمن المعدل الطبيعي"
            m_color = "text-rose-600 bg-rose-50" if mcv_val < 80.0 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "MCV", "val": mcv_val, "ref": "80.0 - 100.0", "unit": "fL", "status": m_stat, "color": m_color})

            m_idx = res.mentzer_index or 0.0
            mi_stat = "اشتباه ثلاسيميا صغرى" if m_idx < 13.0 else "اشتباه فقر دم بنقص الحديد"
            tests_detail.append({"name": "Mentzer Index", "val": m_idx, "ref": "< 13.0", "unit": "Ratio", "status": mi_stat, "color": "text-purple-700 bg-purple-50"})

        elif p_type == "Liver":
            ast_v = res.ast or 0.0
            ast_st = "ارتفاع حاد" if ast_v > 100 else ("ارتفاع خفيف" if ast_v > 40 else "طبيعي")
            ast_c = "text-rose-600 bg-rose-50" if ast_v > 40 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "AST (SGOT)", "val": ast_v, "ref": "10.0 - 40.0", "unit": "U/L", "status": ast_st, "color": ast_c})

            alt_v = res.alt or 0.0
            alt_st = "ارتفاع حاد" if alt_v > 100 else ("ارتفاع خفيف" if alt_v > 45 else "طبيعي")
            alt_c = "text-rose-600 bg-rose-50" if alt_v > 45 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "ALT (SGPT)", "val": alt_v, "ref": "10.0 - 45.0", "unit": "U/L", "status": alt_st, "color": alt_c})

            fib_v = res.fib4_index or 0.0
            fib_st = "خطورة تليف مرتفعة" if fib_v > 2.67 else "ضمن النطاق الآمن"
            fib_c = "text-rose-600 bg-rose-50" if fib_v > 2.67 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "FIB-4 Score", "val": fib_v, "ref": "< 1.45", "unit": "Score", "status": fib_st, "color": fib_c})

        elif p_type == "Renal":
            cr_v = res.creatinine or 0.0
            cr_st = "ارتفاع حاد" if cr_v > 2.0 else ("ارتفاع طفيف" if cr_v > 1.2 else "طبيعي")
            cr_c = "text-rose-600 bg-rose-50" if cr_v > 1.2 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "Serum Creatinine", "val": cr_v, "ref": "0.6 - 1.2", "unit": "mg/dL", "status": cr_st, "color": cr_c})

            egfr_v = res.egfr_val or 0.0
            egfr_st = "قصور كلوي ملحوظ" if egfr_v < 60 else "وظائف كلوية جيدة"
            egfr_c = "text-rose-600 bg-rose-50" if egfr_v < 60 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "eGFR (CKD-EPI)", "val": egfr_v, "ref": "> 90.0", "unit": "mL/min/1.73m²", "status": egfr_st, "color": egfr_c})

        elif p_type == "Thyroid":
            tsh_v = res.tsh or 0.0
            tsh_st = "ارتفاع ملحوظ (قصور)" if tsh_v > 4.5 else ("انخفاض (فرط نشاط)" if tsh_v < 0.4 else "طبيعي")
            tsh_c = "text-rose-600 bg-rose-50" if (tsh_v > 4.5 or tsh_v < 0.4) else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "TSH", "val": tsh_v, "ref": "0.45 - 4.50", "unit": "mIU/L", "status": tsh_st, "color": tsh_c})

        elif p_type == "Metabolic":
            glu_v = res.glucose or 0.0
            glu_st = "ارتفاع ملحوظ (سكري)" if glu_v >= 126 else ("مرحلة ما قبل السكري" if glu_v >= 100 else "طبيعي")
            glu_c = "text-rose-600 bg-rose-50" if glu_v >= 100 else "text-emerald-600 bg-emerald-50"
            tests_detail.append({"name": "Fasting Glucose", "val": glu_v, "ref": "70 - 99", "unit": "mg/dL", "status": glu_st, "color": glu_c})

    p_name = patient.name if patient else "المراجع"
    order_num = order.order_code
    diag = res.clinical_flag if (res and res.clinical_flag) else "طبيعي"
    refl = res.reflex_order if (res and res.reflex_order) else "لا يوجد"
    tube = res.tube_alert if (res and res.tube_alert) else "حفظ روتيني"
    added_cost = f"{res.added_value_iqd:,.0f} د.ع" if (res and res.added_value_iqd > 0) else "مشمول"

    base_host = "http://127.0.0.1:8000"
    report_link = f"{base_host}/report/{order_id}"
    approve_link = f"{base_host}/patient-response/{order_id}?action=approve"
    reject_link = f"{base_host}/patient-response/{order_id}?action=reject"

    wa_msg = (
        f"*مختبر BioReflex السريري التخصصي*\n"
        f"المراجع: {p_name}\n"
        f"رقم الوصل: {order_num}\n"
        f"------------------------------\n"
        f"*التقييم السريري الأولي:*\n{diag}\n\n"
        f"*فحص Reflex الموصى به:*\n[{refl}]\n"
        f"*السبب:* دقة التشخيص وتفادي العلاج غير المناسب.\n"
        f"*التكلفة الإضافية:* {added_cost}\n\n"
        f"*حالة العينة بالمختبر:*\n({tube}) - تم الاحتفاظ بعينتكم ولن تحتاجوا لسحب دم جديد.\n"
        f"------------------------------\n"
        f"*يرجى تأكيد قراركم بالضغط على أحد الروابط:*\n\n"
        f"*أوافق على إجراء الفحص:*\n{approve_link}\n\n"
        f"*أرفض الفحص الإضافي:*\n{reject_link}\n\n"
        f"*عرض التقرير الطبي كاملاً:*\n{report_link}"
    )

    wa_link = "https://wa.me/?text=" + urllib.parse.quote(wa_msg, safe="")

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "order": order,
            "patient": patient,
            "res": res,
            "tests_detail": tests_detail,
            "wa_link": wa_link,
            "active_page": "lab_console"
        }
    )

# 7. مسار استقبال قرار المريض من الرابط الفوري
@app.get("/patient-response/{order_id}", response_class=HTMLResponse)
def patient_response_action(order_id: int, action: str, db: Session = Depends(get_db)):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if not order or not order.results:
        return HTMLResponse("الطلب غير موجود", status_code=404)

    if action == "approve":
        status_text = "تمت موافقة المريض بنجاح"
        clean_order = order.results.reflex_order.split(" [")[0]
        order.results.reflex_order = f"{clean_order} [موافقة مؤكدة من المريض]"
        order.results.clinical_flag = f"{order.results.clinical_flag} (مطلوب مباشرة التحليل)"
        msg_header = "شكراً لك، تم استلام موافقتك!"
        msg_body = "تم إشعار كادر المختبر فوراً للبدء بالفحص الارتكاسي من عينتك المحفوظة دون الحاجة لحضورك مجدداً."
    else:
        status_text = "تم تسجيل رفض المريض"
        clean_order = order.results.reflex_order.split(" [")[0]
        order.results.reflex_order = f"{clean_order} [المريض رفض الفحص]"
        msg_header = "تم تسجيل قرارك"
        msg_body = "تم الاكتفاء بنتائج الفحص الأولي الحالية وإغلاق الملف."

    db.commit()

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
      <meta charset="UTF-8">
      <title>تأكيد القرار - مختبر BioReflex</title>
      <script src="https://cdn.tailwindcss.com"></script>
      <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@500;700&display=swap" rel="stylesheet">
      <style>body {{ font-family: 'Tajawal', sans-serif; }}</style>
    </head>
    <body class="bg-slate-900 text-slate-100 flex items-center justify-center min-h-screen p-4">
      <div class="bg-slate-800 border border-slate-700 max-w-md w-full p-6 rounded-2xl shadow-xl text-center space-y-4">
        <h2 class="text-xl font-bold text-teal-300">{msg_header}</h2>
        <p class="text-sm text-slate-300">{msg_body}</p>
        <div class="p-3 bg-slate-900 rounded-xl text-xs text-slate-400 font-mono">
          حالة الوصل ({order.order_code}): <span class="text-white font-bold">{status_text}</span>
        </div>
        <a href="/report/{order_id}" class="inline-block bg-teal-500 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs">عرض التقرير الحالي</a>
      </div>
    </body>
    </html>
    """)

# 8. مسار تسجيل الموافقة/الرفض المباشر من واجهة التقرير
@app.post("/update-patient-consent")
def update_patient_consent(order_id: int = Form(...), consent: str = Form(...), db: Session = Depends(get_db)):
    order = db.query(LabOrder).filter(LabOrder.id == order_id).first()
    if order and order.results:
        clean_order = order.results.reflex_order.split(" [")[0]
        order.results.reflex_order = f"{clean_order} [{consent}]"
        db.commit()
    return RedirectResponse(url=f"/report/{order_id}", status_code=303)

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)