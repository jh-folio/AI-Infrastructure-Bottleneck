# Scoring 3.1 규칙 발췌

원본: Work Protocol 3.1의 §7.4 및 §8–11. 수치 정책 변경 없음.
원본 SHA-256: 155cf2402d1ba6edbea02899508167d2f4f747fea117ecc7c681fc04b52f36c9

## 7.4 Evidence grade와 독립성

| Grade | 의미 | 주의 |
|---|---|---|
| A | Direct Quantitative | 수치가 있어도 다른 제품·기간·단계이면 적용 불가. Quote와 actual receipt를 구분. |
| B | Direct Qualitative | 해당 제약에 대한 직접 진술. Issuer 진술과 독립 corroboration은 별개. |
| C | Triangulated Proxy | 서로 독립인 복수 관측과 검증 가능한 causal mechanism으로 factor/범위를 지지. |
| D | Analytical Inference | A–C에 근거한 분석적 판단. 추론 경로·가정·반증·범위 제시. |

Evidence grade는 자료의 형태/추론 수준이다. Source tier·freshness·scope fitness·신뢰도와 별도 필드다. Grade A를 자동으로High로 보지 않는다. 근거가 없는 ignorance는Grade D가 아니다.

`original_producer_id`, `independence_group_id`, `transaction_id/project_id`, `claim_family_id`로 출처 계보를 추적한다. 같은 거래의 선급금·장기계약·예약, 같은 보도자료의 재인용은 한 근거 계열이다. 상호 독립인 업계 당사자의 다른 관측도 같은 metric을 직접 검증했다고 과장하지 않는다.

Reservation, prepayment, sold-out, allocation, emergency capex, book-to-bill, secondary sourcing은 scarcity **후보 신호**다. 단일 신호만으로 shortage를 확정하지 않는다. 전략적 공급확보·신제품 ramp·가격변화·고객집중·취소조건 등 대안 설명을 검사한다. 긴 납기만으로 shortage를 중복 고득점 처리하지 않는다.


# 8. Scoring v3.1 — 세 축과9개 factor

**Severity, Persistence, Criticality는 곱셈이 아니라 가중합이다.** Persistence에40%를 두는 것은 구조적 지속성을 중시하는 분석 정책이지 경험적으로 검증된 자연법칙이 아니다. Calibration에서 민감도를 공개한다.

| Axis | Factor ID | Factor | Weight |
|---|---|---|---:|
| Severity | shortage | Current Shortage |15|
| Severity | access | Delivery / Access Lead Time |15|
| Persistence | elasticity | Supply Elasticity |15|
| Persistence | build | Capacity Build Lead Time |10|
| Persistence | demand | Demand Growth / Persistence |10|
| Persistence | substitution | Substitutability |5|
| Criticality | system_criticality | System / Project Criticality |15|
| Criticality | regulatory | Regulatory / Execution Constraints |10|
| Criticality | concentration | Supplier / Geographic Concentration |5|
| Total | | |100|

v2 대비 elasticity20→15, substitution10→5, concentration10→5. 확보한15점을 system_criticality에 배정한다. 나머지 factor의 명칭/해석 변경은 매핑 기록으로 남긴다. 이전 숫자를 새 anchor의 입력으로 재사용하지 않는다.

## 8.1 점수 anchor와 경계

모든 component는0–5 또는 근거가 지지하는 하한–상한이다. 정성 범위도 각 endpoint가 해당 anchor를 지지하는 이유를 기록해야 한다.

| Score | Shortage | System / Project Criticality |
|---:|---|---|
|0|동일 scope의 여유공급/구조적 surplus 확인|해당 scenario에서 실질적 영향 없음 확인|
|1|수급 대체로 균형 확인|비용·효율 영향 위주,일정 영향 미미|
|2|일부 지역·규격에서 타이트|성능 또는 일부capacity 감소;전체COD 영향 제한|
|3|의미 있는 공급긴장·제한적 allocation|구체적 경로상 deployment 지연 가능;인과경로·조건 명시|
|4|광범위한 공급제약을 직접 확인;높은 utilization/backlog만으로 충분하지 않음|정의된 프로젝트의 critical path·낮은 float 확인|
|5|usable supply가 수요/고객 증설을 직접 제한|정해진 목표일/운영요건에서 부족이 전체 또는 명시한capacity의COD를 막고,가능한 우회·재고·단계가동으로 해소되지 않음|

System Criticality5에는 단순한 ‘없으면 제품을 못 만든다’는 BOM 필수성이 아니라 **부족 상태에서의 일정 지배성**이 필요하다. T1/T2는 같은 기준의 forecast/scenario로 표시하며 미래 지연을 이미 관측했다고 쓰지 않는다. Site 전체와 일부phase를 분리한다.

