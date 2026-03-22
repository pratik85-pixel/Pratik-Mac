import math

floor = 22.0
avg   = 38.0
ceil_ = 65.0

WAKING_MIN   = 960
RECOVERY_MIN = 1440

log_stress   = math.log(avg / floor)
log_recovery = math.log(ceil_ / avg)
ns_stress    = log_stress   * WAKING_MIN
ns_recovery  = log_recovery * RECOVERY_MIN

print(f"log_stress_range         = {log_stress:.4f}")
print(f"log_recovery_range       = {log_recovery:.4f}")
print(f"ns_capacity_stress  (expected) = {ns_stress:.2f}")
print(f"ns_capacity_recovery (expected) = {ns_recovery:.2f}")
print()

stored_stress_cap   = 164.98
stored_recovery_cap = 772.99
print(f"max_possible_suppression (stored) = {stored_stress_cap}")
print(f"ns_capacity_recovery     (stored) = {stored_recovery_cap}")
print()

actual_waking_used = stored_stress_cap / log_stress
print(f"Implied WAKING_MINUTES used = {actual_waking_used:.1f} min = {actual_waking_used/60:.1f} h")
print()

raw_suppression = 161.82
correct_pct = raw_suppression / ns_stress * 100
print(f"Correct stress_pct_raw  = {correct_pct:.2f}% (stored: 98.09%)")
print(f"Overstatement factor    = {98.09 / correct_pct:.2f}x")
print()

recovery_pct = 17.71
correct_net = recovery_pct - correct_pct
print(f"Correct net_balance     = {correct_net:.1f} (stored: -80.4)")
print()

# Check recovery side
actual_recovery_used = stored_recovery_cap / log_recovery
print(f"Implied RECOVERY_MINUTES used = {actual_recovery_used:.1f} min = {actual_recovery_used/60:.1f} h")
print(f"(expected 1440 min = 24h)")
