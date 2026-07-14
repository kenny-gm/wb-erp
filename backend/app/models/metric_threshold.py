"""
指标阈值设置模型
"""
from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean
from sqlalchemy.sql import func
from app.database import Base


class MetricThreshold(Base):
    """指标阈值配置表"""
    __tablename__ = "metric_thresholds"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    metric_name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(50), nullable=False)
    warning_threshold = Column(Float, nullable=False)
    danger_threshold = Column(Float, nullable=True)
    comparison = Column(String(20), default="less_than")
    good_color = Column(String(20), default="#67c23a")
    warning_color = Column(String(20), default="#e6a23c")
    danger_color = Column(String(20), default="#f56c6c")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