Access months: <3=0; 3–<6=1; 6–<12=2; 12–<24=3; 24–36=4; >36=5.

Elasticity와Build months: <6=0; 6–<12=1; 12–<24=2; 24–<36=3; 36–60=4; >60=5. Elasticity는 가격만으로 해결되지 않는 구조적 제약의 직접 근거가 있을 때도5를 허용한다. 단순히 관측 시작일을 모르는 것은5의 근거가 아니다.

Growth annual physical rate: 감소=0; 0–5%=1; >5–10%=2; >10–20%=3; >20–40%=4; >40%=5. Structural step-change에는 직접 physical driver와 분모가 필요하다. 지속성·확정 고객수요·교체수요는 horizon/범위 판단에 반영하되 CAGR에 임의 bonus를 더하지 않는다. 일회성 주문 급증과 연간 지속 성장률을 혼합하지 않는다.

| Score | Substitution | Regulatory / Execution | Concentration |
|---:|---|---|---|
|0|요건을 충족하는 즉시 대체 가능|제약 사실상 없음 확인|동일 scope에서 매우 분산|
|1|switching cost 낮음|일반 운영·인증|다수 qualified 공급자·지역|
|2|제한적 qualification|통상적 permit/qualification|일부 집중|
|3|상당한 redesign/qualification|project-specific approval/engineering|높은 집중|
|4|대체에 수년|수년 승인·다기관 조정|극소수 qualified 공급자|
|5|scenario 요건 내 실질적 대체 없음|규제·토지·utility process가 자체적으로binding|검증된 사실상 단일 qualified 업체/지역 의존|

Concentration의 CR3·qualified share·생산지역 share는 서로 다른 분모다. 절대share가 없으면 supplier 목록만으로 중간값을 만들지 않는다. 해당 규격의 대안 가용성으로 정성 anchor 또는 범위를 뒷받침한다. 세 지표가 충돌하면 구분 표시하고 기계적으로 최대값을 선택하지 않는다. 세부 정량cutoff를 채택하려면 pilot 전에 공통 rubric에 공개한다.

## 8.2 접근시간과 공급반응의 구분

각 시간값에 `time_definition`, `clock_start`, `clock_end`, `observed_or_target`, `scope_exclusions`를 기록한다. Order→receipt, qualification, 신청→통전, permit approval, hiring/training은 같은 과정을 측정한 것이 아니다.

고객이 capacity를 얻는 경로를 설명하는 경우에만 equivalent access로 사용한다. Training 기간은 기존 숙련자 채용·지역 이동·overtime으로 우회 가능한지 확인한다. 일부 study90일을 전체 통전90일로 쓰거나, 이미 확보한 전력 기반을 포함하지 않은 hall 공사기간을 신규campus 전체기간으로 쓰지 않는다.

산업 elasticity는 증분 공급의 규모·spare capacity·가동률·yield·동시 증설·upstream·qualification·노동·자금·규제를 종합해 A–C 근거로 범위를 설정할 수 있다. 가격신호 시작과 끝의 완전한 직접 관측만을 요구하지 않는다. 다만 한 공장의3년 건설만으로 산업 elasticity3년이라고 단정하지 않는다.

같은 출처는 여러 factor의 다른 사실을 지지할 수 있다. 동일 주장 하나를 반복 보상하지 않도록 `shared_evidence_group`과 `distinct_factor_mechanism`을 기록한다. Access/build/elasticity, shortage/access, substitution/concentration, system_criticality/regulatory 사이 중복을 검토한다.

---

# 9. 범위와 중앙 계산

## 9.1 산식

각 축을0–100으로 정규화한다.

```text
Severity = 100 × (15×shortage/5 +15×access/5) /30
Persistence = 100 × (15×elasticity/5 +10×build/5 +10×demand/5 +5×substitution/5) /40
Criticality = 100 × (15×system_criticality/5 +10×regulatory/5 +5×concentration/5) /30
Overall = 0.30×Severity +0.40×Persistence +0.30×Criticality
        = Σ(weight_i × score_i/5)
```

각 lower/upper를 같은 식으로 계산한다. 부분 축만 계산 가능하면 그 축만 공개한다. 단순 범위 합은 동시실현을 보장하는 예측구간이 아니라 외곽가능범위다. 관련 factor의 극단을 섞은 불가능한 시나리오를 base forecast로 제시하지 않는다. 상세 scenario 계산에서는 공통 수요·ramp·규제 가정을 연결한다.

## 9.2 Range provenance

