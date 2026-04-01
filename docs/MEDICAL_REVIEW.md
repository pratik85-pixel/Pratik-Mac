# ZenFlow Verity — Scientific & Medical Foundations
### Prepared for medical expert review — March 2026

---

## What This Product Does

ZenFlow Verity is a holistic AI-powered nervous system coach. It uses a Polar Verity Sense optical armband to passively monitor autonomic nervous system (ANS) health around the clock, then uses that data to drive a personalised AI coach that tells the user exactly what to do — and what not to do — at every point in the day.

This goes far beyond breathing exercises. Based on live and historical ANS data, the AI coach makes decisions and recommendations across the full arc of daily life:

- **Recovery and rest** — when to stop, when to sleep early, when to take a recovery day
- **Exercise timing and type** — whether to train hard, train easy, or not train at all today based on ANS readiness; what kind of workout is appropriate (high-intensity vs restorative)
- **Stress load management** — flagging when the user's system is already under load and certain decisions (late meeting, alcohol, skipping sleep) will compound it
- **Training sessions** — guided resonance frequency breathing at biologically optimal moments, not on a calendar schedule
- **Performance windows** — identifying when the nervous system is primed and directing high-stakes work to those windows
- **Lifestyle correlation** — over weeks, connecting ANS patterns to specific behaviours (caffeine timing, alcohol, sleep debt, exercise type) so the coaching becomes increasingly individualised

The underlying measurement system tracks ANS health continuously. The AI coach is the intelligence layer that turns that measurement into specific, actionable daily guidance — the way a sports performance coach would look at an athlete's recovery data and say "don't train today, here's why, here's what to do instead."

The core scientific claim is: **the autonomic nervous system is the common substrate beneath stress reactivity, exercise recovery, cognitive performance, and emotional regulation — and it is both measurable and trainable.** ZenFlow provides the measurement, the training, and the proof that it's working.

---

## The Full Data Chain

```
RAW SENSOR DATA
      ↓
COMPUTED SIGNAL METRICS
      ↓
5 INDICATORS OF NS HEALTH
      ↓
3 USER-FACING SCORES
```

---

## Layer 1 — Raw Sensor Data

The Polar Verity Sense streams the following via BLE (Bluetooth Low Energy):

| Stream | Rate | Description |
|---|---|---|
| **PPI** (Peak-to-Peak Interval) | Event-driven (~1 Hz) | Time in milliseconds between successive optical peaks — the armband equivalent of RR intervals from an ECG |
| **PPG raw** | 135 Hz, 3-channel (Red, IR, Green) | Raw photoplethysmography signal from which PPI is derived and from which additional metrics can be extracted |
| **HR** | 1 Hz | Processed heart rate in BPM |
| **Accelerometer** | 52 Hz, 3-axis | Arm movement (used for motion artefact flagging) |
| **Gyroscope** | 52 Hz | Arm rotation (used for restlessness scoring) |

**Note on PPI vs RR:** Optical PPG introduces slightly more beat-to-beat timing noise than ECG (~5–8 ms vs ~1 ms). This is acceptable for HRV analysis at rest, but the system validates signal quality continuously and discards windows that don't meet a minimum quality standard. All HRV-derived claims depend on the optical signal remaining clean under real-world conditions.

---

## Layer 2 — Computed Signal Metrics

All of the following are derived from the PPI stream (and PPG raw where noted):

### From PPI — Time Domain
| Metric | Calculation | What it represents |
|---|---|---|
| **RMSSD** | √( mean of squared successive PPI differences ) | Beat-to-beat variability. The primary index of cardiac vagal tone. Preferred over SDNN for short recordings. |
| **SDNN** | Standard deviation of all PPI values in a window | Total HRV — captures both sympathetic and parasympathetic contributions |
| **pNN50** | % of successive beats differing by >50 ms | Parasympathetic proxy, less sensitive than RMSSD at lower HRV ranges |
| **Mean HR** | 60,000 / mean(PPI) | Resting heart rate — corroborating signal for stress/recovery |

### From PPI — Frequency Domain
The PPI sequence is converted into a frequency spectrum, revealing how much of the heart rate variability is occurring at different rhythms:

