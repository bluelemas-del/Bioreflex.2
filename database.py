import os
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

DB_FILE = "bioreflex_local.db"
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    orders = relationship("LabOrder", back_populates="patient")

class LabOrder(Base):
    __tablename__ = "lab_orders"
    id = Column(Integer, primary_key=True, index=True)
    order_code = Column(String, unique=True, index=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    base_price = Column(Float, default=10000.0)
    add_on_revenue = Column(Float, default=0.0)
    total_revenue = Column(Float, default=10000.0)
    status = Column(String, default="Pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    patient = relationship("Patient", back_populates="orders")
    results = relationship("ClinicalResult", back_populates="order", uselist=False)

class ClinicalResult(Base):
    __tablename__ = "clinical_results"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("lab_orders.id"), nullable=False)
    panel_type = Column(String, default="CBC")
    
    # مسار الدم (Hematology)
    hgb = Column(Float, nullable=True)
    rbc = Column(Float, nullable=True)
    mcv = Column(Float, nullable=True)
    wbc = Column(Float, nullable=True)
    platelets = Column(Float, nullable=True)
    mentzer_index = Column(Float, nullable=True)
    
    # مسار الكبد (Hepatic)
    ast = Column(Float, nullable=True)
    alt = Column(Float, nullable=True)
    fib4_index = Column(Float, nullable=True)
    
    # مسار الكلى (Renal)
    creatinine = Column(Float, nullable=True)
    egfr_val = Column(Float, nullable=True)
    
    # مسار السكر والأيض (Metabolic)
    glucose = Column(Float, nullable=True)
    insulin = Column(Float, nullable=True)
    homa_ir = Column(Float, nullable=True)
    
    # مسار الغدة الدرقية (Thyroid)
    tsh = Column(Float, nullable=True)
    
    # مخرجات المحرك السريري
    clinical_flag = Column(String, nullable=True)
    reflex_order = Column(String, default="لا يوجد")
    tube_alert = Column(String, default="حفظ روتيني")
    added_value_iqd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("LabOrder", back_populates="results")

Base.metadata.create_all(bind=engine)