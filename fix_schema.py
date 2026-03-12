with open("api/db/schema.py", "r") as f:
    text = f.read()

import re
text = re.sub(r'# ── Tagging & Context ─────────────────────────────────────────────────────────.*', '', text, flags=re.DOTALL)

with open("api/db/schema.py", "w") as f:
    f.write(text.strip() + "\n\n")
    f.write('''# ── Tagging & Context ─────────────────────────────────────────────────────────

class ActivityCatalog(Base):
    __tablename__ = "activity_catalog"

    slug = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    intensity = Column(String(50), nullable=False)
    icon = Column(String(10), nullable=False)
    description = Column(String(200), nullable=True)

class Tag(Base):
    """Explicit mapping from a timeframe to an activity, typically linked to a Stress or Recovery Window."""
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    stress_window_id = Column(UUID(as_uuid=True), ForeignKey("stress_windows.id", ondelete="SET NULL"), nullable=True)
    recovery_window_id = Column(UUID(as_uuid=True), ForeignKey("recovery_windows.id", ondelete="SET NULL"), nullable=True)
    
    activity_slug = Column(String(50), ForeignKey("activity_catalog.slug"), nullable=False)
    
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    
    source = Column(String(50), nullable=False, default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
''')