- `EvidenceBounded`: A–C 또는 추적 가능한D로 두 endpoint를 지지하는 범위.
- `UnknownBounded`: 지식 부재 때문에 가능한 점수0–5를 열어 둔 범위. 관측·추정 factor score가 아니며 evidence coverage에 포함하지 않음.
- `Mixed`: 계산 결과에 위 두 종류가 포함됨. Unknown weight와 그로 인한 총점폭을 함께 표시.

예: 알려진factor의 기여 합55점이고 Unknown weight20이면 논리적 총점범위55–75다.65점이 기본 추정치라는 뜻이 아니다.0과5는 불확실성 분석의 가능한 경계이며 해당factor에0/5점을 관측했다고 기록하지 않는다.

`midpoint=(low+high)/2`는 EvidenceBounded 범위의 표시용 중심값일 뿐이다. **UnknownBounded/Mixed에는 overall_mid=null**을 기본으로 한다. Base score는 별도로 근거가 명시된 scenario가 있을 때만 저장한다. Midpoint를 base나 기대값으로 자동 치환하지 않는다. 기본tier/순위는 midpoint가 아니라 범위·scoreability·confidence·criticality 조건으로 판정한다.

범위는 통계적 신뢰구간이 아니다. 불확실성폭과 confidence를 혼동하지 않는다. GradeD 단독으로 extreme0/5를 정당화하지 않으며, ignorance0–5와 구분한다. ResearchMissing도 민감도용0–5는 가능하지만 추정값으로 숨기지 않는다.

## 9.3 정밀도

Full precision으로 계산하고 화면에 소수1자리 이하로 표시한다. Bounds 표시에서 하한은 바깥쪽 내림,상한은 바깥쪽 올림하여 가능한 값을 잘라내지 않는다. 계산·tier에는 표시 반올림 전 값을 쓴다. 정성ordinal 점수의 작은 소수차를 통계적 우위라고 표현하지 않는다.

---

# 10. Criticality gate, Tier와 실제 Binding

## 10.1 Criticality axis screening

축Criticality<40: 시스템 영향 근거가 약한 공급긴장; 40–<60:조건부; 60–<80:중대한 영향 후보; ≥80:시스템 중요 제약 후보. 이 screening만으로 실제binding/non-binding을 확정하지 않는다.

## 10.2 Tier 판정 정책 — 초기 calibration 기준

Tier는 공통 비교scope 내 constraint screening 등급이다. `binding_status`는 별도다.

- **Tier1 — Strong / Binding Candidate:** Overall lower≥75, Criticality axis lower≥70, **System Criticality component lower≥4**, Shortage lower≥3, confidence≥Medium, Fully/Provisionally Scorable을 모두 충족. System Criticality 자체와 shortage에는 관련 A/B 또는 독립C 근거가 필요. Unknown/D만으로 조건을 충족시킬 수 없음.
- **Tier2 — Major Constraint:** Overall의 해당값이60–<75이거나,≥75지만 Tier1의criticality/shortage/confidence 조건을 충족하지 못함. Criticality<40이면 ‘Supply tightness; binding 미입증’ 표시.
- **Tier3 — Emerging / Conditional:** Overall의 해당값45–<60. 더 낮은score라도 근거 있는tightening이면 별도 Emerging flag를 허용하되 점수를 올리지 않는다.
- **Tier4 — Monitor:** Overall upper<45이고 scoreable. 낮은Overall을 ‘현재non-binding이 입증됨’으로 해석하지 않는다.

각 feasible scenario에서 먼저 Tier1의 모든 조건을 검사하고, 실패하면 Overall≥60은 Tier2, 45≤Overall<60은 Tier3, Overall<45는 Tier4로 분류한다. 고정된 confidence·scoreability 조건을 시나리오마다 유리하게 바꾸지 않는다. 가능한 모든 시나리오가 같은 tier이면 확정하고, 다르면 후보 집합을 표시한다. 범위만으로 공동 실현 가능성을 좁힐 근거가 없으면 보수적인 외곽 후보임을 표시한다.

Tier 판정에서 lower/upper가 다른 구간에 걸리면 `tier_confirmed`는 단일 확정값 대신null, `possible_tiers`는 feasible bounds/scenarios의 후보 집합을 기록한다. Tier1 확정에는 위 모든 **하한 조건**이 필요하다. 상한만 충족하면 Tier1 possibility이지 확정Tier1이 아니다. Tier1조건에 못 미치는 고점수는Tier2 screening이지 실제major delay 입증이 아니다.

Directionally Assessable/Not Scorable에는 숫자tier를 붙이지 않는다. 별도의 ‘강한 제약 신호/조건부/여유 확인/방향 미확인’ 판정을 근거와 함께 쓴다. Unknown 때문에낮게 보이는 node를Tier4에 배정하지 않는다.

