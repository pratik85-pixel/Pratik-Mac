import sys
from api.db.database import SessionLocal
from api.db import schema as db

session = SessionLocal()

# Find user PratikB (or most recent users)
user = session.query(db.User).filter(db.User.username.ilike('%pratikb%')).first()
if not user:
    users = session.query(db.User).order_by(db.User.created_at.desc()).limit(5).all()
    print("No PratikB match. Recent users:")
    for u in users:
        print(f"  id={u.id}  username={u.username}  created={u.created_at}")
    session.close()
    sys.exit(0)

uid = user.id
print(f"=== User: id={uid}  username={user.username}  created={user.created_at} ===\n")

# PPI records
ppi_count = session.query(db.PpiRecord).filter_by(user_id=uid).count()
print(f"PpiRecords total       : {ppi_count}")

# Background windows
bw_count = session.query(db.BackgroundWindow).filter_by(user_id=uid).count()
print(f"BackgroundWindows total: {bw_count}")

# Latest 5 background windows
bws = (session.query(db.BackgroundWindow)
       .filter_by(user_id=uid)
       .order_by(db.BackgroundWindow.window_start.desc())
       .limit(5).all())
if bws:
    print("\nLatest background windows:")
    for bw in bws:
        print(f"  {bw.window_start}  beats={bw.beat_count}  "
              f"median_ppi={bw.median_ppi}  rmssd={bw.rmssd}  context={bw.context}")

# Baseline
baseline = session.query(db.UserBaseline).filter_by(user_id=uid).first()
if baseline:
    print(f"\nBaseline exists:")
    print(f"  resting_hr={baseline.resting_hr}  rmssd_baseline={baseline.rmssd_baseline}")
    print(f"  calibration_days={baseline.calibration_days}  updated_at={baseline.updated_at}")
else:
    print("\nBaseline: NOT YET BUILT")

# Capacity snapshots
cap = (session.query(db.CapacitySnapshot)
       .filter_by(user_id=uid)
       .order_by(db.CapacitySnapshot.snapshot_date.desc())
       .first())
if cap:
    print(f"\nLatest CapacitySnapshot: date={cap.snapshot_date}  "
          f"recovery={cap.recovery_score}  stress={cap.stress_score}")
else:
    print("\nCapacitySnapshot: none yet")

# Daily stress summaries
dss = (session.query(db.DailyStressSummary)
       .filter_by(user_id=uid)
       .order_by(db.DailyStressSummary.summary_date.desc())
       .limit(3).all())
if dss:
    print("\nDailyStressSummaries (latest 3):")
    for d in dss:
        print(f"  {d.summary_date}  balance={d.closing_balance}  "
              f"opening_recovery={d.opening_recovery}  opening_stress={d.opening_stress}")
else:
    print("\nDailyStressSummary: none yet")

session.close()