| Band | Range | Interpretation |
|---|---|---|
| **LF power** | 0.04–0.15 Hz | Mixed sympathetic + parasympathetic activity; includes baroreflex contributions |
| **HF power** | 0.15–0.40 Hz | Primarily parasympathetic; tracks with breathing frequency |
| **LF/HF ratio** | LF ÷ HF | Directional index of sympathovagal balance (contested in literature — treated as a trend signal, not an absolute measure) |
| **RSA amplitude** | Power at ~0.1 Hz | Strength of the heart rhythm oscillation produced by slow diaphragmatic breathing |
| **RSA coherence score** | Correlation measure at the breathing frequency | How tightly the heart is locked to the breathing rhythm — the primary in-session training metric |

### From PPG Raw
| Metric | Calculation | What it represents |
|---|---|---|
| **Perfusion Index (PI)** | AC amplitude ÷ DC amplitude of PPG signal | Peripheral vascular tone. Drops during sympathetic activation (vasoconstriction). Rises with parasympathetic recovery. |
| **PAV** (Pulse Amplitude Variation) | Respiratory-linked modulation of PPG peak amplitude | Alternative/supplementary breath signal — under validation |

---

## Layer 3 — The 5 Indicators of Nervous System Health

The raw metrics from Layer 2 are not presented to the user directly — they are combined into five higher-level indicators, each of which answers a specific clinical question about the state of the autonomic nervous system. Together, they provide a complete picture: what the nervous system looks like at rest, how it responds under pressure, how it recovers, whether it can be trained, and whether the peripheral vasculature confirms what the heart is reporting.

Each indicator is always evaluated relative to that individual's own personal baseline — not against a population average. This is deliberate: ANS metrics vary enormously between individuals, and labelling someone as "abnormal" against a population norm would be both clinically misleading and counterproductive for a wellness product.

---

### 1. Resting Vagal Tone
**The question it answers:** How strong is your parasympathetic nervous system when you are calm?

**Clinical significance:** Resting vagal tone is the foundational indicator — the floor everything else is built on. A well-trained system shows consistently high resting vagal tone. A system under chronic stress shows suppressed tone even at rest, before any stressor arrives. It is associated in the literature with stress tolerance, cardiovascular health, emotional regulation, and immune function.

**What it looks like before vs after training:** Users typically start with a morning reading that is flat and low-variance day-to-day. After 6–8 weeks of consistent training, resting vagal tone rises and shows healthy ultradian variation — higher in the morning, lower in the late afternoon, recovering overnight. This pattern itself signals a healthier, more adaptive ANS.

**Coaching use:** Determines the "Resilience" score baseline. Also drives the morning briefing — "your system is running low today" vs "your system is primed."

**Reference:** Thayer & Lane (2009) — vagal tone as a marker of self-regulatory capacity and health.

---

### 2. Sympathetic Reactivity
**The question it answers:** When something stressful happens, how hard and fast does your nervous system respond?

**Clinical significance:** The size and speed of an ANS stress response is independent of resting vagal tone. A person can have healthy resting HRV but overreact violently to minor stressors — this is the physiological substrate of what people call being "easily triggered" or "thin-skinned." Conversely, a well-trained ANS shows a measured, proportionate response rather than an outsized one. This indicator captures the *magnitude* and *speed* of the sympathetic shift when a stress event is detected.

**What it looks like before vs after training:** Early on, stress events are sharp and steep. After training, the same physiological stressors produce shallower responses — the nervous system has learned not to overreact. This is one of the clearest objective correlates of the user's subjective experience of "feeling less reactive."

**Coaching use:** Feeds into the stress event detection system. Also used to advise on the appropriate intensity of activity immediately after a high-reactivity event — "your system just spiked, avoid high-intensity exercise for the next 90 minutes."

**Reference:** Thayer, Åhs et al. (2012) — HRV and prefrontal regulation of threat response.

---

### 3. Recovery Capacity
**The question it answers:** After something stressful, how quickly does your nervous system find its way back to calm?

**Clinical significance:** This is often the most impactful finding for users, and the one that resonates most immediately. Many people with healthy resting HRV have chronically slow recovery — their system is fine at baseline but takes 2–3 hours to return there after even minor stressors. Accumulated slow recoveries lead to carried stress debt across the day; by evening the system has never fully returned to baseline. Recovery Capacity separates the *depth* of the stress response from the *duration* of its aftermath.