범위가 겹친다는 이유만으로 동등성이 입증된 것은 아니다. ‘순위 미식별/가능tier 중첩’으로 표현한다. 1위/2위는 동일scope·기간에서 범위가 유의하게 분리되고 sensitive inputs/weights에 견고할 때만 제시한다. Top15 적격수가 부족하면 수를 채우지 않는다.

## 10.3 별도 binding_status

`ObservedBinding / ConditionalBinding / NotDemonstrated / DemonstratedNonBinding`을 쓴다.

- ObservedBinding: Project_ID, geography, phase/용량,기간,required path,실제부족,일정영향과 대안·float가 연결된 근거. 점수threshold 통과만으로 부여하지 않음.
- ConditionalBinding: 명시한site/scenario의 조건이 성립하면 마지막필수경로를 제한. 미래T1/T2는 이 상태 또는NotDemonstrated이며 미래지연을Observed로 쓰지 않음.
- NotDemonstrated: 단순기술적 의존성,높은score,자료부재만 존재.
- DemonstratedNonBinding: 현재충족된필수공급,충분한float,사용가능대안 등 적극적 근거. 자료부재나Tier4만으로 부여하지 않음.

System Criticality2/5,regulatory5/5,concentration5/5이면 축Criticality70이지만 System factor의별도gate 때문에Tier1은 불가하다. 이 예를 회귀검증에 포함한다.

---

# 11. Scoreability와 Confidence

## 11.1 Coverage 계산

공통9개factor의100weight를 분모로 유지한다. 각factor의 범위 전체를 정당화하는 결정적 근거grade를 사용한다. 한endpoint가C에 의존하면factor를A로 세지 않는다. 같은factor를A/B/C에 중복계상하지 않는다.

```text
coverage_AB = Σ(weight of A/B supported factors) /100
coverage_ABC = Σ(weight of A/B/C supported factors) /100
inference_weight = Σ(weight of D-only factors) /100
unknown_weight = Σ(weight of Unknown or ResearchMissing factors) /100
```

축별 coverage도 해당축weight를 분모로 계산한다. Unknown은 전체범위가 좁아보여도supported로 세지 않는다. Core factors는 shortage,access,system_criticality다.

## 11.2 초기 판정 기준

다음 수치는 v3.1의 **사전 공개된 pilot 정책값**이지 검증된통계threshold가 아니다. 결과를 좋게 보이게 하기 위해 node별로 변경하지 않는다.

| Status | 필수 조건 | 출력 |
|---|---|---|
| Fully Scorable | 9factor 적용가능; Unknown0; coverage_AB≥70%,coverage_ABC≥90%; core3factor 모두A/B;독립producer≥2 및Tier1/2 포함;material conflict 해소;Overall폭≤10;confidence≥Medium | Point 또는근거범위+3축+Overall |
| Provisionally Scorable | 9factor 적용가능;coverage_ABC≥60%;각축ABC coverage≥40%;Unknown weight≤20%;core3factor가A/B/C로bounded;독립producer≥2 및Tier1/2 포함;Overall폭≤25;주요conflict가경계/가정에반영 | EvidenceBounded/Mixed 범위+Unknown비중+Medium/Low confidence |
| Directionally Assessable | 위수치조건은미달하지만특정scope/horizon의제약수준 또는변화방향에 근거존재 | 축/항목 부분값과ordinal평가;확정Overall순위없음 |
| Not Scorable | 관련scope의 수준·방향성조차 지지할근거없음 | 원인·필요자료;숫자tier없음 |

가능성범위0–100을 계산했다는 이유로Provisionally Scorable이라고 하지 않는다. Node×horizon×scenario별로상태를판정한다. 노드수 보고에서는같은node의기간별상태를별도로보여주고전체node count와record count를혼동하지 않는다.

Coverage를통과해도시간·규격·지역이서로맞지 않으면승격하지 않는다. 부족량절대치비공개만으로강등하지 않으며GradeB/C가factor를충분히지지하는지검토한다.

## 11.3 Confidence

각component,axis,Overall,edge에High/Medium/Low와이유를저장한다. Score에confidence를곱하지 않는다. Source tier/Grade와자동동일시하지 않는다.

- High: 핵심주장복수독립검증,관련Tier1/2,최신/정합적인direct evidence,작은material conflict. Unknown/D가중요결론을결정하면불가.
- Medium: 직접근거와독립proxy가혼재하나core factors의범위·추론을추적가능하고중요대안설명검토.
- Low: vendor/단일계열의존,광범위proxy/Unknown,구형자료,미해결material conflict 또는넓은범위.

Unknown 포함결과는기본Low다. Medium 예외는Unknown범위전체에서도결론/tier가견고하고core근거가충분함을검증·기록해야한다. Confidence를낮추는것으로잘못된근거나식별불가능한좁은범위를정당화하지 않는다.

---
