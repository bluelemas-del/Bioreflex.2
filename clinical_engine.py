class MasterClinicalEngine:
    
    @staticmethod
    def evaluate_hematology(hgb: float, rbc: float, mcv: float, platelets: float = 250.0, gender: str = "female") -> dict:
        is_anemic = (gender == "female" and hgb < 12.0) or (gender == "male" and hgb < 13.0)
        mentzer = round(mcv / rbc, 2) if rbc and rbc > 0 else 0.0

        if is_anemic and mcv < 80.0:
            if mentzer < 13.0:
                return {
                    "panel": "CBC",
                    "indices": {"mentzer": mentzer},
                    "flag": "اشتباه ثلاسيميا صغرى (Thalassemia Minor)",
                    "reflex": "Hb Electrophoresis (HPLC)",
                    "tube_alert": "حفظ أنبوبة EDTA بالثلاجة (2-8°C)",
                    "added_iqd": 35000.0
                }
            else:
                return {
                    "panel": "CBC",
                    "indices": {"mentzer": mentzer},
                    "flag": "اشتباه فقر دم بنقص الحديد (Iron Deficiency)",
                    "reflex": "Serum Ferritin + Iron Profile",
                    "tube_alert": "حفظ أنبوبة المصل في الثلاجة (2-8°C)",
                    "added_iqd": 20000.0
                }
        return {
            "panel": "CBC",
            "indices": {"mentzer": mentzer},
            "flag": "طبيعي / دم ضمن المعدل",
            "reflex": "لا يوجد",
            "tube_alert": "حفظ روتيني",
            "added_iqd": 0.0
        }

    @staticmethod
    def evaluate_liver(ast: float, alt: float, age: int, platelets: float = 250.0) -> dict:
        # حساب Fib-4 = (Age * AST) / (Platelets * sqrt(ALT))
        import math
        fib4 = round((age * ast) / (platelets * math.sqrt(alt)), 2) if (platelets > 0 and alt > 0) else 0.0
        
        if alt > 55.0 or ast > 50.0:
            if fib4 > 2.67:
                return {
                    "panel": "Liver",
                    "indices": {"fib4": fib4},
                    "flag": "اشتباه تليف كبدي متقدم (Advanced Fibrosis Risk)",
                    "reflex": "HBsAg + HCV Ab + Viral Load",
                    "tube_alert": "فصل المصل فوراً وتجميد عينة الاحتياط (-20°C)",
                    "added_iqd": 40000.0
                }
            else:
                return {
                    "panel": "Liver",
                    "indices": {"fib4": fib4},
                    "flag": "ارتفاع أنزيمات الكبد (Elevated Transaminases)",
                    "reflex": "Viral Hepatitis Screening (B & C)",
                    "tube_alert": "حفظ أنبوبة المصل في الثلاجة (2-8°C)",
                    "added_iqd": 25000.0
                }
        return {
            "panel": "Liver",
            "indices": {"fib4": fib4},
            "flag": "طبيعي / وظائف كبد مستقرة",
            "reflex": "لا يوجد",
            "tube_alert": "حفظ روتيني",
            "added_iqd": 0.0
        }

    @staticmethod
    def evaluate_renal(creatinine: float, age: int, gender: str = "female") -> dict:
        # معادلة CKD-EPI المبسطة لتقييم ترشيح الكلى
        kappa = 0.7 if gender == "female" else 0.9
        alpha = -0.241 if gender == "female" else -0.302
        gender_mult = 1.012 if gender == "female" else 1.0
        
        cr_ratio = creatinine / kappa
        egfr = round(142 * (min(cr_ratio, 1.0) ** alpha) * (max(cr_ratio, 1.0) ** -1.200) * (0.9938 ** age) * gender_mult, 1)

        if egfr < 60.0 or creatinine > 1.3:
            return {
                "panel": "Renal",
                "indices": {"egfr": egfr},
                "flag": "قصور كلوي محتمل (Impaired Renal Function)",
                "reflex": "Urine Albumin/Creatinine Ratio (ACR) + Urea",
                "tube_alert": "طلب جمع عينة بول صباحية طازجة للمريض",
                "added_iqd": 20000.0
            }
        return {
            "panel": "Renal",
            "indices": {"egfr": egfr},
            "flag": "طبيعي / وظائف كلوية سليمة",
            "reflex": "لا يوجد",
            "tube_alert": "حفظ روتيني",
            "added_iqd": 0.0
        }

    @staticmethod
    def evaluate_thyroid(tsh: float) -> dict:
        if tsh > 4.5:
            return {
                "panel": "Thyroid",
                "indices": {"tsh": tsh},
                "flag": "قصور درقي مشتبه (Hypothyroidism Reflex)",
                "reflex": "Free T4 (FT4) + Anti-TPO Antibodies",
                "tube_alert": "حفظ المصل مجمد (-20°C) لإكمال قياس الهرمونات",
                "added_iqd": 30000.0
            }
        elif tsh < 0.4:
            return {
                "panel": "Thyroid",
                "indices": {"tsh": tsh},
                "flag": "فرط نشاط درقي مشتبه (Hyperthyroidism Reflex)",
                "reflex": "Free T4 (FT4) + Free T3 (FT3)",
                "tube_alert": "حفظ المصل مجمد (-20°C)",
                "added_iqd": 30000.0
            }
        return {
            "panel": "Thyroid",
            "indices": {"tsh": tsh},
            "flag": "طبيعي / هرمون الغدة الدرقية سليم",
            "reflex": "لا يوجد",
            "tube_alert": "حفظ روتيني",
            "added_iqd": 0.0
        }

    @staticmethod
    def evaluate_metabolic(glucose: float, insulin: float = 10.0) -> dict:
        homa_ir = round((glucose * insulin) / 405.0, 2)
        if glucose >= 126.0 or homa_ir > 2.5:
            return {
                "panel": "Metabolic",
                "indices": {"homa_ir": homa_ir},
                "flag": "مقاومة إنسولين واشتباه سكري (Insulin Resistance / T2D)",
                "reflex": "HbA1c + Lipid Profile Complete",
                "tube_alert": "حفظ أنبوبة فلوريد الصوديوم وأنبوبة المصل بالثلاجة",
                "added_iqd": 25000.0
            }
        return {
            "panel": "Metabolic",
            "indices": {"homa_ir": homa_ir},
            "flag": "طبيعي / مؤشرات الأيض مستقرة",
            "reflex": "لا يوجد",
            "tube_alert": "حفظ روتيني",
            "added_iqd": 0.0
        }