**What it looks like before vs after training:** Before training, recovery arcs are long and incomplete — the system often starts the next stressor before it has finished recovering from the last one. After training, arcs shorten significantly. By week 6–8, users who previously took 90 minutes to recover are often recovering in 20–30 minutes. This is the single metric most correlated with the subjective experience of "handling things better."

**Coaching use:** Directly drives the "Recovery Speed" user score. Also determines when the system will recommend a training session — sessions scheduled inside a recovery arc have a different purpose (stress inoculation) than sessions scheduled during a calm window.

**Reference:** Porges (2007) — polyvagal theory; vagal withdrawal and re-engagement as the substrate of stress and regulation.

---

### 4. Respiratory-Cardiac Coupling
**The question it answers:** When you breathe slowly and deliberately, does your heart actually follow?

**Clinical significance:** This indicator captures whether the training is working at the physiological level. During slow diaphragmatic breathing at approximately 6 breaths per minute, the heart rate should oscillate in tight synchrony with each breath — accelerating on the inhale and decelerating on the exhale. This phenomenon, called Respiratory Sinus Arrhythmia (RSA), is under direct autonomic control. When the heart-breath lock is strong, baroreflex sensitivity improves and vagal tone is directly exercised. When the lock is weak, the session produces little physiological benefit regardless of how it *feels* to the user.

**What it looks like before vs after training:** New users typically show poor heart-breath coupling — their heart rhythm wanders independently of their breathing. After a few weeks of consistent sessions, the lock becomes faster and tighter. The heart begins to respond to the breathing rhythm within a second or two rather than not at all. This is the physiological proof that the training is producing adaptation.

**Coaching use:** This is the primary in-session feedback signal — the visual guidance the user sees in real time. It is also the basis of the Session Score. The AI coach uses trends in this indicator to decide when to advance the user's training level.

**Reference:** Lehrer & Gevirtz (2014) — HRV biofeedback: mechanisms and efficacy.

---

### 5. Peripheral Vascular State
**The question it answers:** Is the rest of your body confirming what the heart signal is telling us?

**Clinical significance:** Sympathetic nervous system activation causes peripheral vasoconstriction — blood is redirected away from the extremities toward the core and muscles. This shows up in the raw PPG signal as a measurable drop in peripheral perfusion. Its value is primarily as a *corroborating signal*: when the heart-derived indicators say "stress," the vascular signal should agree. If they disagree, signal quality is flagged rather than a false stress event declared. This prevents artefacts from motion, posture changes, or temperature from being misclassified as stress events.

**What it looks like in practice:** A confirmed stress event shows HRV suppression *and* peripheral vasoconstriction simultaneously. A posture change or motion artefact shows HR disruption without the vascular signature — and is correctly filtered out. Over training, users in a parasympathetic state show higher peripheral perfusion, which is an independent confirmation of the relaxation response.

**Coaching use:** Used as a validation layer in stress and recovery event detection. Not reported to the user directly — it operates silently to improve the accuracy of the other indicators.

**Reference:** Perfusion Index / Pleth Variability Index — established in clinical monitoring; increasingly validated in wearable contexts.

---

## Layer 4 — The 3 User-Facing Scores

The 5 indicators are condensed into 3 scores that the user sees. The design principle is that every number shown must be immediately interpretable without any background knowledge of physiology. No jargon. No axes. No raw HRV values.

ZenFlow Verity is an **autonomic nervous system coach** — not a breathing app. The product tracks how the nervous system behaves across the full arc of daily life: how much stress accumulated, how well the body recovered overnight, and what that means for today. Stress management tools (including but not limited to slow breathing) are one lever the coach can recommend — they are not the product itself.

The 3 scores answer the 3 questions users actually care about:

---

### Stress Load (0–100, lower is calmer)
**The question it answers:** How much stress has my nervous system accumulated today?

This score tracks cumulative sympathetic activation throughout the day — the running total of stress events, their magnitude, and how completely the system recovered between them. It is not a snapshot of how stressed the user feels right now; it is the physiological debt built up since waking. A score of 20 means the nervous system has been largely calm and recovered. A score of 80 means it has been under sustained load with incomplete recovery arcs.

It is always personal-baseline-relative. A score of 60 is not inherently bad — it is high relative to *that user's* normal. This prevents the score from being meaningless for high-baseline individuals or alarming for users who are simply having a busier-than-average day.

**What it drives:** The coach's intraday recommendations. High Stress Load by mid-afternoon triggers different advice than low Stress Load — what activity is appropriate, whether to protect the evening, whether accumulated load is heading toward a recovery debt. The underlying model is not "reduce stress to zero" but "keep load within a range the system can recover from overnight."

**What it looks like over weeks:** Stress Load patterns are more informative than daily values. A user who consistently peaks at 70+ on weekdays and recovers on weekends has a different ANS profile than one who runs at 40 all week. The coach uses these patterns to personalise recommendations over time.

---

### Recovery (0–100)
**The question it answers:** How well did my body reset overnight?

This score reflects the quality of overnight autonomic recovery — primarily derived from nocturnal HRV (RMSSD during sleep), resting heart rate trends through the night, and the degree to which the ANS returned to parasympathetic dominance. It is the nervous system's equivalent of asking: did sleep actually do its job?

A high Recovery score means the system entered deep parasympathetic rest, stress debt from the previous day was cleared, and the body is starting fresh. A low Recovery score means the system carried load into sleep, stayed partially activated overnight, and is beginning the day with a deficit.

**What it drives:** The morning briefing tone and the day's coaching posture. Recovery is the single strongest predictor of how the system will handle stress today. A low Recovery day is not a failure — it is a signal that the day's demands should be calibrated differently: less aggressive exercise, more margin between commitments, earlier wind-down.

**What it looks like over weeks:** Recovery trends reveal the impact of lifestyle factors more clearly than any single metric. Consistent low Recovery despite adequate sleep duration points to unresolved stress debt or lifestyle factors (alcohol, late eating, high training load) suppressing overnight ANS restoration. The coach surfaces these correlations explicitly over time.

---

### Readiness (0–100)
**The question it answers:** What is my nervous system actually capable of today?

Readiness is the master daily score — a composite that integrates the current Recovery reading with recent Stress Load history and the individual's rolling baseline. It answers the practical question: given everything the system has been through and how well it reset, what is available today?

It is a *relative* score, not an absolute one. It is always compared against the individual's own baseline established during the first 7 days. A score of 65 for one person and 65 for another may represent entirely different physiological states — but for each individual, any movement in Readiness is meaningful and directionally accurate.

**What it drives:** Every coaching recommendation is anchored to the day's Readiness. A low Readiness day triggers a conservative posture — lighter demands, stress protection, prioritising recovery. A high Readiness day is an opportunity to take on hard things, push training intensity, or schedule high-stakes work. The coach does not treat every day as interchangeable.

**What it looks like over weeks:** Readiness is not expected to rise every day. Daily variance is normal and healthy. The meaningful signal is the 7-day and 30-day trend — a slow, sustained upward shift in the baseline is the empirical proof that the system is adapting. By week 8, users who have consistently acted on the coach's recommendations typically show a Readiness baseline that is 10–20 points above their starting average.

---

### How the 3 Scores Work as a System

The scores are not independent — they tell a coherent story together:

- **Recovery** is the overnight input: how well did the system reset?
- **Stress Load** is the intraday accumulator: how much load is building up today?
- **Readiness** is the daily headline: what does all of this mean for what the system can handle?

A user with high Recovery but rapidly rising Stress Load by noon is burning through a good start. A user with low Recovery and controlled Stress Load is managing a deficit wisely. A user with falling Readiness and high Stress Load for 3+ consecutive days gets a different coaching response — the system is not recovering between days and the priority is deloading, not performing.

The AI coach reads all three together. No single score triggers a recommendation in isolation.

---

## How a Stress Event is Identified

A **stress event** is declared when all three of the following are true simultaneously:

**Criterion 1 — HRV suppression:**  
RMSSD drops more than 1 standard deviation below the user's rolling 7-day baseline and stays there for ≥ 2 consecutive minutes.  
*(The 2-minute filter eliminates transient artefacts from posture changes or deep breaths.)*

**Criterion 2 — Heart rate elevation:**  
Mean HR rises ≥ 8 BPM above the user's resting baseline within the same window.  
*(Corroborating signal — ensures RMSSD drop is ANS-driven, not motion artefact.)*

**Criterion 3 — Vascular corroboration:**  
Perfusion Index drops ≥ 20% from the preceding 5-minute mean.  
*(Peripheral vasoconstriction — independent second signal confirming sympathetic activation.)*

**Event timestamp** = the moment Criterion 1 is first met.  
**Event magnitude** = depth of RMSSD nadir below baseline (in SD units).  
**Event duration** = time from timestamp until start of recovery (see below).

---

## How a Recovery Event is Identified

A **recovery arc** begins immediately when a stress event is declared. It ends when:

**Recovery criterion:**  
RMSSD returns to within 0.5 SD of personal baseline AND HR returns to within 5 BPM of resting baseline, both sustained for ≥ 3 consecutive minutes.

**Recovery Speed** = time from RMSSD nadir to recovery criterion being met.

The arc is structured in three phases:
```
STRESS ONSET → [event duration] → RMSSD NADIR → [recovery arc] → BASELINE RETURN
                                                    ↑
                              This is what we measure as "Recovery Speed"
```

**Example interpretation for a user:**  
"Today you had 2 stress events. The first was at 2:14pm — your HRV dropped 1.8 SD below your baseline and took 47 minutes to recover. The second was at 5:30pm and recovered in 12 minutes."

---

## Key Scientific Questions for Discussion

The following are areas where the product design makes assumptions that require validation or expert input:

1. **PPI vs RR for RMSSD computation:** Optical PPI has higher jitter than ECG RR. The threshold of r ≥ 0.3 for coherence detection was calibrated on ECG data. Does the jitter level of optical PPG (~5–8 ms at rest) meaningfully degrade RMSSD accuracy, and does it change the coherence threshold?

2. **LF/HF ratio as sympathovagal index:** The literature is divided on whether LF power is truly sympathetic or primarily baroreflex/respiratory. We use it only as a directional signal, not an absolute measure. Is this framing defensible?

3. **Stress event thresholds (1 SD, 2 minutes, 8 BPM):** These are initialised from published HRV stress studies (e.g., Kim et al. 2018 — physiological response thresholds in ambulatory HRV monitoring). Are these thresholds clinically reasonable for a non-clinical consumer population?

4. **Resonance frequency personalisation:** The product currently targets 6 BPM (~0.1 Hz) as the universal resonance frequency. Published work (Lehrer 2006) suggests this varies between 4.5–7 BPM across individuals. Should the product find each user's resonance frequency individually, and how would that be done reliably with optical PPI?

5. **Population vs personal baseline:** The Resilience score is 100% personal-baseline-referenced. This avoids pathologising healthy variation but means the score cannot be benchmarked against health norms. Is this the right tradeoff, or should there be a population reference layer?

6. **Recovery Speed clinical benchmarks:** What would a clinically meaningful Recovery Speed threshold look like? (e.g., is a 90-minute recovery arc associated with measurable health risk? Is there published normative data?)

---

## Summary: What the Science Supports

| Claim | Support level |
|---|---|
| RMSSD measures cardiac vagal tone | Strong — gold standard in HRV literature |
| Slow diaphragmatic breathing at ~6 BPM increases HRV | Strong — replicated across multiple studies |
| HRV biofeedback improves resting RMSSD over 8 weeks | Moderate–Strong — Lehrer & Gevirtz (2014) meta-analysis |
| RMSSD predicts stress reactivity | Moderate — Thayer, Åhs et al. (2012) |
| PPG-derived PPI is a valid proxy for ECG RR at rest | Moderate — valid at rest, degrades with motion |
| Perfusion Index (PI) reflects sympathetic peripheral tone | Moderate — established in clinical monitoring |
| Personalised resonance frequency training is superior to fixed 6 BPM | Low — limited comparative data |
| Recovery arc duration as a standalone training metric | Low — product innovation, limited direct precedent |

---

*This document is a working draft for expert review. All threshold values and detection criteria are initial design decisions, not clinically validated parameters.*